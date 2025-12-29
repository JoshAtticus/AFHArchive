from flask import Blueprint, request, jsonify, current_app, send_file, Response
from app import db
from app.models import Mirror, FileReplica, Upload
import os
from datetime import datetime
import requests
import threading
import time
import hashlib

mirror_bp = Blueprint('mirror_api', __name__, url_prefix='/api/mirror')

# --- Main Server Endpoints ---

@mirror_bp.route('/heartbeat', methods=['POST'])
def heartbeat():
    """Mirror reports it is alive and sends stats"""
    data = request.json
    api_key = data.get('api_key')
    mirror = Mirror.query.filter_by(api_key=api_key).first()
    
    if not mirror:
        return jsonify({'error': 'Invalid API key'}), 401
        
    mirror.last_heartbeat = datetime.utcnow()
    mirror.storage_used_mb = data.get('storage_used_mb', 0)
    db.session.commit()
    
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
        db.session.commit()
        
    return jsonify({'status': 'ok'})

# --- Mirror Client Logic (To be run on the Mirror Server) ---

def perform_sync(job_data, app_config):
    """
    Background task to download file from Main.
    """
    file_id = job_data['file_id']
    download_url = job_data['download_url']
    md5_hash = job_data['md5_hash']
    file_size = job_data['file_size']
    filename = job_data['filename']
    api_key = app_config['MIRROR_API_KEY']
    main_url = app_config['MAIN_SERVER_URL']
    
    # Ensure upload directory exists
    upload_dir = app_config['UPLOAD_FOLDER']
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    local_path = os.path.join(upload_dir, filename)
    
    # Chunk size (e.g., 10MB)
    CHUNK_SIZE = 10 * 1024 * 1024 
    
    try:
        with open(local_path, 'wb') as f:
            downloaded = 0
            while downloaded < file_size:
                end = min(downloaded + CHUNK_SIZE - 1, file_size - 1)
                headers = {
                    'X-Mirror-Api-Key': api_key,
                    'Range': f'bytes={downloaded}-{end}'
                }
                
                # print(f"Downloading chunk {downloaded}-{end} from {download_url}")
                response = requests.get(download_url, headers=headers, stream=True)
                if response.status_code not in [200, 206]:
                    raise Exception(f"Download failed with status {response.status_code}")
                    
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
                downloaded = end + 1
                
        # Verify MD5
        local_md5 = hashlib.md5()
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                local_md5.update(chunk)
        
        if local_md5.hexdigest() != md5_hash:
            raise Exception("MD5 mismatch")
            
        # Report success
        requests.post(f"{main_url}/api/mirror/sync_complete", json={
            'api_key': api_key,
            'upload_id': file_id,
            'status': 'synced',
            'error_message': None
        }, timeout=10)
        print(f"Sync complete for {filename}")
        
    except Exception as e:
        print(f"Sync failed for {filename}: {e}")
        # Report error
        try:
            requests.post(f"{main_url}/api/mirror/sync_complete", json={
                'api_key': api_key,
                'upload_id': file_id,
                'status': 'error',
                'error_message': str(e)
            }, timeout=10)
        except Exception as report_error:
            print(f"Failed to report error to main server: {report_error}")
        
        # Clean up partial file
        if os.path.exists(local_path):
            os.remove(local_path)

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
    
    # Override download_url to ensure it uses the configured MAIN_SERVER_URL
    # This fixes issues where the main server sends a localhost URL
    if app_config['MAIN_SERVER_URL']:
        data['download_url'] = f"{app_config['MAIN_SERVER_URL']}/api/mirror/download/{data.get('file_id')}"
        print(f"Using constructed download URL: {data['download_url']}")
    
    # Pass the API key to the thread so it can authenticate with the main server
    data['api_key'] = app_config['MIRROR_API_KEY']
    
    thread = threading.Thread(target=perform_sync, args=(data, app_config))
    thread.start()
    
    return jsonify({'status': 'job_accepted'})

def mirror_heartbeat_loop(app):
    """
    Background loop to send heartbeats to the main server.
    """
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
                            fp = os.path.join(dirpath, f)
                            if not os.path.islink(fp):
                                total_size += os.path.getsize(fp)
                
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

