"""Restore Charm Brownell's account to principal if it was stored as registrar.

Does not convert other registrar accounts. Safe to run more than once.

Usage:
  python scripts/repair_principal_role.py
"""
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from app import app, repair_misassigned_principal_role
from models import User, db
from sqlalchemy import func


def main():
    with app.app_context():
        print("Accounts matching Charm Brownell / known principal email:")
        users = User.query.filter(
            db.or_(
                func.lower(User.full_name).like("%charm%brownell%"),
                func.lower(User.email) == "xhangocharm@gmail.com",
            )
        ).all()
        if not users:
            print("  (none found)")
        for user in users:
            print(f"  id={user.id} role={user.role!r} email={user.email} name={user.full_name}")

        repaired = repair_misassigned_principal_role()
        if repaired:
            print(f"Updated {repaired} account(s) to principal.")
        else:
            print("No role change needed.")

        print("After repair:")
        users = User.query.filter(
            db.or_(
                func.lower(User.full_name).like("%charm%brownell%"),
                func.lower(User.email) == "xhangocharm@gmail.com",
            )
        ).all()
        for user in users:
            print(f"  id={user.id} role={user.role!r} email={user.email} name={user.full_name}")


if __name__ == "__main__":
    main()
