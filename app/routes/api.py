from flask import Blueprint, send_file, request, current_app, abort, Response, jsonify
from flask_login import current_user, login_required
import os
import time
import uuid
import hashlib
from app.models import Upload, User
from app import db
from app.utils.rate_limiter import RateLimiter
from app.utils.file_handler import allowed_file, calculate_md5
from werkzeug.utils import secure_filename

api_bp = Blueprint('api', __name__)

# Initialize rate limiter
rate_limiter = RateLimiter()

@api_bp.route('/download/<int:upload_id>')
def download_file(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    
    if upload.status != 'approved':
        abort(404)
    
    # Convert relative path to absolute path
    if not os.path.isabs(upload.file_path):
        # Make path relative to application root directory (go up from app/routes/api.py to project root)
        app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        file_path = os.path.join(app_root, upload.file_path)
    else:
        file_path = upload.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        abort(404)
    
    # Get bandwidth limit from config
    download_speed_limit = current_app.config['DOWNLOAD_SPEED_LIMIT']
    
    # Create bandwidth-limited file object
    limited_file = rate_limiter.create_limited_file(file_path, download_speed_limit)
    
    def generate():
        """Generator function to stream file with bandwidth limiting"""
        try:
            while True:
                # Read in 64KB chunks
                chunk = limited_file.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            limited_file.close()
    
    # Create response with proper headers
    response = Response(
        generate(),
        mimetype='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{upload.original_filename}"',
            'Content-Length': str(upload.file_size)
        }
    )
    
    return response

@api_bp.route('/bandwidth-status')
def bandwidth_status():
    """Debug endpoint to show current bandwidth usage"""
    info = rate_limiter.get_active_downloads_info()
    total_bps = info['total_bandwidth']
    speed_per_download_bps = info['speed_per_download']
    
    return {
        'active_downloads': info['active_count'],
        'total_bandwidth': {
            'bytes_per_sec': total_bps,
            'MB_per_sec': round(total_bps / 1048576, 2),
            'Mbps': round(total_bps * 8 / 1000000, 2)
        },
        'speed_per_download': {
            'bytes_per_sec': speed_per_download_bps,
            'MB_per_sec': round(speed_per_download_bps / 1048576, 2) if speed_per_download_bps > 0 else 0,
            'Mbps': round(speed_per_download_bps * 8 / 1000000, 2) if speed_per_download_bps > 0 else 0
        }
    }

@api_bp.route('/upload-progress', methods=['POST'])
@login_required
def upload_with_progress():
    """Handle file upload with progress tracking"""
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Get metadata from form
        device_manufacturer = request.form.get('device_manufacturer', '').strip()
        device_model = request.form.get('device_model', '').strip()
        afh_link = request.form.get('afh_link', '').strip()
        xda_thread = request.form.get('xda_thread', '').strip()
        notes = request.form.get('notes', '').strip()
        
        # Validate required fields
        if not device_manufacturer:
            return jsonify({'error': 'Device manufacturer is required'}), 400
        
        if not device_model:
            return jsonify({'error': 'Device model is required'}), 400
        
        # Generate unique filename
        original_filename = secure_filename(file.filename)
        file_extension = original_filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
        
        # Create upload path
        upload_dir = current_app.config['UPLOAD_FOLDER']
        file_path = os.path.join(upload_dir, unique_filename)
        
        # Save file with progress tracking
        file_size = 0
        chunk_size = 64 * 1024  # 64KB chunks
        
        with open(file_path, 'wb') as f:
            while True:
                chunk = file.stream.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                file_size += len(chunk)
        
        # Calculate MD5 hash
        md5_hash = calculate_md5(file_path)
        
        # Create upload record
        upload = Upload(
            filename=unique_filename,
            original_filename=file.filename,
            file_path=file_path,
            file_size=file_size,
            md5_hash=md5_hash,
            device_manufacturer=device_manufacturer,
            device_model=device_model,
            afh_link=afh_link,
            xda_thread=xda_thread,
            notes=notes,
            user_id=current_user.id
        )
        
        db.session.add(upload)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'File uploaded successfully and is pending review',
            'upload_id': upload.id
        })
        
    except Exception as e:
        current_app.logger.error(f'Upload error: {str(e)}')
        return jsonify({'error': 'Upload failed. Please try again.'}), 500
