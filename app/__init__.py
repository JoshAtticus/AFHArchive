from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from decouple import config
import os

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()

def safe_int_config(key, default):
    """Safely parse integer config values, handling inline comments"""
    value = config(key, default=str(default))
    # Remove inline comments and whitespace
    value = value.split('#')[0].strip()
    try:
        return int(value)
    except ValueError:
        return default

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = config('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = config('DATABASE_URL', default='sqlite:///afharchive.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = safe_int_config('MAX_CONTENT_LENGTH', 1073741824)
    app.config['UPLOAD_FOLDER'] = config('UPLOAD_DIR', default='uploads')
    app.config['GOOGLE_CLIENT_ID'] = config('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = config('GOOGLE_CLIENT_SECRET')
    app.config['ADMIN_EMAILS'] = config('ADMIN_EMAILS', default='').split(',')
    app.config['DOWNLOAD_SPEED_LIMIT'] = safe_int_config('DOWNLOAD_SPEED_LIMIT', 10485760)
    
    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app
