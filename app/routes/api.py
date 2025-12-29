from flask import Blueprint, send_file, request, current_app, abort, Response, jsonify
from flask_login import current_user, login_required
import os
import time
import uuid
import hashlib
import json
import threading
import re
from app.models import Upload, User, Mirror
from app import db
from app.utils.rate_limiter import RateLimiter, FixedRateLimitedFile
from app.utils.file_handler import allowed_file, calculate_md5, safe_remove_file
from werkzeug.utils import secure_filename

api_bp = Blueprint('api', __name__)

# Initialize rate limiters
rate_limiter = RateLimiter()
mirror_rate_limiter = RateLimiter()

@api_bp.route('/info/<int:upload_id>')
def get_upload_info(upload_id):
    """Get metadata for an upload (public)"""
    upload = Upload.query.get_or_404(upload_id)
    
    if upload.status != 'approved':
        abort(404)
        
    return jsonify({
        'id': upload.id,
        'filename': upload.filename,
        'original_filename': upload.original_filename,
        'file_size': upload.file_size,
        'md5_hash': upload.md5_hash,
        'device_manufacturer': upload.device_manufacturer,
        'device_model': upload.device_model,
        'uploaded_at': upload.uploaded_at.isoformat() if upload.uploaded_at else None
    })

@api_bp.route('/download/<int:upload_id>')
def download_file(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    
    # Check for Mirror API Key
    mirror_key = request.headers.get('X-Mirror-Api-Key')
    is_mirror = False
    if mirror_key:
        mirror = Mirror.query.filter_by(api_key=mirror_key).first()
        if mirror and mirror.is_active:
            is_mirror = True
            current_app.logger.info(f"Mirror download request from {mirror.name}")
        else:
            current_app.logger.warning(f"Invalid or inactive mirror key: {mirror_key}")
    
    if not is_mirror:
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
        # Try fallback to uploads folder
        fallback_path = os.path.join(current_app.config['UPLOAD_FOLDER'], os.path.basename(file_path))
        if os.path.exists(fallback_path):
            file_path = fallback_path
        else:
            current_app.logger.error(f"File not found for upload {upload_id}. Path: {file_path}, Fallback: {fallback_path}")
            abort(404)
    
    file_size = os.path.getsize(file_path)

    # Handle Range Header
    range_header = request.headers.get('Range', None)
    byte1, byte2 = 0, None
    if range_header:
        m = re.search(r'bytes=(\d+)-(\d*)', range_header)
        if m:
            g = m.groups()
            if g[0]: byte1 = int(g[0])
            if g[1]: byte2 = int(g[1])

    length = file_size - byte1
    if byte2 is not None:
        length = byte2 + 1 - byte1
    
    # Ensure length is valid
    if length < 0:
        length = 0
    if byte1 >= file_size:
        return Response('Requested Range Not Satisfiable', 416)

    # Get bandwidth limit from config
    download_speed_limit = current_app.config['DOWNLOAD_SPEED_LIMIT']
    mirror_speed_limit = current_app.config.get('MIRROR_SYNC_SPEED_LIMIT', 1638400)
    # Capture logger to avoid context issues in generator
    app_logger = current_app.logger 
    
    def generate():
        """Stream file with bandwidth limiting"""
        try:
            if is_mirror:
                # Rate limit for mirrors (default 12.5 Mbps)
                # Use shared pool for mirrors to handle parallel downloads
                app_logger.info(f"Starting mirror download with limit: {mirror_speed_limit} bps (Shared Pool)")
                f = mirror_rate_limiter.create_limited_file(file_path, mirror_speed_limit)
            else:
                # Rate limit for users
                app_logger.info(f"Starting user download with limit: {download_speed_limit} bps")
                f = rate_limiter.create_limited_file(file_path, download_speed_limit)
            
            with f:
                f.seek(byte1)
                remaining = length
                while remaining > 0:
                    chunk_size = min(65536, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    yield data
                    remaining -= len(data)
        except Exception as e:
            app_logger.error(f'Download streaming error: {str(e)}')
    
    headers = {
        'Content-Disposition': f'attachment; filename="{upload.original_filename}"',
        'Content-Length': str(length),
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Accept-Ranges': 'bytes'
    }

    status_code = 200
    if range_header:
        status_code = 206
        headers['Content-Range'] = f'bytes {byte1}-{byte1 + length - 1}/{file_size}'

    # Create response with proper headers
    response = Response(
        generate(),
        status=status_code,
        mimetype='application/octet-stream',
        headers=headers
    )
    return response

@api_bp.route('/download/<int:upload_id>/direct')
def download_file_direct(upload_id):
    """Direct download endpoint for mirrors (alias for download_file)"""
    return download_file(upload_id)

def complete_chunked_upload():
    """Assemble chunks into final file and create upload record asynchronously"""
    try:
        data = request.get_json()
        upload_id = data.get('uploadId', '')
        total_chunks = int(data.get('totalChunks', 0))
        original_filename = data.get('originalFilename', '')
        file_hash = data.get('fileHash', '')
        device_manufacturer = data.get('deviceManufacturer', '').strip()
        device_model = data.get('deviceModel', '').strip()
        afh_link = data.get('afhLink', '').strip()
        xda_thread = data.get('xdaThread', '').strip()
        notes = data.get('notes', '').strip()

        # Validate required fields
        if not upload_id or not original_filename:
            return jsonify({'error': 'Missing required parameters'}), 400
        if not device_manufacturer:
            return jsonify({'error': 'Device manufacturer is required'}), 400
        if not device_model:
            return jsonify({'error': 'Device model is required'}), 400
        if not allowed_file(original_filename):
            return jsonify({'error': 'File type not allowed'}), 400

        # Get chunks directory
        chunks_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'chunks', upload_id)
        if not os.path.exists(chunks_dir):
            return jsonify({'error': 'Chunks not found'}), 404

        # Check for missing chunks
        missing_chunks = []
        for i in range(total_chunks):
            chunk_filename = f"chunk_{i:04d}"
            chunk_path = os.path.join(chunks_dir, chunk_filename)
            if not os.path.exists(chunk_path):
                missing_chunks.append(i)
        if missing_chunks:
            return jsonify({'error': f'Missing chunks: {missing_chunks}'}), 400

        # Start background thread for assembly and DB insert
        def process_upload_async(user_id, upload_id, total_chunks, original_filename, file_hash, device_manufacturer, device_model, afh_link, xda_thread, notes, chunks_dir):
            app = current_app._get_current_object()
            with app.app_context():
                try:
                    secure_original = secure_filename(original_filename)
                    file_extension = secure_original.rsplit('.', 1)[1].lower()
                    unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
                    final_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    total_size = 0
                    with open(final_path, 'wb') as final_file:
                        for i in range(total_chunks):
                            chunk_filename = f"chunk_{i:04d}"
                            chunk_path = os.path.join(chunks_dir, chunk_filename)
                            with open(chunk_path, 'rb') as chunk_file:
                                chunk_data = chunk_file.read()
                                final_file.write(chunk_data)
                                total_size += len(chunk_data)
                    md5_hash = calculate_md5(final_path)
                    # Check for duplicate MD5
                    duplicate = Upload.query.filter_by(md5_hash=md5_hash).first()
                    if duplicate:
                        # Auto-reject: do not save file, but record rejected upload for user
                        safe_remove_file(final_path)
                        cleanup_chunks_dir(chunks_dir)
                        upload = Upload(
                            filename=unique_filename,
                            original_filename=original_filename,
                            file_path=final_path,
                            file_size=total_size,
                            md5_hash=md5_hash,
                            device_manufacturer=device_manufacturer,
                            device_model=device_model,
                            afh_link=afh_link,
                            xda_thread=xda_thread,
                            notes=notes,
                            user_id=user_id,
                            status='rejected',
                            rejection_reason='Thank you for your contribution, this file has already been uploaded and is not needed.'
                        )
                        db.session.add(upload)
                        db.session.commit()
                        status = {'error': 'Duplicate file. Auto-rejected.', 'rejected': True}
                    elif file_hash and md5_hash != file_hash:
                        safe_remove_file(final_path)
                        cleanup_chunks_dir(chunks_dir)
                        status = {'error': 'File integrity check failed'}
                    else:
                        upload = Upload(
                            filename=unique_filename,
                            original_filename=original_filename,
                            file_path=final_path,
                            file_size=total_size,
                            md5_hash=md5_hash,
                            device_manufacturer=device_manufacturer,
                            device_model=device_model,
                            afh_link=afh_link,
                            xda_thread=xda_thread,
                            notes=notes,
                            user_id=user_id
                        )
                        db.session.add(upload)
                        db.session.commit()
                        status = {'success': True, 'upload_id': upload.id}
                    cleanup_chunks_dir(chunks_dir)
                except Exception as e:
                    app.logger.error(f'Async complete upload error: {str(e)}')
                    status = {'error': 'Failed to complete upload'}
                # Save status to a temp file for polling
                status_path = os.path.join(app.config['UPLOAD_FOLDER'], 'chunks', f'{upload_id}_status.json')
                with open(status_path, 'w') as f:
                    json.dump(status, f)

        # Start thread
        thread = threading.Thread(target=process_upload_async, args=(current_user.id, upload_id, total_chunks, original_filename, file_hash, device_manufacturer, device_model, afh_link, xda_thread, notes, chunks_dir))
        thread.start()

        return jsonify({
            'success': True,
            'message': 'Upload is being processed asynchronously. You can check status shortly.'
        })
    except Exception as e:
        current_app.logger.error(f'Complete upload error: {str(e)}')
        return jsonify({'error': 'Failed to complete upload'}), 500

# Endpoint to poll for upload completion status
@api_bp.route('/upload-status/<upload_id>')
@login_required
def upload_status(upload_id):
    status_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'chunks', f'{upload_id}_status.json')
    if not os.path.exists(status_path):
        return jsonify({'processing': True})
    with open(status_path, 'r') as f:
        status = json.load(f)
    # Optionally, delete status file after reading
    safe_remove_file(status_path)
    return jsonify(status)


