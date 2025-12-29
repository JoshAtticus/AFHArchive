#!/usr/bin/env python3
"""
AFHArchive Application Runner
"""

# IMPORTANT: Monkey patch BEFORE any other imports to avoid SSL/HTTP conflicts
import gevent.monkey
gevent.monkey.patch_all()

import sys
import os
from app import create_app, db, socketio
from app.models import User, Upload, Announcement
import shutil
import datetime
def backup_database(db_path):
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}, skipping backup.")
        return None
    backup_name = db_path + ".bak-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    shutil.copy2(db_path, backup_name)
    print(f"✓ Database backed up to {backup_name}")
    return backup_name

def auto_migrate():
    """Backup DB and auto-migrate schema (using Flask-Migrate if available, else fallback to create_all)"""
    app = create_app()
    db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
    backup_database(db_path)
    with app.app_context():
        try:
            # Try Flask-Migrate/Alembic if available
            try:
                from flask_migrate import upgrade
                print("Running Flask-Migrate database upgrade...")
                upgrade()
                print("✓ Database migration complete!")
            except ImportError:
                print("Flask-Migrate not installed, falling back to db.create_all()...")
                db.create_all()
                print("✓ Database tables created/updated!")
            return True
        except Exception as e:
            print(f"✗ Error during migration: {e}")
            return False

def init_database():
    """Initialize the database tables"""
    app = create_app()
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("✓ Database tables created successfully")
            return True
        except Exception as e:
            print(f"✗ Error creating database tables: {e}")
            return False

def start_gunicorn():
    """Start the application using Gunicorn"""
    import subprocess
    from decouple import config
    
    # Detect Python command
    python_cmd = 'python3' if os.name != 'nt' else 'python'
    
    # Build Gunicorn command
    cmd = [
        python_cmd,
        '-m',
        'gunicorn',
        '--config', 'gunicorn.conf.py',
        'wsgi:application'
    ]
    
    # Override with environment variables if needed
    bind_host = config('GUNICORN_HOST', default='0.0.0.0')
    bind_port = config('GUNICORN_PORT', default='8000')
    workers = config('GUNICORN_WORKERS', default=None)
    
    cmd.extend(['--bind', f'{bind_host}:{bind_port}'])
    
    if workers:
        cmd.extend(['--workers', str(workers)])
    
    print(f"🚀 Starting AFHArchive with Gunicorn on http://{bind_host}:{bind_port}")
    print(f"📝 Command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"✗ Error starting Gunicorn: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down AFHArchive")
        sys.exit(0)

def main():
    """Main application entry point"""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'init-db':
            success = init_database()
            sys.exit(0 if success else 1)
        elif command == 'auto-migrate':
            success = auto_migrate()
            sys.exit(0 if success else 1)
        elif command == 'gunicorn':
            start_gunicorn()
        elif command == 'production':
            # Set production environment and start with Gunicorn
            os.environ['FLASK_ENV'] = 'production'
            os.environ['FLASK_DEBUG'] = 'False'
            start_gunicorn()
        else:
            print(f"Unknown command: {command}")
            print("Available commands: init-db, auto-migrate, gunicorn, production")
            sys.exit(1)
    
    # Run the Flask development server
    app = create_app()
    
    # Start mirror client if configured
    from app.routes.mirror_api import start_mirror_client
    start_mirror_client(app)
    
    # Get configuration
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5000'))
    
    print(f"🚀 Starting AFHArchive (Development) on http://{host}:{port}")
    if debug:
        print("⚠️  Debug mode is enabled - Use 'python run.py production' for production mode")
    
    # Use allow_unsafe_werkzeug=True to avoid crash with gevent in debug mode
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)

# Legacy Flask CLI commands for backward compatibility
app = create_app()

@app.cli.command()
def init_db():
    """Initialize the database"""
    with app.app_context():
        db.create_all()
        print("Database initialized!")

@app.cli.command()
def create_admin():
    """Create an admin user (interactive)"""
    email = input("Enter admin email: ")
    name = input("Enter admin name: ")
    google_id = input("Enter Google ID (can be temporary): ")
    
    user = User(
        google_id=google_id,
        email=email,
        name=name,
        is_admin=True
    )
    
    db.session.add(user)
    db.session.commit()
    print(f"Admin user {email} created!")

if __name__ == '__main__':
    main()
