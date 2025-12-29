from app import db
from app.models import Mirror, FileReplica, Upload
from flask import url_for, current_app
import requests

def trigger_mirror_sync(upload_id, mirror_ids=None):
    """
    Triggers sync for a file to specified mirrors.
    If mirror_ids is None, selects 2 active mirrors automatically.
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
            download_url = url_for('mirror_api.download_chunk', upload_id=upload.id, _external=True)
            
            current_app.logger.info(f"Triggering sync for {upload.original_filename} to {mirror.url}")
            
            resp = requests.post(
                f"{mirror.url}/api/mirror/job/sync",
                json={
                    'file_id': upload.id,
                    'download_url': download_url,
                    'md5_hash': upload.md5_hash,
                    'file_size': upload.file_size,
                    'filename': upload.filename
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
