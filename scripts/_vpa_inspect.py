"""Inspect VPA class_id-only response."""
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FLASK_ENV", "development")

from app import app, User, Class, get_active_academic_year, _students_for_display_year, _principal_students_for_class


def main():
    with app.app_context():
        vpa = User.query.get(16)
        active = get_active_academic_year()
        klass = Class.query.get(5)

        for label, url in [
            ("archived+class", "/vpa/dashboard?academic_year_id=1&class_id=5"),
            ("class only", "/vpa/dashboard?class_id=5"),
            ("legacy year+class", "/vpa/dashboard?year=2025-2026&class_id=5"),
        ]:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess["_user_id"] = str(vpa.id)
                sess["_fresh"] = True
                sess.pop("vpa_display_year_id", None)
            html = client.get(url).get_data(as_text=True)
            names = re.findall(r"registry-student-name\">([^<]+)", html)
            empty = "No students match this filter." in html
            archived = "Historical academic view" in html
            print(f"{label}: empty={empty} archived={archived} names={names}")

        print("\nDirect logic active year class 5:")
        roster = _principal_students_for_class(klass, active, viewing_archived=False)
        print(f"  active roster: {len(roster)} -> {[s.full_name for s in roster]}")
        live = _students_for_display_year(active, history_mode=False).filter_by(klass_id=5).all()
        print(f"  live filter: {len(live)}")


if __name__ == "__main__":
    main()
