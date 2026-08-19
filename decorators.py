from functools import wraps

from flask import flash, redirect, request, url_for
from flask_login import current_user

# Registry aliases only. Never include vpi/vpa/principal/admin here.
_REGISTRY_ALIASES = frozenset({'registry', 'registry officer'})
_PROTECTED_ROLES = frozenset({
    'vpi', 'vpa', 'principal', 'admin', 'dean', 'teacher',
    'business', 'student', 'parent', 'sponsor',
})
_ROLE_HOME_ENDPOINTS = {
    'vpi': 'vpi_dashboard',
    'vpa': 'vpa_dashboard',
    'principal': 'principal_dashboard',
    'registrar': 'registrar_dashboard',
    'teacher': 'teacher_dashboard',
    'dean': 'dean_dashboard',
    'student': 'student_dashboard',
    'sponsor': 'teacher_dashboard',
    'business': 'business_dashboard',
    'admin': 'dashboard',
    'parent': 'dashboard',
}


def _canonical_role_name(role):
    """Map stored role onto the routing role. Registry aliases must never swallow vpi."""
    role = (role or '').strip().lower()
    if role in _PROTECTED_ROLES:
        return role
    if role in _REGISTRY_ALIASES:
        return 'registrar'
    return role


def _home_endpoint_for_role_name(role):
    return _ROLE_HOME_ENDPOINTS.get(_canonical_role_name(role), 'dashboard')


def role_required(*roles):
    allowed_roles = {role.strip().lower() for role in roles}

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))

            user_role = _canonical_role_name(getattr(current_user, 'role', None))
            if user_role not in allowed_roles:
                home = _home_endpoint_for_role_name(user_role)
                flash('You do not have permission to access that page.', 'danger')
                if request.endpoint == home:
                    return redirect(url_for('index'))
                return redirect(url_for(home))
            return func(*args, **kwargs)

        return wrapper

    return decorator
