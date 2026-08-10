"""One-shot migration for students.is_promoted / students.is_registered."""
import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app, migrate_student_registration_columns, get_sqlite_file_path

if __name__ == '__main__':
    with app.app_context():
        db_file = get_sqlite_file_path()
        print(f'Database: {db_file}')
        migrate_student_registration_columns()
        print('Done.')
