import os
import sqlite3

# Define path to the database file
base_dir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(base_dir, 'instance', 'keeptrack_full.db')

print(f"Connecting to database at: {db_path}")

if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Batch schema column injections for the announcements table
        alterations = [
            ("ALTER TABLE announcements ADD COLUMN content TEXT DEFAULT '';", "announcements.content"),
            ("ALTER TABLE announcements ADD COLUMN target_role TEXT DEFAULT 'all';", "announcements.target_role"),
            ("ALTER TABLE announcements ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;", "announcements.created_at")
        ]
        
        for query, label in alterations:
            try:
                cursor.execute(query)
                print(f"Success: Added missing column -> {label}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"Verified: {label} already exists in schema.")
                else:
                    print(f"Skipped {label}: {e}")
                    
        conn.commit()
        conn.close()
        print("\nAnnouncements table synchronization complete!")
    except Exception as e:
        print(f"Database Error: {e}")
else:
    print("Error: Could not locate 'keeptrack_full.db' inside the instance folder.")