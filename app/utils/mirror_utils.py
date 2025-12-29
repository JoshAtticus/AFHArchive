from app import db
from app.models import Mirror, FileReplica, Upload, User
from flask import url_for, current_app
import requests
import os

def get_or_create_mirror_user():
    """Get or create the system user for mirror uploads"""
    email = 'mirror@afharchive.xyz'
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            name='Mirror System',
            is_admin=True
        )
        db.session.add(user)
        db.session.commit()
    return user

def trigger_mirror_sync(upload_id, mirror_ids=None, source_mirror_id=None):
    """
    Triggers sync for a file to specified mirrors.
    If mirror_ids is None, selects 2 active mirrors automatically.
    If source_mirror_id is provided, uses that mirror as the source.
    """
    upload = Upload.query.get(upload_id)
    if not upload:
        return 0
        
    if not mirror_ids:
        # Select 2 mirrors with least usage or random
        # For now, just pick first 2 active ones
        mirrors = Mirror.query.filter_by(is_active=True).limit(2).all()
    else:
        mirrors = Mirror.query.filter(Mirror.id.in_(mirror_ids), Mirror.is_active==True).all()
    
    # Determine download URL
    download_url = None
    if source_mirror_id:
        source_mirror = Mirror.query.get(source_mirror_id)
        if source_mirror and source_mirror.is_active:
            # Use the source mirror's public download URL
            # Note: This assumes the mirror allows public downloads or we need a way to auth
            # For now, we assume /api/download/<id> is accessible
            download_url = f"{source_mirror.url.rstrip('/')}/api/download/{upload.id}"
            current_app.logger.info(f"Using source mirror {source_mirror.name} for sync: {download_url}")
    
    if not download_url:
        # Default to main server
        download_url = url_for('api.mirror_sync_download', upload_id=upload.id, _external=True)
        
    count = 0
    for mirror in mirrors:
        # Create or update replica record
        replica = FileReplica.query.filter_by(upload_id=upload.id, mirror_id=mirror.id).first()
        if not replica:
            replica = FileReplica(upload_id=upload.id, mirror_id=mirror.id)
            db.session.add(replica)
        
        replica.status = 'pending'
        db.session.commit()
        
        # Trigger sync job on mirror
        try:
            current_app.logger.info(f"Triggering sync for {upload.original_filename} to {mirror.url}")
            
            resp = requests.post(
                f"{mirror.url}/api/mirror/job/sync",
                json={
                    'file_id': upload.id,
                    'download_url': download_url,
                    'md5_hash': upload.md5_hash,
                    'file_size': upload.file_size,
                    'filename': upload.filename,
                    'original_filename': upload.original_filename,
                    'device_manufacturer': upload.device_manufacturer,
                    'device_model': upload.device_model
                },
                timeout=5
            )
            
            if resp.status_code == 200:
                replica.status = 'syncing'
                count += 1
                current_app.logger.info(f"Sync triggered successfully for {mirror.name}")
            else:
                replica.status = 'error'
                replica.error_message = f"Mirror rejected job: {resp.status_code} - {resp.text}"
                current_app.logger.error(f"Mirror {mirror.name} rejected sync job: {resp.status_code} - {resp.text}")
                
            db.session.commit()
            
        except Exception as e:
            replica.status = 'error'
            replica.error_message = str(e)
            current_app.logger.error(f"Error triggering sync to {mirror.name}: {e}")
            db.session.commit()
            
    return count

def sync_to_main(upload_id, source_mirror_id):
    """
    Syncs a file from a mirror to the main server.
    """
    upload = Upload.query.get(upload_id)
    if not upload:
        return False, "Upload not found"
        
    source_mirror = Mirror.query.get(source_mirror_id)
    if not source_mirror or not source_mirror.is_active:
        return False, "Invalid source mirror"
        
    try:
        # Download file
        download_url = f"{source_mirror.url.rstrip('/')}/api/download/{upload.id}"
        current_app.logger.info(f"Downloading from {source_mirror.name} to main server: {download_url}")
        
        resp = requests.get(download_url, stream=True, timeout=30)
        if resp.status_code != 200:
            return False, f"Failed to download from mirror: {resp.status_code}"
            
        # Ensure directory exists
        os.makedirs(os.path.dirname(upload.file_path), exist_ok=True)
        
        # Write to file
        with open(upload.file_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                
        # Verify MD5 (optional but recommended)
        # For now, just assume it's good if download succeeded
        
        upload.is_on_main_server = True
        db.session.commit()
        return True, "Synced to main server"
        
    except Exception as e:
        current_app.logger.error(f"Error syncing to main: {e}")
        return False, str(e)

def delete_from_main(upload_id):
    """
    Deletes a file from the main server if it exists on at least 2 mirrors.
    """
    upload = Upload.query.get(upload_id)
    if not upload:
        return False, "Upload not found"
        
    # Check replicas
    synced_replicas = FileReplica.query.filter_by(upload_id=upload.id, status='synced').count()
    if synced_replicas < 2:
        return False, f"Not enough replicas (Found {synced_replicas}, need 2)"
        
    try:
        if os.path.exists(upload.file_path):
            os.remove(upload.file_path)
            current_app.logger.info(f"Deleted file from main server: {upload.file_path}")
        else:
            current_app.logger.warning(f"File not found on main server: {upload.file_path}")
            
        upload.is_on_main_server = False
        db.session.commit()
        return True, "Deleted from main server"
        
    except Exception as e:
        current_app.logger.error(f"Error deleting from main: {e}")
        return False, str(e)


def trigger_mirror_delete(upload, mirror_ids=None):
    """
    Triggers deletion of a file from specified mirrors.
    """
    if not mirror_ids:
        return 0
        
    mirrors = Mirror.query.filter(Mirror.id.in_(mirror_ids)).all()
    count = 0
    
    for mirror in mirrors:
        try:
            current_app.logger.info(f"Triggering delete for {upload.filename} on {mirror.url}")
            
            resp = requests.post(
                f"{mirror.url}/api/mirror/job/delete",
                json={
                    'filename': upload.filename
                },
                timeout=5
            )
            
            if resp.status_code in [200, 404]:
                count += 1
                current_app.logger.info(f"Delete triggered successfully for {mirror.name}")
                
                # Remove replica record
                replica = FileReplica.query.filter_by(upload_id=upload.id, mirror_id=mirror.id).first()
                if replica:
                    db.session.delete(replica)
                    db.session.commit()
            else:
                current_app.logger.error(f"Mirror {mirror.name} rejected delete job: {resp.status_code} - {resp.text}")
                
        except Exception as e:
            current_app.logger.error(f"Error triggering delete to {mirror.name}: {e}")
            
    return count
