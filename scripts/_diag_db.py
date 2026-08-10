import sqlite3
from collections import Counter

db = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full.db"

try:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check")
    print("integrity:", cur.fetchall())
except Exception as e:
    print("connect/integrity error:", type(e).__name__, e)

try:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master ORDER BY name")
    rows = cur.fetchall()
    print("sqlite_master count:", len(rows))
    for r in rows:
        nm = (r[1] or "").lower()
        sql = (r[4] or "").lower()
        if "attendance" in nm or "attendance" in sql:
            print("ATTENDANCE ROW:", r)
    names = [r[1] for r in rows if r[1]]
    dups = [n for n, c in Counter(names).items() if c > 1]
    print("duplicate names:", dups)
    for r in rows:
        print(r[0], r[1], "rootpage=", r[3])
except Exception as e:
    print("master query error:", type(e).__name__, e)
