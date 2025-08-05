from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response, abort
from flask_login import login_required, current_user
from app import db
from app.models import Upload, User, Announcement, Mirror, MirrorPairingCode, MirrorSyncLog, MirrorFile
from app.utils.decorators import admin_required
from app.utils.file_handler import delete_upload_file, format_file_size
from app.utils.email_utils import send_email, render_email_template
from app.utils.autoreviewer import get_autoreviewer_stats, run_autoreviewer_on_all_pending, get_or_create_autoreviewer
from threading import Timer
from sqlalchemy import or_
from collections import defaultdict
import os
import shutil
import psutil
import subprocess
import signal
import time
import secrets
import requests
from datetime import datetime, timedelta
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
    total_uploads = Upload.query.count()
    
    stats = {
        'pending': pending_count,
        'approved': approved_count,
        'rejected': rejected_count,
        'total_users': total_users,
        'upload_count': total_uploads,
        'user_count': total_users
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
    
    # Try to delete the file from disk
    file_deleted = delete_upload_file(upload.file_path)
    
    # Always delete from database (even if file deletion failed or file was missing)
    db.session.delete(upload)
    db.session.commit()
    
    if file_deleted:
        flash(f'Upload "{upload.original_filename}" deleted', 'info')
    else:
        flash(f'Upload "{upload.original_filename}" deleted from database (file was already missing from disk)', 'warning')
    
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

# Server Tools Routes
@admin_bp.route('/server-tools')
@login_required
@admin_required
def server_tools():
    """Server management tools dashboard"""
    try:
        # Get server uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        
        # Get system information
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Get upload directory info
        upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        chunks_dir = os.path.join(upload_dir, 'chunks')
        
        # Calculate storage usage
        total_uploads_size = 0
        total_chunks_size = 0
        chunks_count = 0
        
        if os.path.exists(upload_dir):
            for root, dirs, files in os.walk(upload_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_size = os.path.getsize(file_path)
                    if 'chunks' in root:
                        total_chunks_size += file_size
                        chunks_count += 1
                    else:
                        total_uploads_size += file_size
        
        # Calculate database size
        db_size = 0
        db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        if db_path and os.path.exists(db_path):
            db_size = os.path.getsize(db_path)
        
        server_stats = {
            'uptime': uptime,
            'memory_total': memory.total,
            'memory_used': memory.used,
            'memory_percent': memory.percent,
            'disk_total': disk.total,
            'disk_used': disk.used,
            'disk_percent': disk.percent,
            'cpu_percent': cpu_percent,
            'uploads_size': total_uploads_size,
            'chunks_size': total_chunks_size,
            'chunks_count': chunks_count,
            'database_size': db_size
        }
        
    except Exception as e:
        current_app.logger.error(f"Error getting server stats: {str(e)}")
        server_stats = {}
        flash(f'Error retrieving server statistics: {str(e)}', 'warning')
    
    return render_template('admin/server_tools.html', stats=server_stats)

@admin_bp.route('/server-tools/clear-chunks', methods=['POST'])
@login_required
@admin_required
def clear_chunks():
    """Clear the chunks cache directory"""
    try:
        upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        chunks_dir = os.path.join(upload_dir, 'chunks')
        
        if not os.path.exists(chunks_dir):
            flash('Chunks directory does not exist', 'info')
            return redirect(url_for('admin.server_tools'))
        
        # Count files before deletion
        files_count = 0
        total_size = 0
        for root, dirs, files in os.walk(chunks_dir):
            for file in files:
                files_count += 1
                file_path = os.path.join(root, file)
                total_size += os.path.getsize(file_path)
        
        # Clear the chunks directory
        if files_count > 0:
            shutil.rmtree(chunks_dir)
            os.makedirs(chunks_dir, exist_ok=True)
            flash(f'Cleared {files_count} chunk files ({format_file_size(total_size)} freed)', 'success')
        else:
            flash('Chunks directory is already empty', 'info')
            
    except Exception as e:
        current_app.logger.error(f"Error clearing chunks: {str(e)}")
        flash(f'Error clearing chunks: {str(e)}', 'error')
    
    return redirect(url_for('admin.server_tools'))

@admin_bp.route('/server-tools/cleanup-orphaned', methods=['POST'])
@login_required
@admin_required
def cleanup_orphaned_files():
    """Remove files from disk that don't have corresponding database entries"""
    try:
        upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        chunks_dir = os.path.join(upload_dir, 'chunks')
        
        # Get all file paths from database
        db_files = set()
        uploads = Upload.query.all()
        for upload in uploads:
            if upload.file_path:
                # Convert to absolute path if needed
                if not os.path.isabs(upload.file_path):
                    db_files.add(os.path.join(upload_dir, os.path.basename(upload.file_path)))
                else:
                    db_files.add(upload.file_path)
        
        # Check files in upload directory
        orphaned_count = 0
        orphaned_size = 0
        
        if os.path.exists(upload_dir):
            for filename in os.listdir(upload_dir):
                file_path = os.path.join(upload_dir, filename)
                
                # Skip directories and chunks directory
                if os.path.isdir(file_path) or filename == 'chunks':
                    continue
                
                # Check if file is in database
                if file_path not in db_files:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    orphaned_count += 1
                    orphaned_size += file_size
        
        if orphaned_count > 0:
            flash(f'Removed {orphaned_count} orphaned files ({format_file_size(orphaned_size)} freed)', 'success')
        else:
            flash('No orphaned files found', 'info')
            
    except Exception as e:
        current_app.logger.error(f"Error cleaning orphaned files: {str(e)}")
        flash(f'Error cleaning orphaned files: {str(e)}', 'error')
    
    return redirect(url_for('admin.server_tools'))

@admin_bp.route('/server-tools/restart-server', methods=['POST'])
@login_required
@admin_required
def restart_server():
    """Restart the server (graceful restart)"""
    try:
        # Log the restart action
        current_app.logger.info(f"Server restart initiated by admin user {current_user.name}")
        
        # For development/testing, we'll just send SIGTERM to self
        # In production, this should be handled by the process manager (systemd, supervisor, etc.)
        flash('Server restart initiated. The server will restart momentarily.', 'info')
        
        # Use threading to delay the restart so the response can be sent
        def delayed_restart():
            time.sleep(2)  # Give time for response to be sent
            try:
                # Try to restart gracefully
                if hasattr(os, 'kill'):
                    os.kill(os.getpid(), signal.SIGTERM)
                else:
                    # Fallback for Windows
                    subprocess.run(['taskkill', '/f', '/pid', str(os.getpid())], check=False)
            except:
                pass
        
        import threading
        threading.Thread(target=delayed_restart, daemon=True).start()
        
    except Exception as e:
        current_app.logger.error(f"Error restarting server: {str(e)}")
        flash(f'Error restarting server: {str(e)}', 'error')
    
    return redirect(url_for('admin.server_tools'))

@admin_bp.route('/server-tools/system-info')
@login_required
@admin_required
def system_info():
    """Get detailed system information as JSON"""
    try:
        # Get detailed system info
        info = {
            'platform': psutil.platform,
            'python_version': f"{psutil.version_info.major}.{psutil.version_info.minor}.{psutil.version_info.micro}",
            'cpu_count': psutil.cpu_count(),
            'cpu_freq': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
            'memory': psutil.virtual_memory()._asdict(),
            'swap': psutil.swap_memory()._asdict(),
            'disk_usage': psutil.disk_usage('/')._asdict(),
            'boot_time': datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            'load_avg': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None,
            'network_io': psutil.net_io_counters()._asdict(),
            'disk_io': psutil.disk_io_counters()._asdict() if psutil.disk_io_counters() else None
        }
        
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/server-tools/process-info')
@login_required
@admin_required
def process_info():
    """Get current process information"""
    try:
        process = psutil.Process()
        info = {
            'pid': process.pid,
            'name': process.name(),
            'status': process.status(),
            'create_time': datetime.fromtimestamp(process.create_time()).isoformat(),
            'cpu_percent': process.cpu_percent(),
            'memory_info': process.memory_info()._asdict(),
            'memory_percent': process.memory_percent(),
            'num_threads': process.num_threads(),
            'open_files_count': len(process.open_files()) if hasattr(process, 'open_files') else 0,
            'connections_count': len(process.connections()) if hasattr(process, 'connections') else 0
        }
        
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Autoreviewer Management Routes
@admin_bp.route('/autoreviewer')
@login_required
@admin_required
def autoreviewer_dashboard():
    """Autoreviewer management dashboard"""
    stats = get_autoreviewer_stats()
    autoreviewer_user = get_or_create_autoreviewer()
    
    return render_template('admin/autoreviewer.html', 
                         stats=stats, 
                         autoreviewer=autoreviewer_user)

@admin_bp.route('/autoreviewer/run-batch', methods=['POST'])
@login_required
@admin_required
def run_autoreviewer_batch():
    """Run autoreviewer on all pending uploads"""
    try:
        rejected_count = run_autoreviewer_on_all_pending()
        flash(f'Autoreviewer batch completed: {rejected_count} duplicate files rejected', 'success')
    except Exception as e:
        current_app.logger.error(f'Autoreviewer batch error: {str(e)}')
        flash(f'Autoreviewer batch failed: {str(e)}', 'error')
    
    return redirect(url_for('admin.autoreviewer_dashboard'))

@admin_bp.route('/autoreviewer/stats')
@login_required
@admin_required
def autoreviewer_stats_api():
    """API endpoint for autoreviewer statistics"""
    return jsonify(get_autoreviewer_stats())


# Mirror Management Routes
@admin_bp.route('/mirrors')
@login_required
@admin_required
def mirrors():
    """Mirror management dashboard"""
    mirrors = Mirror.query.order_by(Mirror.created_at.desc()).all()
    
    # Get recent sync logs
    recent_logs = MirrorSyncLog.query.order_by(
        MirrorSyncLog.created_at.desc()
    ).limit(50).all()
    
    return render_template('admin/mirrors.html', mirrors=mirrors, recent_logs=recent_logs)


@admin_bp.route('/mirrors/create-pairing-code', methods=['POST'])
@login_required
@admin_required
def create_pairing_code():
    """Create a new pairing code for mirror setup"""
    name = request.form.get('name', '').strip()
    if not name:
        flash('Mirror name is required', 'error')
        return redirect(url_for('admin.mirrors'))
    
    # Generate pairing code
    code = secrets.token_hex(6).upper()
    expires_at = datetime.utcnow() + timedelta(hours=24)  # 24 hour expiry
    
    pairing_code = MirrorPairingCode(
        code=code,
        name=name,
        expires_at=expires_at
    )
    
    db.session.add(pairing_code)
    db.session.commit()
    
    flash(f'Pairing code created: {code} (expires in 24 hours)', 'success')
    return redirect(url_for('admin.mirrors'))


@admin_bp.route('/mirrors/<int:mirror_id>')
@login_required
@admin_required
def mirror_detail(mirror_id):
    """Detailed view of a specific mirror"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    # Get mirror files
    mirror_files = MirrorFile.query.filter_by(mirror_id=mirror_id).join(
        Upload
    ).order_by(Upload.download_count.desc()).limit(100).all()
    
    # Get recent logs for this mirror
    logs = MirrorSyncLog.query.filter_by(mirror_id=mirror_id).order_by(
        MirrorSyncLog.created_at.desc()
    ).limit(50).all()
    
    # Try to get live status
    live_status = None
    try:
        response = requests.get(f'http://{mirror.direct_url}/health', timeout=5)
        if response.status_code == 200:
            live_status = response.json()
    except Exception as e:
        current_app.logger.warning(f"Could not fetch live status from mirror {mirror_id}: {e}")
    
    return render_template('admin/mirror_detail.html', 
                         mirror=mirror, 
                         mirror_files=mirror_files, 
                         logs=logs,
                         live_status=live_status)


@admin_bp.route('/mirrors/<int:mirror_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_mirror(mirror_id):
    """Edit mirror configuration"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    if request.method == 'POST':
        mirror.name = request.form.get('name', '').strip()
        mirror.direct_url = request.form.get('direct_url', '').strip()
        mirror.cloudflare_url = request.form.get('cloudflare_url', '').strip()
        mirror.storage_path = request.form.get('storage_path', '').strip()
        mirror.max_files = int(request.form.get('max_files', 1000))
        
        db.session.commit()
        flash('Mirror configuration updated', 'success')
        return redirect(url_for('admin.mirror_detail', mirror_id=mirror_id))
    
    return render_template('admin/edit_mirror.html', mirror=mirror)


@admin_bp.route('/mirrors/<int:mirror_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_mirror(mirror_id):
    """Delete a mirror"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    # Delete all related records
    MirrorFile.query.filter_by(mirror_id=mirror_id).delete()
    MirrorSyncLog.query.filter_by(mirror_id=mirror_id).delete()
    
    # Delete the mirror
    mirror_name = mirror.name
    db.session.delete(mirror)
    db.session.commit()
    
    flash(f'Mirror "{mirror_name}" deleted', 'info')
    return redirect(url_for('admin.mirrors'))


@admin_bp.route('/mirrors/<int:mirror_id>/sync', methods=['POST'])
@login_required
@admin_required
def trigger_mirror_sync(mirror_id):
    """Trigger manual sync for a mirror"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    try:
        # Import the trigger function from mirror routes
        from app.routes.mirror import trigger_mirror_sync
        trigger_mirror_sync(mirror_id)
        flash(f'Sync triggered for mirror "{mirror.name}"', 'success')
    except Exception as e:
        flash(f'Error triggering sync: {str(e)}', 'error')
    
    return redirect(url_for('admin.mirror_detail', mirror_id=mirror_id))


@admin_bp.route('/mirrors/<int:mirror_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_mirror(mirror_id):
    """Approve a pending mirror"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    if mirror.status != 'pending':
        flash(f'Mirror is already {mirror.status}', 'warning')
        return redirect(url_for('admin.mirrors'))
    
    mirror.status = 'active'
    mirror.approved_at = datetime.utcnow()
    mirror.approved_by = current_user.id
    
    # Log the approval
    log = MirrorSyncLog(
        mirror_id=mirror.id,
        action='approve',
        status='success',
        details=f'Mirror approved by {current_user.username}'
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Mirror "{mirror.server_name}" approved and activated', 'success')
    return redirect(url_for('admin.mirrors'))


@admin_bp.route('/mirrors/<int:mirror_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_mirror(mirror_id):
    """Reject a pending mirror"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    if mirror.status != 'pending':
        flash(f'Mirror is already {mirror.status}', 'warning')
        return redirect(url_for('admin.mirrors'))
    
    reason = request.form.get('reason', 'No reason provided')
    mirror.status = 'rejected'
    
    # Log the rejection
    log = MirrorSyncLog(
        mirror_id=mirror.id,
        action='reject',
        status='success',
        details=f'Mirror rejected by {current_user.username}: {reason}'
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Mirror "{mirror.server_name}" rejected', 'warning')
    return redirect(url_for('admin.mirrors'))


@admin_bp.route('/mirrors/<int:mirror_id>/activate', methods=['POST'])
@login_required
@admin_required  
def activate_mirror(mirror_id):
    """Activate a mirror (enable for download routing)"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    mirror.status = 'active'
    
    # Log the activation
    log = MirrorSyncLog(
        mirror_id=mirror.id,
        action='activate',
        status='success',
        details=f'Mirror activated by {current_user.username}'
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Mirror "{mirror.server_name}" activated', 'success')
    return redirect(url_for('admin.mirror_detail', mirror_id=mirror_id))


@admin_bp.route('/mirrors/<int:mirror_id>/deactivate', methods=['POST'])
@login_required
@admin_required
def deactivate_mirror(mirror_id):
    """Deactivate a mirror (disable from download routing)"""
    mirror = Mirror.query.get_or_404(mirror_id)
    
    mirror.status = 'inactive'
    
    # Log the deactivation
    log = MirrorSyncLog(
        mirror_id=mirror.id,
        action='deactivate',
        status='success',
        details=f'Mirror deactivated by {current_user.username}'
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Mirror "{mirror.server_name}" deactivated', 'info')
    return redirect(url_for('admin.mirror_detail', mirror_id=mirror_id))


@admin_bp.route('/mirrors/pairing-codes')
@login_required
@admin_required
def pairing_codes():
    """List all pairing codes"""
    codes = MirrorPairingCode.query.order_by(
        MirrorPairingCode.created_at.desc()
    ).all()
    
    return render_template('admin/pairing_codes.html', codes=codes)


@admin_bp.route('/mirrors/pairing-codes/<int:code_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_pairing_code(code_id):
    """Delete a pairing code"""
    code = MirrorPairingCode.query.get_or_404(code_id)
    
    if code.used:
        flash('Cannot delete used pairing code', 'error')
    else:
        db.session.delete(code)
        db.session.commit()
        flash('Pairing code deleted', 'info')
    
    return redirect(url_for('admin.pairing_codes'))
