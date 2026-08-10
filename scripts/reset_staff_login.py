"""Reset admin and/or principal login passwords (keeps roles unchanged)."""
import getpass
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from sqlalchemy import func

from app import app, db
from models import User

DEFAULT_TARGETS = [
    ("admin@school.com", "admin"),
    ("xhangocharm@gmail.com", "principal"),
]


def resolve_password():
    env_password = (os.environ.get("STAFF_PASSWORD") or "").strip()
    if env_password:
        return env_password
    password = getpass.getpass("New password for staff account(s): ").strip()
    confirm = getpass.getpass("Confirm password: ").strip()
    if not password or password != confirm:
        print("Passwords missing or do not match.")
        sys.exit(1)
    return password


def main():
    password = resolve_password()
    if len(password) < 6:
        print("Password must be at least 6 characters.")
        sys.exit(1)

    only_role = (os.environ.get("RESET_ROLE") or "").strip().lower()

    with app.app_context():
        targets = DEFAULT_TARGETS
        if only_role:
            targets = [t for t in targets if t[1] == only_role]
        if not targets:
            print("No matching staff accounts to reset.")
            sys.exit(1)

        for email, role in targets:
            user = User.query.filter(func.lower(User.email) == email.lower()).first()
            if not user:
                print(f"SKIP: no user for {email}")
                continue
            user.set_password(password)
            user.status = "Active"
            user.is_active = True
            user.deactivated_at = None
            user.deactivation_reason = None
            if role == "admin" and not user.username:
                user.username = "admin"
            print(f"RESET: {user.full_name} ({user.role}) — {user.email}")

        db.session.commit()
        print("Done. Sign in with the email shown above and your new password.")


if __name__ == "__main__":
    main()
