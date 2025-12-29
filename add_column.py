from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE uploads ADD COLUMN is_on_main_server BOOLEAN DEFAULT 1"))
            conn.commit()
        print("Successfully added is_on_main_server column")
    except Exception as e:
        print(f"Error adding column (might already exist): {e}")
