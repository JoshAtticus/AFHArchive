from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Upload, User
from app.utils.decorators import admin_required
from app.utils.file_handler import delete_upload_file
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
    
    query = Upload.query
    
    if status and status != 'all':
        query = query.filter_by(status=status)
    
    if manufacturer:
        query = query.filter(Upload.device_manufacturer.ilike(f'%{manufacturer}%'))
    
    if search:
        query = query.filter(Upload.original_filename.ilike(f'%{search}%'))
    
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
    
    return redirect(url_for('admin.uploads'))

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
