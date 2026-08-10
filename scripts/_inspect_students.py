import sqlite3
src = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full.db.bak"
conn = sqlite3.connect(src)
conn.execute("PRAGMA writable_schema=ON")
cur = conn.cursor()
cur.execute("SELECT rowid, type, name, rootpage, sql FROM sqlite_master WHERE name='students' ORDER BY rowid")
for r in cur.fetchall():
    print("--- rowid", r[0], "rootpage", r[3], "---")
    print(r[4][:500] if r[4] else None)
    print("...")
