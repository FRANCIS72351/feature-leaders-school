#!/usr/bin/env python3
"""Diagnose academic_year_id vs klass_id mismatches in live DB."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, db, get_active_academic_year, _principal_students_for_class, _principal_build_class_portfolios
from models import AcademicYear, Student, Class


def main():
    with app.app_context():
        active = get_active_academic_year()
        if not active:
            print("NO ACTIVE YEAR")
            return 1
        print(f"ACTIVE YEAR: {active.name} (id={active.id})")

        # DB mismatches
        mismatches = (
            db.session.query(Student, Class)
            .join(Class, Student.klass_id == Class.id)
            .filter(Class.academic_year_id == active.id)
            .filter(Student.academic_year_id != active.id)
            .all()
        )
        print(f"\n=== DB MISMATCHES (klass in active-year class, student.ay != active): {len(mismatches)} ===")
        for student, klass in mismatches:
            ay = db.session.get(AcademicYear, student.academic_year_id)
            print(
                f"  {student.first_name} {student.last_name} (id={student.id}) "
                f"student_ay={ay.name if ay else '?'} klass={klass.name} status={student.status}"
            )

        reverse = (
            db.session.query(Student, Class)
            .join(Class, Student.klass_id == Class.id)
            .filter(Student.academic_year_id == active.id)
            .filter(Class.academic_year_id != active.id)
            .all()
        )
        print(f"\n=== REVERSE (student in active year, klass from other year): {len(reverse)} ===")
        for student, klass in reverse:
            print(f"  {student.full_name} klass={klass.name} class_ay={klass.academic_year_id}")

        # App-level portfolio vs strict
        portfolios = _principal_build_class_portfolios(active, viewing_archived=False)
        art_classes = [p for p in portfolios if p['student_count'] > 0 and 'art' in (p['klass'].name or '').lower()]
        print(f"\n=== PORTFOLIOS WITH STUDENTS (Art highlighted) ===")
        for p in portfolios:
            if p['student_count'] == 0:
                continue
            klass = p['klass']
            strict = Student.query.filter_by(academic_year_id=active.id, klass_id=klass.id).count()
            roster = _principal_students_for_class(klass, active, viewing_archived=False)
            flag = " ***" if p['student_count'] != strict or any(s.academic_year_id != active.id for s in roster) else ""
            if 'art' in (klass.name or '').lower() or flag:
                print(
                    f"  {klass.name} (class_id={klass.id}, class_ay={klass.academic_year_id}): "
                    f"portfolio={p['student_count']} strict={strict} roster={len(roster)}{flag}"
                )
                for s in roster:
                    if s.academic_year_id != active.id:
                        ay = db.session.get(AcademicYear, s.academic_year_id)
                        print(f"    BLEED: {s.full_name} ay={ay.name if ay else '?'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
