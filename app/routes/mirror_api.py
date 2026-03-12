from flask import Blueprint, request, jsonify, current_app, send_file, Response
from app import db, socketio
from app.models import Mirror, FileReplica, Upload
from app.utils.mirror_utils import get_or_create_mirror_user
import os
from datetime import datetime
import requests
import threading
import time
import hashlib

mirror_bp = Blueprint('mirror_api', __name__, url_prefix='/api/mirror')

# Set to track filenames that should have their sync aborted
ABORT_SYNCS = set()

# --- Main Server Endpoints ---

@mirror_bp.route('/heartbeat', methods=['POST'])
def heartbeat():
    """Mirror reports it is alive and sends stats"""
    data = request.json
    api_key = data.get('api_key')
    mirror = Mirror.query.filter_by(api_key=api_key).first()
    
    if not mirror:
        return jsonify({'error': 'Invalid API key'}), 401
        
    try:
        mirror.last_heartbeat = datetime.utcnow()
        mirror.storage_used_mb = data.get('storage_used_mb', 0)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning(f"Database locked or busy in heartbeat for mirror {mirror.id}, ignoring: {e}")
        
    # Send back the list of all mirrors so the mirror can replicate API keys locally
    active_mirrors = Mirror.query.all()
    mirrors_data = []
    for m in active_mirrors:
        mirrors_data.append({
            'name': m.name,
            'api_key': m.api_key,
            'url': m.url,
            'location': m.location,
            'storage_limit_gb': m.storage_limit_gb,
            'download_speed_limit_kbps': getattr(m, 'download_speed_limit_kbps', 0),
            'is_active': m.is_active
        })
    
    return jsonify({'status': 'ok', 'mirrors': mirrors_data})

@mirror_bp.route('/progress', methods=['POST'])
def report_progress():
    """Receive sync progress updates from mirrors"""
    data = request.json
    api_key = data.get('api_key')
    upload_id = data.get('upload_id')
    progress = data.get('progress')
    downloaded_bytes = data.get('downloaded_bytes', 0)
    total_bytes = data.get('total_bytes', 0)
    
    mirror = Mirror.query.filter_by(api_key=api_key).first()
    if not mirror:
        return jsonify({'error': 'Invalid API key'}), 401
        
    # Emit socket event to admin UI - broadcast to ALL connected clients
    socketio.emit('mirror_sync_progress', {
        'mirror_id': mirror.id,
        'upload_id': upload_id,
        'progress': progress,
        'downloaded_bytes': downloaded_bytes,
        'total_bytes': total_bytes
    }, namespace='/')
    
    return jsonify({'status': 'ok'})

@mirror_bp.route('/sync_complete', methods=['POST'])
def sync_complete():
    """Mirror reports a file has been synced"""
    data = request.json
    api_key = data.get('api_key')
    mirror = Mirror.query.filter_by(api_key=api_key).first()
    
    if not mirror:
        return jsonify({'error': 'Invalid API key'}), 401
        
    upload_id = data.get('upload_id')
    status = data.get('status') # 'synced' or 'error'
    error_msg = data.get('error_message')
    
    replica = FileReplica.query.filter_by(upload_id=upload_id, mirror_id=mirror.id).first()
    if replica:
        replica.status = status
        replica.error_message = error_msg
        if status == 'synced':
            replica.synced_at = datetime.utcnow()
        replica.updated_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning(f"Database locked or busy in sync_complete for replica {replica.id}, ignoring: {e}")
        
        # Emit completion event to admin UI
        socketio.emit('mirror_sync_complete', {
            'mirror_id': mirror.id,
            'upload_id': upload_id,
            'status': status,
            'error_message': error_msg
        }, namespace='/')
        
    return jsonify({'status': 'ok'})

# --- Mirror Client Logic (To be run on the Mirror Server) ---

