"""List all portal users (no password data)."""
import os
import sqlite3

db = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "instance", "keeptrack_full.db"))
if not os.path.exists(db):
    print("Database not found:", db)
    raise SystemExit(1)

conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute(
    """
    SELECT id, email, COALESCE(username, ''), role, status, is_active, full_name
    FROM users
    ORDER BY id
    """
)
rows = cur.fetchall()
print(f"Total users: {len(rows)}\n")
print(f"{'ID':<4} {'Role':<12} {'Status':<10} {'Active':<6} {'Email':<35} {'Name'}")
print("-" * 100)
for row in rows:
    uid, email, username, role, status, active, name = row
    active_label = "Yes" if active else "No"
    print(f"{uid:<4} {(role or ''):<12} {(status or ''):<10} {active_label:<6} {(email or ''):<35} {name or ''}")
    if username:
        print(f"     username: {username}")

conn.close()
