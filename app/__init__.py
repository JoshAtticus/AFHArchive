from flask import Flask, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_babel import Babel, _
from decouple import config
import os

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
babel = Babel()

def safe_int_config(key, default):
    """Safely parse integer config values, handling inline comments"""
    value = config(key, default=str(default))
    # Remove inline comments and whitespace
    value = value.split('#')[0].strip()
    try:
        return int(value)
    except ValueError:
        return default

def get_locale():
    """Get the best locale for the user"""
    # Check if user explicitly selected a language
    if 'language' in session:
        return session['language']
    
    # Check if Accept-Language header provides a supported language
    # Update this list as you add more languages to Crowdin
    return request.accept_languages.best_match(['en', 'ru', 'es', 'fr', 'de', 'it', 'pt', 'ja', 'ko', 'zh']) or 'en'

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = config('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = config('DATABASE_URL', default='sqlite:///afharchive.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = safe_int_config('MAX_CONTENT_LENGTH', 5368709120)  # 5GB
    app.config['UPLOAD_FOLDER'] = config('UPLOAD_DIR', default='uploads')
    app.config['GOOGLE_CLIENT_ID'] = config('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = config('GOOGLE_CLIENT_SECRET')
    app.config['ADMIN_EMAILS'] = config('ADMIN_EMAILS', default='').split(',')
    app.config['DOWNLOAD_SPEED_LIMIT'] = safe_int_config('DOWNLOAD_SPEED_LIMIT', 10485760)
    
    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Ensure chunks directory exists
    chunks_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'chunks')
    os.makedirs(chunks_dir, exist_ok=True)
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    # Initialize Babel
    babel.init_app(app, locale_selector=get_locale)
    
    # Make translation functions available in templates
    @app.context_processor
    def inject_conf_vars():
        from flask_babel import _ as babel_gettext
        return {
            'get_locale': get_locale,
            '_': babel_gettext
        }
    
    # Set supported languages (add more as they become available from Crowdin)
    app.config['LANGUAGES'] = {
        'en': 'English',
        # Add these as translations become available:
        # 'ru': 'Русский',
        # 'es': 'Español', 
        # 'fr': 'Français',
        # 'de': 'Deutsch',
        # 'it': 'Italiano',
        # 'pt': 'Português',
        # 'ja': '日本語',
        # 'ko': '한국어',
        # 'zh': '中文'
    }
    
    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.errors import errors_bp
    from app.models import Announcement  # Ensure model is registered

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(errors_bp)
    
    return app
