from app import create_app, db
from app.models import Mirror, FileReplica, SiteConfig

app = create_app()

with app.app_context():
    print("Creating new tables...")
    try:
        Mirror.__table__.create(db.engine)
        print("Created 'mirrors' table.")
    except Exception as e:
        print(f"Error creating 'mirrors' table (might already exist): {e}")
        
    try:
        FileReplica.__table__.create(db.engine)
        print("Created 'file_replicas' table.")
    except Exception as e:
        print(f"Error creating 'file_replicas' table (might already exist): {e}")

    try:
        SiteConfig.__table__.create(db.engine)
        print("Created 'site_config' table.")
    except Exception as e:
        print(f"Error creating 'site_config' table (might already exist): {e}")
        
    print("Database update complete.")
