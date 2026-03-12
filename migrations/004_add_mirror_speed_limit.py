import sys
import os
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

def migrate():
    print("Starting migration: Add Mirror Download Speed Limit")
    app = create_app()
    
    with app.app_context():
        inspector = db.inspect(db.engine)
        existing_columns = [col['name'] for col in inspector.get_columns('mirrors')]
        
        new_columns = [
            ('download_speed_limit_kbps', 'INTEGER', '0')
        ]
        
        for col_name, col_type, default_val in new_columns:
            if col_name in existing_columns:
                print(f"✓ Column '{col_name}' already exists.")
            else:
                print(f"Adding column '{col_name}'...")
                try:
                    sql = text(f"ALTER TABLE mirrors ADD COLUMN {col_name} {col_type} DEFAULT {default_val}")
                    db.session.execute(sql)
                    print(f"✓ Added column '{col_name}'")
                except Exception as e:
                    print(f"✗ Failed to add column '{col_name}': {str(e)}")
        
        try:
            db.session.commit()
            print("\nMigration completed successfully!")
        except Exception as e:
            print(f"\nError committing changes: {str(e)}")
            db.session.rollback()

if __name__ == "__main__":
    migrate()
