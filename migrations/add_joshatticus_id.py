"""
Migration script to add joshatticus_id column to users table
Run this with: python migrations/add_joshatticus_id.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text

def migrate():
    app = create_app()
    
    with app.app_context():
        # Check if column already exists
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'joshatticus_id' in columns:
            print("✓ Column 'joshatticus_id' already exists in users table")
            return
        
        print("Adding 'joshatticus_id' column to users table...")
        
        try:
            # Add the new column
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE users ADD COLUMN joshatticus_id VARCHAR(100) UNIQUE'))
                conn.commit()
            
            print("✓ Successfully added 'joshatticus_id' column to users table")
            
        except Exception as e:
            print(f"✗ Error adding column: {e}")
            print("If you're using SQLite, you may need to recreate the database or manually add the column.")

if __name__ == '__main__':
    migrate()
