"""Centralized staff account lifecycle helpers (deactivation, role transfer, class teacher release)."""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timezone, timedelta

from sqlalchemy import func
from werkzeug.security import generate_password_hash

from models import AcademicYear, Class, ClassSubjectTeacher, SecurityLog, StudentPayment, Teacher, User, db

INACTIVE_STATUSES = frozenset({'inactive', 'terminated', 'disabled', 'suspended'})
ALUMNI_STATUSES = frozenset({'ALUMNI', 'GRADUATED'})
ACTIVE_ENROLLMENT_STATUSES = frozenset({'ACTIVE', 'REPEAT', 'FAILED', 'SUSPENDED'})


def user_account_is_active(user) -> bool:
    """Return True when the user may authenticate and use the portal."""
    if user is None:
        return False
    if hasattr(user, 'is_active') and user.is_active is False:
        return False
    status = (getattr(user, 'status', None) or 'Active').strip().lower()
    return status not in INACTIVE_STATUSES


def revoke_user_credentials(user) -> None:
    """Replace stored credentials with a random hash so the old password cannot be reused."""
    random_secret = secrets.token_urlsafe(48)
    user.password_hash = generate_password_hash(random_secret)


def _log_security_event(event: str, actor_id=None) -> None:
    try:
        from flask import request

        ip = request.headers.get('X-Forwarded-For', request.remote_addr) if request else None
    except RuntimeError:
        ip = None
    db.session.add(SecurityLog(ip_address=ip, event=event))


def release_teacher_assignments(teacher_profile, *, replacement_teacher_id=None) -> dict:
    """
    Clear homeroom and subject allocations for a teacher.
    Optionally assign homeroom classes to a replacement teacher.
    """
    summary = {'homeroom_cleared': 0, 'allocations_removed': 0, 'sponsor_cleared': 0}

    homeroom_classes = Class.query.filter_by(teacher_id=teacher_profile.id).all()
    for klass in homeroom_classes:
        if replacement_teacher_id:
            klass.teacher_id = replacement_teacher_id
        else:
            klass.teacher_id = None
            summary['homeroom_cleared'] += 1

    if teacher_profile.user_id:
        sponsor_classes = Class.query.filter_by(sponsor_id=teacher_profile.user_id).all()
        for klass in sponsor_classes:
            klass.sponsor_id = None
        summary['sponsor_cleared'] = len(sponsor_classes)

    removed = ClassSubjectTeacher.query.filter_by(teacher_id=teacher_profile.id).delete(
        synchronize_session=False
    )
    summary['allocations_removed'] = removed or 0

    teacher_profile.status = 'INACTIVE'
    return summary


def deactivate_user_account(user, reason=None, actor_id=None, *, release_teacher=True) -> dict:
    """
    Deactivate a portal account: lock credentials, mark inactive, release teacher duties.
    Returns a summary dict for flash/UI messaging.
    """
    if user is None:
        raise ValueError('User is required.')

    summary = {'teacher_released': False, 'teacher_summary': {}}

    user.status = 'Inactive'
    user.is_active = False
    user.deactivated_at = datetime.now(timezone.utc)
    user.deactivation_reason = (reason or '').strip() or None
    revoke_user_credentials(user)

    teacher_profile = Teacher.query.filter_by(user_id=user.id).first()
    if teacher_profile and release_teacher:
        summary['teacher_summary'] = release_teacher_assignments(teacher_profile)
        summary['teacher_released'] = True

    actor_label = f' by user #{actor_id}' if actor_id else ''
    _log_security_event(
        f"ACCOUNT_DEACTIVATED: User ID {user.id} ({user.full_name}){actor_label}. "
        f"Reason: {user.deactivation_reason or 'Not specified'}"
    )
    return summary


def reactivate_user_account(user, actor_id=None, *, new_password=None) -> None:
    """Restore portal access for a previously deactivated account."""
    user.status = 'Active'
    user.is_active = True
    user.deactivated_at = None
    user.deactivation_reason = None

    if new_password:
        user.set_password(new_password)

    teacher_profile = Teacher.query.filter_by(user_id=user.id).first()
    if teacher_profile:
        teacher_profile.status = 'ACTIVE'

    actor_label = f' by user #{actor_id}' if actor_id else ''
    _log_security_event(
        f"ACCOUNT_REACTIVATED: User ID {user.id} ({user.full_name}){actor_label}."
    )


def transfer_staff_role(role, to_user, actor_id=None, *, deactivate_previous=True) -> list:
    """
    Move a single-holder role (e.g. business manager) to a new user.
    Previous holders are deactivated when deactivate_previous is True.
    """
    role_key = (role or '').strip().lower()
    if not role_key:
        raise ValueError('Role is required.')
    if to_user is None:
        raise ValueError('Target user is required.')

    previous_holders = User.query.filter(
        func.lower(User.role) == role_key,
        User.id != to_user.id,
    ).all()

    affected = []
    for holder in previous_holders:
        if deactivate_previous:
            deactivate_user_account(
                holder,
                reason=f'{role_key.title()} role transferred to {to_user.full_name}',
                actor_id=actor_id,
                release_teacher=(role_key == 'teacher'),
            )
        else:
            holder.role = 'staff'
        affected.append(holder)

    to_user.role = role_key
    to_user.status = 'Active'
    to_user.is_active = True
    to_user.deactivated_at = None
    to_user.deactivation_reason = None

    _log_security_event(
        f"ROLE_TRANSFER: '{role_key}' assigned to user ID {to_user.id} ({to_user.full_name})"
        f"{f' by user #{actor_id}' if actor_id else ''}."
    )
    return affected


