import sqlite3
db = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full.db"
conn = sqlite3.connect(db)
cur = conn.cursor()
try:
    cur.execute("SELECT COUNT(*) FROM students")
    print("students count", cur.fetchone()[0])
    cur.execute("PRAGMA table_info(students)")
    cols = [r[1] for r in cur.fetchall()]
    print("students cols", cols)
    cur.execute("SELECT COUNT(*) FROM attendance")
    print("attendance count", cur.fetchone()[0])
except Exception as e:
    print("query error", e)
