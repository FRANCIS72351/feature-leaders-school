"""Temporary user-count script. Do not print password hashes."""
import os
import sqlite3
import sys

CANDIDATES = [
    os.path.join("instance", "keeptrack_full.db"),
    os.path.join("instance", "future_leaders_full.db"),
    os.path.join("instance", "instance", "keeptrack_full.db"),
    "keeptrack_full.db",
    os.path.join("instance", "future_leaders_full.db"),
]

print("cwd", os.getcwd())
print("python", sys.executable)

found = []
for rel in CANDIDATES:
    path = os.path.abspath(rel)
    exists = os.path.exists(path)
    print(f"check {path} exists={exists}")
    if exists:
        found.append(path)

# Also scan instance/ for .db files without walking the whole tree
inst = os.path.abspath("instance")
if os.path.isdir(inst):
    try:
        for name in os.listdir(inst):
            if name.endswith((".db", ".sqlite", ".sqlite3")):
                found.append(os.path.join(inst, name))
    except OSError as exc:
        print("listdir instance failed", exc)

seen = set()
dbs = []
for path in found:
    if path not in seen:
        seen.add(path)
        dbs.append(path)

if not dbs:
    print("NO DATABASE FOUND")
    sys.exit(1)

STAFF_ROLES = {
    "admin",
    "principal",
    "registrar",
    "registry",
    "registry officer",
    "business",
    "dean",
    "vpi",
    "vpa",
}

for db_path in dbs:
    print("\n====", db_path, "size", os.path.getsize(db_path))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print("tables:", tables)
    if "users" not in tables:
        conn.close()
        continue

    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    print("user columns:", cols)

    cur.execute("SELECT COUNT(*) FROM users")
    print("total users:", cur.fetchone()[0])

    cur.execute("SELECT COALESCE(role, '(null)'), COUNT(*) FROM users GROUP BY role ORDER BY COUNT(*) DESC")
    print("by role:")
    for role, count in cur.fetchall():
        print(f"  {role}: {count}")

    if "is_active" in cols and "status" in cols:
        cur.execute(
            """
            SELECT COALESCE(is_active, -1), COALESCE(status, '(null)'), COUNT(*)
            FROM users
            GROUP BY is_active, status
            ORDER BY COUNT(*) DESC
            """
        )
        print("by is_active/status:")
        for active, status, count in cur.fetchall():
            print(f"  is_active={active} status={status}: {count}")
    elif "is_active" in cols:
        cur.execute("SELECT COALESCE(is_active, -1), COUNT(*) FROM users GROUP BY is_active")
        print("by is_active:")
        for active, count in cur.fetchall():
            print(f"  is_active={active}: {count}")
    elif "status" in cols:
        cur.execute("SELECT COALESCE(status, '(null)'), COUNT(*) FROM users GROUP BY status")
        print("by status:")
        for status, count in cur.fetchall():
            print(f"  status={status}: {count}")

    if "system_settings" in tables:
        cur.execute("PRAGMA table_info(system_settings)")
        scols = [r[1] for r in cur.fetchall()]
        print("system_settings columns:", scols)
        cur.execute("SELECT * FROM system_settings")
        rows = cur.fetchall()
        print("system_settings rows:", rows)

    select_cols = ["id", "email"]
    for extra in ("username", "role", "status", "is_active", "full_name"):
        if extra in cols:
            select_cols.append(extra)
    placeholders = ", ".join(select_cols)
    cur.execute(f"SELECT {placeholders} FROM users ORDER BY id")
    staff = []
    print("\nstaff accounts:")
    for row in cur.fetchall():
        rec = dict(zip(select_cols, row))
        role = (rec.get("role") or "").strip().lower()
        if role in STAFF_ROLES:
            staff.append(rec)
            print(
                "  email={email} username={username} role={role} "
                "is_active={is_active} status={status} name={full_name}".format(
                    email=rec.get("email"),
                    username=rec.get("username"),
                    role=rec.get("role"),
                    is_active=rec.get("is_active"),
                    status=rec.get("status"),
                    full_name=rec.get("full_name"),
                )
            )
    if not staff:
        print("  (none)")
    conn.close()
