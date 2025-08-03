from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
main_bp = Blueprint('main', __name__)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
import hashlib
from app import db
from app.models import Upload, User, Announcement
from app.utils.file_handler import allowed_file, save_upload_file
from app.utils.decorators import admin_required
from app.utils.autoreviewer import auto_review_upload

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    # Check if there's a file ID parameter for AFH link redirection
    fid = request.args.get('fid')
    if fid:
        return handle_afh_redirect(fid)

    # Get approved uploads for public display
    approved_uploads = Upload.query.filter_by(status='approved').order_by(Upload.uploaded_at.desc()).limit(10).all()

    # Get random image from devimages
    devimages_dir = os.path.join(current_app.static_folder, 'devimages')
    try:
        images = [f for f in os.listdir(devimages_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
    except Exception:
        images = []
    import random
    random_image = random.choice(images) if images else None

    # Get latest active announcement (if any)
    announcement = Announcement.query.order_by(Announcement.created_at.desc()).first()
    if announcement and not announcement.is_active:
        announcement = None

    return render_template('index.html', uploads=approved_uploads, random_image=random_image, announcement=announcement)

def handle_afh_redirect(fid):
    try:
        uploads = Upload.query.filter(
            Upload.afh_link.like(f'%fid={fid}%'),
            Upload.status == 'approved'
        ).all()
        
        if uploads:
            # If we found matching uploads, redirect to the first one
            upload = uploads[0]
            return redirect(url_for('main.file_detail', upload_id=upload.id))
        else:
            # If no matching upload found, show error and redirect to main page
            flash(f'File with AFH ID {fid} not found in our archive', 'error')
            return redirect(url_for('main.index'))
            
    except Exception as e:
        current_app.logger.error(f'AFH redirect error: {str(e)}')
        flash('Error processing file ID', 'error')
        return redirect(url_for('main.index'))

@main_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        # Check if file was uploaded
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if not allowed_file(file.filename):
            flash('File type not allowed', 'error')
            return redirect(request.url)
        
        # Get metadata from form
        device_manufacturer = request.form.get('device_manufacturer', '').strip()
        device_model = request.form.get('device_model', '').strip()
        afh_link = request.form.get('afh_link', '').strip()
        xda_thread = request.form.get('xda_thread', '').strip()
        notes = request.form.get('notes', '').strip()
        
        # Validate required fields
        if not device_manufacturer:
            flash('Device manufacturer is required', 'error')
            return redirect(request.url)
        
        if not device_model:
            flash('Device model is required', 'error')
            return redirect(request.url)
        
        try:
            # Save file and calculate hash
            filename, file_path, file_size, md5_hash = save_upload_file(file)
            
            # Create upload record
            upload = Upload(
                filename=filename,
                original_filename=file.filename,
                file_path=file_path,
                file_size=file_size,
                md5_hash=md5_hash,
                device_manufacturer=device_manufacturer,
                device_model=device_model,
                afh_link=afh_link,
                xda_thread=xda_thread,
                notes=notes,
                user_id=current_user.id
            )
            
            db.session.add(upload)
            db.session.commit()
            
            # Trigger autoreviewer to check for duplicates
            # This must happen after the commit so the upload ID exists
            try:
                current_app.logger.info(f"Running autoreviewer for upload {upload.id}")
                duplicate_rejected = auto_review_upload(upload.id)
                if duplicate_rejected:
                    current_app.logger.info(f"Autoreviewer rejected upload {upload.id} as duplicate")
                else:
                    current_app.logger.info(f"Autoreviewer passed upload {upload.id} - no duplicates found")
            except Exception as e:
                current_app.logger.error(f'Autoreviewer error for upload {upload.id}: {str(e)}')
                # Don't fail the upload if autoreviewer fails
            
            flash('File uploaded successfully and is pending review', 'success')
            return redirect(url_for('main.my_uploads'))
            
        except Exception as e:
            current_app.logger.error(f'Upload error: {str(e)}')
            flash('Upload failed. Please try again.', 'error')
            return redirect(request.url)
    
    return render_template('upload.html')

@main_bp.route('/my-uploads')
@login_required
def my_uploads():
    uploads = Upload.query.filter_by(user_id=current_user.id).order_by(Upload.uploaded_at.desc()).all()
    return render_template('my_uploads.html', uploads=uploads)

@main_bp.route('/browse')
def browse():
    page = request.args.get('page', 1, type=int)
    manufacturer = request.args.get('manufacturer', '')
    model = request.args.get('model', '')
    search = request.args.get('search', '')
    
    query = Upload.query.filter_by(status='approved')
    
    if manufacturer:
        query = query.filter(Upload.device_manufacturer.ilike(f'%{manufacturer}%'))
    
    if model:
        query = query.filter(Upload.device_model.ilike(f'%{model}%'))
    
    if search:
        query = query.filter(Upload.original_filename.ilike(f'%{search}%'))
    
    uploads = query.order_by(Upload.uploaded_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    # Get unique manufacturers and models for filters
    manufacturers = db.session.query(Upload.device_manufacturer).filter_by(status='approved').distinct().all()
    manufacturers = [m[0] for m in manufacturers]
    
    return render_template('browse.html', uploads=uploads, manufacturers=manufacturers, 
                         current_manufacturer=manufacturer, current_model=model, current_search=search)

@main_bp.route('/file/<int:upload_id>')
def file_detail(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    
    if upload.status != 'approved':
        flash('File not available', 'error')
        return redirect(url_for('main.index'))
    
    return render_template('file_detail.html', upload=upload)

@main_bp.route('/download/<int:upload_id>')
def download(upload_id):
    upload = Upload.query.get_or_404(upload_id)
    
    if upload.status != 'approved':
        flash('File not available for download', 'error')
        return redirect(url_for('main.index'))
    
    # Increment download count
    upload.download_count += 1
    db.session.commit()
    
    # Use a route that handles rate-limited downloads
    return redirect(url_for('api.download_file', upload_id=upload_id))

# Privacy Policy
@main_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')

# Terms of Service
@main_bp.route('/terms')
def terms():
    return render_template('terms.html')

# Language selection
@main_bp.route('/set_language/<language>')
def set_language(language):
    """Set the user's language preference"""
    supported_languages = current_app.config.get('LANGUAGES', {})
    if language in supported_languages:
        session['language'] = language
    return redirect(request.referrer or url_for('main.index'))