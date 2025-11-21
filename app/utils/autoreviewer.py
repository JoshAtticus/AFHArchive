"""
Autoreviewer system for automatically rejecting duplicate files.
This system acts as an automated admin that reviews uploaded files
and rejects duplicates based on MD5 hash comparison.
"""

from datetime import datetime
from flask import current_app
from app import db
from app.models import Upload, User
from app.utils.email_utils import send_email, render_email_template
from threading import Timer
from collections import defaultdict

# Store pending notifications to batch them
pending_autoreviewer_notifications = defaultdict(lambda: {'rejected': [], 'timer': None})

def get_or_create_autoreviewer():
    """Get or create the autoreviewer user"""
    autoreviewer = User.query.filter_by(email='autoreviewer@afh.joshattic.us').first()
    
    if not autoreviewer:
        autoreviewer = User(
            google_id='autoreviewer_system',
            email='autoreviewer@afh.joshattic.us',
            name='Autoreviewer',
            avatar_url=None,
            is_admin=True,
            created_at=datetime.utcnow()
        )
        db.session.add(autoreviewer)
        db.session.commit()
        current_app.logger.info("Created autoreviewer system user")
    
    return autoreviewer

def check_for_duplicates_by_hash(md5_hash):
    """
    Check if a file with the given MD5 hash already exists.
    Returns tuple (is_duplicate, existing_upload)
    """
    current_app.logger.info(f"Checking for duplicates by MD5 hash: {md5_hash}")
    
    existing_upload = Upload.query.filter(
        Upload.md5_hash == md5_hash,
        Upload.status.in_(['approved', 'pending'])
    ).first()
    
    if existing_upload:
        current_app.logger.info(f"Found duplicate: Upload {existing_upload.id} ({existing_upload.original_filename})")
        return True, existing_upload
    else:
        current_app.logger.info("No duplicates found for this hash")
        return False, None

def check_for_duplicates(upload):
    """
    Check if an upload is a duplicate based on MD5 hash.
    Returns tuple (is_duplicate, existing_upload)
    """
    current_app.logger.info(f"Checking for duplicates of upload {upload.id} with MD5 {upload.md5_hash}")
    
    existing_upload = Upload.query.filter(
        Upload.md5_hash == upload.md5_hash,
        Upload.id != upload.id,
        Upload.status.in_(['approved', 'pending'])
    ).first()
    
    if existing_upload:
        current_app.logger.info(f"Found duplicate: Upload {existing_upload.id} ({existing_upload.original_filename})")
        return True, existing_upload
    else:
        current_app.logger.info("No duplicates found")
        return False, None

def schedule_autoreviewer_notification(user, rejected_uploads):
    """Batch autoreviewer notifications for 5 minutes before sending rejection emails"""
    user_id = user.id
    batch = pending_autoreviewer_notifications[user_id]
    
    # Serialize upload data immediately while still in session context
    for upload in rejected_uploads:
        upload_data = {
            'id': upload.id,
            'original_filename': upload.original_filename,
            'device_manufacturer': upload.device_manufacturer,
            'device_model': upload.device_model,
            'rejection_reason': upload.rejection_reason,
            'reviewed_at': upload.reviewed_at
        }
        batch['rejected'].append(upload_data)
    
    if batch['timer']:
        batch['timer'].cancel()
    
    # Capture the app instance while we're still in the application context
    app = current_app._get_current_object()
    
    # Serialize user data
    user_data = {
        'id': user.id,
        'name': user.name,
        'email': user.email
    }
    
    def send_batched_autoreviewer_email():
        with app.app_context():
            rejected = batch['rejected']
            if not rejected:
                return
            
            subject = "Your uploads were automatically rejected"
            template = 'uploads_rejected.html'
            context = {'user': user_data, 'uploads': rejected}
            
            html = render_email_template(template, **context)
            send_email(user_data['email'], subject, html)
            
            # Clear batch
            pending_autoreviewer_notifications[user_id] = {'rejected': [], 'timer': None}
    
    # Schedule for 5 minutes (300 seconds)
    batch['timer'] = Timer(300, send_batched_autoreviewer_email)
    batch['timer'].start()

