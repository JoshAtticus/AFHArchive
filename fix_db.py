from app import create_app, db
from app.models import ABTestAssignment
from sqlalchemy import inspect

def fix_database():
    app = create_app()
    with app.app_context():
        print(f"Checking database: {app.config['SQLALCHEMY_DATABASE_URI']}")
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        if 'ab_test_assignments' in tables:
            print("✓ Table 'ab_test_assignments' already exists.")
        else:
            print("✗ Table 'ab_test_assignments' is MISSING. Creating it now...")
            try:
                ABTestAssignment.__table__.create(db.engine)
                print("✓ Table 'ab_test_assignments' created successfully.")
            except Exception as e:
                print(f"Error creating table: {e}")
                # Fallback to create_all which is safer
                db.create_all()
                print("✓ Ran db.create_all() as fallback.")

if __name__ == "__main__":
    fix_database()
