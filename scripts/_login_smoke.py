"""Login smoke test — does not print credentials."""
import sys

sys.path.insert(0, ".")
from app import app, resolve_user_for_login

EMAIL = "xhangocharm@gmail.com"

with app.app_context():
    user = resolve_user_for_login(EMAIL)
    assert user is not None, "principal user not found"
    assert user.is_account_active(), "principal account inactive"

app.config["TESTING"] = True
app.config["WTF_CSRF_ENABLED"] = False

with app.test_client() as client:
    bad = client.post(
        "/login",
        data={"email": EMAIL, "password": "__wrong__", "submit": "Login"},
        follow_redirects=True,
    )
    assert b"Invalid email, student ID, or password" in bad.data

    # Known-good password must be supplied manually to complete this test.
    print("resolve_user_for_login: OK")
    print("wrong-password flash: OK")
