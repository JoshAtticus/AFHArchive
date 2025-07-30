from flask import Blueprint, send_file, request, current_app, abort, Response, jsonify
from flask_login import current_user, login_required
import os
import time
import uuid
import hashlib
import json
import threading
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
                        os.remove(final_path)
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
                        os.remove(final_path)
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
    os.remove(status_path)
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
            os.remove(final_path)
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
