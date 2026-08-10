import sqlite3, os, sys

src = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full.db"
dst = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full_rebuilt.db"
sql_path = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full_dump.sql"

# Phase 1: extract schema+data via writable_schema + manual approach
conn = sqlite3.connect(src)
conn.execute("PRAGMA writable_schema=ON")
cur = conn.cursor()
cur.execute("SELECT rowid, type, name, tbl_name, rootpage, sql FROM sqlite_master ORDER BY rowid")
rows = cur.fetchall()
print("master rows fetched", len(rows))

# dedupe by (type,name,sql) keeping lowest rowid
seen = set()
unique = []
for r in rows:
    key = (r[1], r[2], r[5])
    if key in seen:
        print("skip dup master", r[0], r[1], r[2])
        continue
    seen.add(key)
    unique.append(r)
print("unique master", len(unique))

# Build new database from unique schema
if os.path.exists(dst):
    os.remove(dst)
new = sqlite3.connect(dst)
nc = new.cursor()

for r in unique:
    typ, name, sql = r[1], r[2], r[5]
    if typ == "table" and name == "sqlite_sequence":
        continue
    if sql:
        try:
            nc.execute(sql)
        except Exception as e:
            print("schema fail", name, e)

new.commit()

# copy data table by table
for r in unique:
    if r[1] != "table" or r[2] in ("sqlite_sequence", "sqlite_stat1"):
        continue
    t = r[2]
    try:
        cur.execute(f"SELECT * FROM \"{t}\"")
        data = cur.fetchall()
        if not data:
            print(t, "0 rows")
            continue
        cur.execute(f"PRAGMA table_info(\"{t}\")")
        cols = [c[1] for c in cur.fetchall()]
        placeholders = ",".join(["?"] * len(cols))
        collist = ",".join(f'"{c}"' for c in cols)
        nc.executemany(f"INSERT INTO \"{t}\" ({collist}) VALUES ({placeholders})", data)
        print(t, len(data), "rows copied")
    except Exception as e:
        print("data fail", t, e)

new.commit()
new.close()
conn.close()
print("rebuilt at", dst)
