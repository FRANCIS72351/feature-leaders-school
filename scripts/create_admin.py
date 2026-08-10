import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from werkzeug.security import generate_password_hash
from app import app, db
from models import User

with app.app_context():
    # Check if admin already exists
    existing = User.query.filter_by(email="admin@example.com").first()
    if existing:
        print("⚠️ Admin user already exists:", existing.email)
    else:
        hashed_pw = generate_password_hash("admin123")
        user = User(
            email="admin@example.com",
            password_hash=hashed_pw,
            role="admin",
            full_name="Admin"
        )
        db.session.add(user)
        db.session.commit()
        print("✅ Admin user created: admin@example.com / admin123")