def reassign_class_homeroom(class_id, teacher_id=None) -> Class:
    """Assign or clear the homeroom (form) teacher for a class."""
    klass = db.session.get(Class, class_id)
    if klass is None:
        raise ValueError('Class not found.')

    if teacher_id in (None, 0, '0', ''):
        klass.teacher_id = None
    else:
        teacher = db.session.get(Teacher, int(teacher_id))
        if teacher is None or teacher.status != 'ACTIVE':
            raise ValueError('Selected teacher is not active.')
        if not user_account_is_active(teacher.user):
            raise ValueError('Selected teacher account is inactive.')
        klass.teacher_id = teacher.id

    return klass


def get_daily_student_payments(target_date=None):
    """Return StudentPayment rows collected on the given calendar date (UTC)."""
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    day_start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    return (
        StudentPayment.query.filter(
            StudentPayment.paid_on >= day_start,
            StudentPayment.paid_on < day_end,
        )
        .order_by(StudentPayment.paid_on.desc())
        .all()
    )


def student_is_alumni(student) -> bool:
    """True when the student has graduated and should not appear on active rosters."""
    if student is None:
        return False
    status = (getattr(student, 'status', None) or '').strip().upper()
    return status in ALUMNI_STATUSES


def student_registration_gate_active(student) -> bool:
    """True when a promoted student must see the registration-held portal screen."""
    if student is None:
        return False
    if student_is_alumni(student):
        return False
    is_promoted = getattr(student, 'is_promoted', False)
    is_registered = getattr(student, 'is_registered', True)
    return bool(is_promoted and not is_registered)


def mark_student_alumni(student, graduation_year_id=None) -> None:
    """
    Move a graduating student off active rosters into alumni status.
    Keeps them on the graduation-year record, not the newly activated year.
    """
    if student is None:
        raise ValueError('Student is required.')
    if graduation_year_id is None:
        graduation_year_id = student.academic_year_id

    grade = student.grade_level
    if grade is None and student.klass_id:
        klass = student.assigned_class or db.session.get(Class, student.klass_id)
        if klass:
            grade = klass.grade_level
    if grade is None:
        grade = 12

    student.status = 'ALUMNI'
    student.klass_id = None
    student.grade_level = grade
    student.academic_year_id = graduation_year_id
    student.is_promoted = False
    student.is_registered = True
    student.registration_type = 'Alumni'
    student.tuition_cleared = True


def repair_misclassified_alumni(student, graduation_year_id=None) -> bool:
    """
    Fix a Grade 12 / graduated student incorrectly enrolled in a new academic year.
    Returns True when the record was repaired.
    """
    if student is None:
        return False

    status = (getattr(student, 'status', None) or '').strip().upper()
    grade = student.grade_level
    if grade is None and student.klass_id:
        klass = student.assigned_class or db.session.get(Class, student.klass_id)
        if klass:
            grade = klass.grade_level

    needs_repair = status in ALUMNI_STATUSES and student.klass_id is not None
    if not needs_repair:
        return False

    if graduation_year_id is None:
        active_year = AcademicYear.query.filter_by(is_active=True).first()
        if active_year and student.academic_year_id == active_year.id:
            ended = (
                AcademicYear.query.filter_by(is_active=False)
                .order_by(AcademicYear.end_date.desc(), AcademicYear.id.desc())
                .first()
            )
            graduation_year_id = ended.id if ended else student.academic_year_id
        else:
            graduation_year_id = student.academic_year_id

    mark_student_alumni(student, graduation_year_id)
    return True


def mark_student_promoted_pending_fee(student) -> None:
    """Flag a student as promoted for the new year with portal locked until fees are paid."""
    if student is None:
        raise ValueError('Student is required.')
    student.is_promoted = True
    student.is_registered = False


def activate_student_registration(student, actor_id=None) -> None:
    """Unlock the student portal after registration fees are cleared."""
    if student is None:
        raise ValueError('Student is required.')
    student.is_registered = True
    actor_label = f' by user #{actor_id}' if actor_id else ''
    _log_security_event(
        f"STUDENT_REGISTRATION_ACTIVATED: Student ID {student.id} "
        f"({student.full_name}){actor_label}."
    )


def maybe_activate_registration_from_payment(student, description) -> bool:
    """Auto-unlock portal when a registration fee payment is recorded."""
    if student is None:
        return False
    desc = (description or '').strip().lower()
    if 'registration' not in desc:
        return False
    if student.is_registered:
        return False
    student.is_registered = True
    _log_security_event(
        f"STUDENT_REGISTRATION_AUTO_ACTIVATED: Student ID {student.id} "
        f"({student.full_name}) via registration payment."
    )
    return True


def summarize_daily_collections(target_date=None) -> dict:
    """Aggregate tuition/fee collections for a single business day."""
    payments = get_daily_student_payments(target_date)
    total = sum(float(p.amount_paid or 0) for p in payments)
    return {
        'date': target_date or datetime.now(timezone.utc).date(),
        'count': len(payments),
        'total': total,
        'payments': payments,
    }
