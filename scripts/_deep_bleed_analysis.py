#!/usr/bin/env python3
"""One-off deep bleed vs promotion analysis."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (
    app,
    db,
    get_active_academic_year,
    get_student_class_for_year,
    _principal_build_class_portfolios,
    _principal_students_for_class,
    students_for_academic_year,
    _class_id_from_year_grades,
    _class_id_from_year_enrollment,
)
from models import AcademicYear, Student, Class, Grade, Enrollment


def class_label(klass):
    if not klass:
        return "None"
    return f"Grade {klass.grade_level} {klass.name}"


def main():
    with app.app_context():
        active = get_active_academic_year()
        prev = (
            AcademicYear.query.filter(
                AcademicYear.id != active.id,
                AcademicYear.is_active.is_(False),
            )
            .order_by(AcademicYear.start_date.desc(), AcademicYear.id.desc())
            .first()
        )
        print(f"ACTIVE: id={active.id} name={active.name} is_active={active.is_active}")
        if prev:
            print(f"PREV:   id={prev.id} name={prev.name}")

        print("\n=== ALL STUDENTS ===")
        for s in Student.query.order_by(Student.last_name, Student.first_name):
            y = db.session.get(AcademicYear, s.academic_year_id)
            k = db.session.get(Class, s.klass_id) if s.klass_id else None
            print(
                f"  {s.first_name} {s.last_name} id={s.id} "
                f"ay={y.name if y else None}({s.academic_year_id}) "
                f"klass={class_label(k)} grade={s.grade_level} status={s.status}"
            )

        print("\n=== SCREENSHOT CLASSES (active year roster) ===")
        for klass in Class.query.order_by(Class.grade_level, Class.name).all():
            if klass.grade_level not in (5, 11, 12) and "General" not in (klass.name or ""):
                continue
            roster = _principal_students_for_class(klass, active, viewing_archived=False)
            print(f"\n{class_label(klass)} (class_id={klass.id}): {len(roster)} enrolled")
            for s in roster:
                prev_klass = get_student_class_for_year(s, prev.id) if prev else None
                prev_grades = Grade.query.filter_by(
                    student_id=s.id, academic_year_id=prev.id
                ).count() if prev else 0
                curr_grades = Grade.query.filter_by(
                    student_id=s.id, academic_year_id=active.id
                ).count()
                enroll_prev = (
                    Enrollment.query.filter_by(student_id=s.id).all()
                    if prev else []
                )
                if prev_klass and prev_klass.id == klass.id:
                    verdict = "BLEED-same-class-last-year"
                elif prev_klass:
                    verdict = f"PROMOTED-from-{class_label(prev_klass)}"
                elif prev_grades:
                    verdict = "HAD-GRADES-prev-year-no-class-resolved"
                else:
                    verdict = "NEW-or-no-prev-footprint"
                print(
                    f"  {s.first_name} {s.last_name} status={s.status} "
                    f"prev_class={class_label(prev_klass)} prev_grades={prev_grades} "
                    f"curr_grades={curr_grades} => {verdict}"
                )

        print("\n=== STALE: klass_id set but academic_year_id != active ===")
        stale = Student.query.filter(
            Student.klass_id.isnot(None),
            Student.academic_year_id != active.id,
            ~Student.status.in_(["ALUMNI", "GRADUATED"]),
        ).all()
        print(f"count={len(stale)}")
        for s in stale:
            y = db.session.get(AcademicYear, s.academic_year_id)
            k = db.session.get(Class, s.klass_id)
            print(f"  {s.first_name} {s.last_name} year={y.name if y else None} class={class_label(k)} status={s.status}")

        print("\n=== PORTFOLIO vs STRICT ===")
        for p in _principal_build_class_portfolios(active, viewing_archived=False):
            if p["student_count"] == 0:
                continue
            k = p["klass"]
            strict = students_for_academic_year(active.id).filter_by(klass_id=k.id).count()
            print(f"  {class_label(k)}: portfolio={p['student_count']} strict={strict} at_risk={p['at_risk_count']}")


if __name__ == "__main__":
    main()
