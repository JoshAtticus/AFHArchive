"""
Asynchronous download manager for handling file downloads in background threads.
This prevents Gunicorn worker timeouts by offloading downloads to separate threads.
"""

import os
import threading
import time
import uuid
from typing import Dict, Optional, Any
from flask import current_app
from app.utils.rate_limiter import RateLimiter


class DownloadSession:
    """Represents an active download session"""
    
    def __init__(self, upload_id: int, file_path: str, file_size: int, filename: str, rate_limiter: RateLimiter):
        self.upload_id = upload_id
        self.file_path = file_path
        self.file_size = file_size
        self.filename = filename
        self.rate_limiter = rate_limiter
        self.session_id = str(uuid.uuid4())
        self.status = 'pending'  # pending, active, completed, error
        self.progress = 0  # bytes transferred
        self.error_message = None
        self.created_at = time.time()
        self.started_at = None
        self.completed_at = None
        self.limited_file = None
        self.thread = None
        self.chunks = []  # Store downloaded chunks
        self.client_connected = True


class AsyncDownloadManager:
    """Manages asynchronous file downloads"""
    
    def __init__(self):
        self.sessions: Dict[str, DownloadSession] = {}
        self.rate_limiter = RateLimiter()
        self._cleanup_interval = 300  # 5 minutes
        self._max_session_age = 3600  # 1 hour
        self._last_cleanup = time.time()
        self._lock = threading.Lock()
    
    def start_download(self, upload_id: int, file_path: str, file_size: int, filename: str) -> str:
        """Start a new async download session"""
        session = DownloadSession(upload_id, file_path, file_size, filename, self.rate_limiter)
        
        with self._lock:
            self.sessions[session.session_id] = session
        
        # Start download in background thread
        session.thread = threading.Thread(
            target=self._download_worker,
            args=(session,),
            daemon=True
        )
        session.thread.start()
        
        return session.session_id
    
    def get_session(self, session_id: str) -> Optional[DownloadSession]:
        """Get download session by ID"""
        with self._lock:
            return self.sessions.get(session_id)
    
    def get_download_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get download status information"""
        session = self.get_session(session_id)
        if not session:
            return None
        
        status = {
            'session_id': session_id,
            'upload_id': session.upload_id,
            'status': session.status,
            'progress': session.progress,
            'file_size': session.file_size,
            'filename': session.filename,
            'created_at': session.created_at,
            'started_at': session.started_at,
            'completed_at': session.completed_at
        }
        
        if session.error_message:
            status['error'] = session.error_message
        
        if session.status == 'active' and session.started_at:
            elapsed = time.time() - session.started_at
            if elapsed > 0 and session.progress > 0:
                speed = session.progress / elapsed
                status['speed'] = speed
                if speed > 0:
                    remaining_bytes = session.file_size - session.progress
                    status['eta'] = remaining_bytes / speed
        
        return status
    
    def get_download_stream(self, session_id: str):
        """Get download stream generator for completed downloads"""
        session = self.get_session(session_id)
        if not session or session.status != 'completed':
            return None
        
        def generate():
            try:
                for chunk in session.chunks:
                    yield chunk
            finally:
                # Clean up session after streaming
                self._cleanup_session(session_id)
        
        return generate()
    
    def cancel_download(self, session_id: str) -> bool:
        """Cancel an active download"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        session.client_connected = False
        if session.limited_file:
            try:
                session.limited_file.close()
            except:
                pass
        
        self._cleanup_session(session_id)
        return True
    
    def _download_worker(self, session: DownloadSession):
        """Background worker that performs the actual download"""
        try:
            session.status = 'active'
            session.started_at = time.time()
            
            # Check if file exists
            if not os.path.exists(session.file_path):
                session.status = 'error'
                session.error_message = 'File not found'
                return
            
            # Get bandwidth limit from current app context
            download_speed_limit = current_app.config['DOWNLOAD_SPEED_LIMIT']
            
            # Create bandwidth-limited file object
            session.limited_file = session.rate_limiter.create_limited_file(
                session.file_path, download_speed_limit
            )
            
            # Read file in chunks and store in memory
            # Note: For very large files, this might need to be optimized
            # to store chunks on disk instead of in memory
            session.chunks = []
            
            while session.client_connected:
                # Read in 64KB chunks
                chunk = session.limited_file.read(65536)
                if not chunk:
                    break
                
                session.chunks.append(chunk)
                session.progress += len(chunk)
                
                # Periodically check if client is still connected
                if len(session.chunks) % 16 == 0:  # Check every ~1MB
                    if not session.client_connected:
                        break
            
            if session.client_connected and session.progress == session.file_size:
                session.status = 'completed'
                session.completed_at = time.time()
                current_app.logger.info(f'Download completed: {session.filename} ({session.file_size} bytes)')
            else:
                session.status = 'cancelled'
                session.chunks = []  # Free memory
                current_app.logger.info(f'Download cancelled: {session.filename}')
                
        except Exception as e:
            session.status = 'error'
            session.error_message = str(e)
            session.chunks = []  # Free memory on error
            current_app.logger.error(f'Download error for {session.filename}: {e}')
        finally:
            if session.limited_file:
                try:
                    session.limited_file.close()
                except:
                    pass
            session.limited_file = None
    
    def _cleanup_session(self, session_id: str):
        """Clean up a specific session"""
        with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                session.chunks = []  # Free memory
                if session.limited_file:
                    try:
                        session.limited_file.close()
                    except:
                        pass
    
    def cleanup_old_sessions(self):
        """Clean up old/expired sessions"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        self._last_cleanup = now
        expired_sessions = []
        
        with self._lock:
            for session_id, session in self.sessions.items():
                session_age = now - session.created_at
                
                # Clean up sessions that are:
                # 1. Older than max age
                # 2. Completed and older than 5 minutes
                # 3. Failed and older than 1 minute
                if (session_age > self._max_session_age or
                    (session.status == 'completed' and session_age > 300) or
                    (session.status in ['error', 'cancelled'] and session_age > 60)):
                    expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            self._cleanup_session(session_id)
        
        if expired_sessions:
            current_app.logger.info(f'Cleaned up {len(expired_sessions)} expired download sessions')


# Global download manager instance
download_manager = AsyncDownloadManager()