def perform_sync(job_data, app_config, app=None):
    """
    Background task to download file from Main.
    """
    # Setup logging
    logger = app.logger if app else logging.getLogger(__name__)
    
    file_id = job_data['file_id']
    download_url = job_data['download_url']
    md5_hash = job_data['md5_hash']
    file_size = job_data['file_size']
    filename = job_data['filename']
    api_key = app_config['MIRROR_API_KEY']
    main_url = app_config['MAIN_SERVER_URL']
    
    logger.info(f"Starting sync job for {filename} (ID: {file_id})")
    logger.info(f"Download URL: {download_url}")
    logger.info(f"Target Size: {file_size} bytes")
    
    # Ensure upload directory exists
    upload_dir = app_config['UPLOAD_FOLDER']
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    local_path = os.path.join(upload_dir, filename)
    
    try:
        headers = {'X-Mirror-Api-Key': api_key}
        
        # Retry loop for the connection start
        retries = 0
        max_retries = 5
        response = None
        
        while retries < max_retries:
            try:
                logger.debug(f"Attempting connection (Try {retries+1}/{max_retries})...")
                start_time = time.time()
                response = requests.get(download_url, headers=headers, stream=True, timeout=30)
                connect_time = time.time() - start_time
                logger.debug(f"Connection established in {connect_time:.2f}s. Status: {response.status_code}")
                
                if response.status_code == 200:
                    break
                elif response.status_code in [502, 503, 504]:
                     logger.warning(f"Server returned {response.status_code}, retrying...")
                else:
                    logger.error(f"Download failed with status {response.status_code}")
                    logger.error(f"Response headers: {response.headers}")
                    raise Exception(f"Download failed with status {response.status_code}")
            except Exception as e:
                logger.error(f"Connection attempt {retries+1} failed: {e}")
            
            retries += 1
            if retries < max_retries:
                time.sleep(5 * retries)
            
        if not response or response.status_code != 200:
             raise Exception(f"Failed to connect after {max_retries} retries. Status: {response.status_code if response else 'None'}")

        logger.info(f"Starting download stream for {filename}...")
        with open(local_path, 'wb') as f:
            downloaded = 0
            last_progress_time = time.time()
            start_download_time = time.time()
            
            for chunk in response.iter_content(chunk_size=8192):
                if filename in ABORT_SYNCS:
                    logger.warning(f"Sync aborted for {filename}")
                    ABORT_SYNCS.discard(filename)
                    return # Exit early without completing or reporting error
                    
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Report progress every 2 seconds
                    if time.time() - last_progress_time > 2:
                        percent = int((downloaded / file_size) * 100)
                        speed = downloaded / (time.time() - start_download_time)
                        logger.debug(f"Download progress: {percent}% ({downloaded}/{file_size} bytes) - Speed: {speed/1024/1024:.2f} MB/s")
                        try:
                            requests.post(f"{main_url}/api/mirror/progress", json={
                                'api_key': api_key,
                                'upload_id': file_id,
                                'progress': percent,
                                'downloaded_bytes': downloaded,
                                'total_bytes': file_size
                            }, timeout=5)
                            last_progress_time = time.time()
                        except Exception as e:
                            logger.warning(f"Failed to report progress: {e}")
                            pass # Ignore progress report failures
            
            total_time = time.time() - start_download_time
            logger.info(f"Download finished in {total_time:.2f}s. Average speed: {file_size/total_time/1024/1024:.2f} MB/s")
                
        # Verify MD5
                
        # Verify MD5
        local_md5 = hashlib.md5()
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                local_md5.update(chunk)
        
        calculated_md5 = local_md5.hexdigest()
        if calculated_md5 != md5_hash:
            actual_size = os.path.getsize(local_path)
            error_msg = f"MD5 mismatch. Expected: {md5_hash}, Got: {calculated_md5}. Expected Size: {file_size}, Got Size: {actual_size}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
        # Report success
        requests.post(f"{main_url}/api/mirror/sync_complete", json={
            'api_key': api_key,
            'upload_id': file_id,
            'status': 'synced',
            'error_message': None
        }, timeout=10)
        print(f"Sync complete for {filename}")

        # Update local DB if app context is provided
        if app:
            with app.app_context():
                try:
                    # Check if upload exists
                    upload = Upload.query.get(file_id)
                    if not upload:
                        # Get system user for mirror uploads
                        mirror_user = get_or_create_mirror_user()
                        upload = Upload(id=file_id, user_id=mirror_user.id)
                        db.session.add(upload)
                    
                    # Update fields
                    upload.filename = filename
                    upload.original_filename = job_data.get('original_filename', filename)
                    upload.file_path = filename # On mirror, path is just filename in upload folder
                    upload.file_size = file_size
                    upload.md5_hash = md5_hash
                    upload.device_manufacturer = job_data.get('device_manufacturer', 'Unknown')
                    upload.device_model = job_data.get('device_model', 'Unknown')
                    upload.afh_link = job_data.get('afh_link')
                    upload.xda_thread = job_data.get('xda_thread')
                    upload.notes = job_data.get('notes')
                    upload.afh_md5_status = job_data.get('afh_md5_status')
                    upload.status = 'approved'
                    upload.uploaded_at = datetime.utcnow()
                    
                    db.session.commit()
                    logger.info(f"Local DB updated for {filename}")
                except Exception as db_e:
                    logger.error(f"Failed to update local DB: {db_e}")
                    db.session.rollback()
        
    except Exception as e:
        logger.error(f"Sync failed for {filename}: {e}")
        # Report error
        try:
            requests.post(f"{main_url}/api/mirror/sync_complete", json={
                'api_key': api_key,
                'upload_id': file_id,
                'status': 'error',
                'error_message': str(e)
            }, timeout=10)
        except Exception as report_error:
            logger.error(f"Failed to report error to main server: {report_error}")
        
        # Clean up partial file
        if os.path.exists(local_path):
            os.remove(local_path)

