import getpass
import os
import sys

# Ensure the script can locate app.py in the same directory
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from app import app, db, User
except ModuleNotFoundError as exc:
    print("=" * 70)
    print(f"Initialization Error: {exc}")
    print("Make sure this script is beside app.py inside the SCHOOL_MANAGEMENT folder.")
    print("=" * 70)
    sys.exit(1)

# Default credentials
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "xhangocharm@gmail.com")
ADMIN_NAME = os.environ.get("ADMIN_NAME", "Francis Brownell")


def resolve_admin_password():
    """Retrieves password from environment or secure terminal prompt."""
    env_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if env_password:
        return env_password
    password = getpass.getpass("Enter master administrator password: ").strip()
    if not password:
        print("Password is required.")
        sys.exit(1)
    return password


print("=" * 70)
print("INITIALIZING MASTER ADMINISTRATOR SYSTEM RECOVERY")
print("=" * 70)

admin_password = resolve_admin_password()

with app.app_context():
    try:
        # Step 1: Find the account matching the target admin email
        email_user = User.query.filter_by(email=ADMIN_EMAIL).first()
        
        # Step 2: Find who currently holds the 'admin' username
        username_user = User.query.filter_by(username="admin").first()

        if email_user:
            # If a DIFFERENT account is hogging the 'admin' username, rename them first to free it up
            if username_user and username_user.id != email_user.id:
                print(f"Notice: Moving 'admin' username away from User ID {username_user.id} to avoid clash.")
                username_user.username = f"old_admin_{username_user.id}"
                db.session.flush()  # Tells the database to register the username change immediately

            # Elevate the email owner to the master admin slot
            email_user.username = "admin"
            email_user.full_name = ADMIN_NAME
            email_user.role = "admin"
            email_user.set_password(admin_password)
            print("SUCCESS: Target email account located and fully elevated to master admin.")
            
        elif username_user:
            # Fallback: No one has the email, but someone has the username 'admin'. Update their email.
            username_user.email = ADMIN_EMAIL
            username_user.full_name = ADMIN_NAME
            username_user.role = "admin"
            username_user.set_password(admin_password)
            print("SUCCESS: Username 'admin' located; updated email and reset password.")
            
        else:
            # Clean slate: Neither exists, build fresh
            new_admin = User(
                email=ADMIN_EMAIL,
                full_name=ADMIN_NAME,
                role="admin",
                username="admin",
            )
            new_admin.set_password(admin_password)
            db.session.add(new_admin)
            print("SUCCESS: Fresh master administrator account created.")

        db.session.commit()
        
        print("-" * 70)
        print(f"Final Login Username : admin")
        print(f"Final Login Email    : {ADMIN_EMAIL}")
        print("=" * 70)
            
    except Exception as exc:
        db.session.rollback()
        print(f"CRITICAL ERROR during admin recovery: {exc}")
        sys.exit(1)