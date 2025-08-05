#!/usr/bin/env python3
"""
AFHArchive Mirror Server
A standalone script that runs mirror servers for AFHArchive
"""

import os
import sys
import time
import json
import secrets
import hashlib
import shutil
import logging
import sqlite3
import requests
import threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, send_file, abort
from decouple import config
from werkzeug.middleware.proxy_fix import ProxyFix

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mirror.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class MirrorDatabase:
    """Simple SQLite database for mirror server"""
    
    def __init__(self, db_path='mirror.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize mirror database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Mirror files table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mirror_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                md5_hash TEXT NOT NULL,
                download_count INTEGER DEFAULT 0,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Mirror configuration table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mirror_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Mirror database initialized")
    
    def get_config(self, key, default=None):
        """Get configuration value"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM mirror_config WHERE key = ?', (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else default
    
    def set_config(self, key, value):
        """Set configuration value"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO mirror_config (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()
    
    def add_file(self, upload_id, filename, original_filename, file_path, file_size, md5_hash):
        """Add a file to the mirror database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO mirror_files 
            (upload_id, filename, original_filename, file_path, file_size, md5_hash)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (upload_id, filename, original_filename, file_path, file_size, md5_hash))
        conn.commit()
        conn.close()
        logger.info(f"Added file {original_filename} to mirror database")
    
    def remove_file(self, upload_id):
        """Remove a file from the mirror database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT file_path FROM mirror_files WHERE upload_id = ?', (upload_id,))
        result = cursor.fetchone()
        
        if result:
            file_path = result[0]
            # Remove from database
            cursor.execute('DELETE FROM mirror_files WHERE upload_id = ?', (upload_id,))
            conn.commit()
            
            # Remove file from disk
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Removed file {file_path} from mirror")
            except Exception as e:
                logger.error(f"Error removing file {file_path}: {e}")
        
        conn.close()
    
    def get_file_info(self, upload_id):
        """Get file information from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT upload_id, filename, original_filename, file_path, file_size, 
                   md5_hash, download_count, synced_at, last_accessed
            FROM mirror_files WHERE upload_id = ?
        ''', (upload_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'upload_id': result[0],
                'filename': result[1],
                'original_filename': result[2],
                'file_path': result[3],
                'file_size': result[4],
                'md5_hash': result[5],
                'download_count': result[6],
                'synced_at': result[7],
                'last_accessed': result[8]
            }
        return None
    
    def get_all_files(self):
        """Get all files in the mirror"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT upload_id, filename, original_filename, file_path, file_size, 
                   md5_hash, download_count, synced_at, last_accessed
            FROM mirror_files ORDER BY synced_at DESC
        ''')
        results = cursor.fetchall()
        conn.close()
        
        files = []
        for result in results:
            files.append({
                'upload_id': result[0],
                'filename': result[1],
                'original_filename': result[2],
                'file_path': result[3],
                'file_size': result[4],
                'md5_hash': result[5],
                'download_count': result[6],
                'synced_at': result[7],
                'last_accessed': result[8]
            })
        return files
    
    def update_download_count(self, upload_id):
        """Increment download count for a file"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE mirror_files 
            SET download_count = download_count + 1, last_accessed = CURRENT_TIMESTAMP
            WHERE upload_id = ?
        ''', (upload_id,))
        conn.commit()
        conn.close()
    
    def get_file_count(self):
        """Get total number of files stored"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM mirror_files')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def get_total_size(self):
        """Get total size of all files stored"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT SUM(file_size) FROM mirror_files')
        size = cursor.fetchone()[0]
        conn.close()
        return size or 0