@mirror_bp.route('/update', methods=['POST'])
def receive_update_job():
    """
    Endpoint for Main to trigger a git pull and server restart.
    Expects: {'api_key': '...'}
    """
    data = request.json
    api_key_provided = data.get('api_key')
    
    app_config_api_key = current_app.config.get('MIRROR_API_KEY')
    if not app_config_api_key or app_config_api_key != api_key_provided:
        return jsonify({'error': 'Invalid API Key'}), 401
        
    current_app.logger.info("Received remote update command. Running git pull...")
    
    try:
        import subprocess
        import os
        
        # Fix git dubious ownership safely before pulling
        repo_dir = os.path.abspath(os.getcwd())
        subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', repo_dir], capture_output=True)
        subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', '*'], capture_output=True)

        result = subprocess.run(['git', 'pull'], capture_output=True, text=True, check=True)
        current_app.logger.info(f"Git pull result: {result.stdout}")
        
        # Schedule restart
        def delayed_restart():
            import time
            import signal
            import sys
            time.sleep(2)
            try:
                if hasattr(os, 'getppid') and hasattr(signal, 'SIGTERM'):
                    # In Gunicorn, the worker must kill the master (parent) process for a full restart, 
                    # especially since preload_app=True prevents SIGHUP from updating the code.
                    parent_pid = os.getppid()
                    if parent_pid > 1:
                        os.kill(parent_pid, signal.SIGTERM)
                    os.kill(os.getpid(), signal.SIGTERM)
                elif hasattr(os, 'kill'):
                    os.kill(os.getpid(), signal.SIGTERM)
                else:
                    subprocess.run(['taskkill', '/f', '/pid', str(os.getpid())], check=False)
                os._exit(0)
            except Exception:
                os._exit(1)
                
        threading.Thread(target=delayed_restart, daemon=True).start()
        
        return jsonify({
            'status': 'update_initiated',
            'git_output': result.stdout
        })
    except subprocess.CalledProcessError as e:
        current_app.logger.error(f"Git pull failed: {e.stderr}")
        return jsonify({'error': 'Git pull failed', 'details': e.stderr}), 500
    except Exception as e:
        current_app.logger.error(f"Update failed: {e}")
        return jsonify({'error': 'Update failed', 'details': str(e)}), 500

