from flask import Blueprint, request, jsonify, current_app, send_file, Response
from app import db
from app.models import Mirror, FileReplica, Upload
import os
import re
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

@mirror_bp.route('/download/<int:upload_id>', methods=['GET'])
def download_chunk(upload_id):
    """
    Endpoint for mirrors to download file chunks.
    Requires API key in header.
    Supports Range header.
    """
    api_key = request.headers.get('X-Mirror-Api-Key')
    mirror = Mirror.query.filter_by(api_key=api_key).first()
    if not mirror:
        return jsonify({'error': 'Unauthorized'}), 401
        
    upload = Upload.query.get_or_404(upload_id)
    
    file_path = upload.file_path
    if not os.path.isabs(file_path):
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_path)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
        
    size = os.path.getsize(file_path)
    
    range_header = request.headers.get('Range', None)
    if not range_header:
        return send_file(file_path)
        
    byte1, byte2 = 0, None
    
    m = re.search(r'bytes=(\d+)-(\d*)', range_header)
    if m:
        g = m.groups()
        if g[0]: byte1 = int(g[0])
        if g[1]: byte2 = int(g[1])
    
    length = size - byte1
    if byte2 is not None:
        length = byte2 + 1 - byte1
        
    with open(file_path, 'rb') as f:
        f.seek(byte1)
        data = f.read(length)
        
    rv = Response(data, 206, mimetype='application/octet-stream', direct_passthrough=True)
    rv.headers.add('Content-Range', 'bytes {0}-{1}/{2}'.format(byte1, byte1 + length - 1, size))
    return rv

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
        })
        
    except Exception as e:
        # Report error
        requests.post(f"{main_url}/api/mirror/sync_complete", json={
            'api_key': api_key,
            'upload_id': file_id,
            'status': 'error',
            'error_message': str(e)
        })
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
    app_config = {
        'UPLOAD_FOLDER': current_app.config['UPLOAD_FOLDER'],
        'MIRROR_API_KEY': current_app.config.get('MIRROR_API_KEY'),
        'MAIN_SERVER_URL': current_app.config.get('MAIN_SERVER_URL')
    }
    
    if not app_config['MIRROR_API_KEY']:
        return jsonify({'error': 'This server is not configured as a mirror'}), 400
        
    # Start background thread
    thread = threading.Thread(target=perform_sync, args=(data, app_config))
    thread.start()
    
    return jsonify({'status': 'job_accepted'})
