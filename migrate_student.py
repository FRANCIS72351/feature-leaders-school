import sqlite3
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(BASE_DIR, 'instance', 'keeptrack_full.db')

def migrate():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Adding registration columns to students table...")
    
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN registration_type VARCHAR(20) DEFAULT 'New'")
        print("Column registration_type added.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"Error adding registration_type: {e}")

    try:
        cursor.execute("ALTER TABLE students ADD COLUMN created_at DATETIME")
        print("Column created_at added.")
        cursor.execute("UPDATE students SET created_at = datetime('now') WHERE created_at IS NULL")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"Error adding created_at: {e}")

    for col, default in (("is_promoted", 0), ("is_registered", 1)):
        try:
            cursor.execute(f"ALTER TABLE students ADD COLUMN {col} BOOLEAN NOT NULL DEFAULT {default}")
            print(f"Column {col} added.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                print(f"Error adding {col}: {e}")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
