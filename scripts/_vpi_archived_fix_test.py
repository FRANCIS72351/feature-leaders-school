"""Verify VPI archived class finance cards and drill-down roster."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FLASK_ENV", "development")

from app import (
    app,
    User,
    AcademicYear,
    _vpi_class_collection_snapshots,
    _principal_students_for_class,
)


def main():
    with app.app_context():
        y = AcademicYear.query.filter_by(name="2026-2027").first()
        assert y, "2026-2027 year missing"
        snaps = _vpi_class_collection_snapshots(y, viewing_archived=True)
        nonempty = [s for s in snaps if s["student_count"] > 0]
        assert nonempty, "VPI class snapshots should not all be empty for 2026-2027"
        print(f"VPI snapshots nonempty: {len(nonempty)}/{len(snaps)}")

        vpi = User.query.filter(User.role.ilike("vpi")).first()
        assert vpi, "VPI user missing"
        klass = nonempty[0]["klass"]
        roster = _principal_students_for_class(klass, y, viewing_archived=True)
        assert roster, "class roster should not be empty"

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(vpi.id)
            sess["_fresh"] = True

        html = client.get(f"/vpi/dashboard?academic_year_id={y.id}").get_data(as_text=True)
        assert klass.name in html, "VPI dashboard missing class name"
        assert f"{nonempty[0]['student_count']} students" in html, "VPI dashboard missing student count"

        html2 = client.get(
            f"/business/class/{klass.id}/students?academic_year_id={y.id}"
        ).get_data(as_text=True)
        assert roster[0].full_name in html2, "VPI drill-down roster missing student"
        print("PASS: VPI archived year cards and drill-down roster")


if __name__ == "__main__":
    main()
