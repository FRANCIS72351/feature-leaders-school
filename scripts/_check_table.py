import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import app, db
from sqlalchemy import text

with app.app_context():
    names = (
        "class", "classes", "student", "students", "student_payment", "student_payments",
        "academic_year", "academic_years", "business_transaction", "business_transactions",
        "attendance",
    )
    for t in names:
        rows = db.session.execute(text(f'PRAGMA table_info("{t}")')).fetchall()
        print(t, len(rows), "cols" if rows else "MISSING")
