from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
main_bp = Blueprint('main', __name__)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
import hashlib
from app import db
from app.models import Upload, User, Announcement, Mirror, MirrorFile
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
    from app.utils.mirror_picker import mirror_picker
    
    upload = Upload.query.get_or_404(upload_id)
    
    if upload.status != 'approved':
        flash('File not available for download', 'error')
        return redirect(url_for('main.index'))
    
    # Check if this is a direct download request
    if request.args.get('direct') == '1':
        return download_direct(upload_id)
    
    # Get user's IP for geo-routing
    user_ip = request.remote_addr
    if request.headers.get('X-Forwarded-For'):
        user_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    
    # Get the best mirror for this download
    mirror_info = mirror_picker.get_best_mirror_for_download(upload_id, user_ip)
    
    if not mirror_info:
        flash('File not available for download', 'error')
        return redirect(url_for('main.index'))
    
    # Get available mirrors for user choice
    available_mirrors = mirror_picker._get_available_mirrors_for_file(upload_id)
    main_server = mirror_picker._get_main_server_mirror()
    available_mirrors.append(main_server)
    
    # Filter healthy mirrors
    healthy_mirrors = mirror_picker._filter_healthy_mirrors(available_mirrors)
    
    # Show download page with mirror options
    return render_template('download.html', 
                         upload=upload, 
                         recommended_mirror=mirror_info,
                         available_mirrors=healthy_mirrors,
                         user_ip=user_ip)


@main_bp.route('/download/<int:upload_id>/direct')
def download_direct(upload_id):
    """Direct download without mirror selection page"""
    from app.utils.mirror_picker import mirror_picker
    
    upload = Upload.query.get_or_404(upload_id)
    
    if upload.status != 'approved':
        flash('File not available for download', 'error')
        return redirect(url_for('main.index'))
    
    # Get user's IP for geo-routing
    user_ip = request.remote_addr
    if request.headers.get('X-Forwarded-For'):
        user_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    
    # Get the best mirror for this download
    mirror_info = mirror_picker.get_best_mirror_for_download(upload_id, user_ip)
    
    if not mirror_info:
        flash('File not available for download', 'error')
        return redirect(url_for('main.index'))
    
    # Increment download count
    upload.download_count += 1
    db.session.commit()
    
    # Log the mirror selection for debugging
    current_app.logger.info(f"Download {upload_id} routed to {mirror_info['server_name']} (IP: {user_ip})")
    
    # If it's the main server, use the local download route
    if mirror_info['mirror_type'] == 'main':
        return redirect(url_for('api.download_file', upload_id=upload_id))
    else:
        # Redirect to mirror
        return redirect(mirror_info['download_url'])


@main_bp.route('/download/<int:upload_id>/from/<mirror_id>')
def download_from_mirror(upload_id, mirror_id):
    """Download from a specific mirror"""
    upload = Upload.query.get_or_404(upload_id)
    
    if upload.status != 'approved':
        flash('File not available for download', 'error')
        return redirect(url_for('main.index'))
    
    # Increment download count
    upload.download_count += 1
    db.session.commit()
    
    if mirror_id == 'main':
        # Download from main server
        return redirect(url_for('api.download_file', upload_id=upload_id))
    else:
        # Download from specific mirror
        mirror = Mirror.query.get_or_404(mirror_id)
        
        # Check if mirror has the file
        mirror_file = MirrorFile.query.filter_by(
            mirror_id=mirror_id, 
            upload_id=upload_id
        ).first()
        
        if not mirror_file:
            flash('File not available on this mirror', 'error')
            return redirect(url_for('main.download', upload_id=upload_id))
        
        # Construct download URL
        if mirror.cloudflare_url:
            download_url = f"{mirror.cloudflare_url}/download/{upload_id}"
        else:
            download_url = f"http://{mirror.direct_url}/download/{upload_id}"
        
        return redirect(download_url)

# Privacy Policy
@main_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')

# Terms of Service
@main_bp.route('/terms')
def terms():
    return render_template('terms.html')

# About Page
@main_bp.route('/about')
def about():
    return render_template('about.html')

# Contact Page
@main_bp.route('/contact')
def contact():
    return render_template('contact.html')

# Language selection
@main_bp.route('/set_language/<language>')
def set_language(language):
    """Set the user's language preference"""
    supported_languages = current_app.config.get('LANGUAGES', {})
    if language in supported_languages:
        session['language'] = language
    return redirect(request.referrer or url_for('main.index'))