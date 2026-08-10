"""HTTP-level test of VPA dashboard archived class drill-down."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FLASK_ENV", "development")

from app import app, db, User, AcademicYear, get_active_academic_year, Class


def main():
    with app.app_context():
        vpa = User.query.filter_by(role="VPA").first()
        if not vpa:
            print("No VPA user found")
            return

        active = get_active_academic_year()
        archived = AcademicYear.query.filter(AcademicYear.id != active.id).order_by(AcademicYear.id).first()
        klass = Class.query.first()
        print(f"VPA user: {vpa.username}, archived year: {archived.name} (id={archived.id})")

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(vpa.id)
            sess["_fresh"] = True

        # Case 1: archived year + class_id in URL
        url = f"/vpa/dashboard?academic_year_id={archived.id}&class_id={klass.id}"
        resp = client.get(url)
        html = resp.get_data(as_text=True)
        print(f"\nCase 1: {url}")
        print(f"  status={resp.status_code}, len={len(html)}")
        print(f"  has 'No students match': {'No students match this filter.' in html}")
        print(f"  has archived banner: {'Historical academic view' in html}")
        print(f"  selected class in page: {klass.name in html}")

        # Case 2: class_id only (session seeded with archived year)
        with client.session_transaction() as sess:
            sess["_user_id"] = str(vpa.id)
            sess["_fresh"] = True
            sess["vpa_display_year_id"] = archived.id

        url2 = f"/vpa/dashboard?class_id={klass.id}"
        resp2 = client.get(url2)
        html2 = resp2.get_data(as_text=True)
        print(f"\nCase 2: {url2} (session has archived year)")
        print(f"  has 'No students match': {'No students match this filter.' in html}")
        print(f"  has archived banner: {'Historical academic view' in html}")

        # Case 3: class_id only WITHOUT session (simulates broken link)
        client2 = app.test_client()
        with client2.session_transaction() as sess:
            sess["_user_id"] = str(vpa.id)
            sess["_fresh"] = True

        url3 = f"/vpa/dashboard?class_id={klass.id}"
        resp3 = client2.get(url3)
        html3 = resp3.get_data(as_text=True)
        print(f"\nCase 3: {url3} (NO year in session/URL - broken)")
        print(f"  has 'No students match': {'No students match this filter.' in html}")
        print(f"  has archived banner: {'Historical academic view' in html}")

        # Case 4: legacy ?year= param + class_id
        url4 = f"/vpa/dashboard?year={archived.name}&class_id={klass.id}"
        resp4 = client2.get(url4)
        html4 = resp4.get_data(as_text=True)
        print(f"\nCase 4: {url4} (legacy year param)")
        print(f"  has 'No students match': {'No students match this filter.' in html}")
        print(f"  has archived banner: {'Historical academic view' in html}")

        # Find a class with students in archived year
        from app import _vpa_build_class_snapshots

        snaps = _vpa_build_class_snapshots(archived, viewing_archived=True)
        nonempty = [s for s in snaps if s["student_count"] > 0]
        if nonempty:
            k = nonempty[0]["klass"]
            url5 = f"/vpa/dashboard?academic_year_id={archived.id}&class_id={k.id}"
            resp5 = client.get(url5)
            html5 = resp5.get_data(as_text=True)
            print(f"\nCase 5: class with students {k.name} (id={k.id})")
            print(f"  snapshot count={nonempty[0]['student_count']}")
            print(f"  has 'No students match': {'No students match this filter.' in html5}")
            # print first student name if any
            for row in nonempty[0].get("_roster", []):
                pass


if __name__ == "__main__":
    main()
