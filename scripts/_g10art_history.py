#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, db, get_student_class_for_year, _class_id_from_year_grades
from models import AcademicYear, Class, Student, Grade

with app.app_context():
    prev = AcademicYear.query.filter_by(name="2027-2028").first()
    active = AcademicYear.query.filter_by(name="2028-2029").first()
    g10 = Class.query.filter_by(name="Grade 10 Art").first()

    for label, year in [("2027-2028", prev), ("2028-2029", active)]:
        print(f"\n=== {label} (id={year.id}) ===")
        for sid in [19, 31, 22, 29]:
            s = db.session.get(Student, sid)
            if not s:
                continue
            resolved = get_student_class_for_year(s, year.id)
            grades = Grade.query.filter_by(student_id=sid, academic_year_id=year.id).all()
            grade_classes = set()
            for g in grades:
                if g.class_id:
                    c = db.session.get(Class, g.class_id)
                    grade_classes.add(c.name if c else str(g.class_id))
            print(
                f"  {s.full_name}: live_klass={s.klass_id} grade={s.grade_level} ay={s.academic_year_id} "
                f"resolved={resolved.name if resolved else None} grade_records={grade_classes or 'none'}"
            )

    print("\n=== Who was in Grade 10 Art in 2027-2028 per grades? ===")
    if prev and g10:
        rows = Grade.query.filter_by(academic_year_id=prev.id, class_id=g10.id).all()
        sids = {r.student_id for r in rows}
        for sid in sids:
            s = db.session.get(Student, sid)
            print(f"  {s.full_name if s else sid}")
