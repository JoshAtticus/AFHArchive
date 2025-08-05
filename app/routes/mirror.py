from flask import Blueprint, request, jsonify, current_app, send_file, abort
from flask_login import login_required, current_user
from app import db
from app.models import Mirror, MirrorFile, MirrorPairingCode, MirrorSyncLog, Upload
from app.utils.decorators import admin_required
from datetime import datetime, timedelta
import secrets
import hashlib
import os
import requests
from threading import Thread

mirror_bp = Blueprint('mirror', __name__)


def verify_mirror_auth():
    """Verify mirror API authentication"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    api_key = auth_header.split(' ')[1]
    mirror = Mirror.query.filter_by(api_key=api_key).first()
    return mirror


@mirror_bp.route('/register', methods=['POST'])
def register_mirror():
    """Register a new mirror server (requires admin approval)"""
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid request data'}), 400
    
    server_name = data.get('server_name')
    api_key = data.get('api_key')
    direct_url = data.get('direct_url')
    cloudflare_url = data.get('cloudflare_url', '')
    storage_path = data.get('storage_path', '')
    max_files = data.get('max_files', 1000)
    
    if not all([server_name, api_key, direct_url]):
        return jsonify({'error': 'Missing required fields: server_name, api_key, direct_url'}), 400
    
    # Check if mirror with this API key already exists
    existing_mirror = Mirror.query.filter_by(api_key=api_key).first()
    if existing_mirror:
        return jsonify({
            'mirror_id': existing_mirror.id,
            'status': existing_mirror.status,
            'message': 'Mirror already registered'
        }), 200
    
    # Create new mirror (pending approval)
    mirror = Mirror(
        server_name=server_name,
        direct_url=direct_url,
        cloudflare_url=cloudflare_url if cloudflare_url else None,
        api_key=api_key,
        status='pending',  # Requires admin approval
        created_at=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        storage_path=storage_path,
        max_files=max_files,
        priority=5  # Default priority
    )
    
    try:
        db.session.add(mirror)
        db.session.commit()
        
        # Log the registration
        log = MirrorSyncLog(
            mirror_id=mirror.id,
            action='register',
            status='success',
            details=f'Mirror {server_name} registered and pending approval'
        )
        db.session.add(log)
        db.session.commit()
        
        current_app.logger.info(f'New mirror registered: {server_name} (ID: {mirror.id}) - Pending approval')
        
        return jsonify({
            'mirror_id': mirror.id,
            'status': mirror.status,
            'message': 'Mirror registered successfully. Pending admin approval.'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error registering mirror: {e}')
        return jsonify({'error': 'Failed to register mirror'}), 500


@mirror_bp.route('/pair', methods=['POST'])
def pair_mirror():
    """Pair a mirror server using a pairing code (deprecated - use registration instead)"""
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid request data'}), 400
    
    pairing_code = data.get('pairing_code')
    api_key = data.get('api_key')
    direct_url = data.get('direct_url')
    cloudflare_url = data.get('cloudflare_url', '')
    storage_path = data.get('storage_path', '')
    max_files = data.get('max_files', 1000)
    
    if not all([pairing_code, api_key, direct_url]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Find pairing code
    pairing = MirrorPairingCode.query.filter_by(code=pairing_code).first()
    if not pairing or not pairing.is_valid:
        return jsonify({'error': 'Invalid or expired pairing code'}), 400
    
    # Create mirror
    mirror = Mirror(
        name=pairing.name,
        direct_url=direct_url,
        cloudflare_url=cloudflare_url,
        storage_path=storage_path,
        max_files=max_files,
        api_key=api_key,
        status='online',
        last_seen=datetime.utcnow()
    )
    
    db.session.add(mirror)
    db.session.flush()  # Get the mirror ID
    
    # Mark pairing code as used
    pairing.used = True
    pairing.used_at = datetime.utcnow()
    pairing.mirror_id = mirror.id
    
    # Log the pairing
    log = MirrorSyncLog(
        mirror_id=mirror.id,
        action='paired',
        message=f'Mirror "{mirror.name}" paired successfully'
    )
    db.session.add(log)
    
    db.session.commit()
    
    current_app.logger.info(f"Mirror '{mirror.name}' paired successfully with ID {mirror.id}")
    
    return jsonify({
        'success': True,
        'mirror_id': mirror.id,
        'message': 'Mirror paired successfully'
    })


@mirror_bp.route('/heartbeat', methods=['POST'])
def mirror_heartbeat():
    """Receive heartbeat from mirror servers"""
    mirror = verify_mirror_auth()
    if not mirror:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid request data'}), 400
    
    # Update mirror status
    mirror.status = data.get('status', 'online')
    mirror.current_files = data.get('file_count', 0)
    mirror.last_seen = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'success': True})


@mirror_bp.route('/download/<int:upload_id>')
def download_for_mirror(upload_id):
    """Download endpoint for mirrors to fetch files"""
    mirror = verify_mirror_auth()
    if not mirror:
        return jsonify({'error': 'Unauthorized'}), 401
    
    upload = Upload.query.get_or_404(upload_id)
    
    # Only allow approved files
    if upload.status != 'approved':
        abort(404)
    
    file_path = upload.file_path
    if not os.path.exists(file_path):
        abort(404)
    
    # Log the sync action
    log = MirrorSyncLog(
        mirror_id=mirror.id,
        action='file_downloaded',
        message=f'File "{upload.original_filename}" downloaded for sync',
        upload_id=upload_id
    )
    db.session.add(log)
    db.session.commit()
    
    return send_file(file_path, as_attachment=True, download_name=upload.filename)


@mirror_bp.route('/<int:mirror_id>/sync-status')
def get_sync_status(mirror_id):
    """Check if mirror needs synchronization"""
    mirror = verify_mirror_auth()
    if not mirror or mirror.id != mirror_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # For now, always indicate sync is needed for simplicity
    # In a real implementation, you'd check timestamps and file lists
    return jsonify({
        'sync_needed': True,
        'last_sync': mirror.last_sync.isoformat() if mirror.last_sync else None
    })


@mirror_bp.route('/<int:mirror_id>/sync-instructions')
def get_sync_instructions(mirror_id):
    """Get synchronization instructions for a mirror"""
    mirror = verify_mirror_auth()
    if not mirror or mirror.id != mirror_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get current mirror files
    current_mirror_files = {mf.upload_id for mf in mirror.mirror_files}
    
    # Get approved uploads sorted by download count (most popular first)
    approved_uploads = Upload.query.filter_by(status='approved').order_by(
        Upload.download_count.desc()
    ).all()
    
    # Determine which files to add/remove
    add_instructions = []
    remove_instructions = []
    
    # Calculate how many files mirror should have
    target_files = min(len(approved_uploads), mirror.max_files)
    target_upload_ids = {upload.id for upload in approved_uploads[:target_files]}
    
    # Files to add (in target but not in mirror)
    files_to_add = target_upload_ids - current_mirror_files
    for upload in approved_uploads:
        if upload.id in files_to_add:
            add_instructions.append({
                'upload_id': upload.id,
                'filename': upload.filename,
                'original_filename': upload.original_filename,
                'file_size': upload.file_size,
                'md5_hash': upload.md5_hash
            })
    
    # Files to remove (in mirror but not in target)
    files_to_remove = current_mirror_files - target_upload_ids
    for upload_id in files_to_remove:
        remove_instructions.append({'upload_id': upload_id})
    
    # Update last sync time
    mirror.last_sync = datetime.utcnow()
    db.session.commit()
    
    # Log sync instructions
    log = MirrorSyncLog(
        mirror_id=mirror.id,
        action='sync_instructions',
        message=f'Sync instructions: +{len(add_instructions)} -{len(remove_instructions)} files'
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({
        'add': add_instructions,
        'remove': remove_instructions,
        'sync_time': datetime.utcnow().isoformat()
    })


@mirror_bp.route('/<int:mirror_id>/logs')
def get_mirror_logs(mirror_id):
    """Get logs for a specific mirror (admin only)"""
    if not current_user.is_authenticated or not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 401
    
    mirror = Mirror.query.get_or_404(mirror_id)
    
    # Get recent logs from database
    logs = MirrorSyncLog.query.filter_by(mirror_id=mirror_id).order_by(
        MirrorSyncLog.created_at.desc()
    ).limit(100).all()
    
    log_data = []
    for log in logs:
        log_data.append({
            'id': log.id,
            'action': log.action,
            'message': log.message,
            'upload_id': log.upload_id,
            'created_at': log.created_at.isoformat()
        })
    
    # Also try to get live logs from mirror server
    live_logs = []
    try:
        headers = {'Authorization': f'Bearer {mirror.api_key}'}
        response = requests.get(f'http://{mirror.direct_url}/api/logs', headers=headers, timeout=5)
        if response.status_code == 200:
            live_logs = response.json().get('logs', [])
    except Exception as e:
        current_app.logger.warning(f"Could not fetch live logs from mirror {mirror_id}: {e}")
    
    return jsonify({
        'database_logs': log_data,
        'live_logs': live_logs
    })


@mirror_bp.route('/<int:mirror_id>/status')
def get_mirror_status(mirror_id):
    """Get detailed status of a mirror (admin only)"""
    if not current_user.is_authenticated or not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 401
    
    mirror = Mirror.query.get_or_404(mirror_id)
    
    # Try to get live status from mirror
    live_status = None
    try:
        response = requests.get(f'http://{mirror.direct_url}/health', timeout=5)
        if response.status_code == 200:
            live_status = response.json()
    except Exception as e:
        current_app.logger.warning(f"Could not fetch live status from mirror {mirror_id}: {e}")
    
    return jsonify({
        'id': mirror.id,
        'name': mirror.name,
        'direct_url': mirror.direct_url,
        'cloudflare_url': mirror.cloudflare_url,
        'status': mirror.status,
        'is_online': mirror.is_online,
        'current_files': mirror.current_files,
        'max_files': mirror.max_files,
        'storage_usage_percent': mirror.storage_usage_percent,
        'last_seen': mirror.last_seen.isoformat() if mirror.last_seen else None,
        'last_sync': mirror.last_sync.isoformat() if mirror.last_sync else None,
        'created_at': mirror.created_at.isoformat(),
        'live_status': live_status
    })


def trigger_mirror_sync(mirror_id):
    """Trigger synchronization for a specific mirror (background task)"""
    def sync_task():
        try:
            mirror = Mirror.query.get(mirror_id)
            if not mirror:
                return
            
            # Send sync trigger to mirror
            headers = {'Authorization': f'Bearer {mirror.api_key}'}
            response = requests.post(
                f'http://{mirror.direct_url}/api/sync/trigger',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                log = MirrorSyncLog(
                    mirror_id=mirror.id,
                    action='sync_triggered',
                    message='Synchronization triggered successfully'
                )
            else:
                log = MirrorSyncLog(
                    mirror_id=mirror.id,
                    action='sync_error',
                    message=f'Failed to trigger sync: HTTP {response.status_code}'
                )
            
            db.session.add(log)
            db.session.commit()
            
        except Exception as e:
            # Log error to database
            try:
                log = MirrorSyncLog(
                    mirror_id=mirror_id,
                    action='sync_error',
                    message=f'Sync trigger error: {str(e)}'
                )
                db.session.add(log)
                db.session.commit()
            except:
                pass  # Avoid infinite recursion if db is down
    
    # Run in background thread
    thread = Thread(target=sync_task)
    thread.daemon = True
    thread.start()


@mirror_bp.route('/<int:mirror_id>/trigger-sync', methods=['POST'])
def trigger_sync(mirror_id):
    """Manually trigger sync for a mirror (admin only)"""
    if not current_user.is_authenticated or not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 401
    
    mirror = Mirror.query.get_or_404(mirror_id)
    
    # Trigger sync in background
    trigger_mirror_sync(mirror_id)
    
    return jsonify({'success': True, 'message': 'Sync triggered'})
