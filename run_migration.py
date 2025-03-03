import sqlite3
from pathlib import Path

# Path to your SQLite database
DB_PATH = Path('instance/media_analysis.db')

# Ensure the database exists
if not DB_PATH.exists():
    print(f"Database file not found at {DB_PATH}. Please check the path.")
    exit(1)

# Connect to the database
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("Running migration: Add face_id column to users table...")

try:
    # Add has_face_id column to users table
    cursor.execute("ALTER TABLE users ADD COLUMN has_face_id BOOLEAN NOT NULL DEFAULT 0")
    
    # Create login_event table
    cursor.execute("""
        CREATE TABLE login_event (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            login_time DATETIME NOT NULL,
            method VARCHAR(20) NOT NULL,
            success BOOLEAN NOT NULL DEFAULT 1,
            failure_reason VARCHAR(255),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # Commit the changes
    conn.commit()
    print("Migration completed successfully!")
    
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("Column already exists. Migration may have been already applied.")
    else:
        print(f"Error during migration: {e}")
    conn.rollback()
    
except Exception as e:
    print(f"Unexpected error: {e}")
    conn.rollback()
    
finally:
    # Close the connection
    conn.close() 