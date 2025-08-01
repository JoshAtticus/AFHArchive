from flask import Flask, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_babel import Babel, _
from decouple import config
import os
import glob

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

def compile_translations():
    """Automatically compile .po files to .mo files from Crowdin directories"""
    from babel.messages import pofile, mofile
    import io
    
    # Get all language directories created by Crowdin
    lang_dirs = glob.glob(os.path.join(os.path.dirname(__file__), '..', '*', 'app', 'translations', '*', 'LC_MESSAGES', 'messages.po'))
    
    for po_path in lang_dirs:
        mo_path = po_path.replace('.po', '.mo')
        
        # Check if .mo file needs updating
        if not os.path.exists(mo_path) or os.path.getmtime(po_path) > os.path.getmtime(mo_path):
            try:
                with open(po_path, 'rb') as po_file:
                    catalog = pofile.read_po(po_file)
                
                with open(mo_path, 'wb') as mo_file:
                    mofile.write_mo(mo_file, catalog)
                    
                print(f"Compiled {po_path} -> {mo_path}")
            except Exception as e:
                print(f"Error compiling {po_path}: {e}")

def setup_babel_directories(app):
    """Setup Babel to use Crowdin directory structure"""
    import babel.support
    from babel.core import Locale
    
    # Override Babel's default translation loading
    original_load = babel.support.Translations.load
    
    def load_crowdin_translations(dirname=None, locales=None, domain='messages'):
        if dirname is None:
            dirname = os.path.join(app.root_path, 'translations')
        
        catalog = babel.support.Translations()
        
        if locales is None:
            locales = [get_locale()]
        elif isinstance(locales, str):
            locales = [locales]
            
        for locale in locales:
            # Convert locale to string if it's a Locale object
            locale_str = str(locale) if hasattr(locale, 'language') else locale
            
            # Try Crowdin directory structure first
            crowdin_paths = [
                os.path.join(app.root_path, '..', locale_str, 'app', 'translations', locale_str, 'LC_MESSAGES', f'{domain}.mo'),
                os.path.join(app.root_path, '..', f'{locale_str}-{locale_str.upper()}', 'app', 'translations', locale_str, 'LC_MESSAGES', f'{domain}.mo'),
                os.path.join(app.root_path, '..', f'{locale_str}-ES', 'app', 'translations', locale_str, 'LC_MESSAGES', f'{domain}.mo'),
                os.path.join(app.root_path, '..', f'{locale_str}-CN', 'app', 'translations', locale_str, 'LC_MESSAGES', f'{domain}.mo'),
                os.path.join(app.root_path, '..', f'{locale_str}-PT', 'app', 'translations', locale_str, 'LC_MESSAGES', f'{domain}.mo'),
            ]
            
            for mo_path in crowdin_paths:
                if os.path.exists(mo_path):
                    try:
                        with open(mo_path, 'rb') as mo_file:
                            trans = babel.support.Translations(mo_file)
                            catalog.merge(trans)
                        break
                    except Exception as e:
                        print(f"Error loading translation {mo_path}: {e}")
            else:
                # Fallback to standard directory structure
                try:
                    standard_path = os.path.join(dirname, locale_str, 'LC_MESSAGES', f'{domain}.mo')
                    if os.path.exists(standard_path):
                        with open(standard_path, 'rb') as mo_file:
                            trans = babel.support.Translations(mo_file)
                            catalog.merge(trans)
                except Exception:
                    pass
        
        return catalog
    
    babel.support.Translations.load = staticmethod(load_crowdin_translations)

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
    
    # Auto-compile translations and setup Crowdin directory support
    compile_translations()
    setup_babel_directories(app)
    
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
        'ru': 'Русский',
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
