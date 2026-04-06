import os
import time
import requests
import tempfile
import internetarchive
from app import db
from app.models import Upload, SiteConfig, FileReplica
import logging

logger = logging.getLogger(__name__)

class ThrottledFile:
    def __init__(self, fileobj, rate_limit_kbps):
        self.fileobj = fileobj
        self.rate_limit_bytes_sec = rate_limit_kbps * 1024
        
    def read(self, size=-1):
        start_time = time.time()
        data = self.fileobj.read(size)
        if not data:
            return data
            
        elapsed = time.time() - start_time
        expected_time = len(data) / self.rate_limit_bytes_sec
        sleep_time = expected_time - elapsed
        
        if sleep_time > 0:
            time.sleep(sleep_time)
            
        return data
        
    def __getattr__(self, name):
        return getattr(self.fileobj, name)

def get_ia_item_id(upload):
    original_name = upload.original_filename.replace(" ", "_")
    item_id = f"afharchive_{upload.id}_{original_name}"
    return "".join([c for c in item_id if c.isalnum() or c in ("_","-")]).lower()

def upload_to_ia_background(app, upload_id):
    with app.app_context():
        upload = Upload.query.get(upload_id)
        if not upload:
            logger.error(f"Upload {upload_id} not found for IA upload.")
            return

        ia_access_key = SiteConfig.get_value('ia_s3_access_key')
        ia_secret_key = SiteConfig.get_value('ia_s3_secret_key')
        
        if not ia_access_key or not ia_secret_key:
            upload.ia_status = 'error'
            upload.ia_error_message = "IA Auth not configured in SiteConfig (ia_s3_access_key, ia_s3_secret_key)."
            db.session.commit()
            return
            
        # Configure item ID and dict
        item_id = get_ia_item_id(upload)
        
        uploader_name = upload.uploader.name + " (AFHArchive User)" if upload.uploader else "AFHArchive User"
        upload_date = upload.uploaded_at.strftime('%Y-%m-%d')
        main_url = app.config.get('MAIN_SERVER_URL', 'https://afharchive.xyz').rstrip('/')
        afharchive_link = f"{main_url}/file/{upload.id}"
        
        description = (
            f"Name: {upload.original_filename}<br>"
            f"Manufacturer: {upload.device_manufacturer}<br>"
            f"Model: {upload.device_model}<br>"
            f"MD5 Hash: {upload.md5_hash}<br>"
            f"Size: {upload.file_size} bytes<br><br>"
            f"Originally uploaded to AFHArchive by {uploader_name} on {upload_date}<br><br>"
        )
        if upload.afh_link:
            description += f"Original AFH Link: <a href='{upload.afh_link}' rel='nofollow'>{upload.afh_link}</a><br>"
        if upload.xda_thread:
            description += f"XDA Forums Link: <a href='{upload.xda_thread}' rel='nofollow'>{upload.xda_thread}</a><br>"
        description += f"AFHArchive Link: <a href='{afharchive_link}'>{afharchive_link}</a>"
        
        subjects = [
            "Android",
            "AndroidFileHost",
            upload.device_manufacturer,
            upload.device_model,
            "AFHArchive"
        ]
        
        # Setup metadata
        md = {
            'collection': 'opensource_media',
            'title': f"{upload.original_filename} - AFHArchive",
            'mediatype': 'data',
            'description': description,
            'creator': uploader_name,
            'subject': subjects
        }
        
        speed_limit_kbps = SiteConfig.get_value('ia_speed_limit_kbps', '')

        temp_file_path = None
        file_to_upload = upload.file_path
        
        if not os.path.exists(upload.file_path):
            # Tell the mirror to upload it directly to IA
            synced_replica = FileReplica.query.filter_by(upload_id=upload.id, status='synced').join(FileReplica.mirror).filter_by(is_active=True, is_online=True).first()
            if not synced_replica:
                upload.ia_status = 'error'
                upload.ia_error_message = f"File {upload.file_path} not found on main server and no active mirrors have it."
                db.session.commit()
                return
            
            logger.info(f"Downloading skipped. Asking mirror {synced_replica.mirror.name} to upload to IA directly")
            mirror_url = f"{synced_replica.mirror.url.rstrip('/')}/api/mirror/job/upload_ia"
            
            try:
                headers = {'X-Mirror-Api-Key': synced_replica.mirror.api_key}
                payload = {
                    'file_id': upload.id,
                    'ia_access_key': ia_access_key,
                    'ia_secret_key': ia_secret_key,
                    'ia_speed_limit_kbps': speed_limit_kbps,
                    'metadata': md,
                    'item_id': item_id,
                    'original_filename': upload.original_filename
                }
                
                resp = requests.post(mirror_url, headers=headers, json=payload, timeout=20)
                resp.raise_for_status()
                
                upload.ia_status = 'syncing'
                db.session.commit()
                return  # Mirror is handling it
            except Exception as e:
                logger.error(f"Failed to tell mirror {synced_replica.mirror.name} to upload: {e}")
                upload.ia_status = 'error'
                upload.ia_error_message = f"Failed to tell mirror {synced_replica.mirror.name} to upload: {e}"
                db.session.commit()
                return

        upload.ia_status = 'syncing'
        db.session.commit()
        
        try:
            # Login
            session = internetarchive.get_session(config={'s3': {'access': ia_access_key, 'secret': ia_secret_key}})
            
            file_obj = open(file_to_upload, 'rb')
            if speed_limit_kbps and str(speed_limit_kbps).isdigit() and int(speed_limit_kbps) > 0:
                file_obj = ThrottledFile(file_obj, int(speed_limit_kbps))
                
            item = session.get_item(item_id)
            # The internetarchive library's upload() method returns a list of responses
            responses = item.upload(
                files={upload.original_filename: file_obj},
                metadata=md,
                retries=3,
                retries_sleep=30,
                verbose=True
            )
            
            # Close file_obj explicitely to allow temp removing
            file_obj.close()
            
            # Not all uploads return a standard python requests response list depending on how they are uploaded
            # But the 'responses' is usually a list of Responses. We check if it is truthy.
            if responses and hasattr(responses[0], 'status_code') and responses[0].status_code not in [200, 201]:
                raise Exception(f"Upload returned status {responses[0].status_code}: {responses[0].text}")
                
            upload.ia_item_id = item_id
            upload.ia_status = 'synced'
            upload.ia_error_message = None
            db.session.commit()
            
        except Exception as e:
            logger.exception("Failed to upload to IA")
            upload.ia_status = 'error'
            upload.ia_error_message = str(e)
            db.session.commit()
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as cleanup_err:
                    logger.error(f"Failed to cleanup temp file {temp_file_path}: {cleanup_err}")

