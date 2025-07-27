from flask import Blueprint, send_file, request, current_app, abort, Response, jsonify
from flask_login import current_user, login_required
import os
import time
import uuid
import hashlib
import json
from datetime import datetime
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
    try:
        # Log the download request
        current_app.logger.info(f'Download request for upload ID: {upload_id}')
        
        upload = Upload.query.get(upload_id)
        if not upload:
            current_app.logger.warning(f'Upload not found: {upload_id}')
            abort(404)
        
        # Log upload details for debugging
        current_app.logger.info(f'Upload found - ID: {upload.id}, Status: {upload.status}, Path: {upload.file_path}')
        
        if upload.status != 'approved':
            current_app.logger.warning(f'Upload not approved: {upload_id}, status: {upload.status}')
            abort(404)
        
        # Convert relative path to absolute path
        if not os.path.isabs(upload.file_path):
            # Make path relative to application root directory (go up from app/routes/api.py to project root)
            app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            file_path = os.path.join(app_root, upload.file_path)
        else:
            file_path = upload.file_path
        
        # Log file path resolution
        current_app.logger.info(f'Resolved file path: {file_path}')
        
        # Check if file exists
        if not os.path.exists(file_path):
            current_app.logger.error(f'File not found on disk: {file_path}')
            abort(404)
        
        # Verify file is readable
        try:
            with open(file_path, 'rb') as test_file:
                test_file.read(1)
        except (IOError, OSError) as e:
            current_app.logger.error(f'File not readable: {file_path}, error: {str(e)}')
            abort(404)
        
        current_app.logger.info(f'Starting download for file: {upload.original_filename}')
        
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
            except Exception as e:
                current_app.logger.error(f'Error during file streaming: {str(e)}')
                raise
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
        
    except Exception as e:
        current_app.logger.error(f'Unexpected error in download_file: {str(e)}')
        abort(404)

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

@api_bp.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        # Check database connectivity
        upload_count = Upload.query.count()
        approved_count = Upload.query.filter_by(status='approved').count()
        
        # Check upload directory
        upload_dir = current_app.config['UPLOAD_FOLDER']
        upload_dir_exists = os.path.exists(upload_dir)
        upload_dir_writable = os.access(upload_dir, os.W_OK) if upload_dir_exists else False
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'database': {
                'connected': True,
                'total_uploads': upload_count,
                'approved_uploads': approved_count
            },
            'storage': {
                'upload_dir': upload_dir,
                'exists': upload_dir_exists,
                'writable': upload_dir_writable
            },
            'config': {
                'max_content_length': current_app.config.get('MAX_CONTENT_LENGTH'),
                'download_speed_limit': current_app.config.get('DOWNLOAD_SPEED_LIMIT')
            }
        })
    except Exception as e:
        current_app.logger.error(f'Health check failed: {str(e)}')
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

@api_bp.route('/debug/upload/<int:upload_id>')
def debug_upload(upload_id):
    """Debug endpoint to check upload and file status"""
    try:
        upload = Upload.query.get(upload_id)
        if not upload:
            return jsonify({
                'error': 'Upload not found',
                'upload_id': upload_id,
                'exists': False
            }), 404
        
        # Check file path resolution
        if not os.path.isabs(upload.file_path):
            app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            resolved_path = os.path.join(app_root, upload.file_path)
        else:
            resolved_path = upload.file_path
        
        file_exists = os.path.exists(resolved_path)
        file_readable = False
        file_size_on_disk = None
        
        if file_exists:
            try:
                with open(resolved_path, 'rb') as test_file:
                    test_file.read(1)
                file_readable = True
                file_size_on_disk = os.path.getsize(resolved_path)
            except (IOError, OSError):
                pass
        
        return jsonify({
            'upload_id': upload.id,
            'exists': True,
            'status': upload.status,
            'is_approved': upload.status == 'approved',
            'original_filename': upload.original_filename,
            'stored_filename': upload.filename,
            'file_path_stored': upload.file_path,
            'file_path_resolved': resolved_path,
            'file_path_is_absolute': os.path.isabs(upload.file_path),
            'file_exists': file_exists,
            'file_readable': file_readable,
            'file_size_in_db': upload.file_size,
            'file_size_on_disk': file_size_on_disk,
            'size_matches': file_size_on_disk == upload.file_size if file_size_on_disk is not None else None,
            'upload_date': upload.uploaded_at.isoformat() if upload.uploaded_at else None,
            'download_count': upload.download_count
        })
        
    except Exception as e:
        current_app.logger.error(f'Error in debug_upload: {str(e)}')
        return jsonify({
            'error': 'Internal server error',
            'details': str(e),
            'upload_id': upload_id
        }), 500

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
        
        # Calculate chunk size (1MB) and total chunks
        chunk_size = 1 * 1024 * 1024  # 1MB
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
