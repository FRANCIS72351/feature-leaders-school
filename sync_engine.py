import os
import sqlite3
import requests
import uuid
from datetime import datetime

CLOUD_API_URL = "https://francistechschoolmanagement.pythonanywhere.com/api/v1/sync"
LOCAL_DB_PATH = os.path.join(os.path.expanduser("~"), ".school_management", "local_data.db")

def check_internet():
    """Check if the desktop app can reach the cloud API"""
    try:
        # Timeout quickly if there's no internet connection
        response = requests.get(f"{CLOUD_API_URL}/health", timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False

def save_student_offline(name, grade):
    """Saves student data locally when offline or online"""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    cursor = conn.cursor()
    
    student_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO students (id, name, grade, updated_at, is_synced)
        VALUES (?, ?, ?, ?, ?)
    """, (student_id, name, grade, timestamp, 0)) # 0 means False (Not synced)
    
    conn.commit()
    conn.close()
    print(f"💾 Saved student offline with ID: {student_id}")

def get_last_sync_timestamp():
    """Retrieves the last time this specific machine pulled data from the cloud"""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    cursor = conn.cursor()
    
    # Initialize metadata tracking matrix if it doesn't exist yet
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_metadata (
            key TEXT PRIMARY KEY,
            val TEXT
        )
    """)
    
    cursor.execute("SELECT val FROM sync_metadata WHERE key = 'last_pull_time'")
    row = cursor.fetchone()
    conn.close()
    
    # Default to an early Epoch timestamp if this is the machine's first run
    return row[0] if row else "1970-01-01T00:00:00"

def update_last_sync_timestamp(timestamp):
    """Updates the local device checkpoint clock to match the latest server state"""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sync_metadata (key, val) VALUES ('last_pull_time', ?)
        ON CONFLICT(key) DO UPDATE SET val = excluded.val
    """, (timestamp,))
    conn.commit()
    conn.close()

def pull_cloud_to_local():
    """Fetches new additions or adjustments made on other remote devices from the cloud"""
    if not check_internet():
        print("🔌 System offline. Skipping downstream delta engine sync.")
        return False

    last_sync = get_last_sync_timestamp()
    print(f"🔄 Checking cloud for modifications processed since: {last_sync}")
    
    try:
        # Request any entities changed since this device's last pull checkpoint
        response = requests.get(f"{CLOUD_API_URL}/students/delta", params={"since": last_sync}, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            cloud_records = data.get("records", [])
            server_time = data.get("server_time", datetime.utcnow().isoformat())
            
            if not cloud_records:
                print("✨ Downstream status clean. No remote updates found.")
                update_last_sync_timestamp(server_time)
                return True
                
            print(f"📥 Found {len(cloud_records)} updates from other devices. Merging data locally...")
            
            conn = sqlite3.connect(LOCAL_DB_PATH)
            cursor = conn.cursor()
            
            for record in cloud_records:
                # Upsert record safely matching by unique UUID
                cursor.execute("""
                    INSERT INTO students (id, name, grade, updated_at, is_synced)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        grade = excluded.grade,
                        updated_at = excluded.updated_at,
                        is_synced = 1
                """, (record['id'], record['name'], record['grade'], record['updated_at']))
                
            conn.commit()
            conn.close()
            
            update_last_sync_timestamp(server_time)
            print("✅ Local database successfully synchronized with latest global changes.")
            return True
        else:
            print(f"⚠️ Cloud delta endpoint returned error code: {response.status_code}")
            return False
    except requests.RequestException as e:
        print(f"❌ Failed to query downstream cloud changes: {e}")
        return False

def sync_local_to_cloud():
    """Finds all unsynced local data, pushes it up, then triggers a down-stream pull sync"""
    if not check_internet():
        print("🔌 System is offline. Sync skipped.")
        return False

    conn = sqlite3.connect(LOCAL_DB_PATH)
    cursor = conn.cursor()
    
    # Grab all rows that haven't been pushed to the cloud yet
    cursor.execute("SELECT id, name, grade, updated_at FROM students WHERE is_synced = 0")
    unsynced_rows = cursor.fetchall()
    
    if unsynced_rows:
        print(f"🔄 Found {len(unsynced_rows)} records to sync upstream. Uploading...")
        for row in unsynced_rows:
            payload = {
                "id": row[0],
                "name": row[1],
                "grade": row[2],
                "updated_at": row[3]
            }
            
            try:
                response = requests.post(f"{CLOUD_API_URL}/students", json=payload, timeout=5)
                if response.status_code in [200, 201]:
                    cursor.execute("UPDATE students SET is_synced = 1 WHERE id = ?", (row[0],))
                    conn.commit()
                    print(f"✅ Successfully synced record: {row[0]}")
            except requests.RequestException as e:
                print(f"❌ Failed to sync row {row[0]}: {e}")
                break # Stop sync run if connection drops mid-process
    else:
        print("✨ No upstream local data requires synchronization.")

    conn.close()
    
    # Run downstream data pull synchronization right after upstream is handled
    pull_cloud_to_local()
    return True