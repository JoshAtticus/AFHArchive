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
    autoreviewer = User.query.filter_by(email='autoreviewer@afharchive.system').first()
    
    if not autoreviewer:
        autoreviewer = User(
            google_id='autoreviewer_system',
            email='autoreviewer@afharchive.system',
            name='AFH Autoreviewer',
            avatar_url=None,
            is_admin=True,
            created_at=datetime.utcnow()
        )
        db.session.add(autoreviewer)
        db.session.commit()
        current_app.logger.info("Created autoreviewer system user")
    
    return autoreviewer

def check_for_duplicates(upload):
    """
    Check if an upload is a duplicate based on MD5 hash.
    Returns tuple (is_duplicate, existing_upload)
    """
    existing_upload = Upload.query.filter(
        Upload.md5_hash == upload.md5_hash,
        Upload.id != upload.id,
        Upload.status.in_(['approved', 'pending'])
    ).first()
    
    return existing_upload is not None, existing_upload

def schedule_autoreviewer_notification(user, rejected_uploads):
    """Batch autoreviewer notifications for 5 minutes before sending rejection emails"""
    user_id = user.id
    batch = pending_autoreviewer_notifications[user_id]
    batch['rejected'].extend(rejected_uploads)
    
    if batch['timer']:
        batch['timer'].cancel()
    
    # Capture the app instance while we're still in the application context
    app = current_app._get_current_object()
    
    def send_batched_autoreviewer_email():
        with app.app_context():
            rejected = batch['rejected']
            if not rejected:
                return
            
            subject = "Your uploads were automatically rejected"
            template = 'uploads_rejected.html'
            context = {'user': user, 'uploads': rejected}
            
            html = render_email_template(template, **context)
            send_email(user.email, subject, html)
            
            # Clear batch
            pending_autoreviewer_notifications[user_id] = {'rejected': [], 'timer': None}
    
    # Schedule for 5 minutes (300 seconds)
    batch['timer'] = Timer(300, send_batched_autoreviewer_email)
    batch['timer'].start()

def auto_review_upload(upload_id):
    """
    Automatically review an upload for duplicates.
    This function should be called after an upload is created.
    """
    try:
        upload = Upload.query.get(upload_id)
        if not upload:
            current_app.logger.error(f"Upload {upload_id} not found for auto-review")
            return False
        
        # Only auto-review pending uploads
        if upload.status != 'pending':
            return False
        
        # Get autoreviewer user
        autoreviewer = get_or_create_autoreviewer()
        
        # Check for duplicates
        is_duplicate, existing_upload = check_for_duplicates(upload)
        
        if is_duplicate:
            # Reject the duplicate upload
            existing_status = existing_upload.status
            existing_id = existing_upload.id
            existing_filename = existing_upload.original_filename
            
            rejection_reason = (
                f"Duplicate file detected. This file already exists in the archive "
                f"(Upload ID: {existing_id}, Status: {existing_status}, "
                f"Filename: {existing_filename}). "
                f"Automatically rejected by AFH Autoreviewer."
            )
            
            upload.status = 'rejected'
            upload.rejection_reason = rejection_reason
            upload.reviewed_at = datetime.utcnow()
            upload.reviewed_by = autoreviewer.id
            
            db.session.commit()
            
            current_app.logger.info(
                f"Autoreviewer rejected duplicate upload {upload_id} "
                f"(MD5: {upload.md5_hash}, duplicate of upload {existing_id})"
            )
            
            # Schedule notification to uploader
            if upload.uploader:
                schedule_autoreviewer_notification(upload.uploader, [upload])
            
            return True
        
        # Not a duplicate, leave as pending for manual review
        current_app.logger.info(f"Autoreviewer passed upload {upload_id} - no duplicates found")
        return False
        
    except Exception as e:
        current_app.logger.error(f"Autoreviewer error for upload {upload_id}: {str(e)}")
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
    autoreviewer = User.query.filter_by(email='autoreviewer@afharchive.system').first()
    if not autoreviewer:
        return {
            'total_reviewed': 0,
            'total_rejected': 0,
            'duplicate_uploads': []
        }
    
    reviewed_uploads = Upload.query.filter_by(reviewed_by=autoreviewer.id).all()
    rejected_uploads = [u for u in reviewed_uploads if u.status == 'rejected']
    
    return {
        'total_reviewed': len(reviewed_uploads),
        'total_rejected': len(rejected_uploads),
        'duplicate_uploads': rejected_uploads[-10:]  # Last 10 rejected uploads
    }
