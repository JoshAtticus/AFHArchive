#!/usr/bin/env python3
"""
WSGI entry point for AFHArchive application
This file is used by Gunicorn and other WSGI servers
"""

# IMPORTANT: Monkey patch BEFORE any other imports to avoid SSL/HTTP conflicts
import gevent.monkey
gevent.monkey.patch_all()

import os
import sys
from decouple import config

# Add the project directory to Python path
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from app import create_app, db

# Create the Flask application
application = create_app()

# Start mirror client if configured
# The client now uses a file lock to ensure only one worker runs the heartbeat loop
from app.routes.mirror_api import start_mirror_client
start_mirror_client(application)

# Initialize database if needed
def init_db_if_needed():
    """Initialize database tables if they don't exist"""
    with application.app_context():
        try:
            # Try to create tables (this is safe if they already exist)
            db.create_all()
            application.logger.info("Database tables verified/created")
        except Exception as e:
            application.logger.error(f"Error initializing database: {e}")

# Auto-initialize database in production
if config('AUTO_INIT_DB', default=True, cast=bool):
    init_db_if_needed()

if __name__ == "__main__":
    # This allows running the WSGI file directly for testing
    application.run(debug=False)
