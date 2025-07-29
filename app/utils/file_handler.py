import os
import hashlib
import uuid
from werkzeug.utils import secure_filename
from flask import current_app

def get_allowed_extensions():
    """Get allowed extensions from config or use default"""
    try:
        from decouple import config
        return config('ALLOWED_EXTENSIONS', default='zip,apk,img,tar,gz,xz,7z,rar,md5').split(',')
    except ImportError:
        return ['zip', 'apk', 'img', 'tar', 'gz', 'xz', '7z', 'rar', 'md5']

ALLOWED_EXTENSIONS = get_allowed_extensions()

def allowed_file(filename):
    """Check if the file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_md5(file_path):
    """Calculate MD5 hash of a file"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def save_upload_file(file):
    """
    Save uploaded file and return filename, path, size, and MD5 hash
    """
    if not file or not allowed_file(file.filename):
        raise ValueError("Invalid file")
    
    # Generate unique filename
    original_filename = secure_filename(file.filename)
    file_extension = original_filename.rsplit('.', 1)[1].lower()
    unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
    
    # Create upload path
    upload_dir = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_dir, unique_filename)
    
    # Save file
    file.save(file_path)
    
    # Get file size
    file_size = os.path.getsize(file_path)
    
    # Calculate MD5 hash
    md5_hash = calculate_md5(file_path)
    
    return unique_filename, file_path, file_size, md5_hash

def delete_upload_file(file_path):
    """Delete an uploaded file"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    except Exception as e:
        current_app.logger.error(f"Error deleting file {file_path}: {str(e)}")
    return False
