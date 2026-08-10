#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, db, get_active_academic_year, _principal_students_for_class, _student_ids_with_year_history
from models import AcademicYear, Class, Student, Grade

# fallback if helper removed
try:
    from app import _student_ids_with_year_history
except ImportError:
    def _student_ids_with_year_history(year_id):
        ids = set()
        for row in db.session.query(Student.id).filter(Student.academic_year_id == year_id):
            ids.add(row[0])
        for row in (
            db.session.query(Grade.student_id)
            .filter(Grade.academic_year_id == year_id, Grade.student_id.isnot(None))
            .distinct()
        ):
            ids.add(row[0])
        return list(ids)


def class_counts(year, viewing_archived=False):
    rows = []
    for klass in Class.query.order_by(Class.name).all():
        roster = _principal_students_for_class(klass, year, viewing_archived=viewing_archived)
        if roster:
            rows.append((klass.name, len(roster)))
    return rows


with app.app_context():
    active = get_active_academic_year()
    prev = AcademicYear.query.filter_by(name="2027-2028").first()
    print("Active:", active.name if active else None)
    if prev:
        print("2027-2028 archived roster (history):")
        for name, cnt in class_counts(prev, viewing_archived=True):
            print(f"  {name}: {cnt}")
        hist_ids = _student_ids_with_year_history(prev.id)
        print(f"  history union ids: {len(hist_ids)}")
    if active:
        print(f"{active.name} active roster (live):")
        for name, cnt in class_counts(active, viewing_archived=False):
            print(f"  {name}: {cnt}")
