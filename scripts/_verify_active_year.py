"""Verify active academic year resolution against the live database."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_active_academic_year

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'keeptrack_full.db')


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        'SELECT id, name, is_active, start_date, end_date FROM academic_years ORDER BY id'
    )
    rows = cur.fetchall()
    print('DB academic_years:')
    for row in rows:
        print(f'  id={row[0]} name={row[1]!r} is_active={row[2]} start={row[3]} end={row[4]}')
    flagged = [r for r in rows if r[2]]
    print(f'Flagged active count: {len(flagged)}')
    conn.close()

    with app.app_context():
        resolved = get_active_academic_year()
        if resolved:
            print(f'get_active_academic_year(): {resolved.name!r} (id={resolved.id}, is_active={resolved.is_active})')
        else:
            print('get_active_academic_year(): None')


if __name__ == '__main__':
    main()
