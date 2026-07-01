import sys
import os
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

def migrate():
    print("Starting migration: Add Announcement Indefinite Column")
    app = create_app()
    
    with app.app_context():
        inspector = db.inspect(db.engine)
        existing_columns = [col['name'] for col in inspector.get_columns('announcements')]
        
        col_name = 'is_indefinite'
        col_type = 'BOOLEAN'
        default_val = '0'
        
        if col_name in existing_columns:
            print(f"[OK] Column '{col_name}' already exists.")
        else:
            print(f"Adding column '{col_name}'...")
            try:
                sql = text(f"ALTER TABLE announcements ADD COLUMN {col_name} {col_type} DEFAULT {default_val}")
                db.session.execute(sql)
                print(f"[OK] Added column '{col_name}'")
            except Exception as e:
                print(f"[ERROR] Failed to add column '{col_name}': {str(e)}")
        
        try:
            db.session.commit()
            print("\nMigration completed successfully!")
        except Exception as e:
            print(f"\nError committing changes: {str(e)}")
            db.session.rollback()

if __name__ == "__main__":
    migrate()
