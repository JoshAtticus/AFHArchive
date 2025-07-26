from flask import Blueprint, render_template, redirect, url_for, session, flash, current_app, request
from flask_login import login_user, logout_user, login_required, current_user
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
import requests
from app import db, login_manager
from app.models import User

auth_bp = Blueprint('auth', __name__)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@auth_bp.route('/login')
def login():
    return render_template('auth/login.html')

@auth_bp.route('/google')
def google_auth():
    # Google OAuth2 authorization URL
    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/auth?"
        f"client_id={current_app.config['GOOGLE_CLIENT_ID']}&"
        f"redirect_uri={url_for('auth.google_callback', _external=True)}&"
        f"scope=openid email profile&"
        f"response_type=code"
    )
    return redirect(google_auth_url)

@auth_bp.route('/google/callback')
def google_callback():
    code = request.args.get('code')
    if not code:
        flash('Authorization failed', 'error')
        return redirect(url_for('main.index'))
    
    # Exchange code for tokens
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        'client_id': current_app.config['GOOGLE_CLIENT_ID'],
        'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': url_for('auth.google_callback', _external=True)
    }
    
    token_response = requests.post(token_url, data=token_data)
    token_json = token_response.json()
    
    if 'id_token' not in token_json:
        flash('Authentication failed', 'error')
        return redirect(url_for('main.index'))
    
    try:
        # Verify and decode the ID token
        idinfo = id_token.verify_oauth2_token(
            token_json['id_token'], 
            google_requests.Request(), 
            current_app.config['GOOGLE_CLIENT_ID']
        )
        
        # Get user info
        google_id = idinfo['sub']
        email = idinfo['email']
        name = idinfo['name']
        avatar_url = idinfo.get('picture', '')
        
        # Check if user exists
        user = User.query.filter_by(google_id=google_id).first()
        
        if not user:
            # Create new user
            is_admin = email in current_app.config['ADMIN_EMAILS']
            user = User(
                google_id=google_id,
                email=email,
                name=name,
                avatar_url=avatar_url,
                is_admin=is_admin
            )
            db.session.add(user)
            db.session.commit()
            flash(f'Welcome to AFHArchive, {name}!', 'success')
        else:
            # Update existing user info
            user.name = name
            user.avatar_url = avatar_url
            user.is_admin = email in current_app.config['ADMIN_EMAILS']
            db.session.commit()
            flash(f'Welcome back, {name}!', 'success')
        
        login_user(user)
        return redirect(url_for('main.index'))
        
    except ValueError:
        flash('Invalid authentication token', 'error')
        return redirect(url_for('main.index'))

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.index'))
