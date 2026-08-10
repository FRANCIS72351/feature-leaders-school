"""Debug VPA archived class roster against keeptrack_full.db."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("FLASK_ENV", "development")

from app import (
    app,
    db,
    Class,
    AcademicYear,
    Student,
    get_active_academic_year,
    _principal_students_for_class,
    _vpa_build_class_snapshots,
    _students_for_display_year,
    get_student_class_for_year,
)


def main():
    with app.app_context():
        active = get_active_academic_year()
        years = AcademicYear.query.order_by(AcademicYear.id.desc()).all()
        archived = [y for y in years if active and y.id != active.id]
        print(f"Active year: {active.name if active else None} (id={active.id if active else None})")
        print(f"Archived years: {[(y.id, y.name) for y in archived[:3]]}")

        if not archived:
            print("No archived years found.")
            return

        for display_year in archived:
            if display_year.id == 4:  # skip empty test year
                continue
            _test_year(display_year, active)


def _test_year(display_year, active):
        viewing_archived = True
        print(f"\nTesting archived year: {display_year.name} (id={display_year.id})")

        year_students = _students_for_display_year(display_year, history_mode=True).all()
        print(f"Total students in year (history_mode): {len(year_students)}")

        snapshots = _vpa_build_class_snapshots(display_year, viewing_archived=viewing_archived)
        nonempty = [s for s in snapshots if s["student_count"] > 0]
        print(f"Class snapshots with students: {len(nonempty)} / {len(snapshots)}")

        if not nonempty:
            sample = year_students[:5]
            for st in sample:
                resolved = get_student_class_for_year(st, display_year.id)
                print(
                    f"  student {st.id} {st.full_name}: klass_id={st.klass_id}, "
                    f"resolved={resolved.name if resolved else None}"
                )
            return

        snap = nonempty[0]
        klass = snap["klass"]
        print(f"\nFirst class with students: {klass.name} (id={klass.id}), count={snap['student_count']}")

        roster = _principal_students_for_class(klass, display_year, viewing_archived=viewing_archived)
        print(f"_principal_students_for_class returned: {len(roster)} students")

        live = (
            _students_for_display_year(display_year, history_mode=False)
            .filter_by(klass_id=klass.id)
            .all()
        )
        print(f"Live klass_id filter (history_mode=False): {len(live)} students")

        wrong = Student.query.filter_by(klass_id=klass.id).count()
        print(f"Raw Student.klass_id={klass.id} count (any year): {wrong}")


if __name__ == "__main__":
    main()
