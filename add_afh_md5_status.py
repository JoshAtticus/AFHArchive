#!/usr/bin/env python3
"""
Migration script to add afh_md5_status column to uploads table
Run this script to update your database schema
"""

import sqlite3
import os
import sys

def add_afh_md5_status_column():
    """Add afh_md5_status column to the uploads table"""
    
    # Try to find the database file
    possible_db_paths = [
        'instance/app.db',
        'app.db',
        os.path.join(os.path.dirname(__file__), 'instance', 'app.db'),
    ]
    
    db_path = None
    for path in possible_db_paths:
        if os.path.exists(path):
            db_path = path
            break
    
    if not db_path:
        print("Error: Could not find database file.")
        print("Please ensure your database exists in one of these locations:")
        for path in possible_db_paths:
            print(f"  - {path}")
        sys.exit(1)
    
    print(f"Found database at: {db_path}")
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(uploads)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'afh_md5_status' in columns:
            print("Column 'afh_md5_status' already exists. Nothing to do.")
            conn.close()
            return
        
        # Add the new column
        print("Adding 'afh_md5_status' column to uploads table...")
        cursor.execute("""
            ALTER TABLE uploads 
            ADD COLUMN afh_md5_status VARCHAR(20)
        """)
        
        conn.commit()
        print("✓ Successfully added 'afh_md5_status' column")
        
        # Verify the change
        cursor.execute("PRAGMA table_info(uploads)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'afh_md5_status' in columns:
            print("✓ Migration verified successfully")
        else:
            print("✗ Warning: Column was not added properly")
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    print("=" * 60)
    print("Database Migration: Add afh_md5_status column")
    print("=" * 60)
    print()
    
    add_afh_md5_status_column()
    
    print()
    print("Migration completed successfully!")
    print()
    print("You can now:")
    print("  1. Restart your Flask application")
    print("  2. View upload details in the admin panel")
    print("  3. See automatic MD5 verification badges")