class MirrorServer:
    """Mirror server implementation"""
    
    def __init__(self):
        self.db = MirrorDatabase()
        self.app = Flask(__name__)
        self.app.wsgi_app = ProxyFix(self.app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
        
        # Load or generate configuration
        self.load_config()
        self.setup_routes()
        
        # Start background tasks
        self.start_heartbeat_thread()
        self.start_sync_thread()
    
    def load_config(self):
        """Load mirror configuration"""
        # Generate API key if not exists
        self.api_key = self.db.get_config('api_key')
        if not self.api_key:
            self.api_key = secrets.token_urlsafe(32)
            self.db.set_config('api_key', self.api_key)
            logger.info(f"Generated new API key: {self.api_key}")
        
        # Load environment variables
        self.main_server_url = os.getenv('MAIN_SERVER_URL', 'https://afharchive.xyz')
        self.mirror_name = os.getenv('MIRROR_NAME', f'Mirror-{secrets.token_hex(4)}')
        self.mirror_port = int(os.getenv('MIRROR_PORT', '8000'))
        self.storage_path = os.getenv('STORAGE_PATH', 'mirror_uploads')
        self.max_files = int(os.getenv('MAX_FILES', '1000'))
        
        # Create storage directory
        os.makedirs(self.storage_path, exist_ok=True)
        
        # Check if already paired
        self.mirror_id = self.db.get_config('mirror_id')
        self.paired = self.mirror_id is not None
        
        logger.info(f"Mirror configuration loaded - Name: {self.mirror_name}, Port: {self.mirror_port}")
        if self.paired:
            logger.info(f"Mirror is paired with ID: {self.mirror_id}")
        else:
            logger.info("Mirror is not paired yet")
    
    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/health')
        def health():
            """Health check endpoint"""
            return jsonify({
                'status': 'online',
                'mirror_name': self.mirror_name,
                'paired': self.paired,
                'file_count': self.db.get_file_count(),
                'total_size': self.db.get_total_size(),
                'max_files': self.max_files
            })
        
        @self.app.route('/register', methods=['POST'])
        def register():
            """Register with main server (admin approval required)"""
            data = request.json or {}
            direct_url = data.get('direct_url', f'localhost:{self.mirror_port}')
            cloudflare_url = data.get('cloudflare_url', '')
            
            try:
                # Send registration request to main server
                response = requests.post(f'{self.main_server_url}/api/mirrors/register', json={
                    'server_name': self.mirror_name,
                    'api_key': self.api_key,
                    'direct_url': direct_url,
                    'cloudflare_url': cloudflare_url,
                    'storage_path': self.storage_path,
                    'max_files': self.max_files
                }, timeout=30)
                
                if response.status_code == 200:
                    mirror_data = response.json()
                    self.mirror_id = mirror_data['mirror_id']
                    self.db.set_config('mirror_id', str(self.mirror_id))
                    self.paired = True
                    logger.info(f"Successfully registered with main server. Mirror ID: {self.mirror_id}")
                    return jsonify({'success': True, 'mirror_id': self.mirror_id, 'status': 'pending_approval'})
                else:
                    error_msg = response.json().get('error', 'Registration failed')
                    logger.error(f"Registration failed: {error_msg}")
                    return jsonify({'error': error_msg}), response.status_code
                    
            except Exception as e:
                logger.error(f"Error during registration: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/download/<int:upload_id>')
        def download(upload_id):
            """Download file from mirror"""
            file_info = self.db.get_file_info(upload_id)
            if not file_info:
                abort(404)
            
            file_path = file_info['file_path']
            if not os.path.exists(file_path):
                logger.error(f"File not found on disk: {file_path}")
                abort(404)
            
            # Update download count
            self.db.update_download_count(upload_id)
            
            # Send file
            return send_file(
                file_path,
                as_attachment=True,
                download_name=file_info['original_filename']
            )
        
        @self.app.route('/api/files')
        def list_files():
            """List all files on this mirror"""
            if not self.check_auth():
                abort(401)
            
            files = self.db.get_all_files()
            return jsonify({'files': files})
        
        @self.app.route('/api/sync/add', methods=['POST'])
        def sync_add_file():
            """Add file to mirror via sync"""
            if not self.check_auth():
                abort(401)
            
            data = request.json
            if not data:
                return jsonify({'error': 'Invalid data'}), 400
            
            upload_id = data.get('upload_id')
            if not upload_id:
                return jsonify({'error': 'upload_id required'}), 400
            
            # Download file from main server
            try:
                download_url = f"{self.main_server_url}/api/mirrors/download/{upload_id}"
                headers = {'Authorization': f'Bearer {self.api_key}'}
                
                response = requests.get(download_url, headers=headers, stream=True)
                if response.status_code != 200:
                    return jsonify({'error': f'Failed to download file: {response.status_code}'}), 400
                
                # Save file to mirror storage
                filename = data['filename']
                file_path = os.path.join(self.storage_path, filename)
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Verify file integrity
                calculated_hash = self.calculate_md5(file_path)
                if calculated_hash != data['md5_hash']:
                    os.remove(file_path)
                    return jsonify({'error': 'File integrity check failed'}), 500
                
                # Add to database
                self.db.add_file(
                    upload_id=upload_id,
                    filename=filename,
                    original_filename=data['original_filename'],
                    file_path=file_path,
                    file_size=data['file_size'],
                    md5_hash=data['md5_hash']
                )
                
                logger.info(f"Successfully synced file {data['original_filename']} (ID: {upload_id})")
                return jsonify({'success': True})
                
            except Exception as e:
                logger.error(f"Error syncing file: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/sync/remove', methods=['POST'])
        def sync_remove_file():
            """Remove file from mirror via sync"""
            if not self.check_auth():
                abort(401)
            
            data = request.json
            upload_id = data.get('upload_id')
            if not upload_id:
                return jsonify({'error': 'upload_id required'}), 400
            
            self.db.remove_file(upload_id)
            logger.info(f"Removed file with ID: {upload_id}")
            return jsonify({'success': True})
        
        @self.app.route('/api/logs')
        def get_logs():
            """Get mirror logs"""
            if not self.check_auth():
                abort(401)
            
            try:
                with open('mirror.log', 'r') as f:
                    lines = f.readlines()
                    # Return last 100 lines
                    return jsonify({'logs': lines[-100:]})
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    
    def check_auth(self):
        """Check API authentication"""
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return False
        
        token = auth_header.split(' ')[1]
        return token == self.api_key
    
    def calculate_md5(self, file_path):
        """Calculate MD5 hash of a file"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def send_heartbeat(self):
        """Send heartbeat to main server"""
        if not self.paired:
            return
        
        try:
            heartbeat_data = {
                'mirror_id': self.mirror_id,
                'status': 'online',
                'file_count': self.db.get_file_count(),
                'total_size': self.db.get_total_size(),
                'max_files': self.max_files
            }
            
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.post(
                f'{self.main_server_url}/api/mirrors/heartbeat',
                json=heartbeat_data,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.debug("Heartbeat sent successfully")
            else:
                logger.warning(f"Heartbeat failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")
    
    def start_heartbeat_thread(self):
        """Start heartbeat thread"""
        def heartbeat_loop():
            while True:
                self.send_heartbeat()
                time.sleep(60)  # Send heartbeat every minute
        
        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()
        logger.info("Started heartbeat thread")
    
    def start_sync_thread(self):
        """Start sync thread"""
        def sync_loop():
            while True:
                if self.paired:
                    self.check_sync()
                time.sleep(300)  # Check for sync every 5 minutes
        
        thread = threading.Thread(target=sync_loop, daemon=True)
        thread.start()
        logger.info("Started sync thread")
    
    def check_sync(self):
        """Check if sync is needed"""
        try:
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.get(
                f'{self.main_server_url}/api/mirrors/{self.mirror_id}/sync-status',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                sync_data = response.json()
                if sync_data.get('sync_needed'):
                    logger.info("Sync needed, starting sync process")
                    self.perform_sync()
            
        except Exception as e:
            logger.error(f"Error checking sync status: {e}")
    
    def perform_sync(self):
        """Perform synchronization with main server"""
        try:
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.get(
                f'{self.main_server_url}/api/mirrors/{self.mirror_id}/sync-instructions',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                instructions = response.json()
                
                # Process add instructions
                for add_instruction in instructions.get('add', []):
                    self.sync_add_file_internal(add_instruction)
                
                # Process remove instructions
                for remove_instruction in instructions.get('remove', []):
                    self.db.remove_file(remove_instruction['upload_id'])
                
                logger.info("Sync completed successfully")
            
        except Exception as e:
            logger.error(f"Error during sync: {e}")
    
    def sync_add_file_internal(self, file_data):
        """Internal method to add file during sync"""
        try:
            upload_id = file_data['upload_id']
            
            # Check if we already have this file
            if self.db.get_file_info(upload_id):
                return
            
            # Check if we have space
            current_files = self.db.get_file_count()
            if current_files >= self.max_files:
                logger.warning(f"Mirror at capacity ({current_files}/{self.max_files}), skipping file {upload_id}")
                return
            
            # Download and add file
            download_url = f"{self.main_server_url}/api/mirrors/download/{upload_id}"
            headers = {'Authorization': f'Bearer {self.api_key}'}
            
            response = requests.get(download_url, headers=headers, stream=True)
            if response.status_code == 200:
                filename = file_data['filename']
                file_path = os.path.join(self.storage_path, filename)
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Verify and add to database
                calculated_hash = self.calculate_md5(file_path)
                if calculated_hash == file_data['md5_hash']:
                    self.db.add_file(
                        upload_id=upload_id,
                        filename=filename,
                        original_filename=file_data['original_filename'],
                        file_path=file_path,
                        file_size=file_data['file_size'],
                        md5_hash=file_data['md5_hash']
                    )
                    logger.info(f"Synced file: {file_data['original_filename']}")
                else:
                    os.remove(file_path)
                    logger.error(f"MD5 mismatch for file {upload_id}")
        
        except Exception as e:
            logger.error(f"Error syncing file {file_data.get('upload_id')}: {e}")
    
    def auto_register(self):
        """Automatically register with main server on startup"""
        if self.paired:
            logger.info("Mirror is already paired, skipping auto-registration")
            return True
            
        logger.info("Attempting to auto-register with main server...")
        try:
            # Send registration request to main server
            response = requests.post(f'{self.main_server_url}/api/mirrors/register', json={
                'server_name': self.mirror_name,
                'api_key': self.api_key,
                'direct_url': f'localhost:{self.mirror_port}',  # Can be overridden in admin panel
                'cloudflare_url': '',  # Can be set in admin panel
                'storage_path': self.storage_path,
                'max_files': self.max_files
            }, timeout=30)
            
            if response.status_code == 200:
                mirror_data = response.json()
                self.mirror_id = mirror_data['mirror_id']
                self.db.set_config('mirror_id', str(self.mirror_id))
                self.paired = True
                
                status = mirror_data.get('status', 'pending')
                if status == 'pending':
                    logger.info(f"Successfully registered with main server. Mirror ID: {self.mirror_id}")
                    logger.info("Mirror is pending admin approval. Check the admin panel to approve this mirror.")
                else:
                    logger.info(f"Successfully registered and activated. Mirror ID: {self.mirror_id}")
                return True
            else:
                error_msg = response.json().get('error', 'Registration failed')
                logger.error(f"Auto-registration failed: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"Error during auto-registration: {e}")
            logger.info("Mirror will continue running. You can register manually through the admin panel.")
            return False

    def run(self):
        """Run the mirror server"""
        logger.info(f"Starting AFHArchive Mirror Server on port {self.mirror_port}")
        
        # Attempt auto-registration
        self.auto_register()
        
        if not self.paired:
            logger.info("Mirror is not registered. It will auto-register on startup or can be registered through the admin panel.")
        
        self.app.run(host='0.0.0.0', port=self.mirror_port, debug=False)


def create_env_file():
    """Create .env file for mirror configuration"""
    env_content = '''# AFHArchive Mirror Configuration
MAIN_SERVER_URL=https://afharchive.xyz
MIRROR_NAME=My Mirror Server
MIRROR_PORT=5000
STORAGE_PATH=mirror_uploads
MAX_FILES=1000
'''
    
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write(env_content)
        print("Created .env file with default configuration")
        print("Please edit .env to configure your mirror server")
    else:
        print(".env file already exists")


def main():
    """Main entry point"""
    if len(sys.argv) > 1 and sys.argv[1] == 'setup':
        print("Setting up AFHArchive Mirror Server...")
        create_env_file()
        print("\nSetup complete!")
        print("Edit the .env file to configure your mirror, then run:")
        print("python mirror.py")
        return
    
    # Start mirror server
    mirror = MirrorServer()
    try:
        mirror.run()
    except KeyboardInterrupt:
        logger.info("Mirror server stopped by user")
    except Exception as e:
        logger.error(f"Mirror server error: {e}")


if __name__ == '__main__':
    main()
