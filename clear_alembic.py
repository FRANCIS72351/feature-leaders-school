import os
import sqlite3

# Absolute pathing targeting instance folder database asset directly
base_dir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(base_dir, 'instance', 'keeptrack_full.db')

print(f"Targeting Database for missing attribute injection: {db_path}")

if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Inject the active/inactive status string column to the structural table
        cursor.execute("ALTER TABLE teachers ADD COLUMN status TEXT DEFAULT 'ACTIVE';")
        
        conn.commit()
        conn.close()
        print("Success: 'status' column injected cleanly into the 'teachers' table structure!")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Verified: 'status' column already exists inside your schema.")
        else:
            print(f"SQL Execution Error: {e}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("Error: Could not locate 'keeptrack_full.db' inside your instance directory.")