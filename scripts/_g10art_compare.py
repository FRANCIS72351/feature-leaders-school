#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (
    app, db, get_active_academic_year, _principal_students_for_class,
    get_student_class_for_year,
)
from models import AcademicYear, Class, Student, Enrollment, Grade


def roster_ids(klass, year, archived):
    return {s.id: s for s in _principal_students_for_class(klass, year, viewing_archived=archived)}


with app.app_context():
    active = get_active_academic_year()
    prev = AcademicYear.query.filter_by(name="2027-2028").first()
    g10 = Class.query.filter_by(name="Grade 10 Art").first()
    g11 = Class.query.filter_by(name="Grade 11 Art").first()

    print("Active year:", active.name, "is_active=", active.is_active)
    print("Grade 10 Art id:", g10.id if g10 else None)
    print("Grade 11 Art id:", g11.id if g11 else None)

    if prev and g10:
        prev_map = roster_ids(g10, prev, archived=True)
        live_map = roster_ids(g10, active, archived=False)
        overlap = set(prev_map) & set(live_map)
        print(f"\n2027-2028 Grade 10 Art (history): {len(prev_map)} students")
        for sid, s in prev_map.items():
            print(f"  id={sid} {s.full_name} status={s.status} grade={s.grade_level} ay={s.academic_year_id} klass={s.klass_id}")
        print(f"\n2028-2029 Grade 10 Art (live): {len(live_map)} students")
        for sid, s in live_map.items():
            print(f"  id={sid} {s.full_name} status={s.status} grade={s.grade_level} ay={s.academic_year_id} klass={s.klass_id}")
        print(f"\nOVERLAP (same student id in both year folders): {len(overlap)}")
        for sid in overlap:
            s = live_map[sid]
            print(f"  {s.full_name} — should be in Grade 11 if promoted? status={s.status}")

    if g11 and active:
        g11_map = roster_ids(g11, active, archived=False)
        print(f"\n2028-2029 Grade 11 Art (live): {len(g11_map)} students")
        for sid, s in g11_map.items():
            print(f"  id={sid} {s.full_name} status={s.status} grade={s.grade_level}")

    # Check enrollments for overlap students
    if overlap:
        for sid in overlap:
            enr = Enrollment.query.filter_by(student_id=sid).all()
            print(f"\nEnrollments for student {sid}:")
            for e in enr:
                c = db.session.get(Class, e.class_id)
                print(f"  class_id={e.class_id} ({c.name if c else '?'})")