@api_bp.route('/upload-chunk', methods=['POST'])
@login_required
def upload_chunk():
    """Handle individual chunk upload"""
    try:
        # Get chunk metadata
        chunk_index = int(request.form.get('chunkIndex', 0))
        total_chunks = int(request.form.get('totalChunks', 1))
        upload_id = request.form.get('uploadId', '')
        file_hash = request.form.get('fileHash', '')  # Original file hash for verification
        
        if not upload_id:
            return jsonify({'error': 'Upload ID is required'}), 400
            
        # Get the chunk file
        if 'chunk' not in request.files:
            return jsonify({'error': 'No chunk data'}), 400
            
        chunk_file = request.files['chunk']
        if not chunk_file:
            return jsonify({'error': 'Empty chunk'}), 400
        
        # Create chunks directory
        chunks_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'chunks', upload_id)
        os.makedirs(chunks_dir, exist_ok=True)
        
        # Save chunk with index
        chunk_filename = f"chunk_{chunk_index:04d}"
        chunk_path = os.path.join(chunks_dir, chunk_filename)
        
        chunk_file.save(chunk_path)
        
        # Verify chunk was saved
        if not os.path.exists(chunk_path):
            return jsonify({'error': 'Failed to save chunk'}), 500
            
        return jsonify({
            'success': True,
            'chunkIndex': chunk_index,
            'totalChunks': total_chunks,
            'uploadId': upload_id
        })
        
    except Exception as e:
        current_app.logger.error(f'Chunk upload error: {str(e)}')
        return jsonify({'error': 'Chunk upload failed'}), 500

