#!/usr/bin/env python3
"""
Admin diagnostic: academic year roster bleed vs legitimate promotion.

Run from project root:
    python scripts/diagnose_year_bleed.py
"""
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
    _students_for_display_year,
    _students_pending_year_registration,
    repair_stale_student_class_assignments,
)
from models import AcademicYear, Student, Class, Grade


def class_label(klass):
    if not klass:
        return "None"
    return f"Grade {klass.grade_level} {klass.name}"


def previous_academic_year(active):
    return (
        AcademicYear.query.filter(
            AcademicYear.id != active.id,
            AcademicYear.is_active.is_(False),
        )
        .order_by(AcademicYear.start_date.desc(), AcademicYear.id.desc())
        .first()
    )


def main():
    with app.app_context():
        active = get_active_academic_year()
        if not active:
            print("No active academic year configured.")
            return 1

        prev = previous_academic_year(active)
        print(f"Active year: {active.name} (id={active.id})")
        if prev:
            print(f"Previous year: {prev.name} (id={prev.id})")

        print("\n--- Year student counts ---")
        for year in AcademicYear.query.order_by(AcademicYear.start_date.desc()).all():
            strict = students_for_academic_year(year.id).count()
            enrolled = students_for_academic_year(year.id, registered_only=True).count()
            live = _students_for_display_year(year, history_mode=False).count()
            hist = _students_for_display_year(year, history_mode=True).count()
            pending = _students_pending_year_registration(year).count() if year.is_active else 0
            print(
                f"  {year.name} active={year.is_active}: "
                f"strict={strict}, enrolled={enrolled}, live={live}, history={hist}"
                + (f", pending_reg={pending}" if pending else "")
            )

        stale = Student.query.filter(
            Student.klass_id.isnot(None),
            Student.academic_year_id != active.id,
            ~Student.status.in_(["ALUMNI", "GRADUATED"]),
        ).count()
        print(f"\nStale klass seats (non-alumni, wrong year): {stale}")
        if stale:
            for s in Student.query.filter(
                Student.klass_id.isnot(None),
                Student.academic_year_id != active.id,
                ~Student.status.in_(["ALUMNI", "GRADUATED"]),
            ).all():
                y = db.session.get(AcademicYear, s.academic_year_id)
                k = db.session.get(Class, s.klass_id)
                print(
                    f"  STALE: {s.first_name} {s.last_name} "
                    f"year={y.name if y else None} class={class_label(k)} status={s.status}"
                )

        print("\n--- Active year class folders ---")
        portfolios = _principal_build_class_portfolios(active, viewing_archived=False)
        nonzero = [p for p in portfolios if p["student_count"] > 0]
        bleed_found = False

        for portfolio in sorted(
            nonzero,
            key=lambda p: (
                str(p["klass"].grade_level or ""),
                p["klass"].name or "",
            ),
        ):
            klass = portfolio["klass"]
            strict = students_for_academic_year(active.id, registered_only=True).filter_by(
                klass_id=klass.id,
            ).count()
            roster = _principal_students_for_class(klass, active, viewing_archived=False)
            mismatch = portfolio["student_count"] != strict or len(roster) != strict
            flag = " MISMATCH" if mismatch else ""
            print(
                f"\n{class_label(klass)}: enrolled={portfolio['student_count']} "
                f"strict={strict} at_risk={portfolio['at_risk_count']}{flag}"
            )
            if mismatch:
                bleed_found = True

            for student in roster:
                prev_klass = get_student_class_for_year(student, prev.id) if prev else None
                if prev_klass and prev_klass.id == klass.id:
                    verdict = "BLEED-same-class-last-year"
                    bleed_found = True
                elif prev_klass:
                    verdict = f"PROMOTED-from-{class_label(prev_klass)}"
                else:
                    prev_grades = (
                        Grade.query.filter_by(
                            student_id=student.id,
                            academic_year_id=prev.id,
                        ).count()
                        if prev else 0
                    )
                    verdict = (
                        "HAD-grades-prev-year"
                        if prev_grades
                        else "NEW-or-no-prev-footprint"
                    )
                print(f"  {student.first_name} {student.last_name} => {verdict}")

        if stale:
            print("\n--- Repair preview ---")
            print("Run repair_stale_student_class_assignments() to clear stale seats.")

        print("\n--- Optional repair ---")
        print("To repair stale seats: python -c \"from app import app, repair_stale_student_class_assignments; app.app_context().push(); print(repair_stale_student_class_assignments())\"")

        pending = _students_pending_year_registration(active).count()
        if pending:
            print(f"\nPending re-registration (active year, not in rosters): {pending}")
            for s in _students_pending_year_registration(active).limit(10).all():
                k = db.session.get(Class, s.klass_id) if s.klass_id else None
                print(f"  PENDING: {s.first_name} {s.last_name} class={class_label(k)}")

        if bleed_found or stale:
            print("\nRESULT: Issues detected — review rows marked BLEED or STALE.")
            return 1

        print("\nRESULT: No year bleed detected. Active folders show only registered enrolled students.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
