from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response, abort
from flask_login import login_required, current_user
from app import db
from app.models import Upload, User, Announcement
from app.utils.decorators import admin_required
from app.utils.file_handler import delete_upload_file
from app.utils.email_utils import send_email, render_email_template
from threading import Timer
from sqlalchemy import or_
from collections import defaultdict
import os
pending_email_batches = defaultdict(lambda: {'approved': [], 'rejected': [], 'timer': None})
def schedule_upload_notification(user, approved_uploads, rejected_uploads):
    """Batch notifications for 5 minutes before sending approval/rejection emails"""
    user_id = user.id
    batch = pending_email_batches[user_id]
    batch['approved'].extend(approved_uploads)
    batch['rejected'].extend(rejected_uploads)
    if batch['timer']:
        batch['timer'].cancel()
    
    # Capture the app instance while we're still in the application context
    app = current_app._get_current_object()
    
    def send_batched_email():
        with app.app_context():
            approved = batch['approved']
            rejected = batch['rejected']
            subject = None
            template = None
            context = {'user': user}
            if approved and not rejected:
                subject = "Your uploads were approved"
                template = 'uploads_approved.html'
                context['uploads'] = approved
            elif approved and rejected:
                subject = "Some of your uploads were approved"
                template = 'uploads_some_approved.html'
                context['approved_uploads'] = approved
                context['rejected_uploads'] = rejected
            elif rejected and not approved:
                subject = "Your uploads were rejected"
                template = 'uploads_rejected.html'
                context['uploads'] = rejected
            else:
                return
            html = render_email_template(template, **context)
            send_email(user.email, subject, html)
            # Clear batch
            pending_email_batches[user_id] = {'approved': [], 'rejected': [], 'timer': None}
    # Schedule for 5 minutes (300 seconds)
    batch['timer'] = Timer(300, send_batched_email)
    batch['timer'].start()
from datetime import datetime

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    # Get counts for dashboard
    pending_count = Upload.query.filter_by(status='pending').count()
    approved_count = Upload.query.filter_by(status='approved').count()
    rejected_count = Upload.query.filter_by(status='rejected').count()
    total_users = User.query.count()
    
    stats = {
        'pending': pending_count,
        'approved': approved_count,
        'rejected': rejected_count,
        'total_users': total_users
    }
    
    return render_template('admin/dashboard.html', stats=stats)

