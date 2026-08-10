import sqlite3, os
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
db_path = os.path.join(BASE_DIR, 'instance', 'keeptrack_full.db')
print('DB path:', db_path)
if not os.path.exists(db_path):
    print('Database not found:', db_path)
    raise SystemExit(1)
conn = sqlite3.connect(db_path)
c = conn.cursor()
# Check if column exists
c.execute("PRAGMA table_info('grade')")
cols = [r[1] for r in c.fetchall()]
print('grade table columns before:', cols)
if 'class_id' not in cols:
    try:
        c.execute("ALTER TABLE grade ADD COLUMN class_id INTEGER")
        conn.commit()
        print('Added class_id column to grade table.')
    except Exception as e:
        print('Error adding column:', e)
else:
    print('class_id already exists, no change.')
# Verify
c.execute("PRAGMA table_info('grade')")
cols2 = [r[1] for r in c.fetchall()]
print('grade table columns after:', cols2)
conn.close()
