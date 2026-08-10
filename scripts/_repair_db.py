import sqlite3
from collections import defaultdict

db = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full.db"

conn = sqlite3.connect(db)
conn.execute("PRAGMA writable_schema=ON")
cur = conn.cursor()
cur.execute("SELECT rowid, type, name, tbl_name, rootpage, sql FROM sqlite_master ORDER BY rowid")
rows = cur.fetchall()
print("total rows", len(rows))

by_name = defaultdict(list)
for r in rows:
    if r[1] in ("table", "index", "trigger", "view"):
        by_name[(r[1], r[2])].append(r)

dups = {k: v for k, v in by_name.items() if len(v) > 1}
print("duplicate objects:", len(dups))
for k, v in sorted(dups.items()):
    print(k, "count", len(v))
    for r in v:
        print("  rowid", r[0], "rootpage", r[4])

if ("table", "attendance") in dups:
    att_rows = dups[("table", "attendance")]
    keep = min(att_rows, key=lambda r: r[0])
    for r in att_rows:
        if r[0] != keep[0]:
            print("DELETE rowid", r[0])
            cur.execute("DELETE FROM sqlite_master WHERE rowid=?", (r[0],))

for k, v in dups.items():
    if k == ("table", "attendance"):
        continue
    v_sorted = sorted(v, key=lambda r: r[0])
    for r in v_sorted[1:]:
        print("DELETE dup", k, "rowid", r[0])
        cur.execute("DELETE FROM sqlite_master WHERE rowid=?", (r[0],))

conn.commit()
conn.execute("PRAGMA writable_schema=OFF")
cur.execute("PRAGMA integrity_check")
print("integrity:", cur.fetchall())
conn.close()
print("repair pass 1 done")
