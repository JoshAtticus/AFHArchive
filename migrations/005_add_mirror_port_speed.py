import sqlite3
import os

def upgrade():
    # Get the base directory
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(base_dir, 'instance', 'afharchive.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(mirrors)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'port_speed_mbps' not in columns:
            print("Adding port_speed_mbps to mirrors table...")
            cursor.execute("ALTER TABLE mirrors ADD COLUMN port_speed_mbps INTEGER DEFAULT 100")
            conn.commit()
            print("Successfully added port_speed_mbps column.")
        else:
            print("Column port_speed_mbps already exists.")
            
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()