@admin_bp.route('/uploads')
@login_required
@admin_required
def uploads():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'pending')
    manufacturer = request.args.get('manufacturer', '')
    search = request.args.get('search', '')
    user_id = request.args.get('user_id', '', type=int)
    
    query = Upload.query
    
    if status and status != 'all':
        query = query.filter_by(status=status)
    
    if manufacturer:
        query = query.filter(Upload.device_manufacturer.ilike(f'%{manufacturer}%'))
    
    if search:
        query = query.filter(Upload.original_filename.ilike(f'%{search}%'))
    
    if user_id:
        query = query.filter_by(user_id=user_id)
    
    uploads = query.order_by(Upload.uploaded_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    # Get unique manufacturers for filters
    manufacturers = db.session.query(Upload.device_manufacturer).distinct().all()
    manufacturers = [m[0] for m in manufacturers]
    
    return render_template('admin/uploads.html', uploads=uploads, manufacturers=manufacturers,
                         current_status=status, current_manufacturer=manufacturer, current_search=search)

@admin_bp.route('/upload/<int:upload_id>')
@login_required
@admin_required
def view_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    return render_template('admin/upload_detail.html', upload=upload)

@admin_bp.route('/upload/<int:upload_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    upload.status = 'approved'
    upload.reviewed_at = datetime.utcnow()
    upload.reviewed_by = current_user.id
    db.session.commit()
    flash(f'Upload "{upload.original_filename}" approved', 'success')
    # Schedule notification to uploader
    if upload.uploader:
        schedule_upload_notification(upload.uploader, [upload], [])
    return redirect(url_for('admin.uploads'))

@admin_bp.route('/upload/<int:upload_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    reason = request.form.get('reason', '').strip()
    upload.status = 'rejected'
    upload.rejection_reason = reason
    upload.reviewed_at = datetime.utcnow()
    upload.reviewed_by = current_user.id
    db.session.commit()
    flash(f'Upload "{upload.original_filename}" rejected', 'warning')
    # Schedule notification to uploader
    if upload.uploader:
        schedule_upload_notification(upload.uploader, [], [upload])
    return redirect(url_for('admin.uploads'))
# Admin announcement email route
@admin_bp.route('/announcement', methods=['GET', 'POST'])
@login_required
@admin_required
def send_announcement():
    if request.method == 'POST':
        subject = request.form.get('subject', 'Announcement from AFHArchive')
        message = request.form.get('message', '')
        send_homepage = request.form.get('send_homepage') == '1'
        send_email_flag = request.form.get('send_email') == '1'
        recipients_type = request.form.get('recipients', 'all')

        # Determine recipients
        if recipients_type == 'uploaders':
            users = User.query.join(User.uploads).distinct().all()
        else:
            users = User.query.all()

        # Send email if requested
        if send_email_flag:
            html = render_email_template('announcement.html', message=message)
            for user in users:
                send_email(user.email, subject, html)

        # Post to homepage if requested
        if send_homepage:
            announcement = Announcement(subject=subject, message=message)
            db.session.add(announcement)
            db.session.commit()

        if send_email_flag and send_homepage:
            flash('Announcement sent to selected users and posted to homepage', 'success')
        elif send_email_flag:
            flash('Announcement sent to selected users', 'success')
        elif send_homepage:
            flash('Announcement posted to homepage', 'success')
        else:
            flash('No delivery method selected. Announcement not sent.', 'warning')
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/announcement.html')

@admin_bp.route('/upload/<int:upload_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    
    if request.method == 'POST':
        upload.device_manufacturer = request.form.get('device_manufacturer', '').strip()
        upload.device_model = request.form.get('device_model', '').strip()
        upload.afh_link = request.form.get('afh_link', '').strip()
        upload.xda_thread = request.form.get('xda_thread', '').strip()
        upload.notes = request.form.get('notes', '').strip()
        
        db.session.commit()
        flash('Upload metadata updated', 'success')
        return redirect(url_for('admin.view_upload', upload_id=upload_id))
    
    return render_template('admin/edit_upload.html', upload=upload)

@admin_bp.route('/upload/<int:upload_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_upload(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    
    # Delete the file from disk
    if delete_upload_file(upload.file_path):
        # Delete from database
        db.session.delete(upload)
        db.session.commit()
        flash(f'Upload "{upload.original_filename}" deleted', 'info')
    else:
        flash('Error deleting file from disk', 'error')
    
    return redirect(url_for('admin.uploads'))

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/users.html', users=users)

@admin_bp.route('/user/<int:user_id>/make-admin', methods=['POST'])
@login_required
@admin_required
def make_admin(user_id):
    user = User.query.get_or_404(user_id)
    user.is_admin = True
    db.session.commit()
    return jsonify({'success': True, 'message': f'{user.name} is now an admin'})

@admin_bp.route('/user/<int:user_id>/remove-admin', methods=['POST'])
@login_required
@admin_required
def remove_admin(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent removing admin from self
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot remove admin privileges from yourself'})
    
    user.is_admin = False
    db.session.commit()
    return jsonify({'success': True, 'message': f'Admin privileges removed from {user.name}'})

@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent deleting self
    if user.id == current_user.id:
        flash('Cannot delete your own account', 'error')
        return redirect(url_for('admin.users'))
    
    # Delete all uploads by this user first
    uploads = Upload.query.filter_by(user_id=user.id).all()
    for upload in uploads:
        # Delete the file from disk
        delete_upload_file(upload.file_path)
        db.session.delete(upload)
    
    # Delete the user
    db.session.delete(user)
    db.session.commit()
    
    flash(f'User "{user.name}" and all their uploads have been deleted', 'info')
    return redirect(url_for('admin.users'))

@admin_bp.route('/download/<int:upload_id>')
@login_required
@admin_required
def download_file(upload_id):
    """Admin download route that can download any file regardless of status"""
    upload = Upload.query.get_or_404(upload_id)
    
    # Convert relative path to absolute path
    if not os.path.isabs(upload.file_path):
        # Make path relative to application root directory
        app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        file_path = os.path.join(app_root, upload.file_path)
    else:
        file_path = upload.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash('File not found on disk', 'error')
        return redirect(url_for('admin.view_upload', upload_id=upload_id))
    
    # For admin downloads, we don't apply rate limiting but we do increment download count
    upload.download_count += 1
    db.session.commit()
    
    def generate():
        """Stream file without rate limiting for admin downloads"""
        try:
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)  # 64KB chunks
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            current_app.logger.error(f'Admin download streaming error: {str(e)}')
    
    # Create response with proper headers
    response = Response(
        generate(),
        mimetype='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{upload.original_filename}"',
            'Content-Length': str(upload.file_size),
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }
    )
    return response