@mirror_bp.route('/logs', methods=['POST'])
def receive_logs_job():
    """
    Endpoint for Main to fetch the last N lines of logs from this Mirror.
    Expects: {'api_key': '...', 'lines': 500}
    """
    data = request.json
    api_key_provided = data.get('api_key')
    
    app_config_api_key = current_app.config.get('MIRROR_API_KEY')
    if not app_config_api_key or app_config_api_key != api_key_provided:
        return jsonify({'error': 'Invalid API Key'}), 401
    
    lines_count = min(int(data.get('lines', 500)), 5000)
    
    log_path = os.path.join('logs', 'afharchive.log')
    logs = ""
    
    try:
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                logs = "".join(lines[-lines_count:])
        else:
            logs = "Log file not found on the server."
            
        return jsonify({
            'status': 'success',
            'logs': logs
        })
    except Exception as e:
        current_app.logger.error(f"Failed to read logs: {e}")
        return jsonify({'error': 'Failed to read logs', 'details': str(e)}), 500

@mirror_bp.route('/job/sync', methods=['POST'])
def receive_sync_job():
    """
    Endpoint for Main to trigger sync on this Mirror.
    Expects: {
        'file_id': 123,
        'download_url': 'https://main.../api/mirror/download/123',
        'md5_hash': '...',
        'file_size': 1000,
        'filename': '...'
    }
    """
    # Security check: In a real app, verify signature or IP. 
    # Here we rely on the fact that this endpoint is hidden or protected by network/auth if possible.
    # But wait, we should probably have a shared secret for incoming jobs too.
    
    data = request.json
    
    # Extract config needed for the thread
    main_server_url = current_app.config.get('MAIN_SERVER_URL', '')
    if main_server_url:
        main_server_url = main_server_url.rstrip('/')
        
    app_config = {
        'UPLOAD_FOLDER': current_app.config['UPLOAD_FOLDER'],
        'MIRROR_API_KEY': current_app.config.get('MIRROR_API_KEY'),
        'MAIN_SERVER_URL': main_server_url
    }
    
    if not app_config['MIRROR_API_KEY']:
        print("Error: MIRROR_API_KEY not configured on this server")
        return jsonify({'error': 'This server is not configured as a mirror'}), 400
        
    # Start background thread
    print(f"Received sync job for file {data.get('filename')} (ID: {data.get('file_id')})")
    
    # Override download_url to ensure it uses the configured MAIN_SERVER_URL if none provided
    # Only override if the provided URL looks like a generic main server URL (or is missing)
    # AND we have a better one configured locally.
    # However, if it's a P2P sync (from another mirror), we should respect the provided URL.
    
    provided_url = data.get('download_url', '')
    
    # If no URL provided, or if we want to force main server fallback when appropriate
    if not provided_url and app_config['MAIN_SERVER_URL']:
        data['download_url'] = f"{app_config['MAIN_SERVER_URL']}/api/mirror_sync/{data.get('file_id')}"
        print(f"Using constructed fallback URL: {data['download_url']}")
    elif provided_url:
        print(f"Using provided download URL: {provided_url}")
    
    # Pass the API key to the thread so it can authenticate with the main server
    data['api_key'] = app_config['MIRROR_API_KEY']
    
    # Pass the actual app object to the thread to create a context
    app = current_app._get_current_object()
    thread = threading.Thread(target=perform_sync, args=(data, app_config, app))
    thread.start()
    
    return jsonify({'status': 'job_accepted'})

