import sqlite3
dst = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full_rebuilt.db"
conn = sqlite3.connect(dst)
cur = conn.cursor()
cur.execute("PRAGMA integrity_check")
print("integrity", cur.fetchall())
cur.execute("PRAGMA table_info(students)")
print("cols", [c[1] for c in cur.fetchall()])
cur.execute("SELECT COUNT(*) FROM students")
print("students", cur.fetchone()[0])
