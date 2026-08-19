"""Count users by role. Do not print emails or passwords."""
import os
import sqlite3

candidates = [
    os.path.join("instance", "keeptrack_full.db"),
    os.path.join("instance", "future_leaders_full.db"),
    os.path.join("instance", "instance", "keeptrack_full.db"),
    "keeptrack_full.db",
]
found = []
for rel in candidates:
    if os.path.exists(rel):
        found.append(os.path.abspath(rel))
if os.path.isdir("instance"):
    for name in os.listdir("instance"):
        if name.endswith((".db", ".sqlite", ".sqlite3")):
            found.append(os.path.abspath(os.path.join("instance", name)))

seen = set()
if not found:
    print("NO DATABASE FOUND")
    raise SystemExit(0)

for path in found:
    if path in seen:
        continue
    seen.add(path)
    print("FILE", os.path.basename(path))
    uri = "file:" + path.replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    if "users" not in tables:
        print("  no users table")
        conn.close()
        continue
    rows = cur.execute(
        "SELECT lower(trim(coalesce(role, ''))), count(*) FROM users GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    for role, count in rows:
        print("  %s: %d" % (role or "(empty)", count))
    conn.close()