@mirror_bp.route('/job/delete', methods=['POST'])
def receive_delete_job():
    """
    Endpoint for Main to trigger file deletion on this Mirror.
    Expects: {
        'filename': '...'
    }
    """
    data = request.json
    filename = data.get('filename')
    
    if not filename:
        return jsonify({'error': 'Filename required'}), 400
        
    # Security check: Ensure we are configured as a mirror
    if not current_app.config.get('MIRROR_API_KEY'):
        return jsonify({'error': 'This server is not configured as a mirror'}), 400
        
    upload_dir = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_dir, filename)
    
    # Add to abort set in case it's currently syncing
    ABORT_SYNCS.add(filename)
    
    try:
        # Give sync thread a moment to notice the abort and release the file handle
        time.sleep(0.5) 
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Deleted file {filename} from mirror storage")
        else:
            print(f"File {filename} not found on disk, proceeding to DB deletion")
            
        # Always remove from local DB if it exists
        with current_app.app_context():
            upload = Upload.query.filter_by(filename=filename).first()
            if upload:
                db.session.delete(upload)
                db.session.commit()
                print(f"Deleted upload record for {filename} from mirror DB")
        
        return jsonify({'status': 'deleted'})
    except Exception as e:
        print(f"Error deleting file {filename}: {e}")
        return jsonify({'error': str(e)}), 500

import fcntl
import sys

def mirror_heartbeat_loop(app):
    """
    Background loop to send heartbeats to the main server.
    Uses a file lock to ensure only one worker runs this loop.
    """
    lock_file = '/tmp/afh_mirror_heartbeat.lock'
    fp = open(lock_file, 'w')
    
    try:
        # Try to acquire an exclusive lock (non-blocking)
        fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        # Another instance is already running
        print("Mirror heartbeat already running in another worker.")
        return

    with app.app_context():
        api_key = app.config.get('MIRROR_API_KEY')
        main_url = app.config.get('MAIN_SERVER_URL')
        upload_folder = app.config.get('UPLOAD_FOLDER')
        
        if not api_key or not main_url:
            print("Mirror configuration missing. Heartbeat disabled.")
            return

        print(f"Starting mirror heartbeat to {main_url}...")
        
        while True:
            try:
                # Calculate storage usage
                total_size = 0
                if os.path.exists(upload_folder):
                    for dirpath, dirnames, filenames in os.walk(upload_folder):
                        for f in filenames:
                            fp_file = os.path.join(dirpath, f)
                            if not os.path.islink(fp_file):
                                total_size += os.path.getsize(fp_file)
                
                storage_used_mb = int(total_size / (1024 * 1024))
                
                # Send heartbeat
                resp = requests.post(
                    f"{main_url}/api/mirror/heartbeat",
                    json={
                        'api_key': api_key,
                        'storage_used_mb': storage_used_mb
                    },
                    timeout=10
                )
                
                if resp.status_code == 200:
                    print(f"Heartbeat sent successfully to {main_url}")
                    
                    # Update local mirrors table to reflect master server's state
                    mirrors_data = resp.json().get('mirrors', [])
                    if mirrors_data:
                        # Synchronize the list of mirrors
                        try:
                            # Keep track of active IDs to find deleted ones (optional, but good for completeness)
                            seen_keys = set()
                            
                            for m in mirrors_data:
                                seen_keys.add(m['api_key'])
                                local_mirror = Mirror.query.filter_by(api_key=m['api_key']).first()
                                if not local_mirror:
                                    local_mirror = Mirror(api_key=m['api_key'])
                                    db.session.add(local_mirror)
                                    
                                local_mirror.name = m['name']
                                local_mirror.url = m['url']
                                local_mirror.location = m['location']
                                local_mirror.storage_limit_gb = m['storage_limit_gb']
                                local_mirror.download_speed_limit_kbps = m.get('download_speed_limit_kbps', 0)
                                local_mirror.is_active = m['is_active']
                            
                            # Do not delete missing ones immediately as it might drop replica references,
                            # but we can optionally mark them inactive.
                            
                            db.session.commit()
                        except Exception as sync_e:
                            db.session.rollback()
                            print(f"Error syncing mirrors from heartbeat: {sync_e}")
                            
                else:
                    print(f"Heartbeat failed: {resp.status_code} - {resp.text}")
                    
            except Exception as e:
                print(f"Heartbeat error: {e}")
                
            time.sleep(60)

def start_mirror_client(app):
    """Starts the mirror client background tasks if configured."""
    if app.config.get('MIRROR_API_KEY'):
        thread = threading.Thread(target=mirror_heartbeat_loop, args=(app,), daemon=True)
        thread.start()

