#!/usr/bin/env python3
"""Quick smoke test: academic year isolation for dashboard queries."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, db, students_for_academic_year
from models import AcademicYear, Student, Grade, StudentPayment, Assessment, User, Class, Enrollment


def _year_ids():
    return [y.id for y in AcademicYear.query.order_by(AcademicYear.name.desc()).all()]


def _assert_no_cross_year_bleed(year_a_id, year_b_id):
    a_students = {s.id for s in students_for_academic_year(year_a_id).all()}
    b_students = {s.id for s in students_for_academic_year(year_b_id).all()}
    overlap = a_students & b_students
    assert not overlap, f"Student overlap between years {year_a_id} and {year_b_id}: {overlap}"

    for model, col in (
        (Grade, Grade.academic_year_id),
        (StudentPayment, StudentPayment.academic_year_id),
        (Assessment, Assessment.academic_year_id),
    ):
        a_ids = {
            r.id for r in model.query.filter(col == year_a_id).with_entities(model.id).all()
        }
        b_ids = {
            r.id for r in model.query.filter(col == year_b_id).with_entities(model.id).all()
        }
        assert not (a_ids & b_ids), f"{model.__name__} overlap between years"


def main():
    failures = []
    with app.app_context():
        years = _year_ids()
        print(f"Found {len(years)} academic year(s): {years}")
        if len(years) < 2:
            print("SKIP: need at least 2 years to test cross-year bleed")
            return 0

        for i, yid in enumerate(years):
            null_bleed = Student.query.filter(
                Student.academic_year_id.is_(None),
                Student.klass_id.isnot(None),
            ).count()
            if null_bleed:
                print(f"WARN: {null_bleed} active-class student(s) with NULL academic_year_id")

            scoped = students_for_academic_year(yid).count()
            raw = Student.query.filter(Student.academic_year_id == yid).count()
            if scoped != raw:
                failures.append(f"students_for_academic_year mismatch for year {yid}")

        for a, b in zip(years, years[1:]):
            try:
                _assert_no_cross_year_bleed(a, b)
                print(f"OK: no bleed between year {a} and {b}")
            except AssertionError as exc:
                failures.append(str(exc))

        from app import (
            resolve_dashboard_academic_year,
            all_academic_years,
            _build_academic_year_links,
            _principal_build_class_portfolios,
            _principal_students_for_class,
            _students_for_display_year,
            _students_pending_year_registration,
            get_active_academic_year,
            REGISTRAR_YEAR_SESSION_KEY,
            ADMIN_YEAR_SESSION_KEY,
        )

        listed = all_academic_years()
        if len(listed) != len(years):
            failures.append("all_academic_years() count mismatch")

        links = _build_academic_year_links(listed)
        if not isinstance(links, dict):
            failures.append("year_links not built as dict")
        else:
            print(f"OK: year_links built for {len(links)} year(s)")

        with app.test_request_context("/dashboard?academic_year_id=%s" % years[0]):
            from flask import session
            session[REGISTRAR_YEAR_SESSION_KEY] = years[-1]
            display, active, all_y, archived = resolve_dashboard_academic_year(
                session_key=REGISTRAR_YEAR_SESSION_KEY
            )
            if display.id != years[0]:
                failures.append("resolve_dashboard_academic_year ignored query param")
            else:
                print("OK: query param overrides session for year resolution")

        with app.test_request_context("/dashboard"):
            from flask import session
            session.clear()
            session[ADMIN_YEAR_SESSION_KEY] = years[0]
            display, active, all_y, archived = resolve_dashboard_academic_year(
                session_key=ADMIN_YEAR_SESSION_KEY
            )
            if display.id != years[0]:
                failures.append("resolve_dashboard_academic_year ignored session key")
            else:
                print("OK: session key persists selected year")

        active = get_active_academic_year()
        if active:
            enrolled = students_for_academic_year(
                active.id, registered_only=True,
            ).count()
            live = _students_for_display_year(active, history_mode=False).count()
            hist = _students_for_display_year(active, history_mode=True).count()
            if live != enrolled:
                failures.append(
                    f"active year live ({live}) != enrolled ({enrolled})"
                )
            else:
                print(f"OK: active year live matches enrolled count ({live})")
            if hist != enrolled:
                failures.append(
                    f"active year history_mode ({hist}) != enrolled ({enrolled}) — "
                    "history union must not broaden active-year rosters"
                )
            else:
                print(
                    f"OK: active year history_mode does not broaden rosters ({hist})"
                )

            pending_ids = {
                s.id for s in _students_pending_year_registration(active).all()
            }
            live_ids = {
                s.id
                for s in _students_for_display_year(active, history_mode=False).all()
            }
            leaked_pending = pending_ids & live_ids
            if leaked_pending:
                failures.append(
                    f"pending re-registration students in active live roster: "
                    f"{leaked_pending}"
                )
            elif pending_ids:
                print(
                    f"OK: {len(pending_ids)} pending promoted student(s) "
                    "excluded from active live roster"
                )

            portfolios = _principal_build_class_portfolios(active, viewing_archived=False)
            for portfolio in portfolios:
                klass = portfolio['klass']
                strict = students_for_academic_year(
                    active.id, registered_only=True,
                ).filter_by(klass_id=klass.id).count()
                if portfolio['student_count'] != strict:
                    failures.append(
                        f"principal portfolio bleed for {klass.name}: "
                        f"portfolio={portfolio['student_count']} strict={strict}"
                    )
                roster = _principal_students_for_class(
                    klass, active, viewing_archived=False,
                )
                if len(roster) != portfolio['student_count']:
                    failures.append(
                        f"principal folder drill-down mismatch for {klass.name}: "
                        f"portfolio={portfolio['student_count']} roster={len(roster)}"
                    )
                for student in roster:
                    if student.academic_year_id != active.id:
                        failures.append(
                            f"active folder bleed: {student.full_name} in {klass.name} "
                            f"has academic_year_id={student.academic_year_id}"
                        )
                    if not student.is_registered:
                        failures.append(
                            f"active folder unregistered bleed: {student.full_name} "
                            f"in {klass.name} (is_registered=False)"
                        )
                    if (student.status or '').upper() in ('ALUMNI', 'GRADUATED'):
                        failures.append(
                            f"active folder alumni bleed: {student.full_name} "
                            f"status={student.status} in {klass.name}"
                        )
            print("OK: principal class portfolios match strict enrollment")

            pending = _students_pending_year_registration(active).count()
            pending_in_roster = sum(
                1
                for portfolio in portfolios
                for student in _principal_students_for_class(
                    portfolio['klass'], active, viewing_archived=False,
                )
                if not student.is_registered
            )
            if pending_in_roster:
                failures.append(
                    f"pending re-registration students leaked into class folders: {pending_in_roster}"
                )
            elif pending:
                print(f"OK: {pending} pending re-registration student(s) excluded from active rosters")

            principal = User.query.filter(
                db.func.lower(User.role) == 'principal',
            ).first()
            if principal:
                g10_art = Class.query.filter_by(name='Grade 10 Art').first()
                if g10_art:
                    prev_year = AcademicYear.query.filter(
                        AcademicYear.id != active.id,
                    ).order_by(AcademicYear.start_date.desc()).first()
                    with app.test_client() as client:
                        with client.session_transaction() as sess:
                            sess['_user_id'] = str(principal.id)
                            sess['_fresh'] = True
                        resp = client.get(
                            '/principal/dashboard'
                            f'?academic_year_id={active.id}&class_id={g10_art.id}',
                        )
                        if resp.status_code != 200:
                            failures.append(
                                f"principal folder HTTP {resp.status_code} for active year"
                            )
                        else:
                            body = resp.get_data(as_text=True)
                            live_roster = _principal_students_for_class(
                                g10_art, active, viewing_archived=False,
                            )
                            for student in live_roster:
                                if student.full_name not in body:
                                    failures.append(
                                        f"principal folder missing live student "
                                        f"{student.full_name}"
                                    )
                            if prev_year:
                                archived_roster = _principal_students_for_class(
                                    g10_art, prev_year, viewing_archived=True,
                                )
                                live_ids = {s.id for s in live_roster}
                                leaked = [
                                    s.full_name for s in archived_roster
                                    if s.id in live_ids
                                ]
                                if leaked:
                                    failures.append(
                                        "principal active folder leaked archived-only "
                                        f"students: {leaked}"
                                    )
                                for archived_student in archived_roster:
                                    if (
                                        archived_student.id not in live_ids
                                        and archived_student.full_name in body
                                    ):
                                        failures.append(
                                            "principal active folder bled archived student "
                                            f"{archived_student.full_name}"
                                        )
                            print("OK: principal folder HTTP active-year isolation")

            archived = next(
                (y for y in AcademicYear.query.all() if y.id != active.id),
                None,
            )
            if archived:
                archived_hist = _students_for_display_year(
                    archived, history_mode=True,
                ).count()
                archived_live = _students_for_display_year(
                    archived, history_mode=False,
                ).count()
                if archived_hist < archived_live:
                    failures.append("archived history roster smaller than live tag count")
                else:
                    print(
                        f"OK: archived year {archived.id} history "
                        f"({archived_hist}) >= live ({archived_live})"
                    )

    if failures:
        print("\nFAILED:")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print("\nAll year isolation smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
