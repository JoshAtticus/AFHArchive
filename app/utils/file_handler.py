import os
import hashlib
import uuid
from werkzeug.utils import secure_filename
from flask import current_app

def get_allowed_extensions():
    """Get allowed extensions from config or use default"""
    try:
        from decouple import config
        return config('ALLOWED_EXTENSIONS', default='zip,apk,img,tar,gz,xz,7z,rar,md5,tgz').split(',')
    except ImportError:
        return ['zip', 'apk', 'img', 'tar', 'gz', 'xz', '7z', 'rar', 'md5', 'tgz']

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
    Checks for duplicates but doesn't prevent saving - lets autoreviewer handle rejection
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
    
    # Check for duplicates and log, but don't prevent saving
    # The autoreviewer will handle rejection after the upload record is created
    try:
        from app.utils.autoreviewer import check_for_duplicates_by_hash
        is_duplicate, existing_upload = check_for_duplicates_by_hash(md5_hash)
        
        if is_duplicate:
            current_app.logger.info(
                f"Duplicate detected for {original_filename} (MD5: {md5_hash}) - "
                f"matches upload {existing_upload.id} ({existing_upload.original_filename}). "
                f"File saved, autoreviewer will handle rejection."
            )
        else:
            current_app.logger.info(f"No duplicates found for {original_filename} (MD5: {md5_hash})")
            
    except ImportError:
        # If autoreviewer is not available, continue without duplicate checking
        current_app.logger.warning("Autoreviewer not available for duplicate checking")
    except Exception as e:
        # Don't fail the upload if duplicate checking fails
        current_app.logger.error(f"Error during duplicate checking: {str(e)}")
    
    return unique_filename, file_path, file_size, md5_hash

def delete_upload_file(file_path):
    """Delete an uploaded file"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            current_app.logger.info(f"Successfully deleted file: {file_path}")
        else:
            current_app.logger.info(f"File not found (already deleted): {file_path}")
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting file {file_path}: {str(e)}")
        return False

def safe_remove_file(file_path):
    """Safely remove a file, logging but not failing if file doesn't exist"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            current_app.logger.debug(f"Removed file: {file_path}")
        else:
            current_app.logger.debug(f"File not found for removal: {file_path}")
    except Exception as e:
        current_app.logger.warning(f"Failed to remove file {file_path}: {str(e)}")

def format_file_size(size_bytes):
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"
