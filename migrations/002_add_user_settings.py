"""
Migration script to add user settings columns to users table
Run this with: python migrations/add_user_settings.py
"""

import sys
import os
from sqlalchemy import text

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

def migrate():
    print("Starting migration: Add User Settings Columns")
    app = create_app()
    
    with app.app_context():
        inspector = db.inspect(db.engine)
        
        # Get existing columns
        existing_columns = [col['name'] for col in inspector.get_columns('users')]
        print(f"Existing columns: {', '.join(existing_columns)}")
        
        # Columns to verify/add
        # Format: (column_name, sql_type, default_value)
        # default_value: 0 for False, 1 for True (SQLite/MySQL/Postgres)
        new_columns = [
            ('hide_profile', 'BOOLEAN', '0'),
            ('email_opt_in_announcements', 'BOOLEAN', '1'),
            ('email_opt_in_approvals', 'BOOLEAN', '1'),
            ('email_opt_in_rejections', 'BOOLEAN', '1')
        ]
        
        for col_name, col_type, default_val in new_columns:
            if col_name in existing_columns:
                print(f"✓ Column '{col_name}' already exists.")
            else:
                print(f"Adding column '{col_name}'...")
                try:
                    # Construct ALTER TABLE statement
                    # Note: We use text() for raw SQL execution
                    sql = text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type} DEFAULT {default_val}")
                    db.session.execute(sql)
                    print(f"✓ Added column '{col_name}'")
                except Exception as e:
                    print(f"✗ Failed to add column '{col_name}': {str(e)}")
                    # Continue to try other columns even if one fails
        
        try:
            db.session.commit()
            print("\nMigration completed successfully!")
        except Exception as e:
            print(f"\nError committing changes: {str(e)}")
            db.session.rollback()

if __name__ == "__main__":
    migrate()
