from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(*roles):
    allowed_roles = {role.lower() for role in roles}

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_role = (getattr(current_user, "role", "") or "").lower()
            if not current_user.is_authenticated or user_role not in allowed_roles:
                abort(403)
            return func(*args, **kwargs)

        return wrapper

    return decorator