def auto_review_upload(upload_id, use_ai=True):
    """
    Automatically review an upload for duplicates and using AI.
    This function should be called after an upload is created.
    
    Args:
        upload_id: ID of the upload to review
        use_ai: Whether to use AI review (default: True)
    
    Returns:
        bool: True if upload was auto-rejected, False otherwise
    """
    try:
        current_app.logger.info(f"Starting autoreviewer for upload {upload_id} (AI: {use_ai})")
        
        upload = Upload.query.get(upload_id)
        if not upload:
            current_app.logger.error(f"Upload {upload_id} not found for auto-review")
            return False
        
        current_app.logger.info(f"Found upload {upload_id}: {upload.original_filename} (status: {upload.status})")
        
        # Only auto-review pending uploads
        if upload.status != 'pending':
            current_app.logger.info(f"Skipping auto-review for upload {upload_id} - status is {upload.status}")
            return False
        
        # Get autoreviewer user
        autoreviewer = get_or_create_autoreviewer()
        current_app.logger.info(f"Using autoreviewer user: {autoreviewer.name} (ID: {autoreviewer.id})")
        
        # PHASE 1: Check for duplicates by MD5 hash
        current_app.logger.info(f"Checking for duplicates of MD5: {upload.md5_hash}")
        is_duplicate, existing_upload = check_for_duplicates(upload)
        
        if is_duplicate:
            # Reject the duplicate upload
            existing_status = existing_upload.status
            existing_id = existing_upload.id
            existing_filename = existing_upload.original_filename
            
            current_app.logger.info(f"Duplicate found! Upload {upload_id} matches upload {existing_id}")
            
            rejection_reason = (
                f"Duplicate file detected. This file already exists in the archive "
                f"(Upload ID: {existing_id}, Status: {existing_status}, "
                f"Filename: {existing_filename}). "
                f"Automatically rejected by Autoreviewer."
            )
            
            upload.status = 'rejected'
            upload.rejection_reason = rejection_reason
            upload.reviewed_at = datetime.utcnow()
            upload.reviewed_by = autoreviewer.id
            
            # Delete the duplicate file since it's rejected
            try:
                from app.utils.file_handler import delete_upload_file
                file_deleted = delete_upload_file(upload.file_path)
                if file_deleted:
                    current_app.logger.info(f"Deleted duplicate file: {upload.file_path}")
                else:
                    current_app.logger.warning(f"Failed to delete duplicate file: {upload.file_path}")
            except Exception as e:
                current_app.logger.error(f"Error deleting duplicate file {upload.file_path}: {str(e)}")
            
            db.session.commit()
            
            current_app.logger.info(
                f"Autoreviewer rejected duplicate upload {upload_id} "
                f"(MD5: {upload.md5_hash}, duplicate of upload {existing_id})"
            )
            
            # Schedule notification to uploader
            if upload.uploader:
                schedule_autoreviewer_notification(upload.uploader, [upload])
            
            return True
        
        # PHASE 2: AI Review (if enabled and not a duplicate)
        if use_ai:
            try:
                current_app.logger.info(f"Starting AI review for upload {upload_id}")
                from app.utils.ai_autoreviewer import ai_review_upload
                
                # Determine MD5 match status
                md5_matches_afh = False
                if hasattr(upload, 'afh_md5_status') and upload.afh_md5_status:
                    md5_matches_afh = upload.afh_md5_status == 'match'
                
                success, result = ai_review_upload(upload, md5_matches_afh, autoreviewer)
                
                if success and (result.get('approved') or result.get('rejected')):
                    current_app.logger.info(f"AI review completed for upload {upload_id}: approved={result.get('approved')}, rejected={result.get('rejected')}")
                    return result.get('rejected', False)
                else:
                    current_app.logger.info(f"AI review did not make a decision for upload {upload_id}")
                    
            except ImportError:
                current_app.logger.warning("AI autoreviewer not available (google-genai not installed)")
            except ValueError as e:
                current_app.logger.warning(f"AI autoreviewer not configured: {str(e)}")
            except Exception as e:
                current_app.logger.error(f"AI review error for upload {upload_id}: {str(e)}")
                import traceback
                current_app.logger.error(traceback.format_exc())
        
        # Not a duplicate and not auto-approved/rejected by AI, leave as pending for manual review
        current_app.logger.info(f"Autoreviewer passed upload {upload_id} - no duplicates found and no AI decision")
        return False
        
    except Exception as e:
        current_app.logger.error(f"Autoreviewer error for upload {upload_id}: {str(e)}")
        import traceback
        current_app.logger.error(f"Autoreviewer traceback: {traceback.format_exc()}")
        return False

def run_autoreviewer_on_all_pending():
    """
    Run autoreviewer on all pending uploads.
    This can be used for batch processing or migration.
    """
    pending_uploads = Upload.query.filter_by(status='pending').all()
    rejected_count = 0
    
    for upload in pending_uploads:
        if auto_review_upload(upload.id):
            rejected_count += 1
    
    current_app.logger.info(f"Autoreviewer batch run completed: {rejected_count} duplicates rejected")
    return rejected_count

def get_autoreviewer_stats():
    """Get statistics about autoreviewer activity"""
    autoreviewer = User.query.filter_by(email='autoreviewer@afh.joshattic.us').first()
    if not autoreviewer:
        return {
            'total_reviewed': 0,
            'total_rejected': 0,
            'duplicate_uploads': []
        }
    
    reviewed_uploads = Upload.query.filter_by(reviewed_by=autoreviewer.id).all()
    rejected_uploads = [u for u in reviewed_uploads if u.status == 'rejected']
    
    # Serialize upload objects for JSON/template compatibility
    serialized_rejected = []
    for upload in rejected_uploads[-10:]:  # Last 10 rejected uploads
        serialized_rejected.append({
            'id': upload.id,
            'original_filename': upload.original_filename,
            'device_manufacturer': upload.device_manufacturer,
            'device_model': upload.device_model,
            'uploader_name': upload.uploader.name if upload.uploader else 'Unknown',
            'reviewed_at': upload.reviewed_at.strftime('%Y-%m-%d %H:%M') if upload.reviewed_at else 'N/A',
            'rejection_reason': upload.rejection_reason
        })
    
    return {
        'total_reviewed': len(reviewed_uploads),
        'total_rejected': len(rejected_uploads),
        'duplicate_uploads': serialized_rejected
    }

