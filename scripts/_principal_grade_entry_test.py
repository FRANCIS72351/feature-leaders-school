"""Smoke test for principal grade entry navigation."""
import re
import sys

sys.path.insert(0, ".")
import app
from app import User, db, AcademicYear

app.app.config["TESTING"] = True
app.app.config["WTF_CSRF_ENABLED"] = False


def login_principal(client):
    with app.app.app_context():
        user = User.query.filter(db.func.lower(User.role) == "principal").first()
        assert user, "no principal user"
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
        return user


def extract_grade_entry_link(html):
    idx = html.find("Principal Grade Entry")
    if idx < 0:
        return None, None
    start = html.rfind('<a href="', 0, idx)
    if start < 0:
        return None, None
    end = html.find("</a>", idx)
    block = html[start:end + 4] if end >= 0 else html[start:start + 500]
    m = re.search(r'href="([^"]+)"', block)
    return block, m.group(1) if m else None


with app.app.test_client() as client:
    login_principal(client)
    with app.app.app_context():
        active = AcademicYear.query.filter_by(is_active=True).first()
        archived = AcademicYear.query.filter(AcademicYear.is_active.is_(False)).first()
        print("active:", active.id if active else None, getattr(active, "name", None))
        print("archived:", archived.id if archived else None, getattr(archived, "name", None))

    r = client.get("/principal/dashboard")
    block, href = extract_grade_entry_link(r.data.decode("utf-8", errors="replace"))
    print("default dashboard href:", href)
    print("default has pe-none:", "pe-none" in (block or ""))

    if archived:
        r2 = client.get(f"/principal/dashboard?academic_year_id={archived.id}")
        block2, href2 = extract_grade_entry_link(r2.data.decode("utf-8", errors="replace"))
        print("archived dashboard href:", href2)
        print("archived has pe-none:", "pe-none" in (block2 or ""))

    r3 = client.get("/principal/grade-entry")
    print("grade-entry status:", r3.status_code)
    print("grade-entry page ok:", b"Executive Backup Workflow" in r3.data)
