#!/usr/bin/env python3
"""
Migration script to add GitHub OAuth support
Run this script to update your database schema for GitHub authentication
"""

import sqlite3
import os
import sys

def add_github_oauth_columns():
    """Add github_id column and make google_id nullable"""
    
    # Try to find the database file
    possible_db_paths = [
        'instance/app.db',
        'app.db',
        'instance/afharchive.db',
        'afharchive.db',
        os.path.join(os.path.dirname(__file__), 'instance', 'app.db'),
        os.path.join(os.path.dirname(__file__), 'instance', 'afharchive.db'),
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
        
        # Check current table structure
        cursor.execute("PRAGMA table_info(users)")
        columns = {row[1]: row for row in cursor.fetchall()}
        
        changes_made = False
        
        # Check if github_id column exists
        if 'github_id' not in columns:
            print("Adding 'github_id' column to users table...")
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN github_id VARCHAR(100)
            """)
            changes_made = True
            print("✓ Successfully added 'github_id' column")
        else:
            print("Column 'github_id' already exists.")
        
        # Note: SQLite doesn't support modifying column constraints directly
        # google_id is already nullable by default unless explicitly set NOT NULL
        # We need to check and potentially recreate the table if it's NOT NULL
        
        if 'google_id' in columns:
            # Check if google_id is NOT NULL
            google_id_info = columns['google_id']
            # Column info: (cid, name, type, notnull, dflt_value, pk)
            is_not_null = google_id_info[3] == 1
            
            if is_not_null:
                print("Making 'google_id' nullable...")
                
                # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
                # This is a more complex operation
                
                # Get all columns
                cursor.execute("PRAGMA table_info(users)")
                all_columns = cursor.fetchall()
                
                # Create new table with modified schema
                cursor.execute("""
                    CREATE TABLE users_new (
                        id INTEGER PRIMARY KEY,
                        google_id VARCHAR(100) UNIQUE,
                        github_id VARCHAR(100) UNIQUE,
                        email VARCHAR(100) NOT NULL UNIQUE,
                        name VARCHAR(100) NOT NULL,
                        avatar_url VARCHAR(200),
                        is_admin BOOLEAN DEFAULT 0,
                        created_at DATETIME
                    )
                """)
                
                # Copy data from old table
                cursor.execute("""
                    INSERT INTO users_new (id, google_id, github_id, email, name, avatar_url, is_admin, created_at)
                    SELECT id, google_id, github_id, email, name, avatar_url, is_admin, created_at
                    FROM users
                """)
                
                # Drop old table
                cursor.execute("DROP TABLE users")
                
                # Rename new table
                cursor.execute("ALTER TABLE users_new RENAME TO users")
                
                changes_made = True
                print("✓ Successfully made 'google_id' nullable")
            else:
                print("Column 'google_id' is already nullable.")
        
        if changes_made:
            conn.commit()
            print("\n✓ Database migration completed successfully!")
        else:
            print("\n✓ No changes needed. Database is up to date.")
        
        # Verify the changes
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'github_id' in columns:
            print("✓ Migration verified: github_id column exists")
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    print("=" * 60)
    print("Database Migration: Add GitHub OAuth Support")
    print("=" * 60)
    print()
    
    add_github_oauth_columns()
    
    print()
    print("Next steps:")
    print("  1. Add GitHub OAuth credentials to your .env file:")
    print("     GITHUB_CLIENT_ID=your-github-client-id")
    print("     GITHUB_CLIENT_SECRET=your-github-client-secret")
    print()
    print("  2. Create GitHub OAuth App at:")
    print("     https://github.com/settings/developers")
    print()
    print("  3. Restart your Flask application")
    print("  4. Users can now sign in with GitHub!")
