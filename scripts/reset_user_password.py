"""Reset a portal user's password by email (keeps role unchanged)."""
import getpass
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

try:
    from sqlalchemy import func

    from app import app, db
    from models import User
except ModuleNotFoundError as exc:
    print(f"Initialization error: {exc}")
    sys.exit(1)


def resolve_password():
    env_password = (os.environ.get("USER_PASSWORD") or "").strip()
    if env_password:
        return env_password
    password = getpass.getpass("Enter new password: ").strip()
    confirm = getpass.getpass("Confirm new password: ").strip()
    if not password:
        print("Password is required.")
        sys.exit(1)
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)
    return password


def main():
    email = (os.environ.get("USER_EMAIL") or "").strip()
    if not email:
        email = input("User email: ").strip()
    if not email:
        print("USER_EMAIL is required.")
        sys.exit(1)

    new_password = resolve_password()
    if len(new_password) < 6:
        print("Password must be at least 6 characters.")
        sys.exit(1)

    with app.app_context():
        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if not user:
            print(f"No user found for email: {email}")
            sys.exit(1)

        user.set_password(new_password)
        user.status = "Active"
        user.is_active = True
        user.deactivated_at = None
        user.deactivation_reason = None
        db.session.commit()
        print(f"Password reset for {user.full_name} ({user.role}).")
        print(f"Email: {user.email}")


if __name__ == "__main__":
    main()