@api_bp.route('/upload-complete', methods=['POST'])
@login_required
def complete_chunked_upload():
    """Assemble chunks into final file and create upload record"""
    try:
        data = request.get_json()
        upload_id = data.get('uploadId', '')
        total_chunks = int(data.get('totalChunks', 0))
        original_filename = data.get('originalFilename', '')
        file_hash = data.get('fileHash', '')
        
        # Get metadata
        device_manufacturer = data.get('deviceManufacturer', '').strip()
        device_model = data.get('deviceModel', '').strip()
        afh_link = data.get('afhLink', '').strip()
        xda_thread = data.get('xdaThread', '').strip()
        notes = data.get('notes', '').strip()
        
        # Validate required fields
        if not upload_id or not original_filename:
            return jsonify({'error': 'Missing required parameters'}), 400
            
        if not device_manufacturer:
            return jsonify({'error': 'Device manufacturer is required'}), 400
            
        if not device_model:
            return jsonify({'error': 'Device model is required'}), 400
            
        if not allowed_file(original_filename):
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Get chunks directory
        chunks_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'chunks', upload_id)
        
        if not os.path.exists(chunks_dir):
            return jsonify({'error': 'Chunks not found'}), 404
        
        # Verify all chunks exist
        missing_chunks = []
        for i in range(total_chunks):
            chunk_filename = f"chunk_{i:04d}"
            chunk_path = os.path.join(chunks_dir, chunk_filename)
            if not os.path.exists(chunk_path):
                missing_chunks.append(i)
        
        if missing_chunks:
            return jsonify({'error': f'Missing chunks: {missing_chunks}'}), 400
        
        # Generate final filename
        secure_original = secure_filename(original_filename)
        file_extension = secure_original.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
        
        # Create final file path
        final_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Assemble chunks into final file
        total_size = 0
        with open(final_path, 'wb') as final_file:
            for i in range(total_chunks):
                chunk_filename = f"chunk_{i:04d}"
                chunk_path = os.path.join(chunks_dir, chunk_filename)
                
                with open(chunk_path, 'rb') as chunk_file:
                    chunk_data = chunk_file.read()
                    final_file.write(chunk_data)
                    total_size += len(chunk_data)
        
        # Calculate MD5 hash of assembled file
        md5_hash = calculate_md5(final_path)
        
        # Verify file hash if provided
        if file_hash and md5_hash != file_hash:
            # Clean up files
            safe_remove_file(final_path)
            cleanup_chunks_dir(chunks_dir)
            return jsonify({'error': 'File integrity check failed'}), 400
        
        # Create upload record
        upload = Upload(
            filename=unique_filename,
            original_filename=original_filename,
            file_path=final_path,
            file_size=total_size,
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
        
        # Clean up chunks
        cleanup_chunks_dir(chunks_dir)
        
        return jsonify({
            'success': True,
            'message': 'File uploaded successfully and is pending review',
            'upload_id': upload.id
        })
        
    except Exception as e:
        current_app.logger.error(f'Complete upload error: {str(e)}')
        return jsonify({'error': 'Failed to complete upload'}), 500

def cleanup_chunks_dir(chunks_dir):
    """Clean up temporary chunks directory"""
    try:
        import shutil
        if os.path.exists(chunks_dir):
            shutil.rmtree(chunks_dir)
    except Exception as e:
        current_app.logger.error(f'Error cleaning up chunks: {str(e)}')

@api_bp.route('/upload-init', methods=['POST'])
@login_required
def init_chunked_upload():
    """Initialize a chunked upload session"""
    try:
        data = request.get_json()
        filename = data.get('filename', '')
        file_size = int(data.get('fileSize', 0))
        
        if not filename or file_size <= 0:
            return jsonify({'error': 'Invalid file parameters'}), 400
            
        if not allowed_file(filename):
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Check file size limit (5GB)
        max_size = 5 * 1024 * 1024 * 1024
        if file_size > max_size:
            return jsonify({'error': 'File too large. Maximum size is 5GB'}), 400
        
        # Generate upload session ID
        upload_id = str(uuid.uuid4())
        
        # Calculate chunk size (5MB) and total chunks
        chunk_size = 5 * 1024 * 1024  # 5MB
        total_chunks = (file_size + chunk_size - 1) // chunk_size
        
        return jsonify({
            'success': True,
            'uploadId': upload_id,
            'chunkSize': chunk_size,
            'totalChunks': total_chunks
        })
        
    except Exception as e:
        current_app.logger.error(f'Init upload error: {str(e)}')
        return jsonify({'error': 'Failed to initialize upload'}), 500
