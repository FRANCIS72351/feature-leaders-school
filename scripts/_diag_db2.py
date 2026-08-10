import sqlite3
db = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full.db"
for attempt in ["writable_schema", "ignore_check"]:
    try:
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA writable_schema=ON")
        cur = conn.cursor()
        cur.execute("SELECT rowid, type, name, tbl_name, rootpage, sql FROM sqlite_master")
        rows = cur.fetchall()
        print("SUCCESS rows", len(rows))
        att = [r for r in rows if r[2] == "attendance" or r[3] == "attendance"]
        print("attendance entries:", len(att))
        for r in att:
            print(r)
        break
    except Exception as e:
        print(attempt, "failed:", e)
