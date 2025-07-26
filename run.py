#!/usr/bin/env python3
"""
AFHArchive Application Runner
"""

import sys
import os
from app import create_app, db
from app.models import User, Upload

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

def main():
    """Main application entry point"""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'init-db':
            success = init_database()
            sys.exit(0 if success else 1)
        else:
            print(f"Unknown command: {command}")
            print("Available commands: init-db")
            sys.exit(1)
    
    # Run the Flask application
    app = create_app()
    
    # Get configuration
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5000'))
    
    print(f"🚀 Starting AFHArchive on http://{host}:{port}")
    if debug:
        print("⚠️  Debug mode is enabled")
    
    app.run(host=host, port=port, debug=debug)

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