def upload_to_ia_background_for_mirror(app, data):
    with app.app_context():
        try:
            file_id = data['file_id']
            ia_access_key = data['ia_access_key']
            ia_secret_key = data['ia_secret_key']
            speed_limit_kbps = data['ia_speed_limit_kbps']
            md = data['metadata']
            item_id = data['item_id']
            original_filename = data['original_filename']
            main_server_url = data['main_server_url']
            api_key = data['api_key']
            
            upload = Upload.query.get(file_id)
            if not upload:
                raise Exception("Upload not found in mirror DB")
                
            local_path = upload.file_path
            upload_dir = app.config.get('UPLOAD_FOLDER', 'uploads')
            if not os.path.isabs(local_path):
                local_path = os.path.join(upload_dir, local_path)

            if not os.path.exists(local_path):
                raise Exception(f"File not found on mirror disk at {local_path}")
                
            session = internetarchive.get_session(config={'s3': {'access': ia_access_key, 'secret': ia_secret_key}})
            
            file_obj = open(local_path, 'rb')
            if speed_limit_kbps and str(speed_limit_kbps).isdigit() and int(speed_limit_kbps) > 0:
                file_obj = ThrottledFile(file_obj, int(speed_limit_kbps))
                
            item = session.get_item(item_id)
            responses = item.upload(
                files={original_filename: file_obj},
                metadata=md,
                retries=3,
                retries_sleep=30,
                verbose=True
            )
            file_obj.close()
            
            if responses and hasattr(responses[0], 'status_code') and responses[0].status_code not in [200, 201]:
                raise Exception(f"Upload returned status {responses[0].status_code}: {responses[0].text}")
                
            # Report success back to main
            requests.post(f"{main_server_url.rstrip('/')}/api/mirror/ia_upload_complete", json={
                'api_key': api_key,
                'upload_id': file_id,
                'status': 'synced',
                'error_message': None,
                'ia_item_id': item_id
            }, timeout=10)
            
        except Exception as e:
            logger.exception("Failed to upload to IA directly from mirror")
            try:
                requests.post(f"{data.get('main_server_url', '').rstrip('/')}/api/mirror/ia_upload_complete", json={
                    'api_key': data.get('api_key'),
                    'upload_id': data.get('file_id'),
                    'status': 'error',
                    'error_message': str(e)
                }, timeout=10)
            except Exception as report_error:
                logger.error(f"Failed to report IA upload error back to main server: {report_error}")
