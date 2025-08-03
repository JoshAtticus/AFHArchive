#!/usr/bin/env python3
"""
Autoreviewer Migration Script
This script creates the autoreviewer system user if it doesn't exist.
"""

import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Set up Flask app context
from app import create_app, db
from app.utils.autoreviewer import get_or_create_autoreviewer, get_autoreviewer_stats

def main():
    """Initialize the autoreviewer system"""
    app = create_app()
    
    with app.app_context():
        print("AFHArchive Autoreviewer Migration")
        print("=" * 40)
        
        try:
            # Create autoreviewer user
            print("Creating/verifying autoreviewer system user...")
            autoreviewer = get_or_create_autoreviewer()
            print(f"✓ Autoreviewer user ready: {autoreviewer.name} (ID: {autoreviewer.id})")
            
            # Get current stats
            stats = get_autoreviewer_stats()
            print(f"✓ Current autoreviewer stats:")
            print(f"  - Total reviewed: {stats['total_reviewed']}")
            print(f"  - Total rejected: {stats['total_rejected']}")
            print(f"  - Recent duplicates: {len(stats['duplicate_uploads'])}")
            
            print("\n" + "=" * 40)
            print("Autoreviewer system is ready!")
            print("The autoreviewer will automatically check new uploads for duplicates.")
            print("Use the admin dashboard to manage autoreviewer settings.")
            
        except Exception as e:
            print(f"Error setting up autoreviewer: {str(e)}")
            sys.exit(1)

if __name__ == "__main__":
    main()
