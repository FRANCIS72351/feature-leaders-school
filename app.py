# app.py — Future Leaders Academy Management System
from flask import Flask, render_template, redirect, url_for, flash, request, Response, jsonify, send_file, send_from_directory, current_app, abort, session, g, has_app_context, has_request_context
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from models import db, User, Student, Teacher, Class, Announcement, Grade, GradeRelease, TranscriptRelease, AcademicYear, ClassSubjectTeacher, Room, Suspension, Discipline, StudentPayment, StudentRegistryDocument, StaffDocument, default_static_photo_url, school_logo_static_url, liberia_seal_static_url, display_font_static_url, resolve_parent_guardian_name
from itsdangerous import URLSafeTimedSerializer
import pyotp
from reportlab.pdfgen import canvas
from difflib import SequenceMatcher
import re
from decorators import role_required  # Adjust this import to match your layout
from constants import (
    ROLE_ADMIN,
    GRADING_PERIODS,
    grading_period_label,
    PERIOD_COMPONENT_SPECS,
    PERIOD_COMPONENT_MAXIMA,
    PERIOD_COMPONENT_CEILINGS,
    PERIOD_COMPONENT_SCHEME_NOTE,
    PERIOD_COMPONENT_ACTIVITY_TYPES,
    PERIOD_COMPONENT_EXTRA_CREDIT_FACTOR,
    PERIOD_COMPONENT_FIELD_MAX,
    PERIOD_TOTAL_LISTED_MAX,
    PERIOD_TOTAL_EXTRA_CREDIT_MAX,
    period_component_ceiling,
)
from school_divisions import (
    academic_year_span_key,
    canonical_grade_value,
    canonical_subject_name,
    class_document_context,
    class_sort_key_from_klass,
    display_report_score,
    division_document_titles,
    academic_level_for_student,
    division_label_for_class,
    division_legend_rows,
    division_score_remark,
    division_subject_heading,
    format_academic_year_label,
    GRADE_LEVEL_GROUPS_FOR_TEMPLATE,
    group_classes,
    group_items_by_class,
    is_conduct_subject,
    is_report_summary_subject,
    next_academic_year_label,
    next_canonical_grade,
    normalize_academic_year_name,
    numeric_report_score,
    official_subject_score_row,
    order_subjects_by_catalog,
    parse_academic_year_span,
    parse_grade_number,
    report_card_footer_rows,
    resolve_from_class,
    division_subjects,
    school_print_brand,
    SCHOOL_PRINT_EMAIL_ADDRESS,
    subject_match_key,
    build_transcript_grade_groups,
    transcript_conduct_cells,
    transcript_grade_heading,
    transcript_letterhead,
    transcript_promotion_fields,
)
from utils import (
    build_student_financials,
    parse_currency_amount,
    parse_currency_amount_optional,
    currency_to_float,
)
from io import BytesIO, StringIO
from sqlalchemy import func, text, or_, case
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from models import Student, AcademicYear, Class, BusinessTransaction, StudentPayment, SchoolFee
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timezone, timedelta
import csv
import glob
import json
import os
import shutil
import sys
from functools import wraps
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from account_lifecycle import (
    ACTIVE_ENROLLMENT_STATUSES,
    ALUMNI_STATUSES,
    activate_student_registration,
    mark_student_alumni,
    mark_student_promoted_pending_fee,
    maybe_activate_registration_from_payment,
    repair_misclassified_alumni,
    reassign_class_homeroom,
    deactivate_user_account,
    student_is_alumni,
    student_registration_gate_active,
    transfer_staff_role,
)
from deployment import configure_app, configure_sqlite_performance
from flask_migrate import Migrate
from ocr_scanner import (
    build_scan_result,
    extract_text_from_stream,
    ocr_engine_ready,
    ocr_libraries_available,
    parse_scan_keywords,
)
from student_scanner import (
    build_parent_report_url,
    build_student_portal_qr_url,
    build_student_verify_url,
    generate_parent_report_qr_code,
    generate_student_scanner_code,
    get_site_base_url,
    site_url_is_loopback,
)
from id_card_pdf import build_class_id_cards_pdf, id_card_header_title, id_cards_pdf_filename
import secrets
try:
    from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps
except ImportError:
    Image = None
    ImageChops = None
    ImageDraw = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None
try:
    import pytesseract
except ImportError:
    pytesseract = None

import logging

logger = logging.getLogger(__name__)


def normalize_role(user):
    """Return lowercase stripped role string for consistent access checks."""
    return (getattr(user, 'role', None) or '').strip().lower()


DASHBOARD_ROLE_LABELS = {
    'principal': 'Principal',
    'registrar': 'Registrar',
    'registry': 'Registrar',
    'admin': 'Admin',
    'business': 'Business Office',
    'teacher': 'Teacher',
    'dean': 'Dean',
    'vpi': 'VPI — Finance & Operations',
    'vpa': 'VPA — Academics',
    'student': 'Student',
    'parent': 'Parent',
    'sponsor': 'Sponsor',
}

ROLE_HOME_ENDPOINTS = {
    'principal': 'principal_dashboard',
    'teacher': 'teacher_dashboard',
    'dean': 'dean_dashboard',
    'vpi': 'vpi_dashboard',
    'vpa': 'vpa_dashboard',
    'student': 'student_dashboard',
    'sponsor': 'teacher_dashboard',
    'business': 'business_dashboard',
    'registrar': 'registrar_dashboard',
    'registry': 'registrar_dashboard',
    'admin': 'dashboard',
    'parent': 'dashboard',
}

ROLE_ALIASES = {
    'registry': 'registrar',
    'registry officer': 'registrar',
}

# VPA owns academics. VPI owns finance and campus operations. Do not mix the two offices.
ACADEMIC_COMMAND_ROLES = frozenset({'admin', 'principal', 'vpa'})
FISCAL_COMMAND_ROLES = frozenset({'admin', 'business', 'vpi', 'principal'})
STAFF_INTERNAL_GRADE_ROLES = frozenset({
    'admin', 'teacher', 'registrar', 'principal', 'vpa', 'vpi', 'dean', 'business',
})
OFFICIAL_TRANSCRIPT_STAFF_ROLES = frozenset({'admin', 'registrar', 'principal', 'vpa'})
GRADE_RELEASE_TEACHER_FLASH = (
    'Submitted to VPA for approval. Students cannot view this period until approved. '
    'Previously approved periods remain available.'
)
STUDENT_GRADE_HOLD_MESSAGE = (
    'Your report is being reviewed by the Vice Principal for Academics. '
    'It will appear here after approval.'
)
STUDENT_TRANSCRIPT_HOLD_MESSAGE = 'Official Transcript is not released yet.'
STUDENT_GRADE_AWAITING_VPA_NOTE = (
    'Official scores are shown for periods already approved by the Vice Principal '
    'for Academics. Later marking periods will appear here after VPA approval.'
)
# Official document release ladder. A VPA approval releases exactly ONE marking
# period; the semester sheet and the year-end report card are stricter gates.
SEMESTER_PERIOD_MAP = {1: (1, 2, 3, 7), 2: (4, 5, 6, 8)}
YEAR_TERMINAL_PERIODS = (8, 6)  # Exam (Sem 2); Period 6 for divisions without exams
STUDENT_REPORT_CARD_HOLD_MESSAGE = (
    'Your Report Card is issued at the end of the academic year, once the Vice '
    'Principal for Academics approves the final marking period. Results for the '
    'periods already approved are available now on your Grade Sheet.'
)
STUDENT_PERIOD_HOLD_MESSAGE = (
    'This marking period is still under review by the Vice Principal for '
    'Academics. It will appear here once approved.'
)
CLASS_STRUCTURE_ROLES = frozenset({'admin', 'principal', 'registrar', 'vpa', 'vpi', 'lead developer'})
FACILITY_ROLES = frozenset({'admin', 'principal', 'registrar', 'vpi', 'lead developer'})


def role_home_endpoint(user=None):
    role = normalize_role(user or current_user)
    return ROLE_HOME_ENDPOINTS.get(ROLE_ALIASES.get(role, role), 'dashboard')


def deny_unless_roles(allowed_roles, *, academic_office=None):
    """Return a redirect if the current user is outside the office that owns this page."""
    role = normalize_role(current_user)
    if role in allowed_roles:
        return None
    if academic_office is True:
        flash(
            "This is a VPA academic function (curriculum, teachers, grades). "
            "Tuition, fees, and the ledger belong to the VPI office.",
            "danger",
        )
    elif academic_office is False:
        flash(
            "This is a VPI finance and operations function. "
            "Curriculum, teacher assignment, and grades belong to the VPA office.",
            "danger",
        )
    else:
        flash("Unauthorized access for your office.", "danger")
    return redirect(url_for(role_home_endpoint()))


def canonical_role(user):
    """Map stored role strings (e.g. registry) onto the routing role."""
    role = normalize_role(user)
    return ROLE_ALIASES.get(role, role)


def dashboard_role_label(user):
    """Human-readable role label for the dashboard welcome banner."""
    role = canonical_role(user)
    return DASHBOARD_ROLE_LABELS.get(role, (role or 'user').title())


def home_endpoint_for_role(user):
    """Post-login / home endpoint for a user's stored role."""
    endpoint = ROLE_HOME_ENDPOINTS.get(canonical_role(user), 'dashboard')
    try:
        if endpoint in current_app.view_functions:
            return endpoint
    except RuntimeError:
        pass
    return 'dashboard'


def ensure_student_secure_qr_token(student):
    """Assign a unique cryptographic QR token to a student if missing."""
    if not student:
        return None
    if student.secure_qr_token:
        return student.secure_qr_token
    while True:
        token = secrets.token_urlsafe(48)
        if not Student.query.filter_by(secure_qr_token=token).first():
            student.secure_qr_token = token
            return token


def link_student_parent_account(student):
    """Link parent_id when a parent portal User exists for parent_email."""
    if not student:
        return None
    email = (student.parent_email or '').strip()
    if not email:
        student.parent_id = None
        return None
    parent = User.query.filter(func.lower(User.email) == email.lower()).first()
    student.parent_id = parent.id if parent else None
    return parent


def repair_student_qr_tokens():
    """Backfill secure QR tokens for legacy student rows."""
    missing = Student.query.filter(
        or_(Student.secure_qr_token.is_(None), Student.secure_qr_token == '')
    ).all()
    for student in missing:
        ensure_student_secure_qr_token(student)
    if missing:
        db.session.commit()
        return len(missing)
    return 0


def build_student_qr_context(student):
    """Template context for student ID card / QR display."""
    if not student:
        return {'qr_code_data_uri': None, 'student_verify_url': None}
    ensure_student_secure_qr_token(student)
    base_url = get_site_base_url()
    return {
        'qr_code_data_uri': generate_student_scanner_code(student, base_url=base_url),
        'student_verify_url': build_student_verify_url(student, base_url=base_url),
        'student_portal_qr_url': build_student_portal_qr_url(student, base_url=base_url),
    }


PARENT_REPORT_SESSION_HOURS = 2
PARENT_REPORT_MAX_ATTEMPTS = 5


def phone_digits_only(value):
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def ensure_parent_report_token(student):
    """Assign a unique parent report QR token if missing."""
    if not student:
        return None
    if student.parent_report_token:
        return student.parent_report_token
    while True:
        token = secrets.token_urlsafe(48)
        if not Student.query.filter_by(parent_report_token=token).first():
            student.parent_report_token = token
            return token


def persist_parent_report_token(student):
    """Ensure the parent report token exists in the database (required for scannable QR)."""
    if not student:
        return None
    ensure_parent_report_token(student)
    if db.session.is_modified(student, include_collections=False):
        db.session.commit()
    return student.parent_report_token


def parent_phone_digits(student):
    """Digits from parent_phone, linked parent user phone, or student portal phone."""
    if not student:
        return ''
    for candidate in (
        student.parent_phone,
        getattr(getattr(student, 'parent_user', None), 'telephone_number', None),
        getattr(getattr(student, 'user', None), 'telephone_number', None),
    ):
        digits = phone_digits_only(candidate)
        if len(digits) >= 4:
            return digits
    return ''


def parent_phone_last_four(student):
    digits = parent_phone_digits(student)
    return digits[-4:] if len(digits) >= 4 else ''


def set_parent_report_pin(student, pin):
    pin = (pin or '').strip()
    if not pin:
        return False
    if not pin.isdigit() or not (4 <= len(pin) <= 6):
        return False
    student.parent_report_pin_hash = generate_password_hash(pin)
    return True


def verify_parent_report_pin(student, pin):
    if not student or not student.parent_report_pin_hash:
        return False
    return check_password_hash(student.parent_report_pin_hash, (pin or '').strip())


def verify_parent_phone_last4(student, last4):
    expected = parent_phone_last_four(student)
    entered = phone_digits_only(last4)
    if len(expected) != 4 or len(entered) != 4:
        return False
    return entered == expected


def parent_report_access_configured(student):
    return bool(
        student
        and (
            student.parent_report_pin_hash
            or parent_phone_last_four(student)
        )
    )


def grant_parent_report_access(student_id, year_id=None):
    bucket = session.get('parent_report_access') or {}
    bucket[str(student_id)] = {
        'exp': (datetime.now(timezone.utc) + timedelta(hours=PARENT_REPORT_SESSION_HOURS)).timestamp(),
        'year_id': year_id,
    }
    session['parent_report_access'] = bucket
    session.modified = True


def has_parent_report_access(student_id, year_id=None):
    bucket = session.get('parent_report_access') or {}
    entry = bucket.get(str(student_id))
    if not entry:
        return False
    if entry.get('exp', 0) < datetime.now(timezone.utc).timestamp():
        bucket.pop(str(student_id), None)
        session['parent_report_access'] = bucket
        session.modified = True
        return False
    if year_id is not None and entry.get('year_id') not in (None, year_id):
        return False
    return True


def build_parent_report_qr_context(student, academic_year_id=None):
    if not student:
        return {
            'parent_report_qr_data_uri': None,
            'parent_report_url': None,
            'parent_report_configured': False,
            'parent_phone_last4_hint': None,
        }
    persist_parent_report_token(student)
    return {
        'parent_report_qr_data_uri': generate_parent_report_qr_code(student, academic_year_id=academic_year_id),
        'parent_report_url': build_parent_report_url(student, academic_year_id=academic_year_id),
        'parent_report_configured': parent_report_access_configured(student),
        'parent_phone_last4_hint': parent_phone_last_four(student) or None,
    }


def repair_parent_report_tokens():
    missing = Student.query.filter(
        or_(Student.parent_report_token.is_(None), Student.parent_report_token == '')
    ).all()
    for student in missing:
        ensure_parent_report_token(student)
    if missing:
        db.session.commit()
        return len(missing)
    return 0

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ======================== STUDENT ADMISSIONS CONFIG ========================
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
ACTIVITY_ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp',
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'xls', 'xlsx',
}

# Ensure the folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Check if uploaded file has allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_activity_file(filename):
    """Check if an activity attachment has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ACTIVITY_ALLOWED_EXTENSIONS


def activity_file_icon(filename):
    """Bootstrap icon class for an activity attachment."""
    if not filename or '.' not in filename:
        return 'bi-file-earmark'
    ext = filename.rsplit('.', 1)[1].lower()
    icons = {
        'pdf': 'bi-file-earmark-pdf',
        'doc': 'bi-file-earmark-word',
        'docx': 'bi-file-earmark-word',
        'ppt': 'bi-file-earmark-ppt',
        'pptx': 'bi-file-earmark-ppt',
        'xls': 'bi-file-earmark-excel',
        'xlsx': 'bi-file-earmark-excel',
        'txt': 'bi-file-earmark-text',
        'png': 'bi-file-earmark-image',
        'jpg': 'bi-file-earmark-image',
        'jpeg': 'bi-file-earmark-image',
        'gif': 'bi-file-earmark-image',
        'webp': 'bi-file-earmark-image',
    }
    return icons.get(ext, 'bi-file-earmark')

# ======================== END CONFIG =======================================

def resolve_static_upload_path(rel_path):
    """Resolve DB-relative upload path (uploads/...) to an absolute file under static/."""
    rel_path = (rel_path or '').replace('\\', '/').lstrip('/')
    if rel_path.startswith('static/'):
        rel_path = rel_path[len('static/'):]
    return os.path.join(BASE_DIR, 'static', rel_path.replace('/', os.sep))


def safe_send_upload_file(subdirectory, filename):
    """Serve a file from a static upload subdirectory with path-traversal protection."""
    safe_name = os.path.basename((filename or '').replace('\\', '/'))
    if not safe_name or safe_name in ('.', '..'):
        abort(404)
    base_dir = os.path.realpath(os.path.join(BASE_DIR, 'static', subdirectory))
    file_path = os.path.realpath(os.path.join(base_dir, safe_name))
    if not file_path.startswith(base_dir) or not os.path.isfile(file_path):
        abort(404)
    return send_from_directory(base_dir, safe_name, as_attachment=True)


def log_security_event(description):
    """Log security events to the database."""
    from models import db, SecurityLog
    
    event = SecurityLog(
        ip_address=request.remote_addr,
        event=description,
        timestamp=datetime.now(timezone.utc)
    )
    db.session.add(event)
    db.session.commit()

def log_incident(event_type):
    # We import SecurityLog and db locally inside the function
    # to prevent circular dependency lookup blocks during runtime initialization.
    from models import db, SecurityLog
    
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    log = SecurityLog(
        ip_address=ip, 
        event=event_type,
        timestamp=datetime.now(timezone.utc)
    )
    db.session.add(log)
    db.session.commit()

def check_brute_force(ip):
    """Block login after 5 failed attempts from the same IP within 15 minutes."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    recent_fails = SecurityLog.query.filter(
        SecurityLog.ip_address == ip,
        SecurityLog.event == 'FAILED_LOGIN',
        SecurityLog.timestamp >= cutoff,
    ).count()
    return recent_fails >= 5

# Local imports handled in init_db.py to avoid circular imports during app import
from models import (
    db, User, Student, Teacher, Class, ClassSubject, Enrollment, Grade,
    GradeRelease, TranscriptRelease, Attendance, Sponsor, Announcement, Discipline, Payroll,
    Assessment, AcademicYear, BusinessTransaction, StudentPayment,
    Leader, LeaderCategory, Event, SchoolMedia, SecurityLog, Suspension, Room,
    Asset, MaintenanceTicket, Activity, Submission, RolloverLog,
    SponsorWelfareNote, ClassAnnouncement,
)
from forms import (
    LoginForm, RegisterStudentForm, SelfRegistrationForm, PayrollForm, AcademicYearForm, RolloverWizardForm,
    AnnouncementForm, BusinessTransactionForm, AssignTeacherForm, CreateClassForm,
    EventForm, ConfirmDeleteForm, LeaderForm, EnrollmentForm, PaymentForm, TransactionForm,
    DisciplineForm, SchoolMediaForm, RecordClassroomActivityForm,
    AccountPasswordForm, AccountPhotoForm,
)

SCHOOL_VIDEO_MAX_DURATION_SEC = int(os.environ.get('SCHOOL_VIDEO_MAX_DURATION_SEC', '180'))
SCHOOL_VIDEO_MAX_MB = int(os.environ.get('SCHOOL_VIDEO_MAX_MB', '150'))
COMMUNICATIONS_MANAGER_ROLES = frozenset({"admin", "principal", "vpa"})
SCHOOL_MEDIA_MANAGER_ROLES = frozenset({"admin", "principal", "vpa", "registrar"})
REGISTRAR_MEDIA_CATEGORIES = frozenset({"entrance", "info_sheet"})
DOCUMENT_ONLY_MEDIA_CATEGORIES = frozenset({"entrance", "info_sheet"})
HOMEPAGE_FEATURED_MEDIA_CATEGORIES = frozenset({"general", "gallery", "advertisement"})
from flask_wtf import FlaskForm
from export_routes import init_export_routes

# -------------------------------------------------------------------
# SchoolEngine: Business Logic Helpers
# -------------------------------------------------------------------
class SchoolEngine:
    # --- DEAN LOGIC ---
    @staticmethod
    def suspend_student(student_id, days, reason):
        # Updated to standard modern SQLAlchemy get pattern
        student = db.session.get(Student, student_id)
        if not student: 
            return "Student not found"
            
        student.status = 'SUSPENDED'
        
        # Removed the redundant local 'from datetime import timedelta' statement
        end_date = datetime.now(timezone.utc) + timedelta(days=days)
        new_suspension = Suspension(student_id=student_id, reason=reason, return_date=end_date)
        
        db.session.add(new_suspension)
        db.session.commit()
        return f"Student locked out until {end_date.date()}"

    # --- VPA LOGIC ---
    @staticmethod
    def calculate_period_total(ca, exam, ca_weight=60, exam_weight=40, ca_max=60, exam_max=40):
        """
        Calculate a period total using configurable weights.

        - `ca` and `exam` are raw scores (default CA max 60, Exam max 40).
        - `ca_weight` and `exam_weight` are percentages that should sum to 100 (defaults 60/40).
        - `ca_max` and `exam_max` are the score maxima for CA and Exam respectively.

        Returns a float total (0-100) or None for invalid input.
        """
        try:
            ca = float(ca or 0)
            exam = float(exam or 0)
            ca_weight = float(ca_weight)
            exam_weight = float(exam_weight)
            ca_max = float(ca_max)
            exam_max = float(exam_max)
        except Exception:
            return None

        # Normalize weights if they don't sum to 100
        total_weight = ca_weight + exam_weight
        if total_weight <= 0:
            return None
        if abs(total_weight - 100.0) > 0.001:
            ca_weight = (ca_weight / total_weight) * 100.0
            exam_weight = (exam_weight / total_weight) * 100.0

        # Validate scores against maxima
        if ca_max <= 0 or exam_max <= 0:
            return None
        if ca < 0 or exam < 0:
            return None

        # If using default MoE maxima, enforce traditional caps for compatibility
        if ca_max == 60 and exam_max == 40:
            if ca > ca_max or exam > exam_max:
                return None

        # Convert raw scores to percentages of their maxima
        ca_pct = (ca / ca_max) * 100.0
        exam_pct = (exam / exam_max) * 100.0

        # Weighted contribution
        total = (ca_pct * (ca_weight / 100.0)) + (exam_pct * (exam_weight / 100.0))
        return round(float(total), 1)

    @staticmethod
    def calculate_gpa(scores):
        """Calculate GPA based on Liberian MoE scale"""
        grade_points = []
        for score in scores:
            if score >= 90:
                grade_points.append(4.0)  # A
            elif score >= 80:
                grade_points.append(3.0)  # B
            elif score >= 70:
                grade_points.append(2.0)  # C
            elif score >= 60:
                grade_points.append(1.0)  # D
            else:
                grade_points.append(0.0)  # F
        gpa = sum(grade_points) / len(grade_points) if grade_points else 0.0
        return gpa

    @staticmethod
    def get_grade_letter(score):
        if score is None:
            return '-'
        try:
            score = float(score)
        except (TypeError, ValueError):
            return '-'
        if score >= 90:
            return 'A'
        if score >= 80:
            return 'B'
        if score >= 70:
            return 'C'
        if score >= 60:
            return 'D'
        return 'F'

    @staticmethod
    def get_remarks(score):
        if score is None:
            return ''
        try:
            score = float(score)
        except (TypeError, ValueError):
            return ''
        if score >= 90:
            return 'Excellent'
        if score >= 80:
            return 'Very Good'
        if score >= 70:
            return 'Good'
        if score >= 60:
            return 'Satisfactory'
        return 'Failing'


# ----------------------------------------------------------------------
# Helper utilities: centralize teacher -> classes -> students resolution
# ----------------------------------------------------------------------
def get_teacher_class_ids(teacher_profile, user=None):
    """Return class ids the teacher may access (allocations, homeroom, sponsorship)."""
    ids = set()
    if not teacher_profile:
        return ids

    user_id = user.id if user else getattr(teacher_profile, 'user_id', None)

    try:
        allocs = ClassSubjectTeacher.query.filter_by(teacher_id=teacher_profile.id).all()
        for alloc in allocs:
            if getattr(alloc, 'class_id', None):
                ids.add(alloc.class_id)
    except Exception:
        pass

    try:
        for klass in Class.query.filter_by(teacher_id=teacher_profile.id).all():
            ids.add(klass.id)
    except Exception:
        pass

    try:
        if user_id:
            for klass in Class.query.filter_by(sponsor_id=user_id).all():
                ids.add(klass.id)
    except Exception:
        pass

    return ids


def get_teacher_classes(teacher_profile, user=None):
    """Return Class rows the teacher is authorized to work with."""
    class_ids = get_teacher_class_ids(teacher_profile, user)
    if not class_ids:
        return []
    return Class.query.filter(Class.id.in_(class_ids)).order_by(Class.name.asc()).all()


def teacher_can_access_class(teacher_profile, user, class_id):
    if not teacher_profile or not class_id:
        return False
    return int(class_id) in get_teacher_class_ids(teacher_profile, user)


def can_enter_class_grades(user, teacher_profile, class_id):
    """Assigned teachers or administrators may enter grades for a class."""
    if not class_id:
        return False
    role = normalize_role(user)
    if role == 'admin':
        return db.session.get(Class, class_id) is not None
    if role != 'teacher' or not teacher_profile:
        return False
    return teacher_can_access_class(teacher_profile, user, class_id)


def can_take_class_attendance(user, teacher_profile, class_id):
    """Assigned teachers or administrators may record class attendance."""
    return can_enter_class_grades(user, teacher_profile, class_id)


VALID_ATTENDANCE_STATUSES = frozenset({'present', 'absent', 'late', 'excused'})
ATTENDANCE_PRESENT_STATUSES = frozenset({'present', 'late', 'excused'})


def normalize_attendance_status(status, default='present'):
    normalized = (status or default).strip().lower()
    return normalized if normalized in VALID_ATTENDANCE_STATUSES else default


def get_class_students_for_year(class_id, display_year, *, viewing_archived=False):
    """Students in a class for the given academic year (historical resolution when archived)."""
    if not class_id or not display_year:
        return []
    klass = db.session.get(Class, class_id)
    if not klass:
        return []
    return _principal_students_for_class(
        klass, display_year, viewing_archived=viewing_archived,
    )


def upsert_attendance_record(
    student_id,
    attendance_date,
    status,
    notes=None,
    class_id=None,
    teacher_id=None,
    academic_year_id=None,
):
    """Create or update a single student's attendance for a calendar date."""
    if academic_year_id is None:
        academic_year_id = _attendance_year_id()
    row = Attendance.query.filter_by(student_id=student_id, date=attendance_date).first()
    if row:
        row.status = status
        row.notes = notes
        if class_id is not None:
            row.class_id = class_id
        if teacher_id is not None:
            row.teacher_id = teacher_id
        if academic_year_id is not None:
            row.academic_year_id = academic_year_id
        return row
    row = Attendance(
        student_id=student_id,
        date=attendance_date,
        status=status,
        notes=notes,
        class_id=class_id,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(row)
    return row

def save_class_attendance_bulk(class_id, teacher_id, attendance_date, form, active_year=None):
    """Persist attendance for every student in a class from a submitted form."""
    active_year = active_year or resolve_teacher_attendance_year()
    students = get_class_students_for_year(class_id, active_year)
    year_id = _attendance_year_id(active_year)
    saved = 0
    for student in students:
        status = normalize_attendance_status(form.get(f'attendance_{student.id}'))
        notes = (form.get(f'notes_{student.id}') or '').strip() or None
        upsert_attendance_record(
            student.id,
            attendance_date,
            status,
            notes=notes,
            class_id=class_id,
            teacher_id=teacher_id,
            academic_year_id=year_id,
        )
        saved += 1
    return saved

def build_class_attendance_history(class_id, student_ids, days=14, active_year=None):
    """Return recent daily attendance summaries for a class roster."""
    if not student_ids:
        return []
    today = date.today()
    start = today - timedelta(days=days - 1)
    start_str = start.strftime('%Y-%m-%d')
    year_id = _attendance_year_id(active_year)
    q = Attendance.query.filter(
        Attendance.student_id.in_(student_ids),
        Attendance.date >= start_str,
    )
    rows = apply_attendance_year_filter(q, year_id).order_by(Attendance.date.desc()).all()
    by_date = {}
    for row in rows:
        by_date.setdefault(row.date, []).append(row)
    history = []
    for offset in range(days):
        day = today - timedelta(days=offset)
        day_str = day.strftime('%Y-%m-%d')
        day_rows = by_date.get(day_str, [])
        counts = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0}
        for row in day_rows:
            key = normalize_attendance_status(row.status, default='')
            if key in counts:
                counts[key] += 1
        history.append({
            'date': day_str,
            'label': day.strftime('%a, %b %d'),
            'marked': len(day_rows),
            'total': len(student_ids),
            **counts,
        })
    return history


def build_teacher_attendance_context(
    teacher_profile,
    user,
    klass,
    active_year,
    attendance_date=None,
):
    """Assemble data for the teacher attendance roll page."""
    attendance_date = attendance_date or date.today().strftime('%Y-%m-%d')
    students = get_class_students_for_year(klass.id, active_year)
    student_ids = [s.id for s in students]

    year_id = _attendance_year_id(active_year)
    today_attendance = {}
    if student_ids:
        q = Attendance.query.filter(
            Attendance.student_id.in_(student_ids),
            Attendance.date == attendance_date,
        )
        for row in apply_attendance_year_filter(q, year_id).all():
            today_attendance[row.student_id] = row

    roster = []
    counts = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'unmarked': 0}
    for student in students:
        att_row = today_attendance.get(student.id)
        status = normalize_attendance_status(att_row.status if att_row else 'present')
        if att_row:
            counts[status] = counts.get(status, 0) + 1
        else:
            counts['unmarked'] += 1
        roster.append({
            'student': student,
            'attendance_status': status,
            'attendance_rate': _student_attendance_rate(student, academic_year_id=year_id),
            'notes': att_row.notes if att_row else '',
            'is_marked': att_row is not None,
        })

    history = build_class_attendance_history(klass.id, student_ids, active_year=active_year)
    teacher_class_tabs = [
        {
            'id': card['id'],
            'name': card['name'],
            'url': url_for('teacher_class_attendance', class_id=card['id'], date=attendance_date),
        }
        for card in get_teacher_class_cards(teacher_profile, user, active_year.id if active_year else None)
    ]

    try:
        att_date_obj = datetime.strptime(attendance_date, '%Y-%m-%d').date()
    except ValueError:
        att_date_obj = date.today()
    monthly_summary = build_monthly_class_attendance_matrix(
        students,
        att_date_obj.year,
        att_date_obj.month,
        academic_year_id=year_id,
    )

    return {
        'klass': klass,
        'students': students,
        'roster': roster,
        'attendance_date': attendance_date,
        'active_year': active_year,
        'teacher_profile': teacher_profile,
        'counts': counts,
        'history': history,
        'teacher_class_tabs': teacher_class_tabs,
        'total_students': len(students),
        'marked_today': len(students) - counts['unmarked'],
        'monthly_summary': monthly_summary,
    }


ATTENDANCE_YEAR_SESSION_KEY = 'attendance_display_year_id'
ATTENDANCE_SCOPE_FULL = 'full'
ATTENDANCE_SCOPE_READ = 'read_all'
ATTENDANCE_SCOPE_SUMMARY = 'summary'
ATTENDANCE_SCOPE_CLASS = 'class'
ATTENDANCE_SCOPE_OWN = 'own'


def get_attendance_visibility_scope(user):
    """Return attendance access tier for a user, or None if denied."""
    role = normalize_role(user)
    if role in ('admin', 'principal'):
        return ATTENDANCE_SCOPE_FULL
    if role in ('registrar', 'dean'):
        return ATTENDANCE_SCOPE_READ
    if role in ('business', 'vpi', 'vpa'):
        return ATTENDANCE_SCOPE_SUMMARY
    if role == 'teacher':
        return ATTENDANCE_SCOPE_CLASS
    if role == 'student':
        return ATTENDANCE_SCOPE_OWN
    return None


def can_view_attendance_overview(user):
    return get_attendance_visibility_scope(user) in (
        ATTENDANCE_SCOPE_FULL,
        ATTENDANCE_SCOPE_READ,
        ATTENDANCE_SCOPE_SUMMARY,
    )


def can_view_class_attendance_detail(user, class_id, teacher_profile=None):
    scope = get_attendance_visibility_scope(user)
    if scope in (ATTENDANCE_SCOPE_FULL, ATTENDANCE_SCOPE_READ):
        return True
    if scope == ATTENDANCE_SCOPE_CLASS:
        return can_enter_class_grades(user, teacher_profile, class_id)
    return False


def parse_attendance_filter_dates(args, default_days=30):
    """Parse date_from/date_to query params with sensible defaults."""
    today = date.today()
    date_to = (args.get('date_to') or today.strftime('%Y-%m-%d')).strip()
    if args.get('date_from'):
        date_from = args.get('date_from').strip()
    else:
        date_from = (today - timedelta(days=default_days - 1)).strftime('%Y-%m-%d')
    return date_from, date_to


def _attendance_date_label(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date().strftime('%a, %b %d, %Y')
    except ValueError:
        return date_str


def _year_student_ids(display_year, *, viewing_archived=False):
    if not display_year:
        return None
    return [
        row[0]
        for row in _students_for_display_year(
            display_year, history_mode=viewing_archived,
        ).with_entities(Student.id).all()
    ]


def query_attendance_records(
    display_year,
    class_id=None,
    date_from=None,
    date_to=None,
    status=None,
    student_ids=None,
    *,
    viewing_archived=False,
):
    """Year- and filter-aware attendance query."""
    q = Attendance.query
    year_ids = _year_student_ids(display_year, viewing_archived=viewing_archived)
    if year_ids is not None:
        if not year_ids:
            return Attendance.query.filter(Attendance.id < 0)
        q = q.filter(Attendance.student_id.in_(year_ids))
    if class_id:
        klass = db.session.get(Class, class_id)
        if klass and display_year:
            class_student_ids = [
                s.id for s in _principal_students_for_class(
                    klass, display_year, viewing_archived=viewing_archived,
                )
            ]
        else:
            class_student_ids = []
        if class_student_ids:
            q = q.filter(Attendance.student_id.in_(class_student_ids))
        else:
            return Attendance.query.filter(Attendance.id < 0)
    if date_from:
        q = q.filter(Attendance.date >= date_from)
    if date_to:
        q = q.filter(Attendance.date <= date_to)
    if status and status in VALID_ATTENDANCE_STATUSES:
        q = q.filter(Attendance.status == status)
    if student_ids:
        q = q.filter(Attendance.student_id.in_(student_ids))
    return q.order_by(Attendance.date.desc())


def _classes_for_attendance_year(display_year, *, viewing_archived=False):
    classes = Class.query.order_by(Class.name.asc()).all()
    if not display_year:
        return classes
    enrolled_ids = set(
        _roster_sizes_for_display_year(display_year, viewing_archived=viewing_archived).keys()
    )
    if enrolled_ids:
        return [klass for klass in classes if klass.id in enrolled_ids]
    return classes


def build_attendance_overview_context(
    display_year, years, filters, scope=ATTENDANCE_SCOPE_FULL, *, viewing_archived=False,
):
    """Aggregate attendance reporting data for leadership/registrar dashboards."""
    class_id = filters.get('class_id')
    date_from = filters.get('date_from')
    date_to = filters.get('date_to')
    status_filter = (filters.get('status') or '').strip().lower()

    classes = _classes_for_attendance_year(display_year, viewing_archived=viewing_archived)
    records = query_attendance_records(
        display_year,
        class_id=class_id,
        date_from=date_from,
        date_to=date_to,
        status=status_filter or None,
        viewing_archived=viewing_archived,
    ).all()

    class_map = {klass.id: klass for klass in classes}
    student_class_map = _student_class_map_for_display_year(
        display_year, viewing_archived=viewing_archived,
    )

    daily_map = {}
    class_totals = {}
    summary_counts = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0}

    for row in records:
        status = normalize_attendance_status(row.status, default='')
        if status in summary_counts:
            summary_counts[status] += 1
        resolved_class_id = row.class_id or student_class_map.get(row.student_id)
        if not resolved_class_id:
            continue
        key = (resolved_class_id, row.date)
        bucket = daily_map.setdefault(key, {'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'marked': 0})
        if status in bucket:
            bucket[status] += 1
            bucket['marked'] += 1
        class_bucket = class_totals.setdefault(
            resolved_class_id,
            {'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'marked': 0, 'days': set()},
        )
        if status in class_bucket:
            class_bucket[status] += 1
            class_bucket['marked'] += 1
            class_bucket['days'].add(row.date)

    roster_sizes = _roster_sizes_for_display_year(
        display_year, viewing_archived=viewing_archived,
    ) if display_year else {}

    daily_rows = []
    for (kid, day_str), counts in sorted(daily_map.items(), key=lambda item: (item[0][1], item[0][0]), reverse=True):
        klass = class_map.get(kid)
        total = roster_sizes.get(kid, 0)
        present_equiv = counts['present'] + counts['late'] + counts['excused']
        daily_rows.append({
            'class_id': kid,
            'class_name': klass.name if klass else f'Class #{kid}',
            'date': day_str,
            'date_label': _attendance_date_label(day_str),
            'present': counts['present'],
            'absent': counts['absent'],
            'late': counts['late'],
            'excused': counts['excused'],
            'marked': counts['marked'],
            'total': total,
            'present_pct': round(present_equiv / counts['marked'] * 100, 1) if counts['marked'] else None,
        })

    class_summaries = []
    for kid, counts in class_totals.items():
        klass = class_map.get(kid)
        present_equiv = counts['present'] + counts['late'] + counts['excused']
        class_summaries.append({
            'class_id': kid,
            'class_name': klass.name if klass else f'Class #{kid}',
            'present': counts['present'],
            'absent': counts['absent'],
            'late': counts['late'],
            'excused': counts['excused'],
            'marked': counts['marked'],
            'days_tracked': len(counts['days']),
            'present_pct': round(present_equiv / counts['marked'] * 100, 1) if counts['marked'] else None,
        })
    class_summaries.sort(key=lambda row: row['class_name'])

    total_marked = sum(summary_counts.values())
    present_equiv = (
        summary_counts['present']
        + summary_counts['late']
        + summary_counts['excused']
    )
    return {
        'classes': classes,
        'daily_rows': daily_rows,
        'class_summaries': class_summaries,
        'summary_stats': {
            'total_records': total_marked,
            'present_count': present_equiv,
            'absent_count': summary_counts['absent'],
            'late_count': summary_counts['late'],
            'excused_count': summary_counts['excused'],
            'present_pct': round(present_equiv / total_marked * 100, 1) if total_marked else None,
        },
        'filters': {
            'class_id': class_id,
            'date_from': date_from,
            'date_to': date_to,
            'status': status_filter,
        },
        'scope': scope,
        'can_drill_down': scope in (ATTENDANCE_SCOPE_FULL, ATTENDANCE_SCOPE_READ, ATTENDANCE_SCOPE_CLASS),
        'read_only': scope in (ATTENDANCE_SCOPE_READ, ATTENDANCE_SCOPE_SUMMARY),
        'years': years,
        'display_year': display_year,
    }


def build_attendance_class_day_detail(klass, attendance_date, display_year, *, viewing_archived=False):
    """Read-only roster attendance for one class on one calendar day."""
    students = get_class_students_for_year(
        klass.id, display_year, viewing_archived=viewing_archived,
    )
    student_ids = [student.id for student in students]
    by_student = {}
    if student_ids:
        for row in Attendance.query.filter(
            Attendance.student_id.in_(student_ids),
            Attendance.date == attendance_date,
        ).all():
            by_student[row.student_id] = row

    roster = []
    counts = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'unmarked': 0}
    for student in students:
        att_row = by_student.get(student.id)
        status = normalize_attendance_status(att_row.status if att_row else '', default='')
        if att_row and status in counts:
            counts[status] += 1
        elif not att_row:
            counts['unmarked'] += 1
        roster.append({
            'student': student,
            'status': status or 'unmarked',
            'notes': att_row.notes if att_row else '',
            'is_marked': att_row is not None,
        })

    present_equiv = counts['present'] + counts['late'] + counts['excused']
    marked = len(students) - counts['unmarked']
    return {
        'klass': klass,
        'attendance_date': attendance_date,
        'date_label': _attendance_date_label(attendance_date),
        'roster': roster,
        'counts': counts,
        'display_year': display_year,
        'total_students': len(students),
        'marked': marked,
        'present_pct': round(present_equiv / marked * 100, 1) if marked else None,
    }


def build_student_self_attendance_context(student, display_year):
    """Personal attendance ledger for the student dashboard."""
    if not student:
        return {
            'records': [],
            'present_pct': None,
            'counts': {'present': 0, 'absent': 0, 'late': 0, 'excused': 0},
            'total_marked': 0,
        }

    records = []
    for row in student.attendance_ledger.order_by(Attendance.date.desc()).all():
        if display_year:
            if row.academic_year_id and row.academic_year_id != display_year.id:
                continue
            if not row.academic_year_id and student.academic_year_id != display_year.id:
                continue
        status = normalize_attendance_status(row.status, default='')
        records.append({
            'date': row.date,
            'status': status,
            'notes': row.notes or '',
            'label': _attendance_date_label(row.date),
        })

    counts = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0}
    for entry in records:
        if entry['status'] in counts:
            counts[entry['status']] += 1
    total = len(records)
    present_equiv = sum(counts[s] for s in ATTENDANCE_PRESENT_STATUSES if s in counts)
    return {
        'records': records,
        'present_pct': round(present_equiv / total * 100, 1) if total else None,
        'counts': counts,
        'total_marked': total,
    }


def build_monthly_class_attendance_matrix(students, year, month, academic_year_id=None):
    """Monthly per-student attendance grid for teacher export/reporting."""
    import calendar

    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1).strftime('%Y-%m-%d')
    month_end = date(year, month, days_in_month).strftime('%Y-%m-%d')
    day_keys = [date(year, month, day_num).strftime('%Y-%m-%d') for day_num in range(1, days_in_month + 1)]

    student_ids = [student.id for student in students]
    year_id = academic_year_id if academic_year_id is not None else _attendance_year_id()
    att_map = {}
    if student_ids:
        q = Attendance.query.filter(
            Attendance.student_id.in_(student_ids),
            Attendance.date >= month_start,
            Attendance.date <= month_end,
        )
        for row in apply_attendance_year_filter(q, year_id).all():
            att_map.setdefault(row.student_id, {})[row.date] = normalize_attendance_status(row.status)

    rows = []
    for student in students:
        cells = {day_key: att_map.get(student.id, {}).get(day_key) for day_key in day_keys}
        rows.append({'student': student, 'cells': cells})

    return {
        'year': year,
        'month': month,
        'month_label': date(year, month, 1).strftime('%B %Y'),
        'days': day_keys,
        'day_numbers': list(range(1, days_in_month + 1)),
        'rows': rows,
    }


def _attendance_overview_session_key(role):
    role = (role or '').lower()
    if role == 'principal':
        return PRINCIPAL_YEAR_SESSION_KEY
    if role == 'registrar':
        return REGISTRAR_YEAR_SESSION_KEY
    if role == 'dean':
        return DEAN_YEAR_SESSION_KEY
    if role == 'vpi':
        return VPI_YEAR_SESSION_KEY
    if role == 'vpa':
        return VPA_YEAR_SESSION_KEY
    if role == 'admin':
        return ADMIN_YEAR_SESSION_KEY
    return ATTENDANCE_YEAR_SESSION_KEY


def render_attendance_overview(back_url, back_label, page_title):
    """Shared handler for leadership/registrar attendance overview pages."""
    scope = get_attendance_visibility_scope(current_user)
    if not can_view_attendance_overview(current_user):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    session_key = _attendance_overview_session_key(normalize_role(current_user))
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=session_key,
    )
    date_from, date_to = parse_attendance_filter_dates(request.args)
    class_id = request.args.get('class_id', type=int)
    status_filter = (request.args.get('status') or '').strip().lower()

    ctx = build_attendance_overview_context(
        display_year,
        years,
        {
            'class_id': class_id,
            'date_from': date_from,
            'date_to': date_to,
            'status': status_filter,
        },
        scope=scope,
        viewing_archived=viewing_archived,
    )
    return render_template(
        'attendance/overview.html',
        active_year=active_year,
        viewing_archived=viewing_archived,
        back_url=back_url,
        back_label=back_label,
        page_title=page_title,
        **ctx,
    )


def teacher_can_access_student(teacher_profile, user, student, academic_year_id=None):
    if not teacher_profile or not student:
        return False
    class_ids = get_teacher_class_ids(teacher_profile, user)
    if not class_ids:
        return False
    if academic_year_id is None:
        active = get_active_academic_year()
        academic_year_id = active.id if active else None
    if academic_year_id:
        if student.academic_year_id != academic_year_id:
            return False
        if not student.is_registered:
            return False
    if student.klass_id and student.klass_id in class_ids:
        return True
    try:
        enrollment_query = Enrollment.query.filter(
            Enrollment.student_id == student.id,
            Enrollment.class_id.in_(class_ids),
        )
        if academic_year_id:
            enrollment_query = enrollment_query.filter(
                Enrollment.academic_year_id == academic_year_id,
            )
        return enrollment_query.first() is not None
    except Exception:
        return False


def get_teacher_class_cards(teacher_profile, user, academic_year_id=None, *, viewing_archived=False):
    """Build class folder cards with subjects and student counts for the teacher UI."""
    if not teacher_profile or not user:
        return []

    class_ids = get_teacher_class_ids(teacher_profile, user)
    if not class_ids:
        return []

    subject_map = {}
    for alloc in ClassSubjectTeacher.query.filter_by(teacher_id=teacher_profile.id).all():
        subject_map.setdefault(alloc.class_id, set()).add(alloc.subject_name)

    if academic_year_id is not None:
        display_year = db.session.get(AcademicYear, academic_year_id)
    else:
        display_year = get_active_academic_year()
    roster_sizes = (
        _roster_sizes_for_display_year(display_year, viewing_archived=viewing_archived)
        if display_year else {}
    )

    cards = []
    for klass in Class.query.filter(Class.id.in_(class_ids)).order_by(
        Class.grade_level.asc(), Class.name.asc()
    ):
        role_labels = []
        if klass.teacher_id == teacher_profile.id:
            role_labels.append('Homeroom')
        if klass.sponsor_id == user.id:
            role_labels.append('Sponsor')
        if not role_labels:
            role_labels.append('Subject Teacher')

        student_count = roster_sizes.get(klass.id, 0)
        cards.append({
            'id': klass.id,
            'name': klass.name,
            'grade_level': klass.grade_level,
            'stream': klass.stream,
            'subjects': sorted(subject_map.get(klass.id, [])),
            'student_count': student_count,
            'role_labels': role_labels,
            'klass': klass,
        })
    return cards


def build_teacher_dashboard_context(teacher_profile, user, academic_year_id=None, *, viewing_archived=False):
    """Assemble roster-limited teacher dashboard data."""
    if academic_year_id is None:
        active = get_active_academic_year()
        academic_year_id = active.id if active else None
    class_ids = get_teacher_class_ids(teacher_profile, user)
    teaching_classes = get_teacher_classes(teacher_profile, user)
    class_cards = get_teacher_class_cards(
        teacher_profile,
        user,
        academic_year_id,
        viewing_archived=viewing_archived,
    )
    sponsored_classes = (
        Class.query.filter_by(sponsor_id=user.id).order_by(Class.name.asc()).all()
        if user else []
    )
    students = (
        get_students_for_class_ids(
            list(class_ids), academic_year_id, viewing_archived=viewing_archived,
        )
        if class_ids else []
    )
    student_ids = {s.id for s in students}

    activities = []
    recent_submissions = []
    if class_ids:
        try:
            activity_query = Assessment.query.filter(Assessment.klass_id.in_(class_ids))
            if academic_year_id is not None:
                activity_query = activity_query.filter(
                    Assessment.academic_year_id == academic_year_id
                )
            activities = (
                activity_query.order_by(Assessment.id.desc())
                .limit(20)
                .all()
            )
        except Exception:
            activities = []
        try:
            recent_submissions = (
                Submission.query.join(Assessment)
                .filter(Assessment.klass_id.in_(class_ids))
                .order_by(Submission.submitted_at.desc())
                .limit(25)
                .all()
            )
            if academic_year_id is not None:
                recent_submissions = [
                    sub for sub in recent_submissions
                    if sub.assessment and sub.assessment.academic_year_id == academic_year_id
                ]
        except Exception:
            recent_submissions = []

    grades = []
    if teacher_profile:
        grade_query = Grade.query.filter_by(teacher_id=teacher_profile.id)
        if academic_year_id is not None:
            grade_query = grade_query.filter_by(academic_year_id=academic_year_id)
        if student_ids:
            grade_query = grade_query.filter(Grade.student_id.in_(student_ids))
        grades = grade_query.order_by(Grade.id.desc()).all()

    assigned_subjects = sorted(
        {
            subject
            for card in class_cards
            for subject in card.get('subjects', [])
        },
        key=str.lower,
    )

    pending_grading_count = sum(
        1 for s in recent_submissions if not s.is_graded
    )
    activities_with_pending = 0
    if class_ids and activities:
        try:
            activity_ids = [act.id for act in activities]
            pending_subs = Submission.query.filter(
                Submission.activity_id.in_(activity_ids),
                Submission.is_graded.is_(False),
            ).all()
            activities_with_pending = len({
                sub.activity_id
                for sub in pending_subs
                if (sub.file_path or sub.submission_text)
            })
        except Exception:
            pass

    return {
        'teaching_classes': teaching_classes,
        'class_cards': class_cards,
        'sponsored_classes': sponsored_classes,
        'students': students,
        'activities': activities,
        'recent_submissions': recent_submissions,
        'grades': grades,
        'assigned_subjects': assigned_subjects,
        'grading_periods': MOE_GRADING_PERIODS,
        'pending_grading_count': pending_grading_count,
        'activities_with_pending': activities_with_pending,
    }


def _grade_has_entered_scores(grade):
    return (
        grade.ca_score is not None
        or grade.exam_score is not None
        or grade.score is not None
    )


def _ledger_entry_from_grade(grade):
    period_num = grade.marking_period or normalize_grade_period(grade.period) or 1
    return {
        'subject': (grade.subject or grade.subject_name or '').strip(),
        'period_label': grading_period_label(period_num),
        'is_exam_period': period_num in (7, 8),
        'score': grade.score,
        'ca_score': grade.ca_score,
        'exam_score': grade.exam_score,
        'submitted': bool(grade.submitted),
    }


def _ledger_stats_for_grades(grades):
    meaningful = [g for g in grades if _grade_has_entered_scores(g)]
    return {
        'total_entries': len(meaningful),
        'students_with_grades': len({g.student_id for g in meaningful}),
        'published': sum(1 for g in meaningful if g.submitted),
        'draft': sum(1 for g in meaningful if not g.submitted),
    }


def build_teacher_grade_ledger(
    teacher_profile,
    class_cards,
    active_year,
    ledger_class_id=None,
    ledger_subject='',
    grade_class_id=None,
):
    """Build per-class grade ledger summaries and student rows for the teacher UI."""
    empty = {
        'grade_ledger_by_class': {},
        'ledger_class_id': None,
        'selected_ledger_class': None,
        'ledger_class_data': {},
        'ledger_student_rows': [],
        'ledger_subjects': [],
        'ledger_stats': {},
        'ledger_subject': (ledger_subject or '').strip(),
    }
    if not teacher_profile or not class_cards:
        return empty

    if active_year is None:
        active_year = get_active_academic_year()

    valid_class_ids = {card['id'] for card in class_cards}
    if ledger_class_id not in valid_class_ids:
        if grade_class_id in valid_class_ids:
            ledger_class_id = grade_class_id
        else:
            ledger_class_id = class_cards[0]['id']

    academic_year_id = (
        active_year.id if active_year and hasattr(active_year, 'id') else None
    )
    grade_ledger_by_class = {}
    for card in class_cards:
        class_id = card['id']
        grade_query = Grade.query.filter_by(
            class_id=class_id,
            teacher_id=teacher_profile.id,
        )
        if academic_year_id is not None:
            grade_query = grade_query.filter_by(academic_year_id=academic_year_id)
        grade_ledger_by_class[class_id] = {
            'stats': _ledger_stats_for_grades(grade_query.all()),
        }

    selected_ledger_class = next(
        (card for card in class_cards if card['id'] == ledger_class_id),
        None,
    )
    ledger_class_data = grade_ledger_by_class.get(ledger_class_id, {})
    ledger_stats = ledger_class_data.get('stats', {})
    ledger_student_rows = []
    ledger_subjects = []

    if ledger_class_id:
        students = (
            get_class_students_for_year(ledger_class_id, active_year)
            if active_year else []
        )
        grade_query = Grade.query.filter_by(
            class_id=ledger_class_id,
            teacher_id=teacher_profile.id,
        )
        if academic_year_id is not None:
            grade_query = grade_query.filter_by(academic_year_id=academic_year_id)
        grades_by_student = {}
        for grade in grade_query.all():
            if not _grade_has_entered_scores(grade):
                continue
            grades_by_student.setdefault(grade.student_id, []).append(grade)

        for student in students:
            student_grades = grades_by_student.get(student.id, [])
            if not student_grades:
                continue
            entries = sorted(
                (_ledger_entry_from_grade(grade) for grade in student_grades),
                key=lambda entry: (
                    entry['subject'].lower(),
                    entry['period_label'],
                ),
            )
            ledger_student_rows.append({'student': student, 'entries': entries})

        subject_set = {
            entry['subject']
            for row in ledger_student_rows
            for entry in row['entries']
            if entry['subject']
        }
        ledger_subjects = sorted(subject_set, key=str.lower)

    return {
        'grade_ledger_by_class': grade_ledger_by_class,
        'ledger_class_id': ledger_class_id,
        'selected_ledger_class': selected_ledger_class,
        'ledger_class_data': ledger_class_data,
        'ledger_student_rows': ledger_student_rows,
        'ledger_subjects': ledger_subjects,
        'ledger_stats': ledger_stats,
        'ledger_subject': (ledger_subject or '').strip(),
    }


def parse_activity_due_date(raw_value):
    """Return normalized ISO date string or None."""
    raw = (raw_value or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).strftime('%Y-%m-%d')
    except ValueError:
        return None


def normalize_scan_keywords(raw_value):
    """Store comma-separated OCR answer keywords."""
    keywords = parse_scan_keywords(raw_value)
    if not keywords:
        return None
    return ', '.join(keywords)


def normalize_external_url(raw_value):
    """Return a trimmed http(s) URL or None."""
    url = (raw_value or '').strip()
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        return None
    return url[:500]


def classroom_notes_summary(notes, limit=250):
    """Short summary for list views and legacy description field."""
    text = (notes or '').strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def title_from_activity_filename(filename):
    base_name = os.path.splitext(secure_filename(filename))[0]
    return base_name.replace('_', ' ').replace('-', ' ').strip().title() or 'New Activity'


def save_activity_upload_file(task_file, klass_id):
    if not task_file or not task_file.filename:
        return None
    if not allowed_activity_file(task_file.filename):
        return None
    upload_dir = os.path.join(BASE_DIR, 'static', 'uploads', 'activities')
    os.makedirs(upload_dir, exist_ok=True)
    file_name = (
        f"activity_{klass_id}_{int(datetime.now(timezone.utc).timestamp())}_"
        f"{secure_filename(task_file.filename)}"
    )
    task_file.save(os.path.join(upload_dir, file_name))
    return file_name


def delete_activity_upload_file(file_name):
    if not file_name:
        return
    safe_name = os.path.basename(file_name.replace('\\', '/'))
    path = os.path.join(BASE_DIR, 'static', 'uploads', 'activities', safe_name)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def compute_activity_submission_stats(activities, class_sizes_by_id):
    """Return per-activity submission counts for teacher dashboards."""
    if not activities:
        return {}
    activity_ids = [act.id for act in activities]
    submissions = Submission.query.filter(Submission.assessment_id.in_(activity_ids)).all()
    subs_by_activity = {}
    for sub in submissions:
        subs_by_activity.setdefault(sub.assessment_id, []).append(sub)

    stats = {}
    for act in activities:
        class_size = class_sizes_by_id.get(act.klass_id, 0)
        act_subs = subs_by_activity.get(act.id, [])
        submitted_count = sum(
            1 for sub in act_subs if sub.file_path or sub.submission_text
        )
        pending_grade_count = sum(
            1 for sub in act_subs
            if not sub.is_graded and (sub.file_path or sub.submission_text)
        )
        stats[act.id] = {
            'submitted_count': submitted_count,
            'pending_grade_count': pending_grade_count,
            'class_size': class_size,
            'missing_count': max(class_size - submitted_count, 0),
        }
    return stats


def build_activity_grading_inbox(activities, activity_stats, class_cards):
    """Activities with ungraded submissions, newest first."""
    class_names = {card['id']: card['name'] for card in class_cards}
    inbox = []
    for act in activities:
        if is_quick_entry_assessment(act):
            continue
        stats = activity_stats.get(act.id, {})
        pending = stats.get('pending_grade_count', 0)
        if pending <= 0:
            continue
        inbox.append({
            'activity': act,
            'stats': stats,
            'class_name': class_names.get(act.klass_id, 'Class'),
        })
    return inbox


def notify_class_new_activity(klass, teacher_user, title, subject_name, marking_period, description, due_date):
    due_line = f" Due: {due_date}." if due_date else ""
    body = (
        f"{subject_name} · Period {marking_period} — "
        f"{description or 'Open My Tasks to download and submit.'}{due_line}"
    )
    db.session.add(ClassAnnouncement(
        class_id=klass.id,
        author_id=teacher_user.id,
        title=f"New activity: {title}",
        content=body,
        audience='students',
    ))


def teacher_owns_assessment(teacher_profile, user, assessment):
    if not assessment or not teacher_profile:
        return False
    if assessment.teacher_id and assessment.teacher_id == teacher_profile.id:
        return True
    return teacher_can_access_class(teacher_profile, user, assessment.klass_id)


def create_assessment_record(
    *,
    title,
    description,
    evaluation_type,
    submission_mode,
    subject_name,
    marking_period,
    active_year,
    teacher_profile,
    klass_id,
    task_file_name=None,
    due_date=None,
    scan_keywords=None,
    notify_students=False,
    klass=None,
    teacher_user=None,
    max_score=100.0,
    external_url=None,
    classroom_notes=None,
):
    assessment = Assessment(
        title=title,
        description=description,
        activity_type=evaluation_type,
        submission_mode=submission_mode,
        subject_name=subject_name,
        marking_period=marking_period,
        academic_year_id=active_year.id,
        teacher_id=teacher_profile.id if teacher_profile else None,
        klass_id=klass_id,
        file_name=task_file_name,
        max_score=max_score if max_score is not None else 100.0,
        date=date.today().strftime('%Y-%m-%d'),
        due_date=due_date,
        scan_keywords=scan_keywords,
        external_url=external_url,
        classroom_notes=classroom_notes,
    )
    db.session.add(assessment)
    if notify_students and klass and teacher_user:
        notify_class_new_activity(
            klass, teacher_user, title, subject_name, marking_period, description, due_date
        )
    return assessment


QUICK_ENTRY_DESC_MARKER = '[auto:quick_entry]'


def is_quick_entry_assessment(assessment):
    """True for auto-created assessments used by direct grade entry (no manual setup)."""
    if not assessment:
        return False
    desc = (assessment.description or '').strip()
    return desc.startswith(QUICK_ENTRY_DESC_MARKER)


def quick_entry_assessment_title(subject_name, marking_period):
    return f'Quick Entry — {subject_name} — {grading_period_label(marking_period)}'


def find_quick_entry_assessment(class_id, subject_name, marking_period, academic_year_id):
    """Return the implicit quick-entry assessment for class/subject/period, if any."""
    if not class_id or not subject_name or marking_period not in range(1, 9):
        return None
    candidates = Assessment.query.filter_by(
        klass_id=class_id,
        subject_name=subject_name,
        marking_period=marking_period,
        academic_year_id=academic_year_id,
        submission_mode='in_class',
    ).all()
    for assessment in candidates:
        if is_quick_entry_assessment(assessment):
            return assessment
    return None


def get_or_create_quick_entry_assessment(
    class_id, subject_name, marking_period, active_year, teacher_profile
):
    """Get or auto-create the implicit assessment backing direct grade entry."""
    existing = find_quick_entry_assessment(
        class_id, subject_name, marking_period, active_year.id
    )
    if existing:
        return existing
    return create_assessment_record(
        title=quick_entry_assessment_title(subject_name, marking_period),
        description=f'{QUICK_ENTRY_DESC_MARKER} Auto-created for direct activity grade entry.',
        evaluation_type='Class Work',
        submission_mode='in_class',
        subject_name=subject_name,
        marking_period=marking_period,
        active_year=active_year,
        teacher_profile=teacher_profile,
        klass_id=class_id,
    )


def get_students_for_class_ids(class_ids, academic_year_id=None, *, viewing_archived=False):
    """Return unique year-scoped Student rows for the given class ids."""
    if not class_ids:
        return []

    display_year = (
        db.session.get(AcademicYear, academic_year_id)
        if academic_year_id is not None else None
    )
    students_map = {}
    if not display_year:
        active = get_active_academic_year()
        display_year = active
    if not display_year:
        return []

    class_rows = {
        klass.id: klass
        for klass in Class.query.filter(Class.id.in_(class_ids)).all()
    }
    if not class_rows:
        return []

    if viewing_archived:
        year_id = display_year.id
        grade_ids = {
            row[0] for row in db.session.query(Grade.student_id).filter(
                Grade.academic_year_id == year_id,
                Grade.class_id.in_(class_ids),
                Grade.student_id.isnot(None),
            ).distinct()
        }
        enroll_ids = {
            row[0] for row in db.session.query(Enrollment.student_id).filter(
                Enrollment.academic_year_id == year_id,
                Enrollment.class_id.in_(class_ids),
                Enrollment.student_id.isnot(None),
            ).distinct()
        }
        live_ids = {
            row[0] for row in db.session.query(Student.id).filter(
                Student.academic_year_id == year_id,
                Student.klass_id.in_(class_ids),
            )
        }
        ids = grade_ids | enroll_ids | live_ids
        if not ids:
            return []
        return (
            Student.query.filter(Student.id.in_(ids))
            .order_by(Student.last_name.asc(), Student.first_name.asc())
            .all()
        )

    roster = (
        students_for_academic_year(display_year.id, registered_only=True)
        .filter(Student.klass_id.in_(class_ids))
        .filter(~Student.status.in_(list(ALUMNI_STATUSES)))
        .order_by(Student.last_name.asc(), Student.first_name.asc())
        .all()
    )
    for student in roster:
        klass = class_rows.get(student.klass_id)
        if not klass:
            continue
        if klass.grade_level is not None:
            level = _student_grade_level(student)
            if level is not None and not _grades_match(level, klass.grade_level):
                continue
        students_map[student.id] = student
    return sorted(students_map.values(), key=lambda s: (s.last_name or '', s.first_name or ''))


# Single source of truth — see constants.GRADING_PERIODS
MOE_GRADING_PERIODS = GRADING_PERIODS


def get_teacher_subjects_for_class(teacher_profile, class_id):
    """Subjects this teacher is allocated to teach in the given class."""
    if not teacher_profile or not class_id:
        return []
    subjects = {
        alloc.subject_name
        for alloc in ClassSubjectTeacher.query.filter_by(
            teacher_id=teacher_profile.id,
            class_id=class_id,
        ).all()
        if alloc.subject_name
    }
    return sorted(subjects, key=str.lower)


def official_subjects_for_class(klass):
    """Official report-card subjects for a class's school division."""
    if not klass:
        return []
    catalog = list(division_subjects(resolve_from_class(klass)) or ())
    if catalog:
        return catalog
    return list(_stream_preset_for_class(klass) or [])


def list_classes_grouped():
    """All classrooms in Kindergarten → Senior High order for admin pickers."""
    classes = sorted(Class.query.all(), key=class_sort_key_from_klass)
    return classes, group_classes(classes)


def list_assignable_registration_classes():
    """Class folders a registrar can assign a new student to.

    Class rows are school-wide (not per academic year). Roster search and a
    missing active year must not yield an empty Target Class picker when
    classes exist in the database.
    """
    return sorted(Class.query.all(), key=class_sort_key_from_klass)


def registration_class_select_groups(classes=None):
    """Grouped Target Class dropdown options as template-safe dicts.

    Uses the key ``options`` (not ``classes``) so Jinja ``group.classes``
    cannot collide with the registrar dashboard's ``classes`` context
    variable or resolve to an empty search-filtered list.
    """
    rows = list(classes) if classes is not None else list_assignable_registration_classes()
    groups = []
    for group in group_classes(rows):
        groups.append({
            'key': group['key'],
            'label': group['label'],
            'options': [
                {
                    'id': klass.id,
                    'name': klass.name,
                    'division_label': group['label'],
                }
                for klass in (group.get('classes') or [])
            ],
        })
    return groups


def ensure_class_official_subjects(klass, *, commit=False):
    """Seed ClassSubject rows from the division catalog when a class has none."""
    if not klass:
        return 0
    existing = ClassSubject.query.filter_by(class_id=klass.id).count()
    if existing:
        return 0
    added = 0
    for name in official_subjects_for_class(klass):
        db.session.add(ClassSubject(class_id=klass.id, subject_name=name))
        added += 1
    if added and commit:
        db.session.commit()
    return added


def get_class_subject_catalog(class_id):
    """All subject names configured for a class (catalog + teacher allocations)."""
    if not class_id:
        return []
    subjects = set()
    for row in ClassSubject.query.filter_by(class_id=class_id).all():
        if row.subject_name:
            subjects.add(row.subject_name)
    for row in ClassSubjectTeacher.query.filter_by(class_id=class_id).all():
        if row.subject_name:
            subjects.add(row.subject_name)
    if not subjects:
        klass = db.session.get(Class, class_id)
        subjects.update(official_subjects_for_class(klass))
    return sorted(subjects, key=str.lower)


def get_assignable_subjects_for_class(teacher_profile, user, class_id):
    """Subjects a teacher may use when assigning activities in a class."""
    allocated = get_teacher_subjects_for_class(teacher_profile, class_id)
    if allocated:
        return allocated
    if not teacher_can_access_class(teacher_profile, user, class_id):
        return []
    return get_class_subject_catalog(class_id)


SPONSOR_RESPONSIBILITIES = [
    {'icon': 'bi-calendar-check', 'title': 'Daily Attendance', 'detail': 'Mark present, late, or absent and track punctuality.'},
    {'icon': 'bi-heart-pulse', 'title': 'Student Welfare', 'detail': 'Log pastoral notes, concerns, and follow-ups.'},
    {'icon': 'bi-telephone', 'title': 'Parent Liaison', 'detail': 'Primary contact for guardians on class matters.'},
    {'icon': 'bi-shield-exclamation', 'title': 'Conduct Monitoring', 'detail': 'Record incidents and refer serious cases to the Dean.'},
    {'icon': 'bi-megaphone', 'title': 'Class Communication', 'detail': 'Post reminders and notices for your class.'},
    {'icon': 'bi-graph-up', 'title': 'Academic Oversight', 'detail': 'Monitor MoE standings, tasks, and report cards.'},
    {'icon': 'bi-cash-coin', 'title': 'Fee Awareness', 'detail': 'View tuition status — payments are handled by Business.'},
    {'icon': 'bi-clipboard-check', 'title': 'Period Grades', 'detail': 'Enter MoE period grades and publish to report cards.'},
]


def teacher_is_class_sponsor(teacher_profile, user, class_id):
    """True when this teacher is the assigned class sponsor or homeroom teacher."""
    if not teacher_profile or not class_id:
        return False
    klass = db.session.get(Class, class_id)
    if not klass:
        return False
    if user and klass.sponsor_id == user.id:
        return True
    return klass.teacher_id == teacher_profile.id


def _sponsor_hub_redirect(class_id, **kwargs):
    params = {k: v for k, v in kwargs.items() if v is not None}
    return redirect(url_for('sponsor_class_hub', class_id=class_id, **params))


def _student_attendance_rate(student, days=30, academic_year_id=None):
    """Return attendance percentage over the last N calendar days."""
    if not student:
        return None
    today = date.today()
    start = today - timedelta(days=days - 1)
    year_id = academic_year_id if academic_year_id is not None else _attendance_year_id()
    records = []
    for row in student.attendance_ledger.all():
        if not row.date:
            continue
        if year_id and row.academic_year_id not in (year_id, None):
            continue
        try:
            row_date = datetime.strptime(row.date, '%Y-%m-%d').date()
        except ValueError:
            continue
        if start <= row_date <= today:
            records.append(row)
    if not records:
        return None
    present = sum(1 for r in records if (r.status or '').lower() in ATTENDANCE_PRESENT_STATUSES)
    return round(present / len(records) * 100, 1)


def _student_period_average(student, academic_year):
    if not student or not academic_year:
        return None
    grades = Grade.query.filter_by(
        student_id=student.id,
        academic_year_id=academic_year.id,
        submitted=True,
    ).all()
    scores = [g.score for g in grades if g.score is not None]
    if not scores:
        draft = Grade.query.filter_by(
            student_id=student.id,
            academic_year_id=academic_year.id,
            submitted=False,
        ).all()
        scores = [g.score for g in draft if g.score is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def build_sponsor_hub_context(teacher_profile, user, klass, active_year, attendance_date=None):
    """Assemble sponsor command center data for one class."""
    attendance_date = attendance_date or date.today().strftime('%Y-%m-%d')
    students = get_class_students_for_year(klass.id, active_year) if active_year else []
    student_ids = [s.id for s in students]

    year_id = _attendance_year_id(active_year)
    today_attendance = {}
    if student_ids:
        q = Attendance.query.filter(
            Attendance.student_id.in_(student_ids),
            Attendance.date == attendance_date,
        )
        for row in apply_attendance_year_filter(q, year_id).all():
            today_attendance[row.student_id] = row

    discipline_counts = {}
    if student_ids:
        rows = (
            db.session.query(Discipline.student_id, db.func.count(Discipline.id))
            .filter(Discipline.student_id.in_(student_ids))
            .group_by(Discipline.student_id)
            .all()
        )
        discipline_counts = {sid: cnt for sid, cnt in rows}

    roster = []
    at_risk = 0
    fee_alerts = 0
    for student in students:
        fin = build_student_financials(student, active_year) if active_year else {}
        balance = float(fin.get('tuition_balance', 0) or 0)
        att_rate = _student_attendance_rate(student, academic_year_id=year_id)
        incidents = discipline_counts.get(student.id, 0)
        avg = _student_period_average(student, active_year)
        att_row = today_attendance.get(student.id)
        status = normalize_attendance_status(att_row.status if att_row else 'present')

        flags = []
        if att_rate is not None and att_rate < 75:
            flags.append('Low attendance')
            at_risk += 1
        if incidents >= 2:
            flags.append('Conduct concern')
            at_risk += 1
        if balance > 0:
            flags.append('Fee balance')
            fee_alerts += 1
        if avg is not None and avg < MOE_PASSING_SCORE:
            flags.append('Below MoE 70%')

        roster.append({
            'student': student,
            'attendance_status': status,
            'attendance_rate': att_rate,
            'notes': att_row.notes if att_row else '',
            'is_marked': att_row is not None,
            'incidents': incidents,
            'avg_score': avg,
            'tuition_balance': balance,
            'parent_email': student.parent_email,
            'flags': flags,
        })

    present_today = sum(
        1 for r in roster if r['attendance_status'] in ATTENDANCE_PRESENT_STATUSES
    )
    absent_today = sum(1 for r in roster if r['attendance_status'] == 'absent')
    late_today = sum(1 for r in roster if r['attendance_status'] == 'late')

    recent_incidents = (
        Discipline.query.filter(Discipline.student_id.in_(student_ids))
        .order_by(Discipline.created_at.desc())
        .limit(8)
        .all()
    ) if student_ids else []

    welfare_notes = (
        SponsorWelfareNote.query.filter_by(class_id=klass.id)
        .order_by(SponsorWelfareNote.created_at.desc())
        .limit(10)
        .all()
    )

    class_notices = (
        ClassAnnouncement.query.filter_by(class_id=klass.id)
        .order_by(ClassAnnouncement.created_at.desc())
        .limit(8)
        .all()
    )

    open_tasks = Assessment.query.filter_by(klass_id=klass.id).count() if klass else 0
    is_sponsor = user and klass.sponsor_id == user.id
    is_homeroom = teacher_profile and klass.teacher_id == teacher_profile.id

    return {
        'klass': klass,
        'students': students,
        'roster': roster,
        'attendance_date': attendance_date,
        'today_attendance': today_attendance,
        'kpis': {
            'total_students': len(students),
            'present_today': present_today,
            'absent_today': absent_today,
            'late_today': late_today,
            'at_risk': at_risk,
            'fee_alerts': fee_alerts,
            'open_activities': open_tasks,
        },
        'recent_incidents': recent_incidents,
        'welfare_notes': welfare_notes,
        'class_notices': class_notices,
        'is_sponsor': is_sponsor,
        'is_homeroom': is_homeroom,
        'role_title': 'Class Sponsor' if is_sponsor and not is_homeroom else (
            'Form Teacher' if is_homeroom and not is_sponsor else 'Sponsor & Form Teacher'
        ),
        'responsibilities': SPONSOR_RESPONSIBILITIES,
        'active_year': active_year,
    }


def normalize_grade_period(value):
    """Return an int period (1-8) from stored grade period fields."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 8 else None
    if isinstance(value, float) and value == int(value):
        num = int(value)
        return num if 1 <= num <= 8 else None
    text = str(value).strip().lower()
    if not text:
        return None
    if text.isdigit():
        num = int(text)
        return num if 1 <= num <= 8 else None
    p_match = re.match(r'^p(?:eriod)?[\s.\-]*(\d+)$', text)
    if p_match:
        num = int(p_match.group(1))
        return num if 1 <= num <= 8 else None
    is_exam = 'exam' in text
    is_second = any(token in text for token in (
        '2nd', 'second', 'sem 2', 'sem2', 'semester 2', 'final',
    ))
    is_first = any(token in text for token in (
        '1st', 'first', 'sem 1', 'sem1', 'semester 1',
    ))
    if is_exam:
        if is_second:
            return 8
        if is_first or 'semester' in text:
            return 7
        return 7
    if text.startswith('period'):
        digits = ''.join(ch for ch in text if ch.isdigit())
        if digits:
            num = int(digits)
            return num if 1 <= num <= 8 else None
    return None


def _grade_period_number(grade):
    if grade is None:
        return None
    # Older rows can carry a stale marking_period while the textual period
    # correctly identifies a semester exam. Preserve the explicit exam key.
    period_text = str(getattr(grade, 'period', '') or '').strip()
    if 'exam' in period_text.lower():
        stored = normalize_grade_period(period_text)
        if stored in (7, 8):
            return stored
    if grade.marking_period is not None:
        stored = normalize_grade_period(grade.marking_period)
        if stored is not None:
            return stored
    return normalize_grade_period(grade.period)


def find_grade_record(student_id, subject_name, period, class_id=None, academic_year_id=None):
    """Find an existing grade row for a student/subject/period."""
    query = Grade.query.filter_by(student_id=student_id)
    if academic_year_id is not None:
        query = query.filter_by(academic_year_id=academic_year_id)

    matches = []
    for grade in query.all():
        stored_period = grade.marking_period or normalize_grade_period(grade.period)
        if stored_period != period:
            continue
        stored_subject = grade.subject or grade.subject_name
        if subject_name and stored_subject:
            if subject_match_key(stored_subject) != subject_match_key(subject_name) and not subjects_match(
                stored_subject, subject_name
            ):
                continue
        elif subject_name and not stored_subject:
            continue
        matches.append(grade)

    if class_id is not None:
        for grade in matches:
            if grade.class_id == class_id:
                return grade
    return matches[0] if matches else None


def _grade_matches_period(grade, period):
    """True when a grade row carries data for the requested marking period."""
    if _grade_period_number(grade) == period:
        return True
    if 1 <= period <= 6:
        stored = getattr(grade, f'p{period}', None)
        if stored is not None and int(stored) != 0:
            return True
    return False


def _grade_has_period_data(grade, period):
    """True when a grade row has displayable scores for a period."""
    if _parse_grade_component_scores(grade):
        return True
    if grade.score is not None or grade.ca_score is not None or grade.exam_score is not None:
        return True
    if 1 <= period <= 6:
        stored = getattr(grade, f'p{period}', None)
        if stored is not None and int(stored) != 0:
            return True
    return False


def _period_total_from_grade(grade, period):
    """Best total for a period from a grade row (matches report-card display)."""
    if grade is None:
        return None
    if _grade_period_number(grade) == period and grade.score is not None:
        return grade.score
    if 1 <= period <= 6:
        pval = getattr(grade, f'p{period}', None)
        if pval is not None and int(pval) != 0:
            return float(pval)
    return grade.score


def _standing_dict_from_grade(grade, period):
    if not grade:
        return None
    total = _period_total_from_grade(grade, period)
    if total is None:
        comps = _component_score_map_from_grade(grade)
        if comps:
            total = round(sum(comps.values()), 1)
        else:
            return None
    return {
        'ca_score': grade.ca_score,
        'exam_score': grade.exam_score,
        'total': total,
        'grade_letter': SchoolEngine.get_grade_letter(total),
        'remarks': grade.remarks or SchoolEngine.get_remarks(total),
    }


def _student_period_grade_candidates(student_id, subject_name, period, academic_year_id=None):
    """Grade rows matched by normalized subject and period, with typo fallback."""
    query = Grade.query.filter_by(student_id=student_id)
    if academic_year_id is not None:
        query = query.filter_by(academic_year_id=academic_year_id)

    subject_key = subject_match_key(subject_name) if subject_name else None
    period_matches = []
    for grade in query.order_by(Grade.id.desc()).all():
        if not _grade_matches_period(grade, period):
            continue
        period_matches.append(grade)

    if not subject_key:
        return period_matches

    exact_matches = []
    fuzzy_matches = []
    for grade in period_matches:
        stored_keys = {
            subject_match_key(stored_name)
            for stored_name in (grade.subject_name, grade.subject)
            if stored_name
        }
        stored_keys.discard('')
        if not stored_keys:
            continue
        if subject_key in stored_keys:
            exact_matches.append(grade)
            continue
        similarity = max(
            SequenceMatcher(None, stored_key, subject_key).ratio()
            for stored_key in stored_keys
        )
        if similarity >= 0.88:
            fuzzy_matches.append((similarity, grade))

    if exact_matches:
        return exact_matches
    if not fuzzy_matches:
        return []

    best_similarity = max(similarity for similarity, _grade in fuzzy_matches)
    return [
        grade
        for similarity, grade in fuzzy_matches
        if best_similarity - similarity < 0.02
    ]


def find_student_period_grade_pair(student_id, subject_name, period, academic_year_id=None, class_id=None):
    """Return the latest unpublished and published rows for a dashboard cell."""
    matches = _student_period_grade_candidates(
        student_id, subject_name, period, academic_year_id,
    )
    if not matches:
        return None, None

    if class_id is not None:
        class_matches = [g for g in matches if g.class_id == class_id]
        if class_matches:
            matches = class_matches

    exact = [g for g in matches if _grade_period_number(g) == period]
    pool = exact or matches

    published = next(
        (g for g in pool if g.submitted and _grade_has_period_data(g, period)),
        None,
    )
    draft = next(
        (g for g in pool if not g.submitted and _grade_has_period_data(g, period)),
        None,
    )
    return draft, published


def _float_or_none(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _visible_submission_score(submission):
    """Show a teacher-entered mark even if the graded flag was not set."""
    if not submission:
        return None
    return _float_or_none(submission.score)


def _component_key_for_assessment(assessment):
    """Map TEST — Test / ATT — Attendance style activities onto period codes."""
    if not assessment:
        return None
    title = (assessment.title or '').strip().upper()
    type_label = (assessment.activity_type or '').strip()
    for key, code, label, _max_score in PERIOD_COMPONENT_SPECS:
        prefix = (code or '').upper()
        if not prefix:
            continue
        if (
            title == prefix
            or title.startswith(prefix + ' ')
            or title.startswith(prefix + '—')
            or title.startswith(prefix + '–')
            or title.startswith(prefix + '-')
        ):
            return key
        if label and label.upper() in title:
            return key
    type_keys = {}
    for key, activity_type in PERIOD_COMPONENT_ACTIVITY_TYPES.items():
        type_keys.setdefault(activity_type, []).append(key)
    keys = type_keys.get(type_label)
    if keys and len(keys) == 1:
        return keys[0]
    return None


def _component_score_map_from_grade(grade):
    comps = _parse_grade_component_scores(grade) if grade else {}
    mapped = {}
    for key in PERIOD_COMPONENT_MAXIMA:
        score = _float_or_none(comps.get(key))
        if score is not None:
            mapped[key] = score
    return mapped


def _component_score_maps_for_student(student, display_year):
    maps = {}
    if not student or not display_year:
        return maps
    grades = Grade.query.filter_by(
        student_id=student.id,
        academic_year_id=display_year.id,
    ).all()
    for grade in grades:
        period = grade.marking_period or normalize_grade_period(grade.period)
        subject_key = subject_match_key(grade.subject or grade.subject_name)
        scores = _component_score_map_from_grade(grade)
        if subject_key and period and scores:
            maps[(subject_key, period)] = scores
    return maps


def _annotate_activity_item(item, component_map=None):
    """Fill score/status from the submission or matching period component."""
    assessment = item.get('assessment')
    submission = item.get('submission')
    visible = _visible_submission_score(submission)
    max_score = (assessment.max_score if assessment and assessment.max_score else 100)
    key = _component_key_for_assessment(assessment)
    if visible is None and key and component_map and component_map.get(key) is not None:
        visible = component_map[key]
        max_score = PERIOD_COMPONENT_MAXIMA.get(key, max_score)
    item['score'] = visible
    item['max_score'] = max_score
    if visible is not None:
        item['status'] = 'Graded'
    elif submission:
        item['status'] = 'Submitted'
    elif not item.get('status'):
        item['status'] = 'Open'
    return item


def _standing_from_activity_scores(rows):
    total_row = next(
        (row for row in rows if row.get('key') == 'total' and row.get('score') is not None),
        None,
    )
    if total_row:
        total = total_row['score']
    else:
        parts = [row['score'] for row in rows if row.get('key') != 'total' and row.get('score') is not None]
        if not parts:
            return None
        total = round(sum(parts), 1)
    return {
        'ca_score': total,
        'exam_score': 0.0,
        'total': total,
        'grade_letter': SchoolEngine.get_grade_letter(total),
        'remarks': SchoolEngine.get_remarks(total),
    }


def build_student_period_activity_scores(grade, period, assessment_items=None):
    """ATT–TEST rows from gradebook components and/or graded class activities."""
    comps = _component_score_map_from_grade(grade)
    from_assessments = {}
    for item in assessment_items or []:
        assessment = item.get('assessment') if isinstance(item, dict) else None
        if not assessment:
            continue
        key = _component_key_for_assessment(assessment)
        score = item.get('score')
        if score is None:
            score = _visible_submission_score(item.get('submission'))
        if key and score is not None and key not in comps:
            from_assessments[key] = score

    rows = []
    for key, code, label, max_score in PERIOD_COMPONENT_SPECS:
        score = comps.get(key)
        if score is None:
            score = from_assessments.get(key)
        rows.append({
            'key': key,
            'code': code,
            'name': label,
            'max_score': max_score,
            'score': score,
        })

    total = _period_total_from_grade(grade, period) if grade else None
    if total is None:
        parts = [row['score'] for row in rows if row['score'] is not None]
        if parts:
            total = round(sum(parts), 1)
    if total is not None:
        rows.append({
            'key': 'total',
            'code': 'TOT',
            'name': 'Period Total',
            'max_score': 100.0,
            'score': total,
        })
    return rows


def canonicalize_student_subject_names(student, display_year, raw_names):
    """Deduplicate subject pills using the division catalog."""
    if not raw_names:
        return []
    year_id = display_year.id if display_year else None
    klass = get_student_class_for_year(student, year_id) if student else None
    division_key = resolve_from_class(
        klass,
        getattr(student, 'level', None) if student else None,
        getattr(student, 'grade_level', None) if student else None,
    )
    return order_subjects_by_catalog(list(raw_names), division_key, keep_unknown=True)


MOE_ACTIVITY_TYPES = ['Assignment', 'Class Work', 'Quiz', 'Test', 'Exam']

STREAM_SUBJECT_PRESETS = {
    'science': [
        'Mathematics', 'English', 'Biology', 'Chemistry', 'Physics',
        'Geography', 'History', 'French', 'Physical Education', 'Computer Science',
    ],
    'arts': [
        'Mathematics', 'English', 'Literature', 'History', 'Geography',
        'Economics', 'French', 'Religious Education', 'Physical Education', 'Art',
    ],
    'commercial': [
        'Mathematics', 'English', 'Accounting', 'Economics', 'Business Studies',
        'Geography', 'History', 'French', 'Physical Education', 'Computer Science',
    ],
    'general': [
        'Mathematics', 'English', 'Science', 'Social Studies', 'Geography',
        'History', 'French', 'Physical Education', 'Religious Education', 'Computer Science',
    ],
}

MOE_PASSING_SCORE = int(os.environ.get('PROMOTION_PASS_SCORE', '70'))


def promotion_pass_score():
    """Configurable MoE promotion average threshold (default 70%)."""
    try:
        return int(current_app.config.get('PROMOTION_PASS_SCORE', MOE_PASSING_SCORE))
    except RuntimeError:
        return MOE_PASSING_SCORE


def max_failing_subjects_for_promotion():
    """Failing YRLY AVE count that assigns Summer School (default 2).

    Printed red marks are subject yearly averages below the MoE pass mark.
    Fewer than this (0 or 1) may still promote if the overall yearly average
    also meets the pass mark. Exactly this many → Summer School (retained in
    the current class, not promoted). More than this → Repeat class,
    regardless of overall average.
    """
    try:
        return int(current_app.config.get('MAX_FAILING_SUBJECTS', 2))
    except RuntimeError:
        return 2


def repeat_class_failing_subject_threshold():
    """Failing YRLY AVE count at or above which the student repeats class."""
    return max_failing_subjects_for_promotion() + 1


def _subject_key(name):
    return (name or '').strip().lower()


def subjects_match(left, right):
    """Compare subject names ignoring case, spacing, and catalog aliases."""
    if not left or not right:
        return False
    return subject_match_key(left) == subject_match_key(right)


def find_class_for_student_grade(grade_level, stream=None, old_class_id=None):
    """Return the best Class row for a student's grade tier (optionally matching stream)."""
    if not grade_level:
        return None

    requested_grade_numeric = _parse_grade_level(grade_level)
    requested_grade_key = str(grade_level).strip()
    requested_canon = canonical_grade_value(grade_level)

    def class_matches(klass):
        klass_grade_numeric = _parse_grade_level(klass.grade_level)
        if requested_grade_numeric is not None:
            return klass_grade_numeric == requested_grade_numeric
        klass_canon = canonical_grade_value(klass.grade_level, klass.name)
        if requested_canon and klass_canon:
            return requested_canon == klass_canon
        return klass.grade_level == requested_grade_key

    if old_class_id:
        promotion_map = build_default_promotion_map(Class.query.all())
        target_id = promotion_map.get(old_class_id)
        if isinstance(target_id, int):
            klass = db.session.get(Class, target_id)
            if klass and class_matches(klass):
                return klass

    candidates = [klass for klass in Class.query.order_by(Class.name.asc()).all() if class_matches(klass)]
    if not candidates:
        return None
    if stream:
        for klass in candidates:
            if klass.stream == stream:
                return klass
    return candidates[0]


def record_student_class_enrollment(student, class_id, academic_year_id=None):
    """Persist a year-tagged class enrollment when a student's class assignment changes."""
    if not student or not class_id:
        return
    if academic_year_id is None:
        academic_year_id = student.academic_year_id
    if academic_year_id is None:
        active_year = get_active_academic_year()
        academic_year_id = active_year.id if active_year else None

    query = Enrollment.query.filter_by(student_id=student.id, class_id=class_id)
    if academic_year_id is not None:
        query = query.filter(
            or_(
                Enrollment.academic_year_id == academic_year_id,
                Enrollment.academic_year_id.is_(None),
            )
        )
    exists = query.first()
    if exists:
        if academic_year_id is not None and exists.academic_year_id is None:
            exists.academic_year_id = academic_year_id
        return

    db.session.add(Enrollment(
        student_id=student.id,
        class_id=class_id,
        academic_year_id=academic_year_id,
    ))


def get_active_academic_year():
    """Single source of truth for the institution's operating academic year.

    Prefers the row flagged ``is_active=True``. When none is flagged, falls back
    to the latest year whose end date has not passed, then the latest by start.
    Cached once per request so dashboards do not re-query the years table.
    """
    if has_app_context() and hasattr(g, '_flpa_active_year'):
        return g._flpa_active_year

    explicit = (
        AcademicYear.query.filter_by(is_active=True)
        .order_by(AcademicYear.start_date.desc())
        .first()
    )
    year = explicit
    if year is None:
        today = datetime.now(timezone.utc).date()
        year = (
            AcademicYear.query.filter(
                or_(AcademicYear.end_date.is_(None), AcademicYear.end_date >= today)
            )
            .order_by(AcademicYear.start_date.desc())
            .first()
        )
    if year is None:
        year = AcademicYear.query.order_by(AcademicYear.start_date.desc()).first()
    if has_app_context():
        g._flpa_active_year = year
    return year


def resolve_teacher_attendance_year():
    """Academic year for teacher daily attendance — always the active session."""
    return get_active_academic_year()


def _attendance_year_id(academic_year=None):
    """Resolve an academic year id for attendance persistence and filtering."""
    if academic_year is not None:
        return academic_year.id if hasattr(academic_year, 'id') else academic_year
    active = get_active_academic_year()
    return active.id if active else None


def apply_attendance_year_filter(query, academic_year_id):
    """Limit attendance rows to one academic-year folder only."""
    if not academic_year_id:
        return query
    return query.filter(Attendance.academic_year_id == academic_year_id)


def _set_active_academic_year(year):
    """Mark one academic year active and deactivate all others."""
    db.session.execute(
        db.update(AcademicYear)
        .where(AcademicYear.id != year.id)
        .values(is_active=False)
    )
    year.is_active = True
    if has_app_context() and hasattr(g, '_flpa_active_year'):
        delattr(g, '_flpa_active_year')
    if has_request_context() and hasattr(g, '_flpa_all_years'):
        delattr(g, '_flpa_all_years')


def _active_academic_year():
    """Return the institution's active academic year, if configured."""
    return get_active_academic_year()


def _is_current_academic_year(academic_year_id):
    """True when the year is unset or matches the active academic year."""
    if academic_year_id is None:
        return True
    active_year = _active_academic_year()
    return bool(active_year and academic_year_id == active_year.id)


def _infer_student_grade_for_year(student, academic_year_id):
    """Estimate a student's grade tier in a past year from the active-year level."""
    current_grade = _student_grade_level(student)
    if not current_grade or not academic_year_id:
        return current_grade

    active_year = _active_academic_year()
    if not active_year:
        return None

    if academic_year_id == active_year.id:
        return current_grade

    current_grade_numeric = _parse_grade_level(current_grade)
    if current_grade_numeric is None:
        return None

    target_year = db.session.get(AcademicYear, academic_year_id)
    if not target_year:
        return None

    years_ordered = AcademicYear.query.order_by(AcademicYear.start_date.asc()).all()
    year_index = {year.id: index for index, year in enumerate(years_ordered)}
    active_idx = year_index.get(active_year.id)
    target_idx = year_index.get(academic_year_id)
    if active_idx is None or target_idx is None:
        return None

    inferred = current_grade_numeric - (active_idx - target_idx)
    if 1 <= inferred <= 12:
        return inferred
    return None


def _student_grade_level_for_year(student, academic_year_id=None):
    """Grade tier for display in a specific academic year."""
    if not student:
        return None

    klass = get_student_class_for_year(student, academic_year_id)
    if klass and klass.grade_level is not None:
        return klass.grade_level

    if academic_year_id:
        grade_row = (
            Grade.query.filter_by(student_id=student.id, academic_year_id=academic_year_id)
            .filter(Grade.class_id.isnot(None))
            .order_by(Grade.id.desc())
            .first()
        )
        if grade_row and grade_row.class_id:
            row_klass = db.session.get(Class, grade_row.class_id)
            if row_klass and row_klass.grade_level is not None:
                return row_klass.grade_level

    if _is_current_academic_year(academic_year_id):
        return _student_grade_level(student)

    return _infer_student_grade_for_year(student, academic_year_id)


def _class_id_from_year_grades(student_id, academic_year_id):
    """Most recent class_id recorded on grade rows for a student/year."""
    grade_row = (
        Grade.query.filter_by(student_id=student_id, academic_year_id=academic_year_id)
        .filter(Grade.class_id.isnot(None))
        .order_by(Grade.id.desc())
        .first()
    )
    return grade_row.class_id if grade_row else None


def _class_id_from_year_enrollment(student_id, academic_year_id):
    """Enrollment class for a student in the requested academic year."""
    try:
        if academic_year_id:
            year_enrollment = (
                Enrollment.query.filter_by(
                    student_id=student_id,
                    academic_year_id=academic_year_id,
                )
                .order_by(Enrollment.id.desc())
                .first()
            )
            if year_enrollment and year_enrollment.class_id:
                return year_enrollment.class_id

        for enrollment in (
            Enrollment.query.filter_by(student_id=student_id)
            .order_by(Enrollment.id.desc())
            .all()
        ):
            if not enrollment.class_id:
                continue
            has_year_grades = Grade.query.filter_by(
                student_id=student_id,
                academic_year_id=academic_year_id,
                class_id=enrollment.class_id,
            ).first()
            if has_year_grades:
                return enrollment.class_id
    except Exception:
        pass
    return None


def get_student_class_for_year(student, academic_year_id=None):
    """
    Resolve the Class row for a student in a specific academic year.
    Active year uses live klass_id/sync; past years use grade/enrollment history.
    """
    if not student:
        return None

    year_id = academic_year_id
    is_current = _is_current_academic_year(year_id)

    if is_current:
        if student.klass_id:
            klass = student.assigned_class or db.session.get(Class, student.klass_id)
            student_grade = _student_grade_level(student)
            if klass and (
                student_grade is None
                or _grades_match(klass.grade_level, student_grade)
            ):
                return klass

        grade = _student_grade_level(student)
        if grade:
            old_klass = None
            if student.klass_id:
                old_klass = student.assigned_class or db.session.get(Class, student.klass_id)
            matched = find_class_for_student_grade(
                grade,
                stream=old_klass.stream if old_klass else None,
                old_class_id=student.klass_id,
            )
            if matched:
                return matched
        return None

    if not year_id:
        return None

    class_id = _class_id_from_year_grades(student.id, year_id)
    if class_id:
        return db.session.get(Class, class_id)

    class_id = _class_id_from_year_enrollment(student.id, year_id)
    if class_id:
        return db.session.get(Class, class_id)

    if student.academic_year_id == year_id and student.klass_id:
        klass = student.assigned_class or db.session.get(Class, student.klass_id)
        if klass:
            return klass

    inferred_grade = _infer_student_grade_for_year(student, year_id)
    if inferred_grade:
        stream = None
        historical = _class_id_from_year_grades(student.id, year_id)
        if historical:
            hist_klass = db.session.get(Class, historical)
            stream = hist_klass.stream if hist_klass else None
        elif student.klass_id:
            current_klass = student.assigned_class or db.session.get(Class, student.klass_id)
            stream = current_klass.stream if current_klass else None
        matched = find_class_for_student_grade(
            inferred_grade,
            stream=stream,
            old_class_id=student.klass_id,
        )
        if matched:
            return matched

    return None


def resolve_student_class_id(student, academic_year_id=None):
    """Resolve class ID for a student in a specific academic year context."""
    klass = get_student_class_for_year(student, academic_year_id)
    return klass.id if klass else None


def resolve_student_class(student, academic_year_id=None):
    """Return the Class object for a student in the given academic year context."""
    return get_student_class_for_year(student, academic_year_id)


def format_student_class_name(student, academic_year_id=None):
    """Display label for a student's class in a given academic year."""
    klass = get_student_class_for_year(student, academic_year_id)
    if klass:
        label = klass.name
        if klass.stream:
            label = f"{label} ({klass.stream})"
        return label

    is_current = _is_current_academic_year(academic_year_id)
    grade = _student_grade_level_for_year(student, academic_year_id)
    if grade:
        if is_current:
            return f"Grade {grade} — Class Pending"
        return f"Grade {grade} — Unrecorded"
    return "Not Assigned"


def sync_student_class_assignment(student, *, commit=False):
    """
    Repair stale klass_id after promotion rollover.
    Aligns klass_id with grade_level and the active academic year when needed.
    """
    if not student or student_is_alumni(student):
        return False

    status = (student.status or '').upper()
    if status in ('SUMMER_SCHOOL', 'REPEAT', 'FAILED'):
        return False

    changed = False
    grade = _student_grade_level(student)

    if grade is None:
        if changed and commit:
            db.session.commit()
        return changed

    current_klass = None
    if student.klass_id:
        current_klass = student.assigned_class or db.session.get(Class, student.klass_id)

    klass_grade = current_klass.grade_level if current_klass else None
    if current_klass is None or not _grades_match(klass_grade, grade):
        stream = current_klass.stream if current_klass else None
        old_id = student.klass_id
        new_klass = find_class_for_student_grade(grade, stream=stream, old_class_id=old_id)
        if new_klass:
            if student.klass_id != new_klass.id:
                student.klass_id = new_klass.id
                record_student_class_enrollment(
                    student, new_klass.id, academic_year_id=student.academic_year_id,
                )
                changed = True
            if not _grades_match(student.grade_level, new_klass.grade_level):
                student.grade_level = new_klass.grade_level
                changed = True
        elif current_klass and not _grades_match(klass_grade, grade):
            student.klass_id = None
            changed = True

    if changed and commit:
        db.session.commit()
    return changed


def get_student_class_id(student, academic_year_id=None):
    """Resolve the class a student belongs to for the given academic year."""
    return resolve_student_class_id(student, academic_year_id)


def get_class_subjects_for_student(student, academic_year_id=None):
    """Return subject names allocated to the student's class."""
    class_id = get_student_class_id(student, academic_year_id)
    if not student or not class_id:
        return []

    subjects = set()
    for row in ClassSubjectTeacher.query.filter_by(class_id=class_id).all():
        if row.subject_name:
            subjects.add(row.subject_name)
    for row in ClassSubject.query.filter_by(class_id=class_id).all():
        if row.subject_name:
            subjects.add(row.subject_name)
    for assessment in Assessment.query.filter_by(klass_id=class_id).all():
        if assessment.subject_name:
            subjects.add(assessment.subject_name)
    for grade in Grade.query.filter_by(student_id=student.id).all():
        name = grade.subject_name or grade.subject
        if name:
            subjects.add(name)
    if not subjects:
        klass = db.session.get(Class, class_id)
        subjects.update(official_subjects_for_class(klass))
    return sorted(subjects, key=str.lower)


def get_student_assessments(student, display_year):
    """Assessments for the student's class, scoped to the selected academic year."""
    year_id = display_year.id if display_year else None
    class_id = get_student_class_id(student, year_id)
    if not student or not class_id:
        return []
    query = Assessment.query.filter(Assessment.klass_id == class_id)
    if display_year:
        query = query.filter(Assessment.academic_year_id == display_year.id)
    return query.order_by(Assessment.id.desc()).all()


def calculate_ca_from_assessments(student_id, subject_name, marking_period, class_id, academic_year_id):
    """
    Build MoE CA score (0-60) from graded class activities in the same subject/period.
    Each graded activity contributes proportionally; result is scaled to 60.
    """
    assessments = Assessment.query.filter_by(
        klass_id=class_id,
        subject_name=subject_name,
        marking_period=marking_period,
        academic_year_id=academic_year_id,
    ).all()
    ca_assessments = [a for a in assessments if not a.is_exam_component]
    if not ca_assessments:
        return None

    ratios = []
    for assessment in ca_assessments:
        submission = Submission.query.filter_by(
            assessment_id=assessment.id,
            student_id=student_id,
            is_graded=True,
        ).first()
        if not submission or submission.score is None:
            continue
        max_score = assessment.max_score or 100.0
        if max_score <= 0:
            continue
        ratios.append(min(submission.score / max_score, 1.0))

    if not ratios:
        return None
    average_ratio = sum(ratios) / len(ratios)
    return round(average_ratio * 60, 1)


def calculate_exam_from_assessments(student_id, subject_name, marking_period, class_id, academic_year_id):
    """Return exam score (0-40) from graded Exam-type activities, scaled to 40."""
    if not class_id:
        return None
    assessments = Assessment.query.filter_by(
        klass_id=class_id,
        subject_name=subject_name,
        marking_period=marking_period,
        academic_year_id=academic_year_id,
    ).all()
    exam_assessments = [a for a in assessments if a.is_exam_component]
    if not exam_assessments:
        return None

    ratios = []
    for assessment in exam_assessments:
        submission = Submission.query.filter_by(
            assessment_id=assessment.id,
            student_id=student_id,
            is_graded=True,
        ).first()
        if not submission or submission.score is None:
            continue
        max_score = assessment.max_score or 100.0
        if max_score <= 0:
            continue
        ratios.append(min(submission.score / max_score, 1.0))

    if not ratios:
        return None
    return round((sum(ratios) / len(ratios)) * 40, 1)


def sync_draft_period_grade(student, subject_name, marking_period, teacher_id=None, preserve_manual_exam=True):
    """
    Recalculate draft period grade from activity scores.
    Keeps teacher-entered exam unless preserve_manual_exam=False.
    """
    if not student or not subject_name or marking_period not in range(1, 7):
        return None

    active_year = get_active_academic_year()
    if not active_year:
        return None

    student_class_id = get_student_class_id(student)
    ca_score = calculate_ca_from_assessments(
        student.id, subject_name, marking_period, student_class_id, active_year.id
    )
    auto_exam = calculate_exam_from_assessments(
        student.id, subject_name, marking_period, student_class_id, active_year.id
    )

    grade = find_grade_record(
        student.id,
        subject_name,
        marking_period,
        class_id=student_class_id,
        academic_year_id=active_year.id,
    )

    if ca_score is None and auto_exam is None and not grade:
        return None

    if grade and grade.is_finalized:
        return grade

    if not grade:
        grade = Grade(
            student_id=student.id,
            teacher_id=teacher_id,
            class_id=student_class_id,
            academic_year_id=active_year.id,
            subject=subject_name,
            subject_name=subject_name,
            marking_period=marking_period,
            period=marking_period,
            submitted=False,
        )
        db.session.add(grade)

    if teacher_id:
        grade.teacher_id = teacher_id

    if ca_score is not None:
        grade.ca_score = ca_score

    if auto_exam is not None:
        grade.exam_score = auto_exam
    elif not preserve_manual_exam and grade.exam_score is None:
        grade.exam_score = 0.0

    ca_val = grade.ca_score or 0.0
    exam_val = grade.exam_score or 0.0
    total = SchoolEngine.calculate_period_total(ca_val, exam_val)
    if total is not None:
        grade.score = total
        grade.remarks = SchoolEngine.get_remarks(total)
        setattr(grade, f'p{marking_period}', int(round(total)))

    grade.activity_type = 'Period Assessment'
    grade.submitted = False
    db.session.flush()
    return grade


def build_student_academic_portal(student, display_year, selected_subject=None, selected_period=None):
    """Assemble student-facing activity scores and draft/published standings."""
    empty = {
        'subjects': [],
        'selected_subject': None,
        'selected_period': selected_period or 1,
        'activity_scores': [],
        'draft_standing': None,
        'published_standing': None,
        'activity_feed': [],
        'grading_periods': GRADING_PERIODS,
    }
    if not student or not display_year:
        return empty

    if selected_period is None:
        selected_period = 1

    year_id = display_year.id
    class_id = get_student_class_id(student, year_id)
    klass = get_student_class_for_year(student, year_id)
    division_key = resolve_from_class(
        klass,
        getattr(student, 'level', None),
        getattr(student, 'grade_level', None),
    )
    assessments = get_student_assessments(student, display_year)

    raw_subjects = set(get_class_subjects_for_student(student, year_id))
    for assessment in assessments:
        if assessment.subject_name:
            raw_subjects.add(assessment.subject_name)
    for grade in Grade.query.filter_by(student_id=student.id, academic_year_id=year_id).all():
        name = grade.subject_name or grade.subject
        if name:
            raw_subjects.add(name)
    subjects = canonicalize_student_subject_names(student, display_year, raw_subjects)

    if selected_subject:
        for name in subjects:
            if subjects_match(name, selected_subject):
                selected_subject = name
                break
        else:
            selected_subject = canonical_subject_name(selected_subject, division_key) or selected_subject

    if not selected_subject:
        period_assessments = [
            a for a in assessments if (a.marking_period or 1) == selected_period
        ]
        if period_assessments:
            sel_raw = period_assessments[0].subject_name
            for name in subjects:
                if subjects_match(name, sel_raw):
                    selected_subject = name
                    break
            else:
                selected_subject = canonical_subject_name(sel_raw, division_key) or sel_raw
        elif subjects:
            selected_subject = subjects[0]

    filtered_assessments = list(assessments)
    if selected_subject:
        filtered_assessments = [
            a for a in filtered_assessments if subjects_match(a.subject_name, selected_subject)
        ]
    if selected_period:
        filtered_assessments = [
            a for a in filtered_assessments if (a.marking_period or 1) == selected_period
        ]

    activity_feed = []
    for assessment in filtered_assessments:
        submission = Submission.query.filter_by(
            assessment_id=assessment.id,
            student_id=student.id,
        ).first()
        activity_feed.append({
            'assessment': assessment,
            'submission': submission,
            'type_label': assessment.activity_type or 'Assignment',
            'score': _visible_submission_score(submission),
            'max_score': assessment.max_score or 100,
            'status': (
                'Graded' if _visible_submission_score(submission) is not None
                else 'Submitted' if submission
                else 'Open'
            ),
        })

    draft_grade, published_grade = find_student_period_grade_pair(
        student.id,
        selected_subject,
        selected_period,
        academic_year_id=year_id,
        class_id=class_id,
    ) if selected_subject else (None, None)

    score_source = draft_grade or published_grade
    component_map = _component_score_map_from_grade(score_source)
    for item in activity_feed:
        _annotate_activity_item(item, component_map)

    activity_scores = build_student_period_activity_scores(
        score_source, selected_period, activity_feed
    )
    filled_map = {
        row['key']: row['score']
        for row in activity_scores
        if row.get('score') is not None
    }
    for item in activity_feed:
        _annotate_activity_item(item, filled_map)

    draft_standing = (
        _standing_dict_from_grade(draft_grade, selected_period) if draft_grade else None
    )
    published_standing = (
        _standing_dict_from_grade(published_grade, selected_period) if published_grade else None
    )
    if published_standing and not is_grade_package_approved(year_id, class_id, selected_period):
        published_standing = None
    if not draft_standing and not published_standing:
        draft_standing = _standing_from_activity_scores(activity_scores)

    return {
        'subjects': [{'name': name} for name in subjects],
        'selected_subject': selected_subject,
        'selected_period': selected_period,
        'activity_feed': activity_feed,
        'activity_scores': activity_scores,
        'draft_standing': draft_standing,
        'published_standing': published_standing,
        'grading_periods': GRADING_PERIODS,
    }


def official_grade_records(student_id, academic_year_id=None, *, approved_only=False):
    """Grades that may appear on official report cards."""
    query = Grade.query.filter_by(student_id=student_id, submitted=True)
    if academic_year_id:
        query = query.filter_by(academic_year_id=academic_year_id)
    grades = query.all()
    if approved_only:
        grades = [grade for grade in grades if grade_period_is_student_visible(grade)]
    return grades


def _grade_release_period(grade):
    """VPA package key: the school's marking period number (1–6, exam 7/8)."""
    return _grade_period_number(grade)


def _requested_marking_period():
    """Optional single-period view from ?period= (same keys as _grade_period_number)."""
    period = request.args.get('period', type=int)
    if period in range(1, 9):
        return period
    return None


def _requested_semester():
    """Optional semester view from ?semester=1|2."""
    semester = request.args.get('semester', type=int)
    return semester if semester in (1, 2) else None


def _sort_marking_periods(periods):
    order = {num: index for index, (num, _label) in enumerate(GRADING_PERIODS)}
    return sorted(
        (period for period in periods if period in range(1, 9)),
        key=lambda period: (order.get(period, 90 + period), period),
    )


def awaiting_vpa_periods_note(pending_periods):
    """Professional FLPA note when some periods are approved and others are not."""
    labels = [grading_period_label(period) for period in _sort_marking_periods(pending_periods)]
    if not labels:
        return None
    if len(labels) == 1:
        return (
            f'Official scores are shown for periods already approved by the Vice Principal '
            f'for Academics. {labels[0]} is awaiting VPA approval and is not yet released.'
        )
    listed = ', '.join(labels[:-1]) + f', and {labels[-1]}'
    return (
        f'Official scores are shown for periods already approved by the Vice Principal '
        f'for Academics. {listed} are awaiting VPA approval and are not yet released.'
    )


def get_or_create_grade_release(academic_year_id, class_id, period):
    """One approval package per academic year, class, and marking period."""
    if not academic_year_id or not class_id or period not in range(1, 9):
        return None
    release = GradeRelease.query.filter_by(
        academic_year_id=academic_year_id,
        class_id=class_id,
        period=period,
    ).first()
    if release:
        return release
    release = GradeRelease(
        academic_year_id=academic_year_id,
        class_id=class_id,
        period=period,
        status=GradeRelease.STATUS_DRAFT,
    )
    db.session.add(release)
    db.session.flush()
    return release


def class_period_has_submitted_grades(academic_year_id, class_id, period):
    if not academic_year_id or not class_id or period not in range(1, 9):
        return False
    for grade in Grade.query.filter_by(
        class_id=class_id,
        academic_year_id=academic_year_id,
        submitted=True,
    ).all():
        if _grade_release_period(grade) == period:
            return True
    return False


def mark_grade_package_pending_vpa(academic_year_id, class_id, period, actor_id=None):
    """Teacher/principal publish (or republish) — reset to pending VPA approval."""
    release = get_or_create_grade_release(academic_year_id, class_id, period)
    if not release:
        return None
    now = datetime.now(timezone.utc)
    release.status = GradeRelease.STATUS_PENDING_VPA
    release.published_by_id = actor_id or release.published_by_id
    release.published_at = now
    release.approved_by_id = None
    release.approved_at = None
    release.returned_by_id = None
    release.returned_at = None
    return release


def reconcile_grade_package_after_save(
    academic_year_id, class_id, period, *, published, actor_id=None,
):
    """Keep the class/period release in sync after a teacher or principal save."""
    if published:
        return mark_grade_package_pending_vpa(
            academic_year_id, class_id, period, actor_id=actor_id,
        )
    release = GradeRelease.query.filter_by(
        academic_year_id=academic_year_id,
        class_id=class_id,
        period=period,
    ).first()
    if not release:
        return None
    if not class_period_has_submitted_grades(academic_year_id, class_id, period):
        release.status = GradeRelease.STATUS_DRAFT
        release.approved_by_id = None
        release.approved_at = None
        return release
    if release.status == GradeRelease.STATUS_APPROVED:
        return mark_grade_package_pending_vpa(
            academic_year_id, class_id, period, actor_id=actor_id,
        )
    return release


def is_grade_package_approved(academic_year_id, class_id, period):
    if not academic_year_id or not class_id or period not in range(1, 9):
        return False
    release = GradeRelease.query.filter_by(
        academic_year_id=academic_year_id,
        class_id=class_id,
        period=period,
    ).first()
    return bool(release and release.status == GradeRelease.STATUS_APPROVED)


def class_submitted_periods(academic_year_id, class_id):
    """Marking periods this class actually ran (has teacher-submitted grades)."""
    if not academic_year_id or not class_id:
        return frozenset()
    cache = None
    if has_request_context():
        cache = getattr(g, '_class_submitted_periods', None)
        if cache is None:
            cache = g._class_submitted_periods = {}
        cached = cache.get((academic_year_id, class_id))
        if cached is not None:
            return cached
    periods = set()
    for grade in Grade.query.filter_by(
        class_id=class_id,
        academic_year_id=academic_year_id,
        submitted=True,
    ).all():
        period = _grade_release_period(grade)
        if period in range(1, 9):
            periods.add(period)
    result = frozenset(periods)
    if cache is not None:
        cache[(academic_year_id, class_id)] = result
    return result


def year_terminal_period(academic_year_id, class_id):
    """The closing package of the year: Exam (Sem 2), else Period 6.

    Returns None while the class has not reached its closing period yet — a class
    that has only submitted Period 1 is mid-year, not finished, so the report card
    must stay sealed.
    """
    ran = class_submitted_periods(academic_year_id, class_id)
    for candidate in YEAR_TERMINAL_PERIODS:
        if candidate in ran:
            return candidate
    return None


def academic_year_is_closed(academic_year_id):
    """An archived year — no longer the active one, so its records are final."""
    year = db.session.get(AcademicYear, academic_year_id) if academic_year_id else None
    return bool(year and not year.is_active)


def semester_is_released(academic_year_id, class_id, semester):
    """A semester sheet needs every period and exam that semester actually ran."""
    ran = class_submitted_periods(academic_year_id, class_id)
    expected = [period for period in SEMESTER_PERIOD_MAP.get(semester, ()) if period in ran]
    if not expected:
        return False
    return all(
        is_grade_package_approved(academic_year_id, class_id, period)
        for period in expected
    )


def report_card_is_released(academic_year_id, class_id):
    """Year-end gate for the cumulative report card.

    Needs the closing package (Exam Sem 2, else Period 6) approved with no
    unapproved periods behind it. A year that has already been closed out
    releases on its approved periods alone, so historical report cards from
    archived years stay available.
    """
    ran = class_submitted_periods(academic_year_id, class_id)
    if not ran:
        return False
    if not all(
        is_grade_package_approved(academic_year_id, class_id, period)
        for period in ran
    ):
        return False
    terminal = year_terminal_period(academic_year_id, class_id)
    if terminal is not None:
        return is_grade_package_approved(academic_year_id, class_id, terminal)
    return academic_year_is_closed(academic_year_id)


def _report_card_blocker_note(year_id, class_id, terminal_period):
    """Plain-language reason the Report Card is not yet issued."""
    ran = class_submitted_periods(year_id, class_id)
    outstanding = _sort_marking_periods([
        period for period in ran
        if not is_grade_package_approved(year_id, class_id, period)
    ])
    if not outstanding:
        if terminal_period is None:
            closing = grading_period_label(YEAR_TERMINAL_PERIODS[0])
            return (
                'The Report Card is issued once the academic year is complete. '
                f'{closing} has not been submitted yet.'
            )
        return (
            f'The Report Card is issued after {grading_period_label(terminal_period)} '
            'is submitted and approved.'
        )
    labels = [grading_period_label(period) for period in outstanding]
    listed = labels[0] if len(labels) == 1 else (
        ', '.join(labels[:-1]) + f', and {labels[-1]}'
    )
    verb = 'is' if len(labels) == 1 else 'are'
    return (
        'The Report Card is issued at the end of the academic year. '
        f'{listed} {verb} still awaiting approval by the Vice Principal for Academics.'
    )


def grade_period_is_student_visible(grade):
    if not grade or not grade.submitted:
        return False
    period = _grade_release_period(grade)
    class_id = grade.class_id
    if not class_id and grade.student_id:
        student = db.session.get(Student, grade.student_id)
        class_id = get_student_class_id(student, grade.academic_year_id) if student else None
    return is_grade_package_approved(grade.academic_year_id, class_id, period)


def student_official_documents_state(student, year_id, period=None):
    """Whether official report card / grade sheet may be shown to a student or parent.

    Approval releases one marking period at a time. `unlocked` covers the period
    grade sheets; the semester sheet and the year-end report card sit behind the
    stricter `released_semesters` and `report_card_unlocked` gates.
    """
    empty = {
        'unlocked': False,
        'hold': False,
        'empty': True,
        'status': None,
        'class_id': None,
        'pending_count': 0,
        'approved_count': 0,
        'approved_periods': [],
        'pending_periods': [],
        'awaiting_note': None,
        'view_period': period,
        'report_card_unlocked': False,
        'released_semesters': [],
        'terminal_period': None,
        'latest_approved_period': None,
        'report_card_blocker_note': None,
    }
    if not student or not year_id:
        return empty

    klass = get_student_class_for_year(student, year_id)
    class_id = klass.id if klass else get_student_class_id(student, year_id)
    submitted = official_grade_records(student.id, year_id)
    if not submitted:
        return {**empty, 'class_id': class_id}

    periods = set()
    for grade in submitted:
        grade_period = _grade_release_period(grade)
        if grade_period in range(1, 9):
            periods.add(grade_period)
    if not periods:
        return {**empty, 'class_id': class_id, 'empty': True}

    if period in range(1, 9):
        periods = {period} if period in periods else set()
        if not periods:
            return {**empty, 'class_id': class_id, 'empty': True, 'view_period': period}

    pending_periods = []
    approved_periods = []
    returned_count = 0
    for check_period in _sort_marking_periods(periods):
        pkg_class_id = class_id
        sample = next(
            (g for g in submitted if _grade_release_period(g) == check_period and g.class_id),
            None,
        )
        if sample and sample.class_id:
            pkg_class_id = sample.class_id
        if is_grade_package_approved(year_id, pkg_class_id, check_period):
            approved_periods.append(check_period)
            continue
        release = GradeRelease.query.filter_by(
            academic_year_id=year_id, class_id=pkg_class_id, period=check_period,
        ).first()
        if release and release.status == GradeRelease.STATUS_RETURNED:
            returned_count += 1
        pending_periods.append(check_period)

    approved_count = len(approved_periods)
    pending_count = len(pending_periods)
    single_period = period in range(1, 9)
    if single_period:
        unlocked = approved_count > 0
        hold = not unlocked and pending_count > 0
    else:
        unlocked = approved_count > 0
        hold = approved_count == 0 and pending_count > 0
    awaiting_note = awaiting_vpa_periods_note(pending_periods) if unlocked and pending_count else None

    package_class_id = class_id
    sample_any = next((rec for rec in submitted if rec.class_id), None)
    if sample_any and sample_any.class_id:
        package_class_id = sample_any.class_id
    terminal_period = year_terminal_period(year_id, package_class_id)
    report_card_unlocked = report_card_is_released(year_id, package_class_id)
    released_semesters = [
        semester for semester in (1, 2)
        if semester_is_released(year_id, package_class_id, semester)
    ]

    return {
        'unlocked': unlocked,
        'hold': hold,
        'empty': False,
        'status': (
            GradeRelease.STATUS_APPROVED if unlocked and not pending_count
            else GradeRelease.STATUS_RETURNED if returned_count and not approved_count
            else GradeRelease.STATUS_PENDING_VPA if pending_count
            else GradeRelease.STATUS_APPROVED if unlocked
            else None
        ),
        'class_id': class_id,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'approved_periods': approved_periods,
        'pending_periods': pending_periods,
        'awaiting_note': awaiting_note,
        'view_period': period,
        'report_card_unlocked': report_card_unlocked,
        'released_semesters': released_semesters,
        'terminal_period': terminal_period,
        'latest_approved_period': approved_periods[-1] if approved_periods else None,
        'report_card_blocker_note': (
            None if report_card_unlocked
            else _report_card_blocker_note(year_id, package_class_id, terminal_period)
        ),
    }


def _resolve_sheet_scope(doc_state, view_period=None):
    """Pick what the student's grade sheet shows: one period, a semester, or the year.

    Until the year-end report card is released the sheet stays period-scoped, so
    an approval never exposes more than the period it covers. Defaults to the
    most recently approved period when the request does not name one.
    """
    approved_periods = doc_state.get('approved_periods') or []
    if view_period in approved_periods:
        return view_period, None
    semester = _requested_semester()
    if semester in (doc_state.get('released_semesters') or []):
        return None, semester
    if doc_state.get('report_card_unlocked'):
        return None, None
    return doc_state.get('latest_approved_period'), None


def viewer_can_see_unreleased_official_grades():
    """Staff may review internally; students and parents must wait for VPA approval."""
    if not current_user.is_authenticated:
        return False
    return normalize_role(current_user) in STAFF_INTERNAL_GRADE_ROLES


def render_official_grade_hold(
    student, display_year, *, parent_qr_view=False, parent_report_token=None,
    hold_message=None, hold_title=None, hold_meta=None,
):
    return render_template(
        'student/report_hold.html',
        student=student,
        display_year=display_year,
        hold_message=hold_message or STUDENT_GRADE_HOLD_MESSAGE,
        hold_title=hold_title,
        hold_meta=hold_meta,
        parent_qr_view=parent_qr_view,
        parent_report_token=parent_report_token,
        school_print_brand=school_print_brand(),
    )


def official_transcript_is_released(student_id, academic_year_id):
    """True when a student-year approval or a school-wide year release exists."""
    if not academic_year_id:
        return False
    year_wide = TranscriptRelease.query.filter(
        TranscriptRelease.academic_year_id == academic_year_id,
        TranscriptRelease.student_id.is_(None),
        TranscriptRelease.status == TranscriptRelease.STATUS_APPROVED,
    ).first()
    if year_wide:
        return True
    if not student_id:
        return False
    return TranscriptRelease.query.filter_by(
        academic_year_id=academic_year_id,
        student_id=student_id,
        status=TranscriptRelease.STATUS_APPROVED,
    ).first() is not None


def viewer_must_wait_for_transcript_release(student, year_id):
    """Staff printers skip the gate; students and parents wait for administration."""
    if canonical_role(current_user) in OFFICIAL_TRANSCRIPT_STAFF_ROLES:
        return False
    return not official_transcript_is_released(
        getattr(student, 'id', None), year_id,
    )


def render_official_transcript_hold(student, display_year, *, parent_qr_view=False, parent_report_token=None):
    return render_template(
        'student/report_hold.html',
        student=student,
        display_year=display_year,
        hold_page_title='Transcript Not Released',
        hold_title='Official Transcript is not released yet',
        hold_message=STUDENT_TRANSCRIPT_HOLD_MESSAGE,
        hold_meta=(
            'The registrar, VPA, and Principal may still print internally. '
            'Your portal copy unlocks after school administration approves this academic year.'
        ),
        parent_qr_view=parent_qr_view,
        parent_report_token=parent_report_token,
        school_print_brand=school_print_brand(),
    ), 403


def get_or_create_transcript_release(academic_year_id, student_id=None):
    query = TranscriptRelease.query.filter_by(academic_year_id=academic_year_id)
    if student_id is None:
        release = query.filter(TranscriptRelease.student_id.is_(None)).first()
    else:
        release = query.filter_by(student_id=student_id).first()
    if release:
        return release
    release = TranscriptRelease(
        academic_year_id=academic_year_id,
        student_id=student_id,
        status=TranscriptRelease.STATUS_APPROVED,
    )
    db.session.add(release)
    return release


def approve_official_transcript(academic_year_id, student_id=None, user=None, comment=None):
    release = get_or_create_transcript_release(academic_year_id, student_id)
    release.status = TranscriptRelease.STATUS_APPROVED
    release.approved_by_id = getattr(user, 'id', None)
    release.approved_at = datetime.now(timezone.utc)
    if comment:
        release.review_comment = comment
    db.session.commit()
    return release


def count_pending_transcript_releases(display_year):
    """Students in the year still waiting for an Official Transcript release."""
    if not display_year:
        return 0
    if TranscriptRelease.query.filter(
        TranscriptRelease.academic_year_id == display_year.id,
        TranscriptRelease.student_id.is_(None),
        TranscriptRelease.status == TranscriptRelease.STATUS_APPROVED,
    ).first():
        return 0
    student_ids = [
        row[0]
        for row in _students_for_display_year(display_year, history_mode=True)
        .with_entities(Student.id)
        .all()
    ]
    if not student_ids:
        return 0
    approved_ids = {
        row[0]
        for row in TranscriptRelease.query.filter(
            TranscriptRelease.academic_year_id == display_year.id,
            TranscriptRelease.student_id.in_(student_ids),
            TranscriptRelease.status == TranscriptRelease.STATUS_APPROVED,
        ).with_entities(TranscriptRelease.student_id).all()
        if row[0]
    }
    return max(0, len(set(student_ids) - approved_ids) )


def _ordinal_rank(n):
    """1st, 2nd, 3rd, 4th — used on the official rank line."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ''
    if n <= 0:
        return ''
    if 10 <= (n % 100) <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def _competition_ranks(averages_by_id):
    """Map student_id → rank using standard competition ranking (1, 2, 2, 4).

    Highest average is rank 1. Tied averages share a rank; the next rank
    skips ahead by the size of the tie (school-typical 1224, not dense 1223).
    """
    ranked = sorted(
        ((sid, avg) for sid, avg in (averages_by_id or {}).items() if avg is not None),
        key=lambda item: (-item[1], item[0]),
    )
    ranks = {}
    index = 0
    while index < len(ranked):
        avg = ranked[index][1]
        end = index + 1
        while end < len(ranked) and ranked[end][1] == avg:
            end += 1
        rank = index + 1
        for pos in range(index, end):
            ranks[ranked[pos][0]] = rank
        index = end
    return ranks


def _collect_official_period_scores(sub_grades, visible_periods=None):
    """Period cells for one subject, matching the official grade sheet.

    visible_periods=None includes every period (staff / unpublished-visible views).
    When set, only those period numbers are used — the student VPA-approved view.
    """
    def _period_allowed(period_num):
        if visible_periods is None:
            return True
        return period_num in visible_periods

    scores = {}
    for grade in sub_grades or []:
        period_num = _grade_period_number(grade)
        if period_num is None or not _period_allowed(period_num):
            continue
        displayed = display_report_score(getattr(grade, 'score', None))
        if displayed == '' and period_num in (7, 8):
            displayed = display_report_score(getattr(grade, 'exam_score', None))
        if displayed != '' and period_num not in scores:
            scores[period_num] = displayed
    for grade in sub_grades or []:
        for period_num in range(1, 7):
            if period_num in scores or not _period_allowed(period_num):
                continue
            stored = numeric_report_score(getattr(grade, f'p{period_num}', None))
            if stored is not None and stored != 0:
                scores[period_num] = display_report_score(stored)
    return scores


def _sheet_overall_average_from_subjects(subjects):
    """Mean of the yearly averages printed on the grade sheet / report card."""
    yearlies = []
    for subject in subjects or []:
        if not isinstance(subject, dict) or subject.get('is_summary'):
            continue
        yearly = numeric_report_score(subject.get('final_avg') or subject.get('yearly'))
        if yearly is not None:
            yearlies.append(yearly)
    if not yearlies:
        return None
    return round(sum(yearlies) / len(yearlies), 1)


def _sheet_overall_average_from_grades(grades, visible_periods=None, division_key=None):
    """Same overall average as the printed sheet, from raw grade rows."""
    yearlies = _subject_yearly_averages_for_decision(
        grades, visible_periods=visible_periods, division_key=division_key,
    )
    if not yearlies:
        return None
    return round(sum(yearlies) / len(yearlies), 1)


def evaluate_class_rank(
    student,
    year_id,
    *,
    approved_only=False,
    subjects=None,
    visible_periods=None,
    division_key=None,
):
    """Rank this student among classmates in the same klass_id for this year.

    Uses the same yearly average the grade sheet prints (mean of subject
    yearly averages from visible periods). Rank 1 is the highest average.

    Ties use standard competition ranking (1, 2, 2, 4). Students with no
    comparable visible average are omitted from the pool. If this student
    has no scores, returns None so the sheet keeps "—".

    When approved_only is True, unpublished / unapproved periods are excluded
    so rank matches what the student can see on the sheet.
    """
    if not student or not year_id:
        return None

    klass = get_student_class_for_year(student, year_id)
    if not klass:
        # No class assignment — cannot place the student in a ranking pool.
        return None

    display_year = db.session.get(AcademicYear, year_id)
    if not display_year:
        return None

    if approved_only:
        if visible_periods is None:
            release_state = student_official_documents_state(student, year_id)
            visible_periods = set(release_state.get('approved_periods') or [])
        else:
            visible_periods = set(visible_periods)
        if not visible_periods:
            # No VPA-approved periods — same blank averages the sheet prints.
            return None
    else:
        visible_periods = None

    if division_key is None:
        division_key = resolve_from_class(
            klass,
            getattr(student, 'level', None),
            getattr(student, 'grade_level', None),
        )

    viewing_archived = not _is_current_academic_year(year_id)
    roster = list(get_class_students_for_year(
        klass.id, display_year, viewing_archived=viewing_archived,
    ))
    if not any(peer.id == student.id for peer in roster):
        roster.append(student)

    student_ids = [peer.id for peer in roster]
    grades = Grade.query.filter(
        Grade.student_id.in_(student_ids),
        Grade.academic_year_id == year_id,
        Grade.submitted.is_(True),
    ).all()

    by_student = {}
    for grade in grades:
        by_student.setdefault(grade.student_id, []).append(grade)

    averages = {}
    for sid, rows in by_student.items():
        avg = _sheet_overall_average_from_grades(
            rows, visible_periods, division_key,
        )
        if avg is not None:
            averages[sid] = avg

    # Prefer the already-rendered subject rows so this student's average
    # matches the yearly figures printed on the sheet.
    if subjects is not None:
        focus_avg = _sheet_overall_average_from_subjects(subjects)
        if focus_avg is not None:
            averages[student.id] = focus_avg
        elif student.id not in averages:
            return None

    if student.id not in averages:
        return None

    ranks = _competition_ranks(averages)
    rank = ranks.get(student.id)
    if not rank:
        return None
    of = len(averages)
    return {
        'rank': rank,
        'of': of,
        'average': averages[student.id],
        'label': f'{_ordinal_rank(rank)} / {of}',
        'method': 'competition',
    }


def build_report_card_structured_data(
    student, year_id=None, *, approved_only=False, view_period=None, semester=None,
):
    """MoE report-card matrix from published grades for one academic year.

    When approved_only is True, only VPA-approved marking periods appear. Later
    pending periods stay blank and are named in awaiting_vpa_note.

    view_period renders a single approved marking period — no semester or yearly
    averages and no promotion statement, since neither can be computed from one
    period. semester renders one released semester. Neither set is the year-end
    report card.
    """
    empty = {
        'student_name': '',
        'student_id': '',
        'level': '',
        'class_name': '',
        'academic_year': '',
        'subjects': [],
        'legend_rows': division_legend_rows(None),
        'subject_heading': 'SUBJECTS',
        'class_rank': None,
        'scope': 'year',
        'scope_label': None,
        'view_period': None,
        'semester': None,
        'report_card_unlocked': False,
        'report_card_blocker_note': None,
        'grading_periods': GRADING_PERIODS,
    }
    if not student:
        return empty

    display_year = db.session.get(AcademicYear, year_id) if year_id else None
    klass = get_student_class_for_year(student, year_id)
    division_key = resolve_from_class(
        klass,
        getattr(student, 'level', None),
        getattr(student, 'grade_level', None),
    )
    doc_ctx = class_document_context(klass)
    if division_key and division_key != doc_ctx.get('division'):
        doc_ctx = {
            **doc_ctx,
            'division': division_key,
            'division_sheet_title': division_document_titles(division_key, 'sheet'),
            'division_report_title': division_document_titles(division_key, 'report'),
            'subject_heading': division_subject_heading(division_key),
        }

    grades_records = official_grade_records(student.id, year_id, approved_only=approved_only)
    release_state = (
        student_official_documents_state(student, year_id) if student and year_id else None
    )
    approved = set((release_state or {}).get('approved_periods') or [])
    if view_period in range(1, 9):
        scope = 'period'
        cumulative = False
        visible_periods = ({view_period} & approved) if approved_only else {view_period}
        scope_label = grading_period_label(view_period)
    elif semester in (1, 2):
        scope = 'semester'
        cumulative = True
        wanted = set(SEMESTER_PERIOD_MAP[semester])
        visible_periods = (wanted & approved) if approved_only else wanted
        scope_label = f'Semester {semester}'
    else:
        scope = 'year'
        cumulative = True
        visible_periods = approved if approved_only else None
        scope_label = None
    grouped = {}
    first_names = {}
    conduct_grades = []
    for grade in grades_records:
        raw_name = (grade.subject or grade.subject_name or '').strip()
        if not raw_name:
            continue
        # Group by the catalog name when possible so punctuation, abbreviation,
        # and legacy naming variants produce one row (for example Comp.
        # Science, Comp.Science, Computer Science, and ICT).
        official_name = canonical_subject_name(raw_name, division_key)
        key = subject_match_key(official_name or raw_name)
        if not key:
            continue
        if is_report_summary_subject(official_name or raw_name):
            if is_conduct_subject(official_name or raw_name):
                conduct_grades.append(grade)
            continue
        grouped.setdefault(key, []).append(grade)
        first_names.setdefault(key, official_name or raw_name)

    ordered_names = order_subjects_by_catalog(
        list(first_names.values()),
        division_key,
        keep_unknown=True,
    )
    structured_subjects = []
    used_keys = set()

    def _append_subject_row(display_name, sub_grades):
        official_name = canonical_subject_name(display_name, division_key) or display_name
        structured_subjects.append(
            official_subject_score_row(
                official_name,
                _collect_official_period_scores(sub_grades, visible_periods),
                division_key,
                aggregates=cumulative,
            )
        )

    for display_name in ordered_names:
        key = subject_match_key(display_name)
        if not key or key in used_keys:
            continue
        used_keys.add(key)
        _append_subject_row(display_name, grouped.get(key, []))

    for key, sub_grades in grouped.items():
        if key in used_keys:
            continue
        used_keys.add(key)
        _append_subject_row(first_names.get(key, key), sub_grades)

    structured_subjects.extend(
        report_card_footer_rows(
            structured_subjects,
            _collect_official_period_scores(conduct_grades, visible_periods),
            division_key,
            aggregates=cumulative,
        )
    )

    year_label = ''
    if display_year:
        year_label = format_academic_year_label(display_year.name) or display_year.name

    return {
        'student_name': student.full_name,
        'student_id': student.student_id,
        'level': format_student_school_level(student),
        'class_name': format_student_class_name(student, year_id),
        'academic_year': year_label,
        'subjects': structured_subjects,
        'legend_rows': division_legend_rows(division_key),
        'subject_heading': doc_ctx.get('subject_heading') or 'SUBJECTS',
        'division': division_key,
        'division_sheet_title': doc_ctx.get('division_sheet_title'),
        'division_report_title': doc_ctx.get('division_report_title'),
        'school': doc_ctx.get('school'),
        'promotion': evaluate_year_promotion_from_subject_rows(
            structured_subjects, student, academic_year_id=year_id,
        ) if scope == 'year' else None,
        'class_rank': evaluate_class_rank(
            student,
            year_id,
            approved_only=approved_only,
            subjects=structured_subjects,
            visible_periods=visible_periods,
            division_key=division_key,
        ),
        'awaiting_vpa_note': (
            (release_state or {}).get('awaiting_note') if approved_only else None
        ),
        'approved_periods': list((release_state or {}).get('approved_periods') or []),
        'pending_periods': list((release_state or {}).get('pending_periods') or []),
        'scope': scope,
        'scope_label': scope_label,
        'view_period': view_period if scope == 'period' else None,
        'semester': semester if scope == 'semester' else None,
        'report_card_unlocked': bool((release_state or {}).get('report_card_unlocked')),
        'report_card_blocker_note': (release_state or {}).get('report_card_blocker_note'),
        'grading_periods': GRADING_PERIODS,
    }


def build_class_period_grade_sheet_data(class_id, period, year_id, *, approved_only=False):
    """One class, one marking period, every student — the printable class roster.

    Mirrors build_report_card_structured_data's subject matching so the
    figures printed here always agree with each student's own report card.
    """
    empty = {
        'klass': None, 'display_year': None, 'division': None, 'subjects': [],
        'rows': [], 'period_label': grading_period_label(period), 'release': None,
        'school': school_print_brand(),
    }
    klass = db.session.get(Class, class_id) if class_id else None
    display_year = db.session.get(AcademicYear, year_id) if year_id else None
    if not klass or not display_year or period not in range(1, 9):
        return empty

    division_key = resolve_from_class(klass)
    doc_ctx = class_document_context(klass)
    subject_names = order_subjects_by_catalog(
        list(division_subjects(division_key)), division_key, keep_unknown=False,
    )

    roster = get_class_students_for_year(class_id, display_year)
    student_ids = [s.id for s in roster]
    visible_periods = {period} if approved_only else None

    grades = Grade.query.filter(
        Grade.class_id == class_id,
        Grade.academic_year_id == year_id,
        Grade.submitted.is_(True),
        Grade.student_id.in_(student_ids or [0]),
    ).all()

    by_student = {}
    for grade in grades:
        raw_name = (grade.subject or grade.subject_name or '').strip()
        if not raw_name or is_report_summary_subject(raw_name):
            continue
        official_name = canonical_subject_name(raw_name, division_key) or raw_name
        key = subject_match_key(official_name)
        if not key:
            continue
        by_student.setdefault(grade.student_id, {}).setdefault(key, []).append(grade)

    rows = []
    for student in roster:
        subject_scores = by_student.get(student.id, {})
        cells = []
        numeric_values = []
        for name in subject_names:
            key = subject_match_key(name)
            period_scores = _collect_official_period_scores(subject_scores.get(key, []), visible_periods)
            value = period_scores.get(period, '')
            cells.append(value)
            numeric = numeric_report_score(value)
            if numeric is not None:
                numeric_values.append(numeric)
        average = round(sum(numeric_values) / len(numeric_values), 1) if numeric_values else None
        rows.append({
            'student': student,
            'scores': cells,
            'average': average,
        })

    release = GradeRelease.query.filter_by(
        academic_year_id=year_id, class_id=class_id, period=period,
    ).first()

    return {
        'klass': klass,
        'display_year': display_year,
        'division': division_key,
        'division_label': doc_ctx.get('division_label'),
        'school': doc_ctx.get('school'),
        'subjects': subject_names,
        'rows': rows,
        'period_label': grading_period_label(period),
        'release': release,
        'grading_periods': GRADING_PERIODS,
    }


def build_full_activity_record(student, display_year, selected_subject=None, selected_period=None):
    """All graded/open activities for the student activities record view."""
    if not student or not display_year:
        return []

    assessments = get_student_assessments(student, display_year)
    component_maps = _component_score_maps_for_student(student, display_year)
    records = []
    for assessment in assessments:
        if selected_subject and not subjects_match(assessment.subject_name, selected_subject):
            continue
        period_num = assessment.marking_period or 1
        if selected_period and period_num != selected_period:
            continue
        submission = Submission.query.filter_by(
            assessment_id=assessment.id,
            student_id=student.id,
        ).first()
        item = {
            'assessment': assessment,
            'submission': submission,
            'type_label': assessment.activity_type or 'Assignment',
            'period_label': grading_period_label(period_num),
            'score': _visible_submission_score(submission),
            'max_score': assessment.max_score or 100,
            'status': 'Open',
            'submitted_at': submission.submitted_at if submission else None,
            'feedback': submission.teacher_feedback if submission else None,
        }
        cmap = component_maps.get(
            (subject_match_key(assessment.subject_name), period_num),
            {},
        )
        _annotate_activity_item(item, cmap)
        records.append(item)
    return records


def build_student_published_grade_summary(student, display_year):
    """Published period grades for the student grade-sheet summary."""
    if not student or not display_year:
        return []

    grades = official_grade_records(student.id, display_year.id, approved_only=True)
    summary = []
    for grade in sorted(
        grades,
        key=lambda g: (
            (g.subject or '').lower(),
            g.marking_period or normalize_grade_period(g.period) or 0,
        ),
    ):
        period_num = grade.marking_period or normalize_grade_period(grade.period) or 1
        summary.append({
            'subject': grade.subject or grade.subject_name or '—',
            'period': period_num,
            'period_label': grading_period_label(period_num),
            'ca_score': grade.ca_score,
            'exam_score': grade.exam_score,
            'total': grade.score,
            'grade_letter': SchoolEngine.get_grade_letter(grade.score),
            'remarks': grade.remarks,
        })
    return summary


def get_class_period_publish_stats(class_id, subject_name, period, academic_year_id, student_ids=None):
    """Draft vs published counts for a class subject/period."""
    query = Grade.query.filter_by(
        class_id=class_id,
        subject=subject_name,
        academic_year_id=academic_year_id,
    )
    grades = []
    for grade in query.all():
        period_num = grade.marking_period or normalize_grade_period(grade.period)
        if period_num != period:
            continue
        if student_ids is not None and grade.student_id not in student_ids:
            continue
        if not _grade_has_entered_scores(grade):
            continue
        grades.append(grade)

    return {
        'total': len(grades),
        'published': sum(1 for g in grades if g.submitted),
        'draft': sum(1 for g in grades if not g.submitted),
    }


def generate_initial_portal_password(length=8):
    """Readable 8-character password (no ambiguous 0/O/1/l)."""
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    size = max(8, int(length or 8))
    return ''.join(secrets.choice(alphabet) for _ in range(size))


REGISTRAR_CREDENTIAL_SLIP_SESSION_KEY = 'registrar_credential_slip'


def stash_registrar_credential_password(student_id, password):
    """Store the one-time initial password in session (never in the URL)."""
    if not student_id or not password:
        return
    session[REGISTRAR_CREDENTIAL_SLIP_SESSION_KEY] = {
        'student_id': int(student_id),
        'password': password,
    }


def pop_registrar_credential_password(student_id):
    """Read and clear the one-time initial password for this student."""
    payload = session.pop(REGISTRAR_CREDENTIAL_SLIP_SESSION_KEY, None)
    if not isinstance(payload, dict):
        return None
    try:
        stored_id = int(payload.get('student_id'))
    except (TypeError, ValueError):
        return None
    if stored_id != int(student_id):
        return None
    password = payload.get('password')
    return password if password else None


def provision_student_portal_account(student, email, password=None, full_name=None, *, must_change_password=None):
    """
    Create or update the login User for a student and link student.user_id.
    Email is required. New accounts get a secure auto-generated password when
    none is supplied. The plaintext is attached as user._issued_initial_password
    for the registrar credential slip (never persisted).
    """
    if not student:
        return None

    email = (email or '').strip()
    if not email:
        return None

    display_name = (full_name or student.full_name or '').strip() or email
    user = db.session.get(User, student.user_id) if student.user_id else None

    if not user:
        user = User.query.filter(func.lower(User.email) == email.lower()).first()

    if user and user.id != student.user_id:
        existing = Student.query.filter_by(user_id=user.id).first()
        if existing and existing.id != student.id:
            return None

    supplied = (password or '').strip() or None
    issued = None

    if not user:
        issued = supplied or generate_initial_portal_password()
        user = User(
            email=email,
            role='student',
            full_name=display_name,
        )
        user.set_password(issued)
        user.must_change_password = True if must_change_password is None else bool(must_change_password)
        db.session.add(user)
        db.session.flush()
    else:
        user.role = 'student'
        user.full_name = display_name
        if supplied:
            user.set_password(supplied)
            issued = supplied
            user.must_change_password = True if must_change_password is None else bool(must_change_password)

    student.user_id = user.id
    login_username = student.student_id or student.student_id_code
    if login_username:
        username_owner = User.query.filter_by(username=login_username).first()
        if not username_owner or username_owner.id == user.id:
            user.username = login_username
    if student.photo and not user.photo:
        user.photo = student.photo
    user._issued_initial_password = issued
    return user


def get_student_for_user(user, auto_link=True):
    """
    Resolve the Student record for a logged-in user.
    Attempts auto-linking when a student portal account exists without user_id.
    """
    if not user:
        return None

    student = Student.query.filter_by(user_id=user.id).first()
    if student:
        return student

    if getattr(user, 'student_profile', None):
        profile = user.student_profile
        if profile.user_id != user.id:
            profile.user_id = user.id
            db.session.commit()
        return profile

    if not auto_link or (user.role or '').lower() != 'student':
        return None

    email_local = (user.email or '').split('@')[0].lower()
    if email_local:
        id_matches = [
            s for s in Student.query.filter_by(user_id=None).all()
            if s.student_id and s.student_id.lower() == email_local
        ]
        if len(id_matches) == 1:
            id_matches[0].user_id = user.id
            db.session.commit()
            return id_matches[0]

    name_key = (user.full_name or '').strip().lower()
    if name_key:
        matches = [
            s for s in Student.query.filter_by(user_id=None).all()
            if f"{s.first_name} {s.last_name}".strip().lower() == name_key
        ]
        if len(matches) == 1:
            matches[0].user_id = user.id
            db.session.commit()
            return matches[0]

    return None


def repair_restored_active_enrollments(*, commit=True):
    """
    Restore students wrongly marked alumni while still enrolled in the active year.
    Uses year-tagged enrollment rows written during rollover.
    """
    active_year = get_active_academic_year()
    if not active_year:
        return 0

    ended_year = (
        AcademicYear.query.filter(
            AcademicYear.id != active_year.id,
            AcademicYear.is_active.is_(False),
        )
        .order_by(AcademicYear.start_date.desc(), AcademicYear.id.desc())
        .first()
    )

    repaired = 0
    for enrollment in Enrollment.query.all():
        student = db.session.get(Student, enrollment.student_id)
        if not student or not student_is_alumni(student):
            continue
        if enrollment.academic_year_id not in (None, active_year.id):
            continue
        if ended_year and student.academic_year_id not in (active_year.id, ended_year.id, None):
            continue
        klass = db.session.get(Class, enrollment.class_id)
        student.status = 'ACTIVE'
        student.academic_year_id = active_year.id
        student.klass_id = enrollment.class_id
        if klass and klass.grade_level is not None:
            student.grade_level = klass.grade_level
        student.registration_type = 'Returning'
        student.is_promoted = True
        student.is_registered = False
        if enrollment.academic_year_id is None:
            enrollment.academic_year_id = active_year.id
        repaired += 1

    if repaired and commit:
        db.session.commit()
    return repaired


def repair_stale_student_class_assignments(*, commit=True):
    """
    Repair klass_id / academic_year_id drift left by rollover.
    Clears alumni class seats, evicts wrong-year roster bleed, realigns tiers.
    """
    repaired = 0
    repaired += repair_restored_active_enrollments(commit=False)
    active_year = get_active_academic_year()

    if active_year and not active_year.is_active:
        _set_active_academic_year(active_year)
        repaired += 1

    for student in Student.query.filter(
        Student.klass_id.isnot(None),
        Student.status.in_(list(ALUMNI_STATUSES)),
    ).all():
        student.klass_id = None
        repaired += 1

    if active_year:
        for student in Student.query.filter(
            Student.klass_id.isnot(None),
            Student.academic_year_id != active_year.id,
            ~Student.status.in_(list(ALUMNI_STATUSES)),
        ).all():
            student.klass_id = None
            repaired += 1

        for student in Student.query.filter(
            Student.academic_year_id == active_year.id,
            Student.klass_id.is_(None),
            ~Student.status.in_(list(ALUMNI_STATUSES)),
        ).all():
            if sync_student_class_assignment(student):
                repaired += 1

    for student in Student.query.filter(
        ~Student.status.in_(list(ALUMNI_STATUSES)),
    ).all():
        if sync_student_class_assignment(student):
            repaired += 1

    if repaired and commit:
        db.session.commit()
    return repaired


def repair_student_class_assignments():
    """Backward-compatible alias for post-rollover class repair."""
    return repair_stale_student_class_assignments()


def repair_student_portal_links():
    """Link student login accounts to registrar records when a unique match exists."""
    student_users = User.query.filter(func.lower(User.role) == 'student').all()
    repaired = 0
    for user in student_users:
        if Student.query.filter_by(user_id=user.id).first():
            continue
        if get_student_for_user(user, auto_link=True):
            repaired += 1
    return repaired


def link_student_portal_from_form(student, email, password=None, **kwargs):
    """Helper used by registrar registration flows."""
    if not email:
        return None
    return provision_student_portal_account(
        student,
        email,
        password=password,
        full_name=f"{student.first_name} {student.last_name}".strip(),
        **kwargs,
    )


def find_academic_year_by_name(name):
    """Find a year by exact label or equivalent span (hyphen / en-dash / slash / 2-digit)."""
    raw = (name or '').strip()
    if not raw:
        return None
    exact = AcademicYear.query.filter_by(name=raw).first()
    if exact:
        return exact
    normalized = normalize_academic_year_name(raw)
    if normalized and normalized != raw:
        exact = AcademicYear.query.filter_by(name=normalized).first()
        if exact:
            return exact
    key = academic_year_span_key(raw)
    if not key:
        return None
    for year in AcademicYear.query.all():
        if academic_year_span_key(year.name) == key:
            return year
    return None


def _academic_year_id_prefix(academic_year):
    """Build a short stable prefix for auto-generated student IDs."""
    if not academic_year:
        return str(datetime.now(timezone.utc).year)

    year_name = (academic_year.name or '').strip()
    if not year_name:
        return str(academic_year.id)

    span = parse_academic_year_span(year_name)
    if span:
        start_y, end_y = span
        return f'{start_y % 100:02d}{end_y % 100:02d}'

    digits = ''.join(char for char in year_name if char.isdigit())
    return digits[:4] or str(academic_year.id)


def generate_next_student_id(academic_year=None):
    """Generate the next unique student ID (supports 99,999+ students per academic year)."""
    if academic_year is None:
        academic_year = get_active_academic_year()

    prefix = _academic_year_id_prefix(academic_year)
    pattern = f"{prefix}-"
    existing_ids = [
        row[0]
        for row in db.session.query(Student.student_id).filter(Student.student_id.like(f"{pattern}%")).all()
    ]

    max_seq = 0
    for student_id in existing_ids:
        suffix = student_id[len(pattern):]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))

    if existing_ids or not Student.query.count():
        return f"{pattern}{max_seq + 1:05d}"

    legacy_numeric = []
    for (student_id,) in db.session.query(Student.student_id).all():
        if student_id and student_id.isdigit():
            legacy_numeric.append(int(student_id))

    if legacy_numeric:
        return str(max(legacy_numeric) + 1)

    return f"{pattern}00001"


def _same_student_identity(existing_student, form):
    """Return True when the submitted form matches an existing student record."""
    return (
        (existing_student.first_name or '').strip().lower() == (form.first_name.data or '').strip().lower()
        and (existing_student.last_name or '').strip().lower() == (form.last_name.data or '').strip().lower()
        and existing_student.dob == form.dob.data
    )


def student_same_year_fully_enrolled(student, academic_year_id):
    """True when the student is already fully enrolled in the target academic year."""
    if not student or not academic_year_id:
        return False
    if student_is_alumni(student):
        return False
    return (
        student.academic_year_id == academic_year_id
        and student.is_registered
        and student.klass_id is not None
    )


def validate_student_id_for_registration(student_id_value, form, academic_year, *, is_returning=False):
    """
    Validate registrar enrollment student ID.
    Returns (ok, error_message, existing_student, resolved_student_id).
    """
    raw = (student_id_value or '').strip()
    academic_year_id = academic_year.id if academic_year else None

    if not raw:
        if is_returning:
            return False, (
                'Student ID is required for returning registration. '
                'Use Step 1 to search by email or student ID.'
            ), None, None
        resolved = generate_next_student_id(academic_year)
        return True, None, None, resolved

    existing = Student.query.filter_by(student_id=raw).first()
    if not existing:
        return True, None, None, raw

    if is_returning or _same_student_identity(existing, form):
        if student_same_year_fully_enrolled(existing, academic_year_id):
            year_label = academic_year.name if academic_year else 'this academic year'
            return False, (
                f'{existing.full_name} is already fully enrolled for {year_label}. '
                'No duplicate registration is needed.'
            ), existing, raw
        return True, None, existing, raw

    return False, (
        f"Student ID {raw} is already assigned to {existing.full_name}. "
        'Use email or student ID lookup in Step 1 to re-register returning students.'
    ), existing, raw


def compile_student_dashboard_context(student, display_year, request_args=None, active_tab='grades'):
    """Build the full template context for the student dashboard."""
    request_args = request_args or {}
    if hasattr(request_args, 'getlist'):
        selected_subject = request_args.get('subject') or request_args.get('subject_name')
        has_period_param = request_args.get('period') is not None
        raw_period = request_args.get('period', type=int)
    else:
        selected_subject = request_args.get('subject') or request_args.get('subject_name')
        has_period_param = request_args.get('period') is not None
        raw_period = request_args.get('period')
        try:
            raw_period = int(raw_period) if raw_period else None
        except (TypeError, ValueError):
            raw_period = None

    if active_tab == 'activities' and not has_period_param:
        selected_period = None
        portal_period = 1
    else:
        selected_period = raw_period or 1
        portal_period = selected_period

    portal = build_student_academic_portal(
        student,
        display_year,
        selected_subject=selected_subject,
        selected_period=portal_period,
    ) if student and display_year else {
        'subjects': [],
        'selected_subject': None,
        'selected_period': 1,
        'activity_feed': [],
        'draft_standing': None,
        'published_standing': None,
        'grading_periods': GRADING_PERIODS,
    }

    assessments = get_student_assessments(student, display_year) if student and display_year else []
    student_submissions = {}
    if student:
        for sub in Submission.query.filter_by(student_id=student.id).all():
            student_submissions[sub.assessment_id] = sub

    pending_tasks = []
    for assessment in assessments:
        submission = student_submissions.get(assessment.id)
        if submission and submission.is_graded:
            continue
        pending_tasks.append({
            'assessment': assessment,
            'submission': submission,
            'needs_submit': submission is None,
            'needs_grade': submission is not None and not submission.is_graded,
        })

    sel_subject = portal.get('selected_subject')
    sel_period = portal.get('selected_period', 1)
    task_assessments = list(assessments)
    if sel_subject:
        task_assessments = [
            a for a in task_assessments if subjects_match(a.subject_name, sel_subject)
        ]
    if sel_period:
        task_assessments = [
            a for a in task_assessments if (a.marking_period or 1) == sel_period
        ]

    pending_ids = {task['assessment'].id for task in pending_tasks}
    visible_pending = [a for a in task_assessments if a.id in pending_ids]
    if pending_tasks and not visible_pending:
        first_pending = pending_tasks[0]['assessment']
        sel_subject = first_pending.subject_name
        sel_period = first_pending.marking_period or 1
        portal = build_student_academic_portal(
            student,
            display_year,
            selected_subject=sel_subject,
            selected_period=sel_period,
        )
        task_assessments = list(assessments)
        if sel_subject:
            task_assessments = [
                a for a in task_assessments if subjects_match(a.subject_name, sel_subject)
            ]
        if sel_period:
            task_assessments = [
                a for a in task_assessments if (a.marking_period or 1) == sel_period
            ]

    year_id = display_year.id if display_year else None
    klass = get_student_class_for_year(student, year_id) if student else None
    display_grade_level = (
        _student_grade_level_for_year(student, year_id) if student else None
    )
    class_display_name = (
        format_student_class_name(student, year_id) if student else None
    )
    class_is_pending = bool(
        student
        and _is_current_academic_year(year_id)
        and not klass
        and display_grade_level
    )
    financials = build_student_financials(student, display_year) if student else None
    if isinstance(financials, dict):
        financials = type('StudentFinancials', (), financials)()
    fees = []
    if student:
        if hasattr(student, 'payment_records'):
            all_fees = list(student.payment_records.order_by(StudentPayment.paid_on.desc()).all())
        else:
            all_fees = StudentPayment.query.filter_by(student_id=student.id).order_by(
                StudentPayment.paid_on.desc()
            ).all()
        if display_year:
            fees = [p for p in all_fees if p.academic_year_id == display_year.id]

    grades = []
    if student and display_year:
        grades = Grade.query.filter_by(
            student_id=student.id,
            academic_year_id=display_year.id,
        ).all()

    class_notices = []
    resolved_class_id = get_student_class_id(student, year_id) if student else None
    if student and resolved_class_id:
        class_notices = (
            ClassAnnouncement.query.filter_by(class_id=resolved_class_id)
            .order_by(ClassAnnouncement.created_at.desc())
            .limit(6)
            .all()
        )

    official_documents = (
        student_official_documents_state(student, year_id)
        if student and display_year else {
            'unlocked': False, 'hold': False, 'empty': True,
            'report_card_unlocked': False, 'report_card_blocker_note': None,
        }
    )

    return {
        'student': student,
        'display_year': display_year,
        'klass': klass,
        'display_grade_level': display_grade_level,
        'class_display_name': class_display_name,
        'class_is_pending': class_is_pending,
        'grades': grades,
        'financials': financials,
        'fees': fees,
        'activities': assessments,
        'assessments': assessments,
        'task_assessments': task_assessments,
        'pending_tasks': pending_tasks,
        'student_submissions': student_submissions,
        'subjects': portal.get('subjects', []),
        'selected_subject': (
            selected_subject if active_tab == 'activities' else portal.get('selected_subject')
        ),
        'selected_period': (
            selected_period if active_tab == 'activities' else portal.get('selected_period', 1)
        ),
        'activity_feed': portal.get('activity_feed', []),
        'activity_scores': portal.get('activity_scores', []),
        'period_scheme_note': PERIOD_COMPONENT_SCHEME_NOTE,
        'draft_standing': portal.get('draft_standing'),
        'published_standing': portal.get('published_standing'),
        'grading_periods': portal.get('grading_periods', GRADING_PERIODS),
        'current_active_period': portal.get('selected_period', 1),
        'class_notices': class_notices,
        'full_activity_record': build_full_activity_record(
            student,
            display_year,
            selected_subject=selected_subject,
            selected_period=selected_period if active_tab == 'activities' else portal.get('selected_period'),
        ) if student and display_year else [],
        'published_grade_summary': build_student_published_grade_summary(
            student, display_year
        ) if student and display_year else [],
        'official_documents': official_documents,
        'approved_periods': official_documents.get('approved_periods', []),
        'pending_periods': official_documents.get('pending_periods', []),
        'transcript_released': (
            official_transcript_is_released(student.id, display_year.id)
            if student and display_year else False
        ),
        'attendance_self': build_student_self_attendance_context(student, display_year),
        **build_student_qr_context(student),
    }


class DeanManager:
    """The 'Heart' of the school - logic for the Dean of Students"""

    @staticmethod
    def issue_suspension(student_id, reason, duration_days):
        """
        Records a suspension and sets the return date.
        """
        # Removed redundant local timedelta import statement
        return_date = datetime.now(timezone.utc) + timedelta(days=duration_days)
        
        suspension = Suspension(
            student_id=student_id,
            reason=reason,
            return_date=return_date
        )
        
        # Updated to safe, modern session.get syntax pattern
        student = db.session.get(Student, student_id)
        if student:
            student.status = 'SUSPENDED'
            db.session.add(suspension)
            db.session.commit()
            return f"Student {student.full_name} is suspended until {return_date.date()}"
        return "Student context error: Record not found"

    @staticmethod
    def check_suspension_status(student_id):
        """
        Security check: Is the student allowed on campus/in the system today?
        """
        suspension = Suspension.query.filter(
            Suspension.student_id == student_id,
            Suspension.return_date > datetime.now(timezone.utc)
        ).first()
        
        if suspension:
            return False  # Student is still banned
        return True  # Student is clear


class InstitutionalManager:
    """The 'Engine' of the school - logic for the VPI"""

    @staticmethod
    def check_room_availability(room_id, new_student_count):
        """
        Ensures the school is compliant with capacity standards.
        """
        # Updated to safe, modern session.get syntax pattern
        room = db.session.get(Room, room_id)
        if not room:
            return {"status": "ERROR", "message": "Room not found"}
            
        current_total = room.current_occupancy + new_student_count
        
        if current_total > room.capacity:
            return {
                "status": "OVERCROWDED", 
                "shortfall": current_total - room.capacity
            }
        return {"status": "OK", "remaining_seats": room.capacity - current_total}

    @staticmethod
    def log_maintenance(asset_id, issue_description, priority):
        """
        VPI's tool to manage school repairs (generators, roofs, etc.)
        """
        # Cleaned up redundant local 'MaintenanceTicket' import statement
        ticket = MaintenanceTicket(
            asset_id=asset_id,
            description=issue_description,
            priority=priority,  # Low, Medium, High
            status="Open",
            reported_at=datetime.now(timezone.utc)
        )
        db.session.add(ticket)
        db.session.commit()

    @staticmethod
    def check_accreditation_status(permit_expiry_date):
        """Calculates days until permit needs renewal"""
        today = datetime.now(timezone.utc).date()
        days_left = (permit_expiry_date - today).days
        
        if days_left < 0:
            return "EXPIRED - Urgent Action Required"
        elif days_left < 90:
            return f"WARNING: {days_left} days left for renewal"
        return "Compliant"

  # -------------------------------------------------------------------
# 1. FLASK APPLICATION INITIALIZATION & CONFIGURATION
# -------------------------------------------------------------------
# Calculate the absolute root folder where app.py resides
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Inject current directory layout context into the system path for safe module imports
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

app = Flask(__name__)

# Security parameters configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change_this_secret_key')

# ABSOLUTE DATABASE PATHING RESOLUTION
INSTANCE_PATH = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_PATH, exist_ok=True)

# Generate an absolute path to ensure desynchronization bugs are impossible
db_path = os.path.abspath(os.path.join(INSTANCE_PATH, 'future_leaders_full.db'))

# Assign SQLALCHEMY configuration parameters
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
from scale import apply_database_engine_options, ensure_scale_indexes, clamp_page, DASHBOARD_PAGE_SIZE, seal_academic_year_folders, recommended_waitress_threads, env_int
apply_database_engine_options(app)
app.config['PROMOTION_PASS_SCORE'] = int(os.environ.get('PROMOTION_PASS_SCORE', '70'))
app.config['MAX_FAILING_SUBJECTS'] = int(os.environ.get('MAX_FAILING_SUBJECTS', '2'))
MOE_PASSING_SCORE = app.config['PROMOTION_PASS_SCORE']
configure_app(app)

# =====================================================================
# ENGINE PLUGINS & EXTENSIONS INITIALIZATION
# =====================================================================

# 1. Bind SQLAlchemy to the Flask app instance FIRST
db.init_app(app)
configure_sqlite_performance(app, db)

# 2. Safely initialize Migrate now that db is bound to app
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

class AcademicManager:
    """The 'Brain' of the school - logic for the VPA"""

    @staticmethod
    def calculate_annual_result(student_id):
        """Year-end promotion / summer school / repeat from printed YRLY AVE marks."""
        student = db.session.get(Student, student_id)
        year = get_active_academic_year()
        decision = evaluate_year_promotion_decision(student, year)
        status_map = {
            'PROMOTED': 'PROMOTED',
            'GRADUATED': 'GRADUATED',
            'SUMMER_SCHOOL': 'SUMMER_SCHOOL',
            'REPEAT': 'RETAINED',
            'INCOMPLETE': 'RETAINED',
        }
        return {
            'status': status_map.get(decision.get('code'), 'RETAINED'),
            'gpa': decision.get('overall_average') or 0,
            'failed_subjects': decision.get('failing_subject_count') or 0,
        }


# -------------------------------------------------------------------
# 3. SECURITY UTILITY LOGIC
# -------------------------------------------------------------------
def track_failed_attempt(ip_address, username=None):
    """Logs a failed login attempt and returns True if the IP should be blocked."""
    log = SecurityLog(
        ip_address=ip_address,
        event='FAILED_LOGIN',
        timestamp=datetime.now(timezone.utc),
    )
    db.session.add(log)
    db.session.commit()
    return check_brute_force(ip_address)


def generate_recovery_token(user_id):
    s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    return s.dumps(user_id, salt='password-recovery-salt')


def verify_recovery_token(token, expiration=600): # 10 minutes
    s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    try:
        user_id = s.loads(token, salt='password-recovery-salt', max_age=expiration)
    except:
        return None
    return user_id


def generate_transcript_verify_token(student_id):
    """Signed token embedded in transcript QR codes (does not expire)."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps({'sid': student_id}, salt='transcript-verify-salt')


def decode_transcript_verify_token(token):
    """Resolve a transcript QR token to an internal student id."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        payload = serializer.loads(token, salt='transcript-verify-salt')
    except Exception:
        return None
    return payload.get('sid') if isinstance(payload, dict) else None


def calculate_period_score(ca_score, exam_score):
    """
    Logic to ensure the weights follow MoE standards.
    CA is usually out of 60, Exam out of 40.
    """
    if ca_score > 60 or exam_score > 40:
        raise ValueError("Score exceeds Liberian national standard limits.")
    
    return ca_score + exam_score 


# -------------------------------------------------------------------
# 4. ACCOUNTING & FINANCIAL MATRICES
# -------------------------------------------------------------------
def money(value):
    """Return a two-decimal float using Decimal math for fee totals."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, str) and any(ch in value for ch in (",", "$", "₱", "₦", "€", "£")):
        return currency_to_float(value)
    return float((Decimal(str(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_yearly_fee_for_student(student, academic_year=None):
    if not student:
        return money(0.0)

    klass = getattr(student, 'klass', None)
    if not klass and getattr(student, 'klass_id', None):
        klass = db.session.get(Class, student.klass_id)

    if klass is not None:
        raw_fee = getattr(klass, 'yearly_fees', None) or getattr(klass, 'yearly_fee', None)
        if raw_fee:
            return money(raw_fee)

    if academic_year:
        global_fee = SchoolFee.query.filter_by(
            academic_year_id=academic_year.id,
            fee_type='tuition',
            class_id=None,
        ).first()
        if global_fee and global_fee.amount:
            return money(global_fee.amount)

    return money(0.0)


def is_yearly_fee_payment(description):
    desc = (description or "").strip().lower()
    if not desc:
        return True

    non_yearly_keywords = ("uniform", "graduation", "utility", "transport", "bus", "lunch", "book", "activity")
    if any(keyword in desc for keyword in non_yearly_keywords):
        return False

    yearly_keywords = ("tuition", "school fee", "yearly", "annual", "registration", "fee", "fees")
    return any(keyword in desc for keyword in yearly_keywords)


def build_student_financials(student, academic_year=None):
    """
    Computes precise financial metrics for an individual student.
    Aggregates metrics directly from the student_payments table using 
    the dynamic relationship backref to preserve multi-tenancy sandboxing.
    """
    financials = {
        'yearly_fee': 0.0, 'tuition_paid': 0.0, 'tuition_balance': 0.0,
        'utility_paid': 0.0, 'registration_paid': 0.0, 'total_paid': 0.0
    }

    if not student:
        return financials

    # 1. Fetch all payment records safely via dynamic relationship or fallback query
    if hasattr(student, 'payment_records'):
        all_payments = student.payment_records.all()
    else:
        # Fallback direct lookup if model metadata hasn't completed mapping
        all_payments = StudentPayment.query.filter_by(student_id=student.id).all()

    # 2. Filter payments by the selected academic year if provided
    year_id = academic_year.id if academic_year else None
    if year_id:
        payments = [p for p in all_payments if p.academic_year_id == year_id]
    else:
        payments = all_payments

    # 3. Totals come only from recorded StudentPayment rows — never from
    # student.registration_fees (that field is registrar metadata, not a ledger entry).
    yearly_fee = Decimal(str(get_yearly_fee_for_student(student, academic_year)))
    yearly_paid = Decimal("0")
    other_paid = Decimal("0")
    total_paid = Decimal("0")
    registration_payment_paid = Decimal("0")

    for payment in payments:
        amount = Decimal(str(payment.amount_paid or 0))
        total_paid += amount

        desc = (payment.description or "").lower()
        if "registration" in desc:
            registration_payment_paid += amount

        if is_yearly_fee_payment(payment.description):
            yearly_paid += amount
        else:
            other_paid += amount

    # 4. Final aggregation updates
    registration_paid = registration_payment_paid
    tuition_balance = max(Decimal("0"), yearly_fee - yearly_paid)

    financials.update({
        'yearly_fee': money(yearly_fee),
        'tuition_paid': money(yearly_paid),
        'tuition_balance': money(tuition_balance),
        'utility_paid': money(other_paid),
        'registration_paid': money(registration_paid),
        'total_paid': money(total_paid)
    })
    
    return financials


# -------------------------------------------------------------------
# 5. SCHEMA REPAIRS TOOLKIT
# -------------------------------------------------------------------
def ensure_legacy_sqlite_schema():
    """Add model columns that db.create_all() cannot add to existing SQLite tables."""
    repairs = {
        "classes": {
            "yearly_fees": "FLOAT DEFAULT 0.0",
            "sponsor_id": "INTEGER",
            "grading_scheme": "TEXT",
        },
        "students": {
            "photo_filename": "VARCHAR(200) DEFAULT 'default_student.png'",
            "status": "VARCHAR(20) DEFAULT 'ACTIVE'",
            "grade_level": "INTEGER",
            "level": "VARCHAR(50)",
            "student_id_code": "VARCHAR(20)",
            "registration_type": "VARCHAR(20) DEFAULT 'New'",
            "created_at": "DATETIME",
            "tuition_cleared": "BOOLEAN DEFAULT 0",
            "registrar": "VARCHAR(100)",
            "registration_fees": "FLOAT DEFAULT 0.0",
            "is_promoted": "BOOLEAN DEFAULT 0",
            "is_registered": "BOOLEAN DEFAULT 1",
            "secure_qr_token": "VARCHAR(128)",
            "parent_id": "INTEGER",
            "parent_phone": "VARCHAR(20)",
            "guardian_name": "VARCHAR(120)",
            "parent_report_token": "VARCHAR(128)",
            "parent_report_pin_hash": "VARCHAR(200)",
            "signature_filename": "VARCHAR(200)",
            "id_card_ready": "BOOLEAN DEFAULT 0",
            "id_expiration_date": "DATE",
        },
        "student_payments": {
            "installment": "INTEGER",
            "description": "VARCHAR(250)",
        },
        "grades": {
            "academic_year_id": "INTEGER",
            "class_id": "INTEGER",
            "marking_period": "INTEGER",
            "component_scores": "TEXT",
        },
        "assessments": {
            "subject_name": "VARCHAR(100)",
            "activity_type": "VARCHAR(50) DEFAULT 'Assignment'",
            "submission_mode": "VARCHAR(30) DEFAULT 'file_upload'",
            "marking_period": "INTEGER DEFAULT 1",
            "academic_year_id": "INTEGER",
            "teacher_id": "INTEGER",
            "file_name": "VARCHAR(255)",
            "due_date": "VARCHAR(20)",
            "scan_keywords": "VARCHAR(500)",
            "external_url": "VARCHAR(500)",
            "classroom_notes": "TEXT",
        },
        "business_transactions": {
            "balance_after": "FLOAT DEFAULT 0.0",
            "is_deleted": "BOOLEAN DEFAULT 0",
            "deleted_at": "DATETIME",
            "deleted_by_id": "INTEGER",
        },
        "academic_years": {
            "current_year": "VARCHAR(20)",
            "klass_id": "INTEGER",
        },
        "events": {
            "event_type": "VARCHAR(50) DEFAULT 'general'",
            "updated_at": "DATETIME",
        },
        "discipline_records": {
            "logged_by_id": "INTEGER",
        },
        "suspensions": {
            "start_date": "DATE",
        },
        "users": {
            "username": "VARCHAR(80)",
            "photo": "VARCHAR(200)",
            "totp_secret": "VARCHAR(32)",
            "home_address": "VARCHAR(255)",
            "telephone_number": "VARCHAR(20)",
            "must_change_password": "BOOLEAN DEFAULT 0",
            "id_card_photo_path": "VARCHAR(200)",
            "id_card_signature_path": "VARCHAR(200)",
            "id_expiration_date": "DATE",
            "staff_id_card_ready": "BOOLEAN DEFAULT 0",
            "job_title": "VARCHAR(120)",
            "department": "VARCHAR(120)",
            "employment_type": "VARCHAR(40)",
            "hire_date": "DATE",
            "date_of_birth": "DATE",
            "gender": "VARCHAR(20)",
            "national_id_number": "VARCHAR(60)",
            "highest_qualification": "VARCHAR(160)",
            "emergency_contact_name": "VARCHAR(120)",
            "emergency_contact_phone": "VARCHAR(40)",
            "staff_notes": "TEXT",
        },
        "announcements": {
            "content": "TEXT DEFAULT ''",
            "target_role": "TEXT DEFAULT 'all'",
            "category": "VARCHAR(50)",
        },
        "school_fees": {
            "class_id": "INTEGER",
            "fee_type": "VARCHAR(30) DEFAULT 'tuition'",
        },
        "submissions": {
            "assessment_id": "INTEGER",
            "submission_text": "TEXT",
            "score": "FLOAT",
            "teacher_feedback": "TEXT",
            "is_graded": "BOOLEAN DEFAULT 0",
        },
        "attendance": {
            "class_id": "INTEGER",
            "teacher_id": "INTEGER",
            "academic_year_id": "INTEGER",
            "created_at": "DATETIME",
        },
        "enrollments": {
            "academic_year_id": "INTEGER",
        },
        "school_media": {
            "duration_seconds": "INTEGER",
        },
    }

    for table_name, columns in repairs.items():
        existing = {
            row[1]
            for row in db.session.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
        }
        if not existing:
            continue

        for column_name, column_type in columns.items():
            if column_name not in existing:
                db.session.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN {column_name} {column_type}')
                )

    db.session.commit()

    try:
        db.session.execute(
            text('UPDATE events SET updated_at = created_at WHERE updated_at IS NULL')
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


def ensure_grade_releases_table():
    """Create grade_releases if missing and grandfather previously published packages."""
    existing = {
        row[1]
        for row in db.session.execute(text('PRAGMA table_info("grade_releases")')).fetchall()
    }
    if not existing:
        db.session.execute(text(
            """
            CREATE TABLE IF NOT EXISTS grade_releases (
                id INTEGER PRIMARY KEY,
                academic_year_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                period INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                published_by_id INTEGER,
                published_at DATETIME,
                approved_by_id INTEGER,
                approved_at DATETIME,
                returned_by_id INTEGER,
                returned_at DATETIME,
                review_comment TEXT,
                FOREIGN KEY(academic_year_id) REFERENCES academic_years(id) ON DELETE CASCADE,
                FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
                FOREIGN KEY(published_by_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(approved_by_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(returned_by_id) REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE(academic_year_id, class_id, period)
            )
            """
        ))
        db.session.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_grade_releases_status ON grade_releases(status)'
        ))
        db.session.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_grade_releases_year_class '
            'ON grade_releases(academic_year_id, class_id)'
        ))
        db.session.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_grade_release_year_class_period '
            'ON grade_releases(academic_year_id, class_id, period)'
        ))
        db.session.commit()
        existing = {
            row[1]
            for row in db.session.execute(text('PRAGMA table_info("grade_releases")')).fetchall()
        }

    columns = {
        "academic_year_id": "INTEGER",
        "class_id": "INTEGER",
        "period": "INTEGER",
        "status": "VARCHAR(20) DEFAULT 'draft'",
        "published_by_id": "INTEGER",
        "published_at": "DATETIME",
        "approved_by_id": "INTEGER",
        "approved_at": "DATETIME",
        "returned_by_id": "INTEGER",
        "returned_at": "DATETIME",
        "review_comment": "TEXT",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing:
            db.session.execute(
                text(f'ALTER TABLE grade_releases ADD COLUMN {column_name} {column_type}')
            )
    db.session.commit()
    try:
        db.session.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_grade_release_year_class_period '
            'ON grade_releases(academic_year_id, class_id, period)'
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
    _grandfather_existing_grade_releases()


def _grandfather_existing_grade_releases():
    """Existing submitted class/period packages stay visible until a teacher republishes."""
    now = datetime.now(timezone.utc)
    seen = set()
    for grade in Grade.query.filter_by(submitted=True).all():
        period = _grade_release_period(grade)
        class_id = grade.class_id
        year_id = grade.academic_year_id
        if not class_id or not year_id or period not in range(1, 9):
            continue
        key = (year_id, class_id, period)
        if key in seen:
            continue
        seen.add(key)
        existing = GradeRelease.query.filter_by(
            academic_year_id=year_id, class_id=class_id, period=period,
        ).first()
        if existing:
            continue
        db.session.add(GradeRelease(
            academic_year_id=year_id,
            class_id=class_id,
            period=period,
            status=GradeRelease.STATUS_APPROVED,
            published_at=now,
            approved_at=now,
            review_comment='Backfilled from previously published grades.',
        ))
    db.session.commit()


def ensure_transcript_releases_table():
    """Create transcript_releases if missing so portal gates work on existing databases."""
    existing = {
        row[1]
        for row in db.session.execute(text('PRAGMA table_info("transcript_releases")')).fetchall()
    }
    if not existing:
        db.session.execute(text(
            """
            CREATE TABLE IF NOT EXISTS transcript_releases (
                id INTEGER PRIMARY KEY,
                academic_year_id INTEGER NOT NULL,
                student_id INTEGER,
                status VARCHAR(20) NOT NULL DEFAULT 'approved',
                approved_by_id INTEGER,
                approved_at DATETIME,
                review_comment TEXT,
                FOREIGN KEY(academic_year_id) REFERENCES academic_years(id) ON DELETE CASCADE,
                FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY(approved_by_id) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        ))
        db.session.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_transcript_releases_status ON transcript_releases(status)'
        ))
        db.session.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_transcript_releases_year_student '
            'ON transcript_releases(academic_year_id, student_id)'
        ))
        db.session.commit()
        existing = {
            row[1]
            for row in db.session.execute(text('PRAGMA table_info("transcript_releases")')).fetchall()
        }

    columns = {
        "academic_year_id": "INTEGER",
        "student_id": "INTEGER",
        "status": "VARCHAR(20) DEFAULT 'approved'",
        "approved_by_id": "INTEGER",
        "approved_at": "DATETIME",
        "review_comment": "TEXT",
    }
    for column_name, column_type in columns.items():
        if column_name not in existing:
            db.session.execute(
                text(f'ALTER TABLE transcript_releases ADD COLUMN {column_name} {column_type}')
            )
    db.session.commit()
    try:
        db.session.execute(text('PRAGMA wal_checkpoint(PASSIVE)'))
    except Exception:
        pass


def repair_submission_legacy_links():
    """Backfill legacy activity_id values from newer assessment_id rows."""
    existing = {
        row[1]
        for row in db.session.execute(text('PRAGMA table_info("submissions")')).fetchall()
    }
    if not existing or "activity_id" not in existing:
        return 0
    if "assessment_id" in existing:
        db.session.execute(
            text(
                "UPDATE submissions SET activity_id = assessment_id "
                "WHERE (activity_id IS NULL OR activity_id = 0) AND assessment_id IS NOT NULL"
            )
        )
    db.session.commit()
    return 1


def normalize_misplaced_school_media():
    """Move photos/videos out of document-only entrance/info_sheet categories."""
    misplaced = SchoolMedia.query.filter(
        SchoolMedia.category.in_(DOCUMENT_ONLY_MEDIA_CATEGORIES),
        SchoolMedia.media_type.in_(("video", "photo")),
    ).all()
    if not misplaced:
        return 0
    for item in misplaced:
        item.category = "advertisement" if item.media_type == "video" else "gallery"
    db.session.commit()
    return len(misplaced)

# =====================================================================
# ✅ PLACE IMPORTS HERE (Right after extensions init, before anything else)
# =====================================================================
from models import (
    User, Student, Teacher, Class, ClassSubject, ClassSubjectTeacher, Enrollment, Grade,
    Attendance, Sponsor, Announcement, Discipline, Payroll,
    Assessment, AcademicYear, BusinessTransaction, StudentPayment,
    Leader, LeaderCategory, Event, SecurityLog, Suspension, Room,
    Asset, MaintenanceTicket, Activity, Submission, SystemSetting, SchoolMedia,
)
from forms import (
    LoginForm, RegisterStudentForm, SelfRegistrationForm, PayrollForm, AcademicYearForm, RolloverWizardForm,
    AnnouncementForm, BusinessTransactionForm, AssignTeacherForm, CreateClassForm,
    EventForm, ConfirmDeleteForm, LeaderForm, EnrollmentForm, PaymentForm, TransactionForm,
    DisciplineForm, RecordClassroomActivityForm, ParentReportGateForm,
)
from export_routes import init_export_routes
#
# Custom Jinja filters
@app.template_filter('grade_letter')
def grade_letter_filter(score):
    return SchoolEngine.get_grade_letter(score)

@app.template_filter('remarks')
def remarks_filter(score):
    return SchoolEngine.get_remarks(score)

@app.template_filter('activity_file_icon')
def activity_file_icon_filter(filename):
    return activity_file_icon(filename)

@app.template_filter('marking_period_label')
def marking_period_label_filter(period_num):
    return grading_period_label(period_num)

@app.template_filter('subjects_match')
def subjects_match_filter(left, right):
    return subjects_match(left, right)


@app.template_filter('score_mark_class')
def score_mark_class_filter(value):
    """Pass (blue) vs fail (red) class for official grade-sheet cells."""
    num = numeric_report_score(value)
    if num is None:
        return 'mark-empty'
    threshold = promotion_pass_score()
    if num < threshold:
        return 'mark-fail'
    return 'mark-pass'

SYSTEM_ARCHITECT_NAME = os.environ.get('SYSTEM_ARCHITECT_NAME', 'Francis Brownell')


def _whatsapp_digits(phone):
    if not phone:
        return ''
    return ''.join(ch for ch in str(phone) if ch.isdigit())


def get_system_settings():
    """Return the singleton system license row, creating defaults if needed."""
    settings = SystemSetting.query.order_by(SystemSetting.id.asc()).first()
    if not settings:
        settings = SystemSetting(system_active=True)
        db.session.add(settings)
        db.session.commit()
    return settings


def _system_hold_exempt_endpoints():
    return {
        'static', 'login', 'logout', 'index', 'about', 'contact',
        'events_list', 'school_media_gallery', 'school_media_download',
        'admin_system_control', 'admin_system_activate', 'admin_system_deactivate',
        'student_enrollment', 'submit_registration', 'api_lookup_student',
        'verify_student', 'verify_transcript', 'parent_report_gate', 'parent_report_view',
        'download_report_card',
    }


@app.before_request
def enforce_system_license():
    """Block non-admin users when the platform is on hold."""
    endpoint = request.endpoint
    if not endpoint or endpoint in _system_hold_exempt_endpoints():
        return None
    if endpoint and endpoint.startswith('export_'):
        return None
    try:
        settings = get_system_settings()
    except Exception:
        return None
    if settings.system_active:
        return None
    if current_user.is_authenticated and normalize_role(current_user) == 'admin':
        return None
    if current_user.is_authenticated:
        logout_user()
    return render_template(
        'system_unavailable.html',
        settings=settings,
        system_architect_name=SYSTEM_ARCHITECT_NAME,
        system_admin_whatsapp=_whatsapp_digits(settings.admin_contact_phone),
    ), 503


_PASSWORD_CHANGE_EXEMPT_ENDPOINTS = frozenset({
    'account_settings', 'logout', 'login', 'static',
})


@app.before_request
def enforce_initial_password_change():
    """Students issued an initial password must change it before using the portal."""
    if not getattr(current_user, 'is_authenticated', False):
        return None
    if not getattr(current_user, 'must_change_password', False):
        return None
    endpoint = request.endpoint
    if not endpoint or endpoint in _PASSWORD_CHANGE_EXEMPT_ENDPOINTS:
        return None
    if request.path.startswith('/static'):
        return None
    flash('Please change your initial password before continuing.', 'warning')
    return redirect(url_for('account_settings'))


@app.context_processor
def inject_nav_flags():
    role = getattr(current_user, "role", None)
    role_lower = (role or "").lower()
    try:
        settings = get_system_settings()
        system_is_active = settings.system_active
    except Exception:
        settings = None
        system_is_active = True
    return {
        "announcements_link": role_lower in {"admin", "teacher", "principal", "vpa", "vpi", "dean"},
        "is_vpa_office": role_lower == "vpa",
        "is_vpi_office": role_lower == "vpi",
        "can_manage_leaders": role_lower in {"admin", "principal"},
        "can_manage_events": role_lower in COMMUNICATIONS_MANAGER_ROLES,
        "can_manage_school_media": role_lower in SCHOOL_MEDIA_MANAGER_ROLES,
        "registrar_media_only": role_lower == "registrar",
        "system_settings": settings,
        "system_is_active": system_is_active,
        "system_on_hold": not system_is_active,
        "system_architect_name": SYSTEM_ARCHITECT_NAME,
        "system_admin_whatsapp": _whatsapp_digits(
            settings.admin_contact_phone if settings else ''
        ),
        "ocr_available": ocr_engine_ready(),
        "ocr_libraries_installed": ocr_libraries_available(),
        "school_video_max_minutes": SCHOOL_VIDEO_MAX_DURATION_SEC // 60,
        "school_video_max_mb": SCHOOL_VIDEO_MAX_MB,
        "video_mime_type": _school_media_video_mime,
        "format_video_duration": _format_video_duration,
        "current_year": datetime.now(timezone.utc).year,
        "school_print_brand": school_print_brand(),
        "id_card_header_name": id_card_header_title(),
        "school_logo_url": school_logo_static_url(),
        "liberia_seal_url": liberia_seal_static_url(),
        "display_font_url": display_font_static_url(),
        "default_avatar_url": default_static_photo_url(),
        "can_issue_id_cards": (
            getattr(current_user, "is_authenticated", False)
            and canonical_role(current_user) in {"admin", "principal", "registrar"}
        ),
        "can_issue_staff_id_cards": (
            getattr(current_user, "is_authenticated", False)
            and canonical_role(current_user) in {"admin", "principal", "registrar", "vpi", "vpa"}
        ),
        "can_print_official_transcript": (
            getattr(current_user, "is_authenticated", False)
            and canonical_role(current_user) in OFFICIAL_TRANSCRIPT_STAFF_ROLES
        ),
        "can_open_staff_folders": (
            getattr(current_user, "is_authenticated", False)
            and normalize_role(current_user) in ACADEMIC_COMMAND_ROLES
        ),
    }

# -------------------------------------------------------------------
# Login Manager
# -------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.route('/sw.js')
def service_worker():
    """Serve the worker from the root so it can control every page, not just /static/."""
    response = send_from_directory(
        app.static_folder, 'sw.js', mimetype='application/javascript'
    )
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@app.route('/manifest.webmanifest')
def web_app_manifest():
    """Install manifest for the FLPA portal (Add to Home Screen / desktop install)."""
    response = send_from_directory(
        app.static_folder, 'manifest.webmanifest', mimetype='application/manifest+json'
    )
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


@app.route('/offline')
def offline_page():
    """Branded offline notice shown by the service worker when the network is down."""
    return send_from_directory(app.static_folder, 'offline.html')


@app.route('/health')
def health():
    """Liveness/readiness probe for Docker, ALB, and deploy scripts."""
    try:
        db.session.execute(db.select(1))
        return jsonify(status='ok', service='school-management', database='connected'), 200
    except Exception:
        logger.exception('Health check database probe failed')
        return jsonify(status='error', service='school-management', database='unreachable'), 503


@app.route('/')
def index():
    # Show the next three upcoming events on the public homepage
    upcoming_events = (
        Event.query.order_by(Event.date.asc())
        .filter(Event.date >= datetime.now(timezone.utc).date())
        .limit(3)
        .all()
    )
    total_events = Event.query.count()
    featured_media = (
        SchoolMedia.query.filter(
            SchoolMedia.is_published.is_(True),
            SchoolMedia.category.in_(HOMEPAGE_FEATURED_MEDIA_CATEGORIES),
        )
        .order_by(SchoolMedia.created_at.desc())
        .limit(6)
        .all()
    )
    entrance_highlights = (
        SchoolMedia.query.filter(
            SchoolMedia.is_published.is_(True),
            SchoolMedia.category == "entrance",
            SchoolMedia.media_type == "document",
        )
        .order_by(SchoolMedia.created_at.desc())
        .limit(2)
        .all()
    )
    info_sheet_highlights = (
        SchoolMedia.query.filter(
            SchoolMedia.is_published.is_(True),
            SchoolMedia.category == "info_sheet",
            SchoolMedia.media_type == "document",
        )
        .order_by(SchoolMedia.created_at.desc())
        .limit(3)
        .all()
    )
    latest_announcements = (
        Announcement.query.order_by(Announcement.created_at.desc())
        .limit(6)
        .all()
    )
    return render_template(
        'index.html',
        events=upcoming_events,
        highlighted_event=upcoming_events[0] if upcoming_events else None,
        featured_media=featured_media,
        entrance_highlights=entrance_highlights,
        info_sheet_highlights=info_sheet_highlights,
        latest_announcements=latest_announcements,
        current_year=datetime.now(timezone.utc).year,
        total_events=total_events,
        youtube_embed_url=_youtube_embed_url,
    )

# ----------------------------- LOGIN -------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    if form.validate_on_submit():
        if check_brute_force(ip):
            flash('Too many failed login attempts. Please try again in 15 minutes.', 'danger')
            return render_template('login.html', form=form)

        identifier = (form.email.data or '').strip()
        password = (form.password.data or '').strip()
        user = resolve_user_for_login(identifier)
        if user and not user.is_account_active():
            track_failed_attempt(ip, identifier)
            flash('This account is inactive. Contact your administrator to restore access.', 'danger')
        elif user and user.check_password(password):
            settings = get_system_settings()
            if not settings.system_active and normalize_role(user) != 'admin':
                flash('The system is on hold. Contact the administrator to renew service.', 'danger')
                return render_template('login.html', form=form)
            login_user(user)
            log_incident('SUCCESSFUL_LOGIN')
            if getattr(user, 'must_change_password', False):
                flash('Please change your initial password before continuing.', 'warning')
                return redirect(url_for('account_settings'))
            flash('Login successful.', 'success')
            home_ep = home_endpoint_for_role(user)
            next_url = (request.args.get('next') or request.form.get('next') or '').strip()
            next_path = next_url.split('?', 1)[0].rstrip('/')
            # /dashboard is the shared business gateway — never send registrar/registry there via ?next=
            if next_path in ('/dashboard', '/business_dashboard'):
                return redirect(url_for(home_ep))
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for(home_ep))

        track_failed_attempt(ip, identifier)
        if user:
            flash('Incorrect password for that account. Staff: use your portal email (admin may also use username admin).', 'danger')
        elif looks_like_student_id(identifier):
            flash('Student ID not found, or that student has no portal account yet. Try your email instead.', 'danger')
        else:
            flash('No account found for that email. Staff must sign in with their portal email address.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/admin/system-control', methods=['GET', 'POST'])
@login_required
def admin_system_control():
    if normalize_role(current_user) != 'admin':
        flash('Administrator access required.', 'danger')
        return redirect(url_for('login'))

    settings = get_system_settings()
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip().lower()
        if action == 'save_contact':
            settings.admin_contact_email = (request.form.get('admin_contact_email') or '').strip()
            settings.admin_contact_phone = (request.form.get('admin_contact_phone') or '').strip() or None
            settings.hold_message = (request.form.get('hold_message') or '').strip() or settings.hold_message
            db.session.commit()
            flash('Hold page contact details saved.', 'success')
            return redirect(url_for('admin_system_control'))
        if action == 'activate':
            settings.system_active = True
            settings.deactivated_at = None
            settings.deactivated_by_id = None
            db.session.commit()
            flash('System activated. All users may sign in again.', 'success')
            return redirect(url_for('admin_system_control'))

    return render_template(
        'admin_system_control.html',
        settings=settings,
        system_architect_name=SYSTEM_ARCHITECT_NAME,
    )


@app.route('/admin/system-control/activate', methods=['POST'])
@login_required
def admin_system_activate():
    if normalize_role(current_user) != 'admin':
        flash('Administrator access required.', 'danger')
        return redirect(url_for('login'))
    settings = get_system_settings()
    settings.system_active = True
    settings.deactivated_at = None
    settings.deactivated_by_id = None
    db.session.commit()
    flash('System activated for all users.', 'success')
    return redirect(url_for('admin_system_control'))


@app.route('/admin/system-control/deactivate', methods=['POST'])
@login_required
def admin_system_deactivate():
    if normalize_role(current_user) != 'admin':
        flash('Administrator access required.', 'danger')
        return redirect(url_for('login'))
    settings = get_system_settings()
    settings.system_active = False
    settings.deactivated_at = datetime.now(timezone.utc)
    settings.deactivated_by_id = current_user.id
    db.session.commit()
    flash('System placed on hold. Only administrators can sign in.', 'warning')
    return redirect(url_for('admin_system_control'))
# -------------------------------------------------------------------------
# Dashboard Access Control & Core Routing Gateway
# -------------------------------------------------------------------------

BUSINESS_DASHBOARD_ROLES = frozenset({
    'admin', 'business', 'principal', 'vpi', 'vpa', 'registrar', 'registry', 'dean'
})
PRINCIPAL_GRADE_ENTRY_ROLES = frozenset({'principal', 'admin'})


def _require_business_dashboard_access():
    """Verify authorization for business office functions without unauthenticating valid users."""
    if not current_user.is_authenticated:
        flash('Please log in to continue.', 'danger')
        return redirect(url_for('login'))

    user_role = normalize_role(current_user)
    if user_role not in BUSINESS_DASHBOARD_ROLES:
        flash('Access restricted: Business dashboard privileges required.', 'danger')
        return render_template('errors/403.html'), 403

    return None


def _render_business_dashboard():
    """Render shared business office dashboard (tuition ledger, payments, analytics)."""
    active_year = get_active_academic_year()
    selected_year_name = active_year.name if active_year else "No Active Year Setup"
    all_students = Student.query.all()
    current_role = normalize_role(current_user)

    admin_view_requested = (request.args.get('view') or '').strip().lower() == 'admin'
    can_open_admin_view = current_role in {'admin', 'principal'}
    effective_role = 'admin' if admin_view_requested and can_open_admin_view else current_role
    announcements_link = current_role in {"admin", "principal", "dean"}

    display_year, active_year_biz, years_biz, viewing_archived_biz = resolve_dashboard_academic_year(
        session_key=BUSINESS_YEAR_SESSION_KEY,
    )
    biz_stats = _registrar_counts_for_year(display_year, viewing_archived=viewing_archived_biz)
    payment_form = PaymentForm()

    if request.method == 'POST' and 'submit_payment' in request.form:
        populate_business_payment_form(
            payment_form,
            display_year,
            years_biz,
            class_id=request.form.get('class_id', type=int),
            student_id=request.form.get('student_id', type=int),
            viewing_archived=viewing_archived_biz,
        )
        if payment_form.validate_on_submit():
            try:
                student = db.session.get(Student, payment_form.student.data)
                if not student:
                    flash('Student record not found.', 'danger')
                else:
                    paid_amount = parse_currency_amount(payment_form.amount_paid.data)
                    payment = record_student_payment_with_income(
                        student,
                        payment_form.academic_year.data,
                        payment_form.term.data,
                        paid_amount,
                        (payment_form.description.data or 'Tuition Payment').strip(),
                        installment=payment_form.installment.data,
                    )
                    db.session.commit()
                    flash(
                        f"Payment of ${float(paid_amount):,.2f} recorded for {student.full_name}.",
                        'success',
                    )
                    if payment:
                        return redirect(url_for('print_business_payment_receipt', payment_id=payment.id))
                    redirect_kwargs = {
                        'tab': 'tuition',
                        'class_id': request.form.get('class_id', type=int),
                        'student_id': payment_form.student.data,
                    }
                    if display_year:
                        redirect_kwargs['academic_year_id'] = display_year.id

                    target_endpoint = 'business_dashboard' if 'business_dashboard' in app.view_functions else 'dashboard'
                    return redirect(url_for(target_endpoint, **redirect_kwargs))
            except Exception as exc:
                db.session.rollback()
                flash(f'Failed to record transaction: {exc}', 'danger')
        else:
            for field, errors in payment_form.errors.items():
                for err in errors:
                    flash(f'Payment Validation ({field}): {err}', 'danger')

    selected_year_label = display_year.name if display_year else selected_year_name
    business_ctx = build_business_dashboard_context(
        display_year,
        biz_stats,
        years_biz,
        selected_year_label,
        search_class=request.args.get('search_class'),
        payment_form=payment_form,
        viewing_archived=viewing_archived_biz,
    )

    counts = {
        'students': biz_stats.get('students', len(all_students)) if isinstance(biz_stats, dict) else len(all_students),
        'teachers': Teacher.query.count() if 'Teacher' in globals() else 0,
        'classes': ClassGroup.query.count() if 'ClassGroup' in globals() else 0,
        'users': User.query.count() if 'User' in globals() else 0,
    }
    business_ctx['counts'] = counts

    # Explicit template rendering by role
    if current_role in {'admin', 'principal'} or effective_role == 'admin':
        template_name = 'dashboard_admin.html'
        dashboard_title = f"Welcome to Your {current_role.capitalize()} Dashboard"
    else:
        template_name = 'dashboard_business.html'
        dashboard_title = "Welcome to Your Business Office Dashboard"

    return render_template(
        template_name,
        dashboard_title=dashboard_title,
        announcements_link=announcements_link,
        all_students=all_students,
        selected_year_name=selected_year_label,
        active_year=display_year,
        system_active_year=active_year_biz,
        effective_role=effective_role,
        show_admin_hub_link=current_role in {'admin', 'principal'},
        show_principal_hub_link=current_role == 'principal',
        **business_ctx
    )


@app.route('/dashboard', methods=['GET', 'POST'], endpoint='dashboard')
@app.route('/dashboard', methods=['GET', 'POST'], endpoint='business_dashboard')
@app.route('/business/dashboard', methods=['GET', 'POST'], endpoint='business_dashboard_path')
@login_required
def core_dashboard_gateway():
    """
    Centralized Core Routing Gateway.
    Evaluates active user roles and dispatches request contexts to appropriate 
    operational dashboards.
    """
    user_role = canonical_role(current_user)

    # 1. Handle Principal Role First
    if user_role == 'principal':
        for ep in ('principal_dashboard', 'principal.dashboard', 'principal_hub'):
            if ep in app.view_functions:
                return redirect(url_for(ep))
        # If no separate principal endpoint exists, render admin template
        return _render_business_dashboard()

    # 2. Handle Registry / Registrar Role explicitly
    if user_role == 'registrar':
        for ep in ('registrar_dashboard', 'registry_dashboard', 'register_student'):
            if ep in app.view_functions:
                return redirect(url_for(ep, **registrar_dashboard_redirect_kwargs()))
        form = RegisterStudentForm()
        context = build_registrar_dashboard_context(form=form)
        return render_template('dashboard_registrar.html', **context)

    # 3. Handle Other Roles
    role_route_map = {
        'teacher': 'teacher_dashboard',
        'vpi': 'vpi_dashboard',
        'vpa': 'vpa_dashboard',
        'dean': 'dean_dashboard',
        'student': 'student_dashboard',
    }

    target_endpoint = role_route_map.get(user_role)
    if target_endpoint and target_endpoint in app.view_functions:
        return redirect(url_for(target_endpoint))

    # 4. Fallback check for business/admin roles
    access_check = _require_business_dashboard_access()
    if access_check:
        return access_check

    return _render_business_dashboard()

# ----------------------------------------------------------------------
    # 1. CORE TELEMETRY & SYSTEM STATE INITIALIZATION
    # ----------------------------------------------------------------------
    active_year = get_active_academic_year()
    active_year_id = active_year.id if active_year else None
    selected_year_name = active_year.name if active_year else "No Active Year Setup"
    selected_year = active_year

    # Query year-scoped students
    all_students = []
    if active_year_id:
        all_students = students_for_academic_year(
            active_year_id, registered_only=True,
        ).order_by(Student.last_name.asc(), Student.first_name.asc()).all()

    # Base analytics tracking matrix
    stats = {
        'students': Student.query.filter_by(academic_year_id=active_year_id).count() if active_year_id else 0,
        'new_students': Student.query.filter_by(registration_type='New', academic_year_id=active_year_id).count() if active_year_id else 0,
        'returning_students': Student.query.filter_by(registration_type='Returning', academic_year_id=active_year_id).count() if active_year_id else 0,
        'teachers': Teacher.query.count() if 'Teacher' in globals() else 0,
        'classes': Class.query.count() if 'Class' in globals() else 0,
        'payments': StudentPayment.query.count() if 'StudentPayment' in globals() else 0
    }

    # Global template view model layer anchors
    years = all_academic_years()
    current_role = (current_user.role or "").strip().lower()
    effective_role = session.get('effective_role', current_role)

    announcements_link = current_role in {"admin", "principal", "dean"}

    # ======================================================================
    # 1.5 SPECIALIZED ROLE DISPATCH (PREVENT INFINITE REDIRECTS)
    # ======================================================================
    if current_role == "principal" and effective_role != 'admin':
        return principal_dashboard()
    elif current_role == "teacher":
        return redirect(url_for('teacher_dashboard', _external=False))
    elif current_role == "vpi":
        return redirect(url_for('vpi_dashboard', _external=False))
    elif current_role == "vpa":
        return redirect(url_for('vpa_dashboard', _external=False))
    elif current_role == "dean":
        return redirect(url_for('dean_dashboard', _external=False))
    elif current_role == "student":
        return redirect(url_for('student_dashboard', _external=False))
    elif current_role == "sponsor":
        return redirect(url_for('teacher_dashboard', _external=False))

    # Interface mapping
    template_map = {
        "admin": "dashboard_admin.html",
        "student": "dashboard_student.html",
        "registrar": "dashboard_registrar.html",
        "registry": "dashboard_registrar.html",
        "parent": "dashboard_parent.html",
    }

    template_name = template_map.get(effective_role, "dashboard_admin.html")

    # ======================================================================
    # 2. TEMPLATE RENDER DISPATCH
    # ======================================================================
    if template_name == 'dashboard_admin.html':
        display_year, active_year_admin, years_admin, viewing_archived = resolve_dashboard_academic_year(
            session_key=ADMIN_YEAR_SESSION_KEY,
        )
        admin_stats = _registrar_counts_for_year(display_year, viewing_archived=viewing_archived)
        
        recent_payments = []
        if 'StudentPayment' in globals():
            query = StudentPayment.query
            if display_year:
                query = query.filter_by(academic_year_id=display_year.id)
            recent_payments = query.order_by(StudentPayment.paid_on.desc()).limit(8).all()

        selected_year_label = display_year.name if display_year else selected_year_name

        return render_template(
            template_name,
            stats=admin_stats,
            counts=admin_stats,
            active_year=active_year_admin,
            display_year=display_year,
            viewing_archived=viewing_archived,
            all_students=all_students,
            years=years_admin,
            all_years=years_admin,
            selected_year=selected_year_label,
            selected_year_name=selected_year_label,
            announcements_link=announcements_link,
            payments=recent_payments,
            effective_role=effective_role,
        )

    # Standard Fallback Render for non-admin mapped templates (e.g., Registrar, Parent)
    return render_template(
        template_name,
        stats=stats,
        counts=stats,
        active_year=active_year,
        all_students=all_students,
        years=years,
        selected_year=selected_year,
        selected_year_name=selected_year_name,
        announcements_link=announcements_link,
        effective_role=effective_role,
    )

@app.route('/registrar/class/<int:class_id>/students', methods=['GET'])
@login_required
def registrar_class_students(class_id):
    """
    Renders the authorized class roster for an assigned classroom block.
    Supports granular role evaluation, eager-loading optimizations, and 
    defensive image asset pathway matching.
    """
    # 1. Broadened Authorization Guard
    authorized_roles = {'admin', 'registrar', 'business', 'principal', 'vpa', 'vpi', 'dean'}

    if not current_user.is_authenticated or normalize_role(current_user) not in authorized_roles:
        flash("Access Denied: Your system authority profile cannot read this database leaf.", "danger")
        return redirect(url_for('dashboard' if hasattr(current_user, 'role') else 'login'))

    # 2. Defensive Structural Query Resolution
    # Look up the specific class directory block or handle failure safely
    klass = db.session.get(Class, class_id)
    if not klass:
        flash(f"System Matrix Failure: Class record node #{class_id} could not be resolved.", "warning")
        return redirect(url_for('dashboard', **registrar_dashboard_redirect_kwargs()))

    # 3. Eager Loading Student Roster Payload (strict year isolation)
    session_key = dashboard_year_session_key()
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=session_key,
    )
    students = _principal_students_for_class(
        klass, display_year, viewing_archived=viewing_archived,
    )
    _attach_display_class(students, display_year, viewing_archived=viewing_archived)
    roster_folder_ctx = _build_registrar_roster_folders(
        display_year,
        viewing_archived=viewing_archived,
        open_class_id=klass.id,
    )

    # 4. Secure Context Response Delivery
    # Photo URLs are now handled via the photo_url property on the Student model
    return render_template(
        'registrar_class_students.html',
        klass=klass,
        students=students,
        current_user=current_user,
        active_year=active_year,
        display_year=display_year,
        viewing_archived=viewing_archived,
        years=years,
        **roster_folder_ctx,
    )


@app.route('/business/class/<int:class_id>/students', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'business', 'VPI', 'principal')
def business_class_students(class_id):
    klass = Class.query.get_or_404(class_id)

    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=BUSINESS_YEAR_SESSION_KEY,
    )
    payment_year = display_year or active_year

    # ==========================================
    # HANDLE POST REQUEST: RECORDING A PAYMENT
    # ==========================================
    if request.method == 'POST':
        if not payment_year:
            flash("Cannot accept payments without an active session configuration.", "danger")
            return redirect(url_for(
                'business_class_students',
                class_id=class_id,
                academic_year_id=display_year.id if display_year else None,
            ))

        student_id = request.form.get('student_id', type=int)
        term = request.form.get('term', type=int)
        raw_amount_paid = request.form.get('amount_paid')
        description = request.form.get('description', 'Tuition Payment')
        installment = request.form.get('installment', type=int) # Optional installment tracking

        try:
            amount_paid = parse_currency_amount(raw_amount_paid)
        except ValueError:
            amount_paid = None

        # Basic input validation
        if not student_id or term is None or amount_paid is None:
            flash("All required payment fields (Student, Term, Amount) must be provided.", "danger")
            return redirect(url_for(
                'business_class_students',
                class_id=class_id,
                academic_year_id=display_year.id if display_year else None,
            ))

        student = db.session.get(Student, student_id)
        if not student:
            flash("Student record not found.", "danger")
            return redirect(url_for(
                'business_class_students',
                class_id=class_id,
                academic_year_id=display_year.id if display_year else None,
            ))

        try:
            record_student_payment_with_income(
                student,
                payment_year.id,
                term,
                amount_paid,
                description,
                installment=installment,
            )
            db.session.commit()
            flash("Payment recorded and posted to business income.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Could not record payment: {exc}", "danger")
        return redirect(url_for(
            'business_class_students',
            class_id=class_id,
            academic_year_id=display_year.id if display_year else None,
        ))

    # ==========================================
    # HANDLE GET REQUEST: RENDER STUDENT LEDGER
    # ==========================================
    students_list = _principal_students_for_class(
        klass, display_year, viewing_archived=viewing_archived,
    )
    students_data = []
    for student in students_list:
        financials = build_student_financials(student, display_year or active_year)
        payment_query = StudentPayment.query.filter_by(student_id=student.id)
        if display_year:
            payment_query = payment_query.filter_by(academic_year_id=display_year.id)
        payment_count = payment_query.count()
        
        students_data.append({
            "id": student.id,
            "student_id": student.student_id,
            "first_name": student.first_name,
            "last_name": student.last_name,
            "full_name": student.full_name,
            "email": student.user.email if student.user else (student.parent_email or "-"),
            "academic_year": student.academic_year.name if student.academic_year else "-",
            "academic_year_id": student.academic_year_id,
            "registration_fees": financials["registration_paid"],
            "yearly_fee": financials["yearly_fee"],
            "total_paid": financials["total_paid"],
            "balance": financials["tuition_balance"],
            "payment_count": payment_count,
            "photo_url": student.photo_url,
            "is_registered": student.is_registered,
            "is_promoted": student.is_promoted,
        })

    return render_template(
        'business_class_students.html',
        klass=klass,
        students=students_data,
        active_year=display_year or active_year,
        display_year=display_year,
        viewing_archived=viewing_archived,
        years=years,
        current_user=current_user
    )


@app.route('/business/student/<int:student_id>/activate-registration', methods=['POST'])
@login_required
@role_required('admin', 'business', 'VPI', 'principal')
def finance_activate_student(student_id):
    """Manually unlock a student's portal after registration fee clearance."""
    student = Student.query.get_or_404(student_id)

    if student.is_registered:
        flash(f"{student.full_name} is already registered for the portal.", "info")
    else:
        try:
            activate_student_registration(student, actor_id=current_user.id)
            db.session.commit()
            flash(
                f"Registration activated for {student.full_name}. Portal access unlocked.",
                "success",
            )
        except Exception as exc:
            db.session.rollback()
            flash(f"Could not activate registration: {exc}", "danger")

    next_url = (request.form.get('next') or '').strip()
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/grade_entry_class')
@login_required
def grade_entry():
    """
    Landing Page: Shows the list of ALL classes this specific teacher has clearance
    to enter grades for (both taught classes and sponsored classes).
    """
    if normalize_role(current_user) != 'teacher':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    all_classes = get_teacher_classes(teacher, current_user)
    if not all_classes:
        flash('No classes assigned yet.', 'warning')
        return redirect(url_for('teacher_dashboard'))
    if len(all_classes) == 1:
        return redirect(url_for('grade_entry_class', class_id=all_classes[0].id))

    active_year = get_active_academic_year()
    if active_year:
        for klass in all_classes:
            if get_class_students_for_year(klass.id, active_year):
                return redirect(url_for('grade_entry_class', class_id=klass.id))

    return redirect(url_for('grade_entry_class', class_id=all_classes[0].id))


@app.route('/grade-entry/<int:class_id>', methods=['GET'])
@login_required
def grade_entry_class(class_id):
    """
    MoE-standard grade entry sheet for one class, subject, and marking period.
    """
    if normalize_role(current_user) != 'teacher':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher = Teacher.query.filter_by(user_id=current_user.id).first()
    klass = Class.query.get_or_404(class_id)

    if not teacher or not teacher_can_access_class(teacher, current_user, class_id):
        flash('Access mapping violation: You do not possess clearance for this room.', 'danger')
        return redirect(url_for('login'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found. Please contact the administrator.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    subjects = get_assignable_subjects_for_class(teacher, current_user, class_id)
    selected_subject = (request.args.get('subject') or '').strip()
    if selected_subject not in subjects:
        selected_subject = subjects[0] if subjects else ''

    selected_period = request.args.get('period', 1, type=int)
    if selected_period not in range(1, 9):
        selected_period = 1

    students = get_class_students_for_year(class_id, active_year)

    grade_rows = {}
    if selected_subject:
        existing_grades = Grade.query.filter_by(
            class_id=class_id,
            subject=selected_subject,
            academic_year_id=active_year.id,
        ).all()
        for grade in existing_grades:
            period_num = grade.marking_period or normalize_grade_period(grade.period)
            if period_num == selected_period and grade.student_id in {s.id for s in students}:
                grade_rows[grade.student_id] = grade

    period_label = grading_period_label(selected_period)
    is_semester_exam = selected_period in (7, 8)
    activity_sheet_items = []
    activity_submission_map = {}

    if selected_subject and not is_semester_exam:
        quick_entry_assessment = find_quick_entry_assessment(
            class_id, selected_subject, selected_period, active_year.id
        )
        activity_sheet_items.append({
            'key': 'quick',
            'assessment_id': quick_entry_assessment.id if quick_entry_assessment else None,
            'title': 'Quick Activity',
            'max_score': (quick_entry_assessment.max_score if quick_entry_assessment and quick_entry_assessment.max_score is not None else 100.0),
            'is_quick': True,
        })

        named_activities = [
            act for act in Assessment.query.filter_by(
                klass_id=class_id,
                subject_name=selected_subject,
                marking_period=selected_period,
                academic_year_id=active_year.id,
            ).order_by(Assessment.id.asc()).all()
            if not is_quick_entry_assessment(act)
        ]
        activity_sheet_items.extend([
            {
                'key': str(act.id),
                'assessment_id': act.id,
                'title': act.title,
                'max_score': act.max_score or 100.0,
                'is_quick': False,
            }
            for act in named_activities
        ])

        submission_assessment_ids = [
            item['assessment_id'] for item in activity_sheet_items if item.get('assessment_id')
        ]
        if submission_assessment_ids:
            submissions = Submission.query.filter(
                Submission.assessment_id.in_(submission_assessment_ids)
            ).all()
            for submission in submissions:
                activity_submission_map.setdefault(submission.assessment_id, {})[submission.student_id] = submission

    teacher_class_tabs = [
        {
            'id': card['id'],
            'name': card['name'],
            'grade_level': card['grade_level'],
            'stream': card.get('stream'),
            'active': card['id'] == class_id,
        }
        for card in get_teacher_class_cards(teacher, current_user)
    ]

    return render_template(
        'grade_entry_class.html',
        klass=klass,
        students=students,
        grade_rows=grade_rows,
        active_year=active_year,
        subjects=subjects,
        selected_subject=selected_subject,
        selected_period=selected_period,
        period_label=period_label,
        grading_periods=MOE_GRADING_PERIODS,
        is_semester_exam=is_semester_exam,
        teacher_name=teacher.full_name,
        teacher_class_tabs=teacher_class_tabs,
        activity_sheet_items=activity_sheet_items,
        activity_submission_map=activity_submission_map,
        grade_release=GradeRelease.query.filter_by(
            academic_year_id=active_year.id,
            class_id=class_id,
            period=selected_period,
        ).first() if active_year else None,
    )


@app.route('/teacher/class/<int:class_id>/period-activity-sheet', methods=['POST'])
@login_required
def save_period_activity_sheet(class_id):
    """Save scores for all activities shown on the teacher period activity sheet."""
    role = normalize_role(current_user)
    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if role not in ('teacher', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    if role == 'teacher' and not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    if not can_enter_class_grades(current_user, teacher_profile, class_id):
        flash('You are not authorized to enter grades for this class.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    subject_name = (request.form.get('subject') or '').strip()
    period = request.form.get('period', type=int)
    publish_action = (request.form.get('publish_action') or 'draft').strip().lower()
    publish_to_report = publish_action == 'publish'
    if not subject_name:
        flash('Please select a subject before saving scores.', 'danger')
        return redirect(url_for('grade_entry_class', class_id=class_id))
    if period not in range(1, 7):
        flash('This activity sheet is available for regular periods only.', 'danger')
        return redirect(url_for('grade_entry_class', class_id=class_id, subject=subject_name, period=period or 1))

    if role == 'teacher':
        allowed_subjects = get_assignable_subjects_for_class(
            teacher_profile, current_user, class_id
        )
        if subject_name not in allowed_subjects:
            flash('You are not assigned to teach that subject in this class.', 'danger')
            return redirect(url_for('grade_entry_class', class_id=class_id))

    roster = get_class_students_for_year(class_id, active_year)
    roster_ids = {student.id for student in roster}
    activity_keys = [key for key in request.form.getlist('activity_keys') if key]
    quick_assessment = None
    if 'quick' in activity_keys:
        quick_assessment = get_or_create_quick_entry_assessment(
            class_id, subject_name, period, active_year, teacher_profile
        )

    named_assessments = {}
    named_ids = []
    for key in activity_keys:
        if key == 'quick':
            continue
        try:
            named_ids.append(int(key))
        except (TypeError, ValueError):
            continue
    if named_ids:
        for assessment in Assessment.query.filter(Assessment.id.in_(named_ids)).all():
            named_assessments[assessment.id] = assessment

    saved_count = 0
    errors = []
    for activity_key in activity_keys:
        if activity_key == 'quick':
            assessment = quick_assessment
        else:
            try:
                assessment = named_assessments.get(int(activity_key))
            except (TypeError, ValueError):
                assessment = None
        if not assessment:
            continue
        if assessment.klass_id != class_id or assessment.academic_year_id != active_year.id:
            continue
        if (assessment.subject_name or '').strip() != subject_name:
            continue
        if (assessment.marking_period or 1) != period:
            continue

        max_score = assessment.max_score or 100.0
        for student in roster:
            score_raw = (request.form.get(f'score_{activity_key}_{student.id}') or '').strip()
            if score_raw == '':
                continue
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                errors.append(f'Invalid score for {student.full_name} in {assessment.title}.')
                continue
            if score < 0 or score > max_score:
                errors.append(
                    f'Score for {student.full_name} in {assessment.title} must be 0–{max_score}.'
                )
                continue
            _apply_activity_score(
                teacher_profile,
                assessment,
                student,
                score,
            )
            saved_count += 1

    if errors:
        for msg in errors[:3]:
            flash(msg, 'danger')
        if not saved_count:
            db.session.rollback()
            return redirect(url_for(
                'grade_entry_class',
                class_id=class_id,
                subject=subject_name,
                period=period,
            ))

    published_count = 0
    if publish_to_report:
        for grade in Grade.query.filter_by(
            class_id=class_id,
            subject=subject_name,
            academic_year_id=active_year.id,
        ).all():
            period_num = grade.marking_period or normalize_grade_period(grade.period)
            if period_num != period or grade.student_id not in roster_ids:
                continue
            if grade.is_finalized or grade.submitted or not _grade_has_entered_scores(grade):
                continue
            grade.submitted = True
            published_count += 1

    if publish_to_report and (saved_count or published_count):
        reconcile_grade_package_after_save(
            active_year.id, class_id, period, published=True, actor_id=current_user.id,
        )
    elif not publish_to_report:
        reconcile_grade_package_after_save(
            active_year.id, class_id, period, published=False, actor_id=current_user.id,
        )
    db.session.commit()
    period_label = grading_period_label(period)
    if publish_to_report:
        if saved_count or published_count:
            flash(
                f'Saved {saved_count} activity score{"s" if saved_count != 1 else ""} and '
                f'published {published_count} final grade{"s" if published_count != 1 else ""} '
                f'for {subject_name} · {period_label}. {GRADE_RELEASE_TEACHER_FLASH}',
                'success',
            )
        else:
            flash('No activity scores or draft grades were ready to publish.', 'warning')
    else:
        if saved_count:
            flash(
                f'Saved {saved_count} activity score{"s" if saved_count != 1 else ""} '
                f'for {subject_name} · {period_label}. Student draft standing updated.',
                'success',
            )
        else:
            flash('No scores entered. Fill in at least one activity field.', 'warning')

    return redirect(url_for(
        'grade_entry_class',
        class_id=class_id,
        subject=subject_name,
        period=period,
    ))


def _parse_grade_component_scores(grade):
    """Return stored component breakdown from a Grade row."""
    if not grade or not grade.component_scores:
        return {}
    try:
        data = json.loads(grade.component_scores)
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def build_grade_component_rows(grade_rows):
    """Map student_id -> component field values for grade-entry templates."""
    rows = {}
    for student_id, grade in (grade_rows or {}).items():
        comps = _parse_grade_component_scores(grade)
        row = {}
        for key in PERIOD_COMPONENT_MAXIMA:
            val = comps.get(key)
            if val is not None and val != '':
                row[key] = val
        direct_total = comps.get('direct_total')
        if direct_total is not None and direct_total != '':
            row['direct_total'] = direct_total
        if row:
            rows[student_id] = row
    return rows


def _period_component_label(component_key):
    for spec_key, _code, label, _max_score in PERIOD_COMPONENT_SPECS:
        if spec_key == component_key:
            return label
    return component_key.replace('_', ' ').title()


def _positive_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _listed_max_for_component(component_key, form=None):
    """Listed activity max from the official sheet; never below the UI-posted max."""
    listed_max = PERIOD_COMPONENT_MAXIMA.get(component_key)
    posted = _positive_float(form.get(f'component_max_{component_key}')) if form is not None else None
    if listed_max is None and posted is None:
        return None
    if listed_max is None:
        return posted
    listed_max = float(listed_max)
    if posted is not None:
        listed_max = max(listed_max, posted)
    return listed_max


def _component_field_max(form=None):
    """Hard cap for an activity input. Teachers may exceed the listed weight up to this."""
    posted = _positive_float(form.get('component_field_max')) if form is not None else None
    if posted is not None:
        return max(posted, PERIOD_COMPONENT_FIELD_MAX)
    return PERIOD_COMPONENT_FIELD_MAX


def _validate_period_component_score(component_key, score_val, student_name, form=None):
    field_max = _component_field_max(form)
    if score_val < 0:
        return f'Invalid {_period_component_label(component_key)} score for {student_name}.'
    if score_val > field_max:
        return (
            f'Invalid {_period_component_label(component_key)} score for {student_name}. '
            f'Max in this field is {field_max:g}.'
        )
    return None


def _redirect_after_save_grades(class_id, subject_name, period):
    """Stay on the sheet the teacher posted from (dashboard vs grade-entry)."""
    return_to = (request.form.get('return_to') or '').strip()
    if return_to == 'grading_hub':
        return redirect(
            url_for(
                'class_grading_hub',
                class_id=class_id,
                subject=subject_name,
                period=period,
                hub_tab='moe',
            )
        )
    if return_to == 'manual_activity_grades':
        return redirect(
            url_for(
                'manual_activity_grades',
                class_id=class_id,
                subject=subject_name,
                period=period,
            )
        )
    if return_to in ('teacher_dashboard', 'teacher_grade_sheet'):
        return redirect(
            url_for(
                'teacher_dashboard',
                grade_class_id=class_id,
                grade_subject=subject_name,
                grade_period=period,
            )
        )
    return redirect(
        url_for(
            'grade_entry_class',
            class_id=class_id,
            subject=subject_name,
            period=period,
        )
    )


def _resolve_period_weights(form, klass):
    scheme = getattr(klass, 'grading_scheme', None)
    ca_weight_raw = form.get('ca_weight')
    exam_weight_raw = form.get('exam_weight')
    if ((ca_weight_raw or '').strip() == '' and (exam_weight_raw or '').strip() == '') and scheme and isinstance(scheme, dict):
        try:
            ca_weight = float(scheme.get('ca_weight', 60))
            exam_weight = float(scheme.get('exam_weight', 40))
        except Exception:
            ca_weight, exam_weight = 60.0, 40.0
    else:
        try:
            ca_weight = float(ca_weight_raw or (scheme.get('ca_weight', 60) if scheme else 60))
            exam_weight = float(exam_weight_raw or (scheme.get('exam_weight', 40) if scheme else 40))
        except Exception:
            ca_weight, exam_weight = 60.0, 40.0
    return ca_weight, exam_weight


def _parse_student_period_grade_from_form(student, form, klass, period):
    """Parse one student's period grade from POST fields."""
    if period not in range(1, 7):
        exam_raw = (form.get(f'exam_{student.id}') or '').strip()
        if exam_raw == '':
            return {'skip': True}, None
        try:
            exam_score = float(exam_raw)
        except ValueError:
            return None, f'Invalid exam score for {student.full_name}.'
        if exam_score < 0 or exam_score > 100:
            return None, (
                f'Invalid exam score for {student.full_name}. Score must be between 0 and 100.'
            )
        return {
            'skip': False,
            'ca_score': 0.0,
            'exam_score': exam_score,
            'total': exam_score,
            'component_scores_json': None,
        }, None

    direct_raw = (form.get(f'direct_total_{student.id}') or '').strip()
    ca_raw = (form.get(f'ca_{student.id}') or '').strip()
    exam_raw = (form.get(f'exam_{student.id}') or '').strip()
    component_values = {}
    has_component_input = False
    for component_key in PERIOD_COMPONENT_MAXIMA:
        raw_val = (form.get(f'{component_key}_{student.id}') or '').strip()
        component_values[component_key] = raw_val
        if raw_val != '':
            has_component_input = True

    if direct_raw == '' and not has_component_input and ca_raw == '' and exam_raw == '':
        return {'skip': True}, None

    stored_components = {}

    if direct_raw != '':
        try:
            direct_total = float(direct_raw)
        except ValueError:
            return None, f'Invalid direct period grade for {student.full_name}.'
        if direct_total < 0 or direct_total > PERIOD_TOTAL_EXTRA_CREDIT_MAX:
            return None, (
                f'Invalid direct period grade for {student.full_name}. '
                f'Must be between 0 and {int(PERIOD_TOTAL_EXTRA_CREDIT_MAX)}.'
            )
        stored_components['direct_total'] = direct_total
        total = direct_total
        ca_score = direct_total
        exam_score = 0.0
        if has_component_input:
            for component_key, raw_val in component_values.items():
                if raw_val == '':
                    continue
                try:
                    score_val = float(raw_val)
                except ValueError:
                    return None, f'Invalid {_period_component_label(component_key)} score for {student.full_name}.'
                err = _validate_period_component_score(
                    component_key, score_val, student.full_name, form,
                )
                if err:
                    return None, err
                stored_components[component_key] = score_val
    elif has_component_input:
        ca_score = 0.0
        for component_key, raw_val in component_values.items():
            if raw_val == '':
                continue
            try:
                score_val = float(raw_val)
            except ValueError:
                return None, f'Invalid {_period_component_label(component_key)} score for {student.full_name}.'
            err = _validate_period_component_score(
                component_key, score_val, student.full_name, form,
            )
            if err:
                return None, err
            stored_components[component_key] = score_val
            ca_score += score_val
        total = ca_score
        exam_score = 0.0
    else:
        try:
            ca_score = float(ca_raw or 0)
            exam_score = float(exam_raw or 0)
        except ValueError:
            return None, f'Invalid scores for {student.full_name}.'
        ca_weight, exam_weight = _resolve_period_weights(form, klass)
        total = SchoolEngine.calculate_period_total(
            ca_score, exam_score, ca_weight=ca_weight, exam_weight=exam_weight,
        )
        if total is None:
            return None, (
                f'Invalid scores for {student.full_name}. CA must be ≤ 60 and Exam ≤ 40.'
            )

    component_scores_json = json.dumps(stored_components) if stored_components else None
    return {
        'skip': False,
        'ca_score': ca_score,
        'exam_score': exam_score,
        'total': total,
        'component_scores_json': component_scores_json,
    }, None


def teacher_is_viewing_archived_year():
    """True when the teacher dashboard year picker is not the active session."""
    _display, _active, _years, viewing_archived = resolve_dashboard_academic_year(
        session_key=TEACHER_YEAR_SESSION_KEY,
    )
    return viewing_archived


@app.route('/save-grades/<int:class_id>', methods=['POST'])
@login_required
def save_grades(class_id):
    if normalize_role(current_user) != 'teacher':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    if not teacher_can_access_class(teacher, current_user, class_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found. Please contact the administrator.', 'danger')
        return redirect(url_for('grade_entry_class', class_id=class_id))

    if teacher_is_viewing_archived_year():
        flash(
            'Grade entry is read-only for archived academic years. '
            'Switch to the active year before saving scores.',
            'warning',
        )
        return _redirect_after_save_grades(
            class_id,
            (request.form.get('subject') or '').strip(),
            request.form.get('period', type=int) or 1,
        )

    subject_name = (request.form.get('subject') or '').strip()
    period = request.form.get('period', type=int)
    publish_action = (request.form.get('publish_action') or 'draft').strip().lower()
    publish_to_report = publish_action == 'publish'
    if not subject_name:
        flash('Please select a subject before saving grades.', 'danger')
        return redirect(url_for('grade_entry_class', class_id=class_id))
    if period not in range(1, 9):
        flash('Invalid marking period selected.', 'danger')
        return redirect(url_for('grade_entry_class', class_id=class_id, subject=subject_name))

    allowed_subjects = get_assignable_subjects_for_class(teacher, current_user, class_id)
    if subject_name not in allowed_subjects:
        flash('You are not assigned to teach that subject in this class.', 'danger')
        return redirect(url_for('grade_entry_class', class_id=class_id))

    students = get_class_students_for_year(class_id, active_year)
    period_label = grading_period_label(period)
    saved_count = 0

    for student in students:
        parsed, err = _parse_student_period_grade_from_form(student, request.form, klass, period)
        if err:
            flash(err, 'danger')
            return _redirect_after_save_grades(class_id, subject_name, period)
        if parsed.get('skip'):
            continue

        ca_score = parsed['ca_score']
        exam_score = parsed['exam_score']
        total = parsed['total']

        grade = find_grade_record(
            student.id,
            subject_name,
            period,
            class_id=class_id,
            academic_year_id=active_year.id,
        )

        if grade and grade.is_finalized:
            flash(f'Grades for {student.full_name} are finalized and cannot be changed.', 'warning')
            continue

        if not grade:
            grade = Grade(
                student_id=student.id,
                teacher_id=teacher.id,
                class_id=class_id,
                academic_year_id=active_year.id,
                subject=subject_name,
                subject_name=subject_name,
            )
            db.session.add(grade)

        grade.teacher_id = teacher.id
        grade.class_id = class_id
        grade.academic_year_id = active_year.id
        grade.subject = subject_name
        grade.subject_name = subject_name
        grade.marking_period = period
        grade.period = period
        grade.activity_type = 'Semester Exam' if period in (7, 8) else 'Period Assessment'
        grade.ca_score = ca_score
        grade.exam_score = exam_score if period in range(1, 7) else total
        grade.score = total
        grade.component_scores = parsed.get('component_scores_json')
        grade.remarks = SchoolEngine.get_remarks(total)
        grade.submitted = publish_to_report

        if 1 <= period <= 6:
            setattr(grade, f'p{period}', int(round(total)))

        saved_count += 1

    if saved_count:
        reconcile_grade_package_after_save(
            active_year.id, class_id, period, published=publish_to_report,
            actor_id=current_user.id,
        )
    db.session.commit()
    if saved_count:
        if publish_to_report:
            flash(
                f'{period_label} grades published for {subject_name}. {GRADE_RELEASE_TEACHER_FLASH}',
                'success',
            )
        else:
            flash(f'{period_label} draft saved for {subject_name}. Students can see their standing; report cards unchanged.', 'success')
    else:
        flash('No grade values were entered.', 'warning')

    return _redirect_after_save_grades(class_id, subject_name, period)


def _persist_period_grades_from_form(
    class_id,
    subject_name,
    period,
    publish_to_report,
    *,
    teacher_id,
    entered_by_user_id=None,
    entered_by_role=None,
):
    """Save MoE period grades from POST form fields (ca_{id}, exam_{id})."""
    active_year = get_active_academic_year()
    if not active_year:
        return 0, 'No active academic year found. Please contact the administrator.'

    klass = Class.query.get(class_id)
    students = get_class_students_for_year(class_id, active_year)
    saved_count = 0

    for student in students:
        parsed, err = _parse_student_period_grade_from_form(student, request.form, klass, period)
        if err:
            return 0, err
        if parsed.get('skip'):
            continue

        ca_score = parsed['ca_score']
        exam_score = parsed['exam_score']
        total = parsed['total']

        grade = find_grade_record(
            student.id,
            subject_name,
            period,
            class_id=class_id,
            academic_year_id=active_year.id,
        )
        if grade and grade.is_finalized:
            continue

        if not grade:
            grade = Grade(
                student_id=student.id,
                teacher_id=teacher_id,
                class_id=class_id,
                academic_year_id=active_year.id,
                subject=subject_name,
                subject_name=subject_name,
            )
            db.session.add(grade)

        grade.teacher_id = teacher_id
        grade.class_id = class_id
        grade.academic_year_id = active_year.id
        grade.subject = subject_name
        grade.subject_name = subject_name
        grade.marking_period = period
        grade.period = period
        grade.activity_type = 'Semester Exam' if period in (7, 8) else 'Period Assessment'
        grade.ca_score = ca_score
        grade.exam_score = exam_score if period in range(1, 7) else total
        grade.score = total
        grade.component_scores = parsed.get('component_scores_json')
        grade.remarks = SchoolEngine.get_remarks(total)
        grade.submitted = publish_to_report
        if entered_by_user_id is not None:
            grade.entered_by_user_id = entered_by_user_id
        if entered_by_role:
            grade.entered_by_role = entered_by_role
        if 1 <= period <= 6:
            setattr(grade, f'p{period}', int(round(total)))
        saved_count += 1

    if saved_count:
        reconcile_grade_package_after_save(
            active_year.id,
            class_id,
            period,
            published=publish_to_report,
            actor_id=entered_by_user_id,
        )
    db.session.commit()
    return saved_count, None


@app.route('/teacher/class/<int:class_id>/publish-grades', methods=['POST'])
@login_required
def publish_period_grades(class_id):
    """Publish existing draft period grades without re-entering scores."""
    role = normalize_role(current_user)
    teacher = Teacher.query.filter_by(user_id=current_user.id).first()
    if role not in ('teacher', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    if role == 'teacher' and not teacher:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    if role == 'teacher' and not teacher_can_access_class(teacher, current_user, class_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    subject_name = (request.form.get('subject') or '').strip()
    period = request.form.get('period', type=int)
    if not subject_name or period not in range(1, 9):
        flash('Subject and marking period are required.', 'danger')
        return redirect(url_for('class_grading_hub', class_id=class_id))

    if role == 'teacher':
        allowed_subjects = get_assignable_subjects_for_class(teacher, current_user, class_id)
        if subject_name not in allowed_subjects:
            flash('You are not assigned to teach that subject in this class.', 'danger')
            return redirect(url_for('class_grading_hub', class_id=class_id))

    students = Student.query.filter_by(
        klass_id=class_id, academic_year_id=active_year.id
    ).all()
    student_ids = {s.id for s in students}
    published_count = 0

    for grade in Grade.query.filter_by(
        class_id=class_id,
        subject=subject_name,
        academic_year_id=active_year.id,
    ).all():
        period_num = grade.marking_period or normalize_grade_period(grade.period)
        if period_num != period or grade.student_id not in student_ids:
            continue
        if grade.is_finalized or grade.submitted or not _grade_has_entered_scores(grade):
            continue
        grade.submitted = True
        published_count += 1

    if published_count:
        reconcile_grade_package_after_save(
            active_year.id, class_id, period, published=True, actor_id=current_user.id,
        )
    db.session.commit()
    period_label = grading_period_label(period)
    if published_count:
        flash(
            f'Published {published_count} {period_label} grade{"s" if published_count != 1 else ""} '
            f'for {subject_name}. {GRADE_RELEASE_TEACHER_FLASH}',
            'success',
        )
    else:
        flash('No draft grades with scores were found to publish.', 'warning')

    return_to = (request.form.get('return_to') or 'grading_hub').strip()
    if return_to == 'teacher_dashboard':
        return redirect(url_for(
            'teacher_dashboard',
            tab='grades',
            grade_class_id=class_id,
            grade_subject=subject_name,
            grade_period=period,
        ))
    if return_to == 'manual_activity_grades':
        return redirect(url_for(
            'manual_activity_grades',
            class_id=class_id,
            subject=subject_name,
            period=period,
        ))
    return redirect(url_for(
        'class_grading_hub',
        class_id=class_id,
        subject=subject_name,
        period=period,
        hub_tab='moe',
    ))


@app.route('/download-grades/<int:class_id>')
@login_required
def download_grades(class_id):
    role = normalize_role(current_user)
    if role not in ('registrar', 'teacher', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    if role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=current_user.id).first()
        if not teacher or not teacher_can_access_class(teacher, current_user, class_id):
            flash('Access denied.', 'danger')
            return redirect(url_for('login'))

    year_name = request.args.get('year')
    active_year = find_academic_year_by_name(year_name) if year_name else None
    if not active_year:
        active_year = get_active_academic_year()
    if not active_year:
        flash('No academic year found for export.', 'warning')
        return redirect(url_for('login'))

    subject = (request.args.get('subject') or '').strip()
    period = request.args.get('period', type=int)

    grades_query = Grade.query.filter_by(
        class_id=class_id,
        academic_year_id=active_year.id,
    )
    if subject:
        grades_query = grades_query.filter(Grade.subject == subject)
    if period:
        grades_query = grades_query.filter(Grade.marking_period == period)

    grades = grades_query.order_by(
        Grade.subject.asc(),
        Grade.marking_period.asc(),
        Grade.student_id.asc(),
    ).all()
    student_ids = {g.student_id for g in grades if g.student_id}
    student_map = {
        s.id: s for s in Student.query.filter(Student.id.in_(student_ids)).all()
    } if student_ids else {}

    def generate():
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            'Student ID', 'Student Name', 'Subject', 'Period',
            'CA Score', 'Exam Score', 'Total', 'Grade Letter', 'Published',
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for grade in grades:
            student = student_map.get(grade.student_id)
            writer.writerow([
                student.student_id if student else grade.student_id,
                student.full_name if student else '',
                grade.subject or grade.subject_name or '',
                grade.marking_period or grade.period or '',
                grade.ca_score if grade.ca_score is not None else '',
                grade.exam_score if grade.exam_score is not None else '',
                grade.score if grade.score is not None else '',
                SchoolEngine.get_grade_letter(grade.score or 0),
                'Yes' if grade.submitted else 'No',
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    safe_class = (klass.name or f'class_{class_id}').replace(' ', '_')[:40]
    filename = f'grades_{safe_class}_{active_year.name}.csv'
    return Response(
        generate(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )

@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    return safe_send_upload_file('uploads/activities', filename)


@app.route('/teacher/download-activity/<int:assessment_id>')
@login_required
def teacher_download_activity(assessment_id):
    """Let teachers download the assignment file they attached to an activity."""
    if normalize_role(current_user) != 'teacher':
        flash('Only teachers can download activity resources.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    assessment = Assessment.query.get_or_404(assessment_id)
    klass = assessment.klass
    if not klass or not teacher_can_access_class(teacher_profile, current_user, klass.id):
        flash('You are not authorized to access this activity.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if not assessment.file_name:
        flash('No assignment file was attached to this activity.', 'warning')
        return redirect(url_for('activity_detail', assessment_id=assessment.id))

    return safe_send_upload_file('uploads/activities', assessment.file_name)


@app.route('/student/download-activity/<int:assessment_id>')
@login_required
def student_download_activity(assessment_id):
    """Let a student download the teacher's assignment file for an activity."""
    if normalize_role(current_user) != 'student':
        flash('Only students can download class activities.', 'danger')
        return redirect(url_for('login'))

    student = get_student_for_user(current_user)
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('login'))

    assessment = Assessment.query.get_or_404(assessment_id)
    class_id = get_student_class_id(student)
    if class_id != assessment.klass_id:
        flash('You are not authorized to access this activity.', 'danger')
        return redirect(url_for('student_dashboard'))

    if not assessment.file_name:
        flash('No assignment file was attached to this activity.', 'warning')
        return redirect(url_for('student_dashboard'))

    return safe_send_upload_file('uploads/activities', assessment.file_name)


@app.route('/student/download-submission/<int:assessment_id>')
@login_required
def student_download_submission(assessment_id):
    """Let a student download their own submitted work."""
    if normalize_role(current_user) != 'student':
        flash('Only students can download submissions.', 'danger')
        return redirect(url_for('login'))

    student = get_student_for_user(current_user)
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('login'))

    assessment = Assessment.query.get_or_404(assessment_id)
    class_id = get_student_class_id(student)
    if class_id != assessment.klass_id:
        flash('You are not authorized to access this submission.', 'danger')
        return redirect(url_for('student_dashboard'))

    submission = Submission.query.filter_by(
        assessment_id=assessment_id,
        student_id=student.id,
    ).first()
    if not submission or not submission.file_path:
        flash('You have not uploaded a file for this activity yet.', 'warning')
        return redirect(url_for('student_dashboard'))

    rel_path = submission.file_path.replace('\\', '/').lstrip('/')
    if rel_path.startswith('static/'):
        rel_path = rel_path[len('static/'):]
    return safe_send_upload_file(os.path.dirname(rel_path), os.path.basename(rel_path))

@app.route('/student/upload/<int:assessment_id>', methods=['POST'])
@app.route('/student/upload/activity/<int:assessment_id>', methods=['POST'])
@login_required
def student_upload(assessment_id):
    if normalize_role(current_user) != 'student':
        flash('Only students can upload activities.', 'danger')
        return redirect(url_for('login'))

    student = get_student_for_user(current_user)
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('login'))

    if 'assignment' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('student_dashboard'))
    
    file = request.files['assignment']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('student_dashboard'))

    assessment = Assessment.query.get_or_404(assessment_id)
    if get_student_class_id(student) != assessment.klass_id:
        flash('You are not authorized to submit for this class activity.', 'danger')
        return redirect(url_for('student_dashboard'))

    upload_dir = os.path.join(BASE_DIR, 'static', 'uploads', 'submissions')
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"sub_{assessment_id}_{student.id}_{secure_filename(file.filename)}"
    file_path = os.path.join(upload_dir, filename)
    file.save(file_path)

    submission_db_path = os.path.join('uploads', 'submissions', filename).replace('\\', '/')
    submission = Submission.query.filter_by(assessment_id=assessment_id, student_id=student.id).first()
    if submission:
        submission.file_path = submission_db_path
        submission.submitted_at = datetime.now(timezone.utc)
    else:
        submission = Submission(
            assessment_id=assessment_id,
            student_id=student.id,
            file_path=submission_db_path
        )
        db.session.add(submission)

    db.session.commit()
    flash('Activity uploaded successfully!', 'success')
    return redirect(url_for('student_dashboard', tab='tasks'))

@app.route('/student/submit-activity/<int:assessment_id>', methods=['POST'])
@login_required
def submit_activity(assessment_id):
    if normalize_role(current_user) != 'student':
        flash('Only students can submit activities.', 'danger')
        return redirect(url_for('login'))

    student = get_student_for_user(current_user)
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('login'))

    assessment = Assessment.query.get_or_404(assessment_id)
    if get_student_class_id(student) != assessment.klass_id:
        flash('You are not authorized to submit for this class activity.', 'danger')
        return redirect(url_for('student_dashboard'))

    quiz_answers = request.form.get('quiz_answers', '').strip()
    if not quiz_answers:
        flash('Please provide answers before submitting.', 'danger')
        return redirect(url_for('student_dashboard'))

    if assessment.submission_mode != 'text_entry':
        flash('This activity does not accept text submissions.', 'danger')
        return redirect(url_for('student_dashboard'))

    submission = Submission.query.filter_by(assessment_id=assessment_id, student_id=student.id).first()
    if submission:
        submission.submission_text = quiz_answers
        submission.submitted_at = datetime.now(timezone.utc)
    else:
        submission = Submission(
            assessment_id=assessment_id,
            student_id=student.id,
            submission_text=quiz_answers
        )
        db.session.add(submission)

    db.session.commit()
    flash('Text submission received successfully!', 'success')
    return redirect(url_for('student_dashboard', tab='tasks'))

@app.route('/teacher/activity/<int:assessment_id>')
@app.route('/teacher/assessment/<int:assessment_id>')
@login_required
def activity_detail(assessment_id):
    if normalize_role(current_user) != 'teacher':
        flash('Only teachers can view activity review pages.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    assessment = Assessment.query.get_or_404(assessment_id)
    klass = assessment.klass
    if not klass or not teacher_can_access_class(teacher_profile, current_user, klass.id):
        flash('You are not authorized to review this activity.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    class_students = sorted(
        get_students_for_class_ids([klass.id]),
        key=lambda s: ((s.last_name or '').lower(), (s.first_name or '').lower()),
    )
    submissions = Submission.query.filter_by(assessment_id=assessment.id).all()
    submission_by_student = {sub.student_id: sub for sub in submissions}
    pending_grades = sum(
        1 for sub in submissions if not sub.is_graded and (sub.file_path or sub.submission_text)
    )
    active_year = get_active_academic_year()
    scan_keyword_list = parse_scan_keywords(assessment.scan_keywords)

    return render_template(
        'activity_detail.html',
        activity=assessment,
        assessment=assessment,
        submissions=submissions,
        class_students=class_students,
        submission_by_student=submission_by_student,
        pending_grades=pending_grades,
        current_user=current_user,
        active_year=active_year,
        scan_keyword_list=scan_keyword_list,
    )

@app.route('/finalize-grades/<int:class_id>', methods=['POST'])
@login_required
def finalize_grades(class_id):
    if normalize_role(current_user) != 'registrar':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    
    klass = Class.query.get_or_404(class_id)
    active_year = get_active_academic_year()
    grade_query = Grade.query.filter_by(class_id=class_id)
    if active_year:
        grade_query = grade_query.filter_by(academic_year_id=active_year.id)
    grades = grade_query.all()
    for grade in grades:
        grade.is_finalized = True
    
    db.session.commit()
    flash('Grades finalized for this class.', 'success')
    return redirect(url_for('login'))
#--------------------------------------------
#Report card generation and download
#--------------------------------------------
def format_student_school_level(student):
    """Return the academic level label shown on report cards."""
    if student.level:
        return student.level
    grade = student.grade_level
    if grade is None and student.klass:
        grade = student.klass.grade_level
    if grade is not None:
        return f"Grade {grade}"
    return "Not Set"


@app.route('/report-card/<int:student_id>')
@login_required
def report_card(student_id):
    student = Student.query.get_or_404(student_id)
    
    staff_roles = {'admin', 'teacher', 'registrar', 'principal', 'vpa', 'vpi', 'dean', 'business'}
    user_role = (current_user.role or '').lower()
    if user_role == 'student':
        linked_student = get_student_for_user(current_user)
        if not linked_student or linked_student.id != student.id:
            flash('Access denied.', 'danger')
            return redirect(url_for('login'))
    elif user_role == 'parent':
        if student.parent_email != current_user.email:
            flash('Access denied.', 'danger')
            return redirect(url_for('login'))
    elif user_role not in staff_roles:
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    if user_role == 'teacher':
        teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
        if not teacher_profile or not teacher_can_access_student(teacher_profile, current_user, student):
            flash('You may only view report cards for students in your assigned classes.', 'danger')
            return redirect(url_for('teacher_dashboard'))
    
    active_year = get_active_academic_year()
    year_id = request.args.get('academic_year_id', type=int) or (active_year.id if active_year else None)
    display_year = db.session.get(AcademicYear, year_id) if year_id else None
    student_facing = (
        user_role in ('student', 'parent') or not viewer_can_see_unreleased_official_grades()
    )
    if student_facing:
        doc_state = student_official_documents_state(student, year_id)
        if not doc_state.get('report_card_unlocked'):
            return render_official_grade_hold(
                student, display_year,
                hold_title='Report Card not yet issued',
                hold_message=STUDENT_REPORT_CARD_HOLD_MESSAGE,
                hold_meta=doc_state.get('report_card_blocker_note'),
            )
    data = build_report_card_structured_data(
        student, year_id, approved_only=student_facing,
    )

    return render_template(
        'report_card.html',
        student=student,
        data=data,
        display_year=display_year,
        parent_qr_view=False,
        school_print_brand=school_print_brand(),
        **build_parent_report_qr_context(student, year_id),
    )

@app.route('/download-report-card/<int:student_id>')
def download_report_card(student_id):
    student = Student.query.get_or_404(student_id)
    
    staff_roles = {'admin', 'teacher', 'registrar', 'principal', 'vpa', 'vpi', 'dean', 'business'}
    active_year = get_active_academic_year()
    year_id = request.args.get('academic_year_id', type=int) or (active_year.id if active_year else None)
    data = build_report_card_structured_data(student, year_id)
    parent_qr_access = has_parent_report_access(student.id, year_id)

    if not parent_qr_access:
        if not current_user.is_authenticated:
            abort(403)
        user_role = (current_user.role or '').lower()
        if (user_role not in staff_roles and 
            student.user_id != current_user.id and 
            (user_role != 'parent' or student.parent_email != current_user.email)):
            abort(403)
        if user_role == 'teacher':
            teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
            if not teacher_profile or not teacher_can_access_student(teacher_profile, current_user, student):
                abort(403)
        if not student.tuition_cleared and user_role not in {'admin', 'teacher', 'registrar', 'principal'}:
            pass

    is_staff_preview = viewer_can_see_unreleased_official_grades() and not parent_qr_access
    if not is_staff_preview:
        doc_state = student_official_documents_state(student, year_id)
        if not doc_state.get('report_card_unlocked'):
            display_year = db.session.get(AcademicYear, year_id) if year_id else None
            return render_official_grade_hold(
                student, display_year,
                hold_title='Report Card not yet issued',
                hold_message=STUDENT_REPORT_CARD_HOLD_MESSAGE,
                hold_meta=doc_state.get('report_card_blocker_note'),
            )

    return build_official_grade_sheet_pdf(
        student, year_id, kind='report', approved_only=not is_staff_preview,
    )


@app.route('/grades/period-sheet/<int:class_id>/<int:period>')
@login_required
def class_period_grade_sheet(class_id, period):
    """Printable roster: every student in one class, one marking period.

    VPA/principal/admin see the sheet as soon as the teacher submits it, so
    they can review before approving. Teachers see only their own classes.
    Once approved it stays visible; a return/edit puts it back on hold.
    """
    role = normalize_role(current_user)
    if period not in range(1, 9):
        flash('Unknown marking period.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    if role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=current_user.id).first()
        if not teacher or not teacher_can_access_class(teacher, current_user, class_id):
            flash('You may only view the grade sheet for your assigned classes.', 'danger')
            return redirect(url_for('teacher_dashboard'))
    elif role not in ACADEMIC_COMMAND_ROLES:
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    active_year = get_active_academic_year()
    year_id = request.args.get('academic_year_id', type=int) or (active_year.id if active_year else None)
    if not year_id:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('login'))

    data = build_class_period_grade_sheet_data(class_id, period, year_id, approved_only=False)
    if not data.get('klass'):
        flash('No roster found for that class and academic year.', 'danger')
        return redirect(url_for('login'))

    return render_template(
        'class_period_grade_sheet.html',
        data=data,
        klass=klass,
        period=period,
        display_year=data.get('display_year'),
        school_print_brand=school_print_brand(),
        can_review=role in ACADEMIC_COMMAND_ROLES,
    )


def build_student_record_summaries(student):
    """Published-grade academic years for held-portal history cards."""
    if not student:
        return []

    year_ids = [
        row[0]
        for row in db.session.query(Grade.academic_year_id)
        .filter(
            Grade.student_id == student.id,
            Grade.submitted.is_(True),
            Grade.academic_year_id.isnot(None),
        )
        .distinct()
        .all()
        if row[0]
    ]

    summaries = []
    for year_id in year_ids:
        year = db.session.get(AcademicYear, year_id)
        if not year:
            continue
        if not student_official_documents_state(student, year_id).get('unlocked'):
            continue
        grades = official_grade_records(student.id, year_id, approved_only=True)
        scores = [g.score for g in grades if g.score is not None]
        gpa = SchoolEngine.calculate_gpa(scores) if scores else 0.0
        summaries.append({
            'year': year,
            'gpa': gpa,
            'subject_count': len({g.subject for g in grades if g.subject}),
            'transcript_released': official_transcript_is_released(student.id, year.id),
        })
    summaries.sort(key=lambda item: item['year'].name, reverse=True)
    return summaries


def compile_registration_held_context(student, display_year=None):
    """Template context for the registration-held student portal."""
    active_year = get_active_academic_year()
    record_summaries = build_student_record_summaries(student)

    if display_year is None:
        requested_id = request.args.get('academic_year_id', type=int)
        if requested_id:
            display_year = db.session.get(AcademicYear, requested_id)

    grades = []
    gpa = 0.0
    if display_year:
        grades = official_grade_records(student.id, display_year.id, approved_only=True)
        scores = [g.score for g in grades if g.score is not None]
        gpa = SchoolEngine.calculate_gpa(scores) if scores else 0.0

    return {
        'student': student,
        'active_year': active_year,
        'display_year': display_year,
        'record_summaries': record_summaries,
        'grades': grades,
        'gpa': gpa,
        'klass': get_student_class_for_year(
            student,
            active_year.id if active_year else None,
        ),
    }


def compile_alumni_portal_context(student, display_year=None):
    """Template context for the alumni read-only student portal."""
    past_years = all_academic_years()
    graduation_year = db.session.get(AcademicYear, student.academic_year_id) if student.academic_year_id else None

    if display_year is None:
        requested_id = request.args.get('academic_year_id', type=int)
        if requested_id:
            display_year = db.session.get(AcademicYear, requested_id)
        elif graduation_year:
            display_year = graduation_year
        elif past_years:
            display_year = past_years[0]

    grades = []
    gpa = 0.0
    if display_year:
        grades = official_grade_records(student.id, display_year.id, approved_only=True)
        scores = [g.score for g in grades if g.score is not None]
        gpa = SchoolEngine.calculate_gpa(scores) if scores else 0.0

    return {
        'student': student,
        'graduation_year': graduation_year,
        'display_year': display_year,
        'past_years': past_years,
        'grades': grades,
        'gpa': gpa,
        'transcript_released': (
            official_transcript_is_released(student.id, display_year.id)
            if student and display_year else False
        ),
    }


@app.route('/student/dashboard', methods=['GET'])
@login_required
def student_dashboard():
    """
    Unified Student Dashboard Engine
    Handles historical continuity filtering, academic term matrix routing,
    financial contextual data loads, and localized assignment state tracking.
    """
    # Strict role verification barrier
    if (current_user.role or '').lower() != 'student':
        abort(403, description="Access restricted to student ledger signatures only.")

    try:
        # 1. Fetch core student identity profile
        student_profile = get_student_for_user(current_user)
        if student_profile:
            ensure_student_secure_qr_token(student_profile)
            if sync_student_class_assignment(student_profile) or db.session.is_modified(
                student_profile, include_collections=False
            ):
                db.session.commit()

        if student_profile and student_is_alumni(student_profile):
            ctx = compile_alumni_portal_context(student_profile)
            return render_template('student/alumni_portal.html', current_user=current_user, **ctx)

        if student_profile and student_registration_gate_active(student_profile):
            ctx = compile_registration_held_context(student_profile)
            return render_template('student/registration_held.html', current_user=current_user, **ctx)
        
        # 2. Extract full chronological record catalog for dropdown historical tracking
        past_years = all_academic_years()

        # 3. Handle historical continuity selection logic
        selected_year_id = request.args.get('academic_year_id', type=int)
        
        if selected_year_id:
            display_year = db.session.get(AcademicYear, selected_year_id)
        else:
            # Fallback seamlessly to system primary active year
            display_year = get_active_academic_year()
            # Emergency fallback rule if no terms are active in database
            if not display_year and past_years:
                display_year = past_years[0]

        if student_profile and not display_year and student_profile.academic_year_id:
            display_year = db.session.get(AcademicYear, student_profile.academic_year_id)

        if student_profile and display_year:
            active_tab = request.args.get('tab', 'grades')
            if active_tab not in ('grades', 'activities', 'tasks', 'account', 'attendance'):
                active_tab = 'grades'

            ctx = compile_student_dashboard_context(
                student_profile,
                display_year,
                request.args,
                active_tab=active_tab,
            )
            if ctx.get('pending_tasks') and request.args.get('tab') is None:
                active_tab = 'tasks'
                ctx = compile_student_dashboard_context(
                    student_profile,
                    display_year,
                    request.args,
                    active_tab=active_tab,
                )
        else:
            active_tab = request.args.get('tab', 'grades')
            if active_tab not in ('grades', 'activities', 'tasks', 'account', 'attendance'):
                active_tab = 'grades'
            ctx = compile_student_dashboard_context(None, display_year, request.args, active_tab=active_tab)

        return render_template(
            'dashboard_student.html',
            past_years=past_years,
            current_user=current_user,
            active_tab=active_tab,
            **ctx,
        )

    except Exception as e:
        logger.error(f"Critical error rendering student dashboard: {str(e)}", exc_info=True)
        abort(500, description="Internal Data Layer Synthesis Failure.")


@app.route('/student/records/<int:academic_year_id>', methods=['GET'])
@login_required
def student_academic_records(academic_year_id):
    """Read-only academic year view for gated students (registration pending)."""
    if (current_user.role or '').lower() != 'student':
        abort(403)

    student = get_student_for_user(current_user)
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('logout'))

    display_year = db.session.get(AcademicYear, academic_year_id)
    if not display_year:
        flash('Academic year not found.', 'warning')
        return redirect(url_for('student_dashboard'))

    if viewer_must_wait_for_transcript_release(student, display_year.id):
        return render_official_transcript_hold(student, display_year)

    return redirect(url_for(
        'transcript',
        student_id=student.id,
        academic_year_id=display_year.id,
    ))


@app.route('/verify-student/<token>', methods=['GET'])
def verify_student(token):
    """
    Public student identity verification (QR / barcode scan destination).
    Shows limited info; staff see expanded details when logged in.
    """
    token = (token or '').strip()
    if not token:
        abort(404)

    student = Student.query.filter_by(secure_qr_token=token).first()
    if not student:
        return render_template(
            'verify_student.html',
            verified=False,
            student=None,
            staff_view=False,
        )

    display_year = get_active_academic_year() or student.academic_year
    year_id = display_year.id if display_year else student.academic_year_id
    klass = get_student_class_for_year(student, year_id) if year_id else student.klass
    staff_view = False
    if current_user.is_authenticated:
        role = normalize_role(current_user)
        staff_view = role in {'admin', 'principal', 'registrar', 'teacher', 'business', 'sponsor'}

    registration_label = 'Registered' if student.is_registered else 'Pending'
    if student.status and str(student.status).upper() in ALUMNI_STATUSES:
        registration_label = 'Alumni'

    return render_template(
        'verify_student.html',
        verified=True,
        student=student,
        klass=klass,
        display_year=display_year,
        staff_view=staff_view,
        registration_label=registration_label,
        verify_url=build_student_verify_url(student),
        class_display_name=format_student_class_name(student, year_id) if year_id else None,
    )


def _portal_user_for_student(student):
    """Linked student portal User for an ID-card QR login."""
    if not student:
        return None
    if student.user_id:
        user = student.user or db.session.get(User, student.user_id)
        if user:
            return user
    if student.student_id:
        return resolve_user_for_login(student.student_id)
    return None


@app.route('/student/id-portal/<token>', methods=['GET', 'POST'])
def student_id_portal(token):
    """
    ID-card QR destination: student signs in on their phone and opens the portal.
    Password is still required so a lost card cannot open the account by itself.
    """
    token = (token or '').strip()
    if not token:
        abort(404)

    student = Student.query.filter_by(secure_qr_token=token).first()
    portal_user = _portal_user_for_student(student) if student else None
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    if request.args.get('switch') == '1' and current_user.is_authenticated:
        logout_user()
        flash('Signed out. Enter your student portal password to continue.', 'info')
        return redirect(url_for('student_id_portal', token=token))

    if current_user.is_authenticated and student and portal_user and current_user.id == portal_user.id:
        return redirect(url_for('student_dashboard'))

    if request.method == 'POST' and student and portal_user:
        if check_brute_force(ip):
            flash('Too many failed sign-in attempts. Please try again in 15 minutes.', 'danger')
            return render_template(
                'student/id_portal_gate.html',
                student=student,
                portal_user=portal_user,
                valid=True,
            )
        password = (request.form.get('password') or '').strip()
        settings = get_system_settings()
        if not settings.system_active and normalize_role(portal_user) != 'admin':
            flash('The system is on hold. Contact the school office.', 'danger')
        elif not portal_user.is_account_active():
            track_failed_attempt(ip, student.student_id)
            flash('This portal account is inactive. See the Registrar.', 'danger')
        elif portal_user.check_password(password):
            login_user(portal_user)
            log_incident('STUDENT_ID_QR_LOGIN')
            flash('Welcome to your student portal.', 'success')
            return redirect(url_for('student_dashboard'))
        else:
            track_failed_attempt(ip, student.student_id)
            flash('Incorrect password. Use the password for your student portal account.', 'danger')

    return render_template(
        'student/id_portal_gate.html',
        student=student,
        portal_user=portal_user,
        valid=bool(student),
        other_session=bool(
            current_user.is_authenticated
            and (not portal_user or current_user.id != portal_user.id)
        ),
    )


@app.route('/parent/report/<token>', methods=['GET', 'POST'])
def parent_report_gate(token):
    """Parent report access — verify with PIN or phone last 4, no dashboard login."""
    token = (token or '').strip()
    if not token:
        abort(404)

    student = Student.query.filter_by(parent_report_token=token).first()
    if not student:
        return render_template(
            'parent_report_gate.html',
            valid=False,
            student=None,
            form=ParentReportGateForm(),
        )

    persist_parent_report_token(student)

    active_year = get_active_academic_year()
    year_id = request.args.get('academic_year_id', type=int) or (active_year.id if active_year else None)
    display_year = db.session.get(AcademicYear, year_id) if year_id else None

    if has_parent_report_access(student.id, year_id):
        return redirect(url_for(
            'parent_report_view',
            token=token,
            academic_year_id=year_id,
        ))

    form = ParentReportGateForm()
    attempts_key = f'parent_report_attempts_{token}'
    attempts = session.get(attempts_key, 0)

    if request.method == 'POST' and form.validate_on_submit():
        if attempts >= PARENT_REPORT_MAX_ATTEMPTS:
            flash('Too many failed attempts. Please try again later or contact the school.', 'danger')
        elif not parent_report_access_configured(student):
            flash(
                'Parent access is not configured yet. Ask the registrar to set a parent phone or report PIN.',
                'warning',
            )
        else:
            method = (request.form.get('verify_method') or form.verify_method.data or 'pin').strip()
            verified = False
            if method == 'phone':
                verified = verify_parent_phone_last4(student, form.phone_last4.data)
                if not verified:
                    flash('Incorrect phone digits. Enter the last 4 digits of the parent phone on file.', 'danger')
            else:
                verified = verify_parent_report_pin(student, form.parent_pin.data)
                if not verified:
                    flash('Incorrect parent PIN. Check the PIN provided by the school.', 'danger')

            if verified:
                session.pop(attempts_key, None)
                grant_parent_report_access(student.id, year_id)
                return redirect(url_for(
                    'parent_report_view',
                    token=token,
                    academic_year_id=year_id,
                ))
            session[attempts_key] = attempts + 1
            session.modified = True

    phone_hint = parent_phone_last_four(student)
    return render_template(
        'parent_report_gate.html',
        valid=True,
        student=student,
        form=form,
        display_year=display_year,
        year_id=year_id,
        phone_hint_available=bool(phone_hint),
        pin_configured=bool(student.parent_report_pin_hash),
        attempts_remaining=max(0, PARENT_REPORT_MAX_ATTEMPTS - attempts),
    )


@app.route('/parent/report/<token>/view', methods=['GET'])
def parent_report_view(token):
    """Read-only report card after parent QR verification."""
    token = (token or '').strip()
    student = Student.query.filter_by(parent_report_token=token).first()
    if not student:
        abort(404)

    active_year = get_active_academic_year()
    year_id = request.args.get('academic_year_id', type=int) or (active_year.id if active_year else None)
    if not has_parent_report_access(student.id, year_id):
        return redirect(url_for(
            'parent_report_gate',
            token=token,
            academic_year_id=year_id,
        ))

    display_year = db.session.get(AcademicYear, year_id) if year_id else None
    doc_state = student_official_documents_state(student, year_id)
    if not doc_state.get('report_card_unlocked'):
        return render_official_grade_hold(
            student, display_year, parent_qr_view=True, parent_report_token=token,
            hold_title='Report Card not yet issued',
            hold_message=STUDENT_REPORT_CARD_HOLD_MESSAGE,
            hold_meta=doc_state.get('report_card_blocker_note'),
        )
    data = build_report_card_structured_data(student, year_id, approved_only=True)

    return render_template(
        'report_card.html',
        student=student,
        data=data,
        display_year=display_year,
        parent_qr_view=True,
        parent_report_token=token,
        school_print_brand=school_print_brand(),
        **build_parent_report_qr_context(student, year_id),
    )


@app.route('/student/grade-sheet', methods=['GET'])
@login_required
def student_grade_sheet():
    """Official published grade sheet for the logged-in student (year-aware)."""
    if (current_user.role or '').lower() != 'student':
        abort(403)

    student = get_student_for_user(current_user)
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('logout'))

    past_years = all_academic_years()
    selected_year_id = request.args.get('academic_year_id', type=int)
    if selected_year_id:
        display_year = db.session.get(AcademicYear, selected_year_id)
    else:
        display_year = get_active_academic_year()
        if not display_year and past_years:
            display_year = past_years[0]

    year_id = display_year.id if display_year else None
    view_period = _requested_marking_period()
    doc_state = student_official_documents_state(student, year_id, period=view_period)
    if doc_state.get('hold'):
        return render_official_grade_hold(
            student, display_year,
            hold_message=STUDENT_PERIOD_HOLD_MESSAGE if view_period else None,
        )
    view_period, semester = _resolve_sheet_scope(doc_state, view_period)
    data = build_report_card_structured_data(
        student, year_id, approved_only=True, view_period=view_period, semester=semester,
    )
    published_grades = official_grade_records(student.id, year_id, approved_only=True) if year_id else []
    has_published = bool(published_grades)
    approved_periods = doc_state.get('approved_periods') or []
    pending_periods = doc_state.get('pending_periods') or []

    return render_template(
        'grade_sheet.html',
        student=student,
        data=data,
        display_year=display_year,
        past_years=past_years,
        has_published=has_published,
        published_count=len(published_grades),
        approved_periods=approved_periods,
        pending_periods=pending_periods,
        grading_periods=GRADING_PERIODS,
        released_semesters=doc_state.get('released_semesters') or [],
        report_card_unlocked=doc_state.get('report_card_unlocked'),
        report_card_blocker_note=doc_state.get('report_card_blocker_note'),
        school_print_brand=school_print_brand(),
    )


def _official_sheet_score_display(value, *, empty_display='—'):
    if value in (None, ''):
        return empty_display
    if isinstance(value, str) and '%' in value:
        return value.strip()
    shown = display_report_score(value)
    if shown in (None, ''):
        return empty_display
    return str(shown)


def _official_sheet_score_color(value):
    from reportlab.lib import colors
    num = numeric_report_score(value)
    if num is None:
        return colors.HexColor('#64748b')
    if num < promotion_pass_score():
        return colors.HexColor('#b42318')
    return colors.HexColor('#1d4ed8')


def _official_sheet_pick(subject, *keys):
    for key in keys:
        if isinstance(subject, dict):
            value = subject.get(key)
        else:
            value = getattr(subject, key, None)
        if value not in (None, ''):
            return value
    return None


_DISPLAY_FONT = None


def register_display_font():
    """Register Algerian for the school name on official PDFs.

    Algerian ships with Windows/Office and is not redistributable, so a Linux
    server needs a copy at static/fonts/algerian.ttf. Falls back to Times-Bold,
    which is what these documents used before, so a missing font never breaks
    a report card.
    """
    global _DISPLAY_FONT
    if _DISPLAY_FONT:
        return _DISPLAY_FONT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    windir = os.environ.get('WINDIR') or r'C:\Windows'
    local_appdata = os.environ.get('LOCALAPPDATA') or ''
    candidates = [
        os.path.join(app.root_path, 'static', 'fonts', 'algerian.ttf'),
        os.path.join(windir, 'Fonts', 'ALGER.TTF'),
    ]
    if local_appdata:
        candidates.append(os.path.join(local_appdata, 'Microsoft', 'Windows', 'Fonts', 'ALGER.TTF'))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont('FLPADisplay', path))
            _DISPLAY_FONT = 'FLPADisplay'
            return _DISPLAY_FONT
        except Exception:
            logger.warning('Could not register Algerian from %s', path, exc_info=True)
    _DISPLAY_FONT = 'Times-Bold'
    return _DISPLAY_FONT


def build_official_grade_sheet_pdf(
    student, year_id, kind='sheet', *, approved_only=False, view_period=None, semester=None,
):
    """Landscape official FLPA grade sheet / report card (P1–P6 MoE matrix)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.units import mm
    from io import BytesIO

    data = build_report_card_structured_data(
        student, year_id, approved_only=approved_only,
        view_period=view_period, semester=semester,
    )
    brand = data.get('school') or school_print_brand()
    display_year = db.session.get(AcademicYear, year_id) if year_id else None
    year_label = data.get('academic_year') or (display_year.name if display_year else '')
    if kind == 'report':
        sheet_title = (data.get('division_report_title') or 'Report Card').upper()
        file_prefix = 'report_card'
    else:
        sheet_title = (data.get('division_sheet_title') or 'Grade Sheet').upper()
        file_prefix = 'grade_sheet'
    if data.get('scope_label'):
        sheet_title = f"{data['scope_label'].upper()} — {sheet_title}"
        slug = re.sub(r'[^a-z0-9]+', '_', data['scope_label'].lower()).strip('_')
        file_prefix = f'{file_prefix}_{slug}' if slug else file_prefix
    promotion_statement = (
        data['promotion']['label']
        if data.get('promotion') and data['promotion'].get('label')
        else 'Pending promotion decision'
    )
    if (data.get('promotion') or {}).get('code') == 'PROMOTED' and data['promotion'].get('promoted_to'):
        promotion_statement = f"Promoted to {data['promotion']['promoted_to']}"
    if data.get('promotion') and data['promotion'].get('reason'):
        promotion_statement = f"{promotion_statement} — {data['promotion']['reason']}"
    rank_label = (
        data['class_rank']['label']
        if data.get('class_rank') and data['class_rank'].get('label')
        else '—'
    )
    legend_rows = data.get('legend_rows') or [
        ('Excellent', '90 – 100', 'A'),
        ('Good', '80 – 89', 'B'),
        ('Fair', '70 – 79', 'C'),
        ('Failure', 'Below 70', 'D'),
    ]

    ink = colors.HexColor('#111111')
    brand_red = colors.HexColor(brand.get('brand_red') or '#c82828')

    buffer = BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=7 * mm,
        bottomMargin=7 * mm,
        title=f'{sheet_title} — {student.full_name}',
    )
    styles = getSampleStyleSheet()
    school_style = ParagraphStyle(
        'SheetSchool',
        parent=styles['Normal'],
        fontName=register_display_font(),
        fontSize=16,
        leading=19,
        alignment=TA_CENTER,
        textColor=brand_red,
    )
    contact_style = ParagraphStyle(
        'SheetContact',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=8.5,
        leading=11,
        alignment=TA_CENTER,
        textColor=ink,
    )
    year_style = ParagraphStyle(
        'SheetYear',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        textColor=brand_red,
    )
    title_style = ParagraphStyle(
        'SheetTitle',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=10,
        leading=13,
        alignment=TA_CENTER,
        textColor=ink,
    )
    meta_style = ParagraphStyle(
        'SheetMeta',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=8.5,
        leading=11,
        textColor=ink,
    )
    motto_style = ParagraphStyle(
        'SheetMotto',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=brand_red,
    )
    sign_style = ParagraphStyle(
        'SheetSign',
        parent=styles['Normal'],
        fontName='Times-Bold',
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
        textColor=ink,
    )

    elements = []
    logo_path = os.path.join(app.root_path, 'static', 'images', 'LOGO.png')
    if not os.path.exists(logo_path):
        alt = os.path.join(app.root_path, 'static', 'images', 'logo.png')
        if os.path.exists(alt):
            logo_path = alt
    logo = None
    if os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=18 * mm, height=18 * mm)
        except Exception:
            logo = None

    center_block = [
        Paragraph((brand.get('name') or 'Future Leaders Preparatory Academy').upper(), school_style),
        Paragraph(brand.get('full_address') or '', contact_style),
        Paragraph(brand.get('phones') or '', contact_style),
        Paragraph(brand.get('email_address') or brand.get('email') or '', contact_style),
    ]
    header_center = Table([[block] for block in center_block], colWidths=[220 * mm])
    header_center.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    header_row = [[logo or '', header_center, logo or '']]
    header = Table(header_row, colWidths=[22 * mm, 237 * mm, 22 * mm])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'CENTER'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header)
    elements.append(Spacer(1, 3 * mm))

    title_box = Table(
        [[Paragraph(sheet_title, title_style)]],
        colWidths=[72 * mm],
    )
    title_box.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, ink),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    title_row = Table(
        [['', title_box, Paragraph(f'Academic Year: {year_label}', year_style)]],
        colWidths=[70 * mm, 80 * mm, 131 * mm],
    )
    title_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(title_row)
    elements.append(Spacer(1, 2.5 * mm))

    def meta_cell(label, value):
        return Paragraph(
            f'<b>{label}:</b> {value or "—"}',
            meta_style,
        )

    meta = Table([[
        meta_cell('Name', data.get('student_name')),
        meta_cell('Class', data.get('class_name')),
        meta_cell('Gender', getattr(student, 'gender', None)),
        meta_cell('Promotion Statement', promotion_statement),
    ]], colWidths=[75 * mm, 55 * mm, 40 * mm, 111 * mm])
    meta.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.8, ink),
        ('INNERGRID', (0, 0), (-1, -1), 0.6, ink),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(meta)
    awaiting_note = data.get('awaiting_vpa_note')
    if awaiting_note:
        note_style = ParagraphStyle(
            'SheetAwaitingNote',
            parent=styles['Normal'],
            fontName='Times-Italic',
            fontSize=8,
            leading=10,
            textColor=ink,
        )
        elements.append(Spacer(1, 1.5 * mm))
        elements.append(Paragraph(awaiting_note, note_style))
    elements.append(Spacer(1, 2 * mm))

    headers = [
        (data.get('subject_heading') or 'SUBJECTS').upper(),
        'P1', 'P2', 'P3', 'EXAM', 'SEM.AVE',
        'P4', 'P5', 'P6', 'EXAM', 'SEM.AVE',
        'YRLY AVE', 'REMARKS',
    ]
    score_keys = [
        ('p1',),
        ('p2',),
        ('p3',),
        ('exam', 'exam1'),
        ('avg', 'sem1'),
        ('p4',),
        ('p5',),
        ('p6',),
        ('final_exam', 'exam2'),
        ('sem2_avg', 'sem2'),
        ('final_avg', 'yearly'),
    ]
    col_widths = [
        48 * mm, 16 * mm, 16 * mm, 16 * mm, 18 * mm, 22 * mm,
        16 * mm, 16 * mm, 16 * mm, 18 * mm, 22 * mm,
        24 * mm, 33 * mm,
    ]

    table_data = [headers]
    subjects = data.get('subjects') or []
    raw_score_grid = []
    for subject in subjects:
        row = [subject.get('name') if isinstance(subject, dict) else str(subject)]
        score_row = []
        empty_display = '' if isinstance(subject, dict) and subject.get('blank_empty') else '—'
        for keys in score_keys:
            raw = _official_sheet_pick(subject, *keys)
            score_row.append(raw)
            row.append(_official_sheet_score_display(raw, empty_display=empty_display))
        remark = _official_sheet_pick(subject, 'remark', 'remarks')
        if remark in (None, ''):
            row.append('' if isinstance(subject, dict) and subject.get('is_summary') else '—')
        else:
            row.append(remark)
        table_data.append(row)
        raw_score_grid.append(score_row + [remark])

    if len(table_data) == 1:
        table_data.append(['Published grades will appear after your teacher publishes period scores.'] + [''] * 12)

    grade_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.5),
        ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('FONTNAME', (0, 1), (0, -1), 'Times-Bold'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (1, 1), (-2, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (-1, 1), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.6, ink),
        ('BOX', (0, 0), (-1, -1), 0.9, ink),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), ink),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (0, -1), 5),
        ('RIGHTPADDING', (0, 0), (0, -1), 3),
        ('LEFTPADDING', (1, 0), (-1, -1), 2),
        ('RIGHTPADDING', (1, 0), (-1, -1), 2),
    ]
    for r, score_row in enumerate(raw_score_grid, start=1):
        for c, raw in enumerate(score_row, start=1):
            if c >= 12:
                yearly_raw = score_row[10] if len(score_row) > 10 else raw
                color = _official_sheet_score_color(yearly_raw)
            else:
                color = _official_sheet_score_color(raw)
            style_cmds.append(('TEXTCOLOR', (c, r), (c, r), color))
            style_cmds.append(('FONTNAME', (c, r), (c, r), 'Times-Bold'))
        if subjects and subjects[r - 1].get('is_summary'):
            style_cmds.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#f8fafc')))
            style_cmds.append(('FONTNAME', (0, r), (-1, r), 'Times-Bold'))
    grade_table.setStyle(TableStyle(style_cmds))
    elements.append(grade_table)
    elements.append(Spacer(1, 3 * mm))

    elements.append(Paragraph(f'RANK IN CLASS: {rank_label}', ParagraphStyle(
        'Rank', parent=styles['Normal'], fontName='Times-Bold', fontSize=9, textColor=ink, spaceAfter=3,
    )))

    legend_cells = [
        Paragraph(f'{label} {band} {letter}'.upper(), ParagraphStyle(
            f'Leg{i}', parent=styles['Normal'], fontName='Times-Bold', fontSize=7.5,
            alignment=TA_CENTER, textColor=ink,
        ))
        for i, (label, band, letter) in enumerate(legend_rows)
    ]
    legend = Table([legend_cells], colWidths=[70 * mm] * max(len(legend_cells), 1) if legend_cells else [281 * mm])
    if len(legend_cells) == 4:
        legend = Table([legend_cells], colWidths=[70.25 * mm] * 4)
    legend.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.7, ink),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, ink),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(Paragraph('GRADING METHOD', ParagraphStyle(
        'LegCap', parent=styles['Normal'], fontName='Times-Bold', fontSize=8,
        textColor=ink, spaceAfter=2,
    )))
    elements.append(legend)
    elements.append(Spacer(1, 8 * mm))

    vpi = f"{brand.get('vpi_title') or 'VPI'} {(brand.get('vpi_name') or '').upper()}".strip()
    signs = Table([[
        Paragraph(vpi, sign_style),
        Paragraph((brand.get('sponsor_title') or 'CLASS SPONSOR').upper(), sign_style),
        Paragraph((brand.get('principal_title') or 'PRINCIPAL').upper(), sign_style),
    ]], colWidths=[93.6 * mm, 93.6 * mm, 93.8 * mm])
    signs.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LINEABOVE', (0, 0), (0, 0), 0.7, ink),
        ('LINEABOVE', (1, 0), (1, 0), 0.7, ink),
        ('LINEABOVE', (2, 0), (2, 0), 0.7, ink),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(signs)
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph((brand.get('motto') or '').upper(), motto_style))

    def _draw_border(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(ink)
        canvas.setLineWidth(1.2)
        canvas.rect(6 * mm, 6 * mm, page[0] - 12 * mm, page[1] - 12 * mm)
        canvas.restoreState()

    doc.build(elements, onFirstPage=_draw_border, onLaterPages=_draw_border)
    buffer.seek(0)
    safe_id = (student.student_id or str(student.id)).replace('/', '-')
    year_slug = (year_label or 'year').replace('/', '-')
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'{file_prefix}_{safe_id}_{year_slug}.pdf',
        mimetype='application/pdf',
    )


@app.route('/student/grade-sheet/pdf', methods=['GET'], endpoint='student_grade_sheet_pdf')
@login_required
def student_grade_sheet_pdf():
    """PDF download of the official landscape grade sheet."""
    if (current_user.role or '').lower() != 'student':
        abort(403)

    student = get_student_for_user(current_user)
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('logout'))

    past_years = all_academic_years()
    selected_year_id = request.args.get('academic_year_id', type=int)
    if selected_year_id:
        display_year = db.session.get(AcademicYear, selected_year_id)
    else:
        display_year = get_active_academic_year()
        if not display_year and past_years:
            display_year = past_years[0]
    year_id = display_year.id if display_year else None
    view_period = _requested_marking_period()
    doc_state = student_official_documents_state(student, year_id, period=view_period)
    if doc_state.get('hold'):
        return render_official_grade_hold(
            student, display_year,
            hold_message=STUDENT_PERIOD_HOLD_MESSAGE if view_period else None,
        )
    view_period, semester = _resolve_sheet_scope(doc_state, view_period)
    return build_official_grade_sheet_pdf(
        student, year_id, kind='sheet', approved_only=True,
        view_period=view_period, semester=semester,
    )


@app.route('/update-tuition/<int:student_id>', methods=['POST'])
@login_required
def update_tuition(student_id):
    if (current_user.role or '').lower() not in ('admin', 'business'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    
    if student_id == 0:
        student_id = request.form.get('student_id', type=int)
    
    student = Student.query.get_or_404(student_id)
    cleared = request.form.get('tuition_cleared') == 'on'
    student.tuition_cleared = cleared
    db.session.commit()
    
    flash('Tuition status updated.', 'success')
    pass

@app.route('/verify/transcript/<token>')
def verify_transcript(token):
    """Public transcript authenticity check — opened when the QR code is scanned."""
    student_pk = decode_transcript_verify_token(token)
    if not student_pk:
        return render_template(
            'verify_transcript.html',
            valid=False,
            error='This verification link is invalid or has been tampered with.',
        )

    student = db.session.get(Student, student_pk)
    if not student:
        return render_template(
            'verify_transcript.html',
            valid=False,
            error='No matching student record was found for this verification code.',
        )

    official_grades = official_grade_records(student.id)
    all_scores = [g.score for g in official_grades if g.score is not None]
    overall_gpa = SchoolEngine.calculate_gpa(all_scores) if all_scores else 0.0
    active_year = get_active_academic_year()

    return render_template(
        'verify_transcript.html',
        valid=True,
        student=student,
        overall_gpa=overall_gpa,
        grade_count=len(all_scores),
        active_year=active_year,
        verified_at=datetime.now(timezone.utc),
    )


def user_can_view_official_transcript(user, student):
    """Registrar, VPA, principal, admin, the student, or the linked parent."""
    if not user or not getattr(user, 'is_authenticated', False) or not student:
        return False
    role = canonical_role(user)
    if role in OFFICIAL_TRANSCRIPT_STAFF_ROLES:
        return True
    if student.user_id and student.user_id == user.id:
        return True
    if role == 'parent' and student.parent_email and student.parent_email == user.email:
        return True
    return False


def student_transcript_year_span_labels(student):
    """First and last attendance years printed in the certified paragraph."""
    year_ids = set()
    if getattr(student, 'academic_year_id', None):
        year_ids.add(student.academic_year_id)
    for (year_id,) in db.session.query(Grade.academic_year_id).filter(
        Grade.student_id == student.id,
        Grade.academic_year_id.isnot(None),
    ).distinct():
        year_ids.add(year_id)
    for (year_id,) in db.session.query(Enrollment.academic_year_id).filter(
        Enrollment.student_id == student.id,
        Enrollment.academic_year_id.isnot(None),
    ).distinct():
        year_ids.add(year_id)
    if not year_ids:
        return 'N/A', 'N/A'
    years = AcademicYear.query.filter(AcademicYear.id.in_(year_ids)).all()

    def sort_key(year):
        span = parse_academic_year_span(year.name)
        if span:
            return (span[0], span[1], year.id)
        start = year.start_date.year if year.start_date else 0
        return (start, start, year.id)

    years.sort(key=sort_key)
    first = format_academic_year_label(years[0].name) or years[0].name
    last = format_academic_year_label(years[-1].name) or years[-1].name
    return first, last


def build_official_transcript_page_data(student, year_id, *, approved_only=False):
    """Portrait Official Transcript from the same SEM.AVE / YRLY AVE grid."""
    report = build_report_card_structured_data(
        student, year_id, approved_only=approved_only,
    )
    groups, average_row, conduct_row = build_transcript_grade_groups(
        report.get('subjects') or [],
        report.get('division'),
    )
    first_year, last_year = student_transcript_year_span_labels(student)
    klass = get_student_class_for_year(student, year_id)
    grade_parts = (
        getattr(klass, 'grade_level', None) if klass else None,
        getattr(student, 'grade_level', None),
        getattr(student, 'level', None),
    )
    promoted_to, conditioned_in, retained_in = transcript_promotion_fields(
        report.get('promotion'),
        *grade_parts,
    )
    yearly_average = ''
    if average_row:
        yearly_average = average_row.get('final_avg') or average_row.get('yearly') or ''
    return {
        **report,
        'groups': groups,
        'yearly_average': yearly_average,
        'conduct': transcript_conduct_cells(conduct_row),
        'first_year': first_year,
        'last_year': last_year,
        'grade_heading': transcript_grade_heading(*grade_parts),
        'promoted_to': promoted_to,
        'conditioned_in': conditioned_in,
        'retained_in': retained_in,
        'print_date': datetime.now().strftime('%B %d, %Y'),
        'letterhead': transcript_letterhead(),
    }


@app.route('/transcript/<int:student_id>', methods=['GET'], strict_slashes=False)
@login_required
def transcript(student_id):
    """Official FLPA portrait transcript (not the 6-period report card)."""
    student = Student.query.get_or_404(student_id)
    if not user_can_view_official_transcript(current_user, student):
        flash('Access denied.', 'danger')
        return redirect(url_for(role_home_endpoint()))

    active_year = get_active_academic_year()
    year_id = request.args.get('academic_year_id', type=int) or (
        active_year.id if active_year else None
    )
    display_year = db.session.get(AcademicYear, year_id) if year_id else None
    if viewer_must_wait_for_transcript_release(student, year_id):
        return render_official_transcript_hold(student, display_year)
    staff_preview = canonical_role(current_user) in OFFICIAL_TRANSCRIPT_STAFF_ROLES
    data = build_official_transcript_page_data(
        student, year_id, approved_only=not staff_preview,
    )
    return render_template(
        'transcript.html',
        student=student,
        data=data,
        display_year=display_year,
        school_print_brand=school_print_brand(),
    )


@app.route('/transcripts/<int:student_id>', methods=['GET'], strict_slashes=False)
@app.route('/official-transcript/<int:student_id>', methods=['GET'], strict_slashes=False)
def official_transcript_alias(student_id):
    """Canonicalize older/mistyped transcript URLs onto GET /transcript/<id>."""
    return redirect(url_for(
        'transcript',
        student_id=student_id,
        **request.args.to_dict(flat=True),
    ))

@app.route("/about")
def about():
    categories = LeaderCategory.query.order_by(LeaderCategory.name.asc()).all()
    return render_template("about.html", categories=categories)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        subject = (request.form.get("subject") or "").strip()
        message = (request.form.get("message") or "").strip()
        if not (name and email and subject and message):
            flash("Please complete every field so we can respond.", "warning")
        else:
            current_app.logger.info(
                "Contact inquiry from %s <%s> — %s",
                name,
                email,
                subject,
            )
            flash(
                "Thank you. The academy has your message. You can also reach us at "
                f"{SCHOOL_PRINT_EMAIL_ADDRESS} or by phone during administration hours.",
                "success",
            )
        return redirect(url_for("contact"))
    return render_template("contact.html")


@app.route('/api/stats')
@login_required
def api_stats():
    import random
    # Mock system stats
    cpu = random.randint(10, 90)
    memory = random.randint(20, 80)
    # db_wave: perhaps student count or recent activity
    db_wave = Student.query.count() + random.randint(-10, 10)
    return jsonify({'cpu': cpu, 'memory': memory, 'db_wave': db_wave})


# --------------------------------------------------------------
# ADMIN: Manage Events
# --------------------------------------------------------------


def _require_admin():
    if not current_user.is_authenticated or normalize_role(current_user) != "admin":
        flash("Administrator access required.", "danger")
        return redirect(url_for("dashboard"))
    return None


def _require_communications_manager():
    """Admin, Principal, and VPA can manage events and announcements."""
    if not current_user.is_authenticated:
        flash("Please log in to continue.", "danger")
        return redirect(url_for("login"))
    if normalize_role(current_user) not in COMMUNICATIONS_MANAGER_ROLES:
        flash("Communications management access required.", "danger")
        return redirect(url_for("dashboard"))
    return None


def _require_school_media_manager():
    """Admin, Principal, VPA, and Registrar can manage school media."""
    if not current_user.is_authenticated:
        flash("Please log in to continue.", "danger")
        return redirect(url_for("login"))
    if normalize_role(current_user) not in SCHOOL_MEDIA_MANAGER_ROLES:
        flash("School media management access required.", "danger")
        return redirect(url_for("dashboard"))
    return None


def _registrar_media_restricted():
    return normalize_role(current_user) == "registrar"


def _school_media_category_choices():
    all_choices = [
        ("general", "General Update"),
        ("advertisement", "Advertisement / Promo Video"),
        ("gallery", "School Gallery"),
        ("entrance", "Entrance Exam Notice (documents only)"),
        ("info_sheet", "Academic Year Info Sheet (documents only)"),
    ]
    if _registrar_media_restricted():
        return [choice for choice in all_choices if choice[0] in REGISTRAR_MEDIA_CATEGORIES]
    return all_choices


def _user_can_manage_media_item(item):
    if not _registrar_media_restricted():
        return True
    return item.category in REGISTRAR_MEDIA_CATEGORIES


def _school_media_query_for_user():
    query = SchoolMedia.query
    if _registrar_media_restricted():
        query = query.filter(SchoolMedia.category.in_(REGISTRAR_MEDIA_CATEGORIES))
    return query.order_by(SchoolMedia.created_at.desc())


def _school_media_upload_dir():
    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "school_media")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _save_school_media_file(upload_file):
    filename = secure_filename(upload_file.filename)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{timestamp}_{filename}"
    upload_dir = _school_media_upload_dir()
    full_path = os.path.join(upload_dir, stored_name)
    upload_file.save(full_path)
    return os.path.join("uploads", "school_media", stored_name).replace("\\", "/")


def _school_media_allowed_file(filename, media_type):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    allowed = {
        "photo": {"jpg", "jpeg", "png", "webp", "gif"},
        "video": {"mp4", "webm", "mov"},
        "document": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt"},
    }
    return ext in allowed.get(media_type, set())


def _school_media_abs_path(relative_path):
    rel = str(relative_path or "").replace("\\", "/").lstrip("/")
    if rel.startswith("static/"):
        rel = rel[7:]
    return os.path.join(current_app.root_path, "static", rel)


def _probe_video_duration_seconds(abs_path):
    """Return video length in seconds when metadata can be read."""
    try:
        from mutagen import File as media_file

        meta = media_file(abs_path)
        if meta and getattr(meta, "info", None) and getattr(meta.info, "length", None):
            return float(meta.info.length)
    except Exception:
        logger.debug("Could not read video duration for %s", abs_path, exc_info=True)
    return None


def _validate_uploaded_video(abs_path):
    """
    Enforce promo-video limits (up to ~3 minutes, generous file size).
    Returns (ok, duration_seconds_or_error_message).
    """
    if not os.path.isfile(abs_path):
        return False, "Uploaded video file could not be found."

    size_mb = os.path.getsize(abs_path) / (1024 * 1024)
    if size_mb > SCHOOL_VIDEO_MAX_MB:
        return (
            False,
            f"Video file is too large ({size_mb:.0f} MB). "
            f"Maximum upload size is {SCHOOL_VIDEO_MAX_MB} MB for a 2–3 minute clip.",
        )

    duration = _probe_video_duration_seconds(abs_path)
    if duration is not None and duration > SCHOOL_VIDEO_MAX_DURATION_SEC:
        return (
            False,
            f"Video is too long ({duration / 60:.1f} minutes). "
            f"Please upload a clip up to {SCHOOL_VIDEO_MAX_DURATION_SEC // 60} minutes.",
        )

    return True, int(duration) if duration is not None else None


def _remove_school_media_file(relative_path):
    abs_path = _school_media_abs_path(relative_path)
    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            logger.warning("Could not delete school media file %s", abs_path)


def _school_media_video_mime(relative_path):
    ext = (str(relative_path or "").rsplit(".", 1)[-1]).lower()
    return {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
    }.get(ext, "video/mp4")


def _format_video_duration(seconds):
    if not seconds:
        return None
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _apply_uploaded_school_media_file(media_type, file_path):
    """Validate uploaded video files and return duration_seconds."""
    if media_type != "video" or not file_path:
        return True, None

    ok, payload = _validate_uploaded_video(_school_media_abs_path(file_path))
    if not ok:
        _remove_school_media_file(file_path)
        return False, payload
    return True, payload


def _youtube_embed_url(url):
    if not url:
        return None
    url = url.strip()
    if "youtu.be/" in url:
        video_id = url.rsplit("/", 1)[-1].split("?")[0]
        return f"https://www.youtube.com/embed/{video_id}"
    if "watch?v=" in url:
        video_id = url.split("watch?v=", 1)[-1].split("&")[0]
        return f"https://www.youtube.com/embed/{video_id}"
    if "youtube.com/embed/" in url:
        return url
    return None


def _require_analytics_access():
    """Restrict analytics APIs to staff roles."""
    if normalize_role(current_user) not in ('admin', 'registrar', 'principal', 'business'):
        abort(403)


def _require_leader_manager():
    """About-page leadership profiles — admin and principal."""
    if not current_user.is_authenticated:
        flash("Please log in to continue.", "danger")
        return redirect(url_for("dashboard"))
    if (current_user.role or "").lower() not in {"admin", "principal"}:
        flash("Administrator access required.", "danger")
        return redirect(url_for("dashboard"))
    return None


def get_or_create_leader_category(name):
    """Find or create a leader category from free-text input."""
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    existing = LeaderCategory.query.filter(
        db.func.lower(LeaderCategory.name) == cleaned.lower()
    ).first()
    if existing:
        return existing
    category = LeaderCategory(name=cleaned)
    db.session.add(category)
    db.session.flush()
    return category


@app.route("/admin/events")
@login_required
def admin_events_list():
    redirect_resp = _require_communications_manager()
    if redirect_resp:
        return redirect_resp

    events = Event.query.order_by(Event.date.desc()).all()
    return render_template("admin/events/list.html", events=events)


@app.route("/admin/events/create", methods=["GET", "POST"])
@login_required
def admin_events_create():
    redirect_resp = _require_communications_manager()
    if redirect_resp:
        return redirect_resp

    form = EventForm()
    if form.validate_on_submit():
        event = Event(
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            location=form.location.data.strip() if form.location.data else None,
            date=form.date.data,
            event_type=form.event_type.data or "general",
        )
        db.session.add(event)
        db.session.commit()
        flash("Event created successfully and is now visible on the homepage.", "success")
        return redirect(url_for("index") + "#upcoming-schedule")

    return render_template("admin/events/create.html", form=form)


@app.route("/admin/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def admin_events_edit(event_id):
    redirect_resp = _require_communications_manager()
    if redirect_resp:
        return redirect_resp

    event = Event.query.get_or_404(event_id)
    form = EventForm(obj=event)
    if form.validate_on_submit():
        event.title = form.title.data.strip()
        event.description = form.description.data.strip()
        event.location = form.location.data.strip() if form.location.data else None
        event.date = form.date.data
        event.event_type = form.event_type.data or "general"
        db.session.commit()
        flash("Event updated successfully.", "success")
        return redirect(url_for("admin_events_list"))

    return render_template("admin/events/edit.html", form=form, event=event)

@app.route("/admin/events/<int:event_id>/delete", methods=["GET", "POST"])
@login_required
def admin_events_delete(event_id):
    redirect_resp = _require_communications_manager()
    if redirect_resp:
        return redirect_resp

    event = Event.query.get_or_404(event_id)
    form = ConfirmDeleteForm()
    if form.validate_on_submit():
        db.session.delete(event)
        db.session.commit()
        flash("Event deleted.", "success")
        return redirect(url_for("admin_events_list"))

    return render_template("admin/events/delete.html", form=form, event=event)


# --------------------------------------------------------------
# PUBLIC: Events
# --------------------------------------------------


@app.route('/events')
def events_list():
    events = Event.query.order_by(Event.date.asc()).all()
    return render_template('events/list.html', events=events)


def _populate_school_media_form(form):
    years = all_academic_years()
    form.academic_year.choices = [(0, "-- Any / All Years --")] + [(y.id, y.name) for y in years]
    form.category.choices = _school_media_category_choices()
    active_year = get_active_academic_year()
    if request.method == "GET":
        if active_year:
            form.academic_year.default = active_year.id
        if not _registrar_media_restricted():
            form.category.default = "gallery"
        preset_type = (request.args.get("type") or "").strip().lower()
        preset_category = (request.args.get("category") or "").strip().lower()
        if preset_type in {"photo", "video", "document"}:
            form.media_type.default = preset_type
        if preset_category in {choice[0] for choice in _school_media_category_choices()}:
            form.category.default = preset_category
        form.process()


def _validate_school_media_submission(form):
    category = form.category.data or "general"
    media_type = form.media_type.data or "document"

    if _registrar_media_restricted() and category not in REGISTRAR_MEDIA_CATEGORIES:
        flash("Registrars can only post Entrance Exam and Academic Year Info Sheet items.", "danger")
        return False

    if category in DOCUMENT_ONLY_MEDIA_CATEGORIES and media_type != "document":
        flash(
            "Entrance Exam and Info Sheet categories are for downloadable documents only. "
            "Use Advertisement, Gallery, or General for photos and videos.",
            "danger",
        )
        return False

    if _registrar_media_restricted() and media_type != "document":
        flash(
            "Registrars can only upload documents for entrance notices and info sheets. "
            "Ask Principal or VPA to publish advertisement videos.",
            "danger",
        )
        return False

    return True


@app.route("/school-media")
def school_media_gallery():
    category = (request.args.get("category") or "").strip()
    media_type = (request.args.get("type") or "").strip()
    year_id = request.args.get("year_id", type=int)

    query = SchoolMedia.query.filter_by(is_published=True)
    if category:
        query = query.filter_by(category=category)
    if media_type:
        query = query.filter_by(media_type=media_type)
    if year_id:
        query = query.filter_by(academic_year_id=year_id)

    items = query.order_by(SchoolMedia.created_at.desc()).all()
    active_year = get_active_academic_year()
    years = all_academic_years()

    return render_template(
        "school_media/gallery.html",
        items=items,
        active_year=active_year,
        years=years,
        selected_category=category,
        selected_type=media_type,
        selected_year_id=year_id,
        youtube_embed_url=_youtube_embed_url,
    )


@app.route("/school-media/manage")
@login_required
def school_media_manage():
    redirect_resp = _require_school_media_manager()
    if redirect_resp:
        return redirect_resp

    items = _school_media_query_for_user().all()
    return render_template("school_media/manage.html", items=items)


@app.route("/school-media/create", methods=["GET", "POST"])
@login_required
def school_media_create():
    redirect_resp = _require_school_media_manager()
    if redirect_resp:
        return redirect_resp

    form = SchoolMediaForm()
    _populate_school_media_form(form)

    if form.validate_on_submit():
        if not _validate_school_media_submission(form):
            return render_template("school_media/form.html", form=form, item=None)

        media_type = form.media_type.data
        has_file = form.media_file.data and getattr(form.media_file.data, "filename", None)
        external_url = (form.external_url.data or "").strip() or None

        if media_type == "video" and not has_file and not external_url:
            flash("Upload a video file or provide a YouTube/Vimeo link.", "danger")
            return render_template("school_media/form.html", form=form, item=None)

        if media_type in {"photo", "document"} and not has_file:
            flash("Please upload a file for this media type.", "danger")
            return render_template("school_media/form.html", form=form, item=None)

        file_path = None
        duration_seconds = None
        if has_file:
            if not _school_media_allowed_file(form.media_file.data.filename, media_type):
                flash("That file type is not allowed for the selected media type.", "danger")
                return render_template("school_media/form.html", form=form, item=None)
            file_path = _save_school_media_file(form.media_file.data)
            ok, payload = _apply_uploaded_school_media_file(media_type, file_path)
            if not ok:
                flash(payload, "danger")
                return render_template("school_media/form.html", form=form, item=None)
            duration_seconds = payload

        item = SchoolMedia(
            title=form.title.data.strip(),
            description=(form.description.data or "").strip() or None,
            media_type=media_type,
            category=form.category.data or "general",
            file_path=file_path,
            external_url=external_url,
            academic_year_id=form.academic_year.data or None,
            is_published=bool(form.is_published.data),
            author_id=current_user.id,
            duration_seconds=duration_seconds,
        )
        db.session.add(item)
        db.session.commit()
        flash("School media published successfully.", "success")
        return redirect(url_for("school_media_manage"))

    return render_template("school_media/form.html", form=form, item=None)


@app.route("/school-media/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def school_media_edit(item_id):
    redirect_resp = _require_school_media_manager()
    if redirect_resp:
        return redirect_resp

    item = SchoolMedia.query.get_or_404(item_id)
    if not _user_can_manage_media_item(item):
        flash("You are not authorized to edit this media item.", "danger")
        return redirect(url_for("school_media_manage"))

    form = SchoolMediaForm(obj=item)
    _populate_school_media_form(form)
    if request.method == "GET":
        form.academic_year.data = item.academic_year_id or 0

    if form.validate_on_submit():
        if not _validate_school_media_submission(form):
            return render_template("school_media/form.html", form=form, item=item)

        media_type = form.media_type.data
        has_file = form.media_file.data and getattr(form.media_file.data, "filename", None)
        external_url = (form.external_url.data or "").strip() or None

        if media_type == "video" and not has_file and not external_url and not item.file_path:
            flash("Upload a video file or provide a video link.", "danger")
            return render_template("school_media/form.html", form=form, item=item)

        if media_type in {"photo", "document"} and not has_file and not item.file_path:
            flash("Please upload a file for this media type.", "danger")
            return render_template("school_media/form.html", form=form, item=item)

        if has_file:
            if not _school_media_allowed_file(form.media_file.data.filename, media_type):
                flash("That file type is not allowed for the selected media type.", "danger")
                return render_template("school_media/form.html", form=form, item=item)
            new_path = _save_school_media_file(form.media_file.data)
            ok, payload = _apply_uploaded_school_media_file(media_type, new_path)
            if not ok:
                flash(payload, "danger")
                return render_template("school_media/form.html", form=form, item=item)
            if item.file_path and item.file_path != new_path:
                _remove_school_media_file(item.file_path)
            item.file_path = new_path
            if media_type == "video":
                item.duration_seconds = payload

        item.title = form.title.data.strip()
        item.description = (form.description.data or "").strip() or None
        item.media_type = media_type
        item.category = form.category.data or "general"
        item.external_url = external_url
        item.academic_year_id = form.academic_year.data or None
        item.is_published = bool(form.is_published.data)
        db.session.commit()
        flash("School media updated successfully.", "success")
        return redirect(url_for("school_media_manage"))

    return render_template("school_media/form.html", form=form, item=item)


@app.route("/school-media/<int:item_id>/delete", methods=["GET", "POST"])
@login_required
def school_media_delete(item_id):
    redirect_resp = _require_school_media_manager()
    if redirect_resp:
        return redirect_resp

    item = SchoolMedia.query.get_or_404(item_id)
    if not _user_can_manage_media_item(item):
        flash("You are not authorized to delete this media item.", "danger")
        return redirect(url_for("school_media_manage"))
    form = ConfirmDeleteForm()
    if form.validate_on_submit():
        db.session.delete(item)
        db.session.commit()
        flash("School media removed.", "success")
        return redirect(url_for("school_media_manage"))

    return render_template("school_media/delete.html", form=form, item=item)


@app.route("/school-media/<int:item_id>/download")
def school_media_download(item_id):
    item = SchoolMedia.query.get_or_404(item_id)
    if not item.is_published:
        if not current_user.is_authenticated or normalize_role(current_user) not in SCHOOL_MEDIA_MANAGER_ROLES:
            flash("This file is not available.", "danger")
            return redirect(url_for("school_media_gallery"))

    if not item.file_path:
        flash("No file attached to this item.", "warning")
        return redirect(url_for("school_media_gallery"))

    rel_path = item.static_file_path
    if not rel_path:
        flash("File not found.", "danger")
        return redirect(url_for("school_media_gallery"))

    full_path = os.path.join(current_app.root_path, "static", rel_path.replace("/", os.sep))
    if not os.path.isfile(full_path):
        flash("File not found on disk.", "danger")
        return redirect(url_for("school_media_gallery"))

    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return send_from_directory(directory, filename, as_attachment=True)


# --------------------------------------------------------------
# ADMIN: Manage Leaders
# --------------------------------------------------------------

@app.route('/admin/leaders')
@login_required
def manage_leaders():
    redirect_resp = _require_leader_manager()
    if redirect_resp:
        return redirect_resp

    leaders = Leader.query.all()
    return render_template('admin/manage_leaders.html', leaders=leaders)

@app.route('/admin/leaders/add', methods=['GET', 'POST'])
@login_required
def add_leader():
    redirect_resp = _require_leader_manager()
    if redirect_resp:
        return redirect_resp

    form = LeaderForm()

    if form.validate_on_submit():
        category = get_or_create_leader_category(form.category.data)
        if not category:
            flash('Category is required.', 'danger')
            return render_template('admin/add_leader.html', form=form)

        leader = Leader(
            name=form.name.data,
            role=form.role.data,
            bio=form.bio.data,
            contact=form.contact.data,
            category_id=category.id,
        )

        if form.photo.data:
            photo_file = form.photo.data
            filename = secure_filename(photo_file.filename)
            photo_path = os.path.join('static/uploads/leaders', filename)
            os.makedirs(os.path.dirname(photo_path), exist_ok=True)
            photo_file.save(photo_path)
            leader.photo = photo_path

        db.session.add(leader)
        db.session.commit()
        flash('Leader added successfully!', 'success')
        return redirect(url_for('manage_leaders'))

    return render_template('admin/add_leader.html', form=form)


@app.route('/admin/edit_leader/<int:leader_id>', methods=['GET', 'POST'])
@login_required
def edit_leader(leader_id):
    redirect_resp = _require_leader_manager()
    if redirect_resp:
        return redirect_resp

    leader = Leader.query.get_or_404(leader_id)
    form = LeaderForm(obj=leader)
    if request.method == 'GET' and leader.category_node:
        form.category.data = leader.category_node.name

    if form.validate_on_submit():
        category = get_or_create_leader_category(form.category.data)
        if not category:
            flash('Category is required.', 'danger')
            return render_template('admin/edit_leader.html', form=form, leader=leader)

        leader.name = form.name.data
        leader.role = form.role.data
        leader.bio = form.bio.data
        leader.contact = form.contact.data
        leader.category_id = category.id

        if form.photo.data:
            photo_file = form.photo.data
            filename = secure_filename(photo_file.filename)
            photo_path = os.path.join('static/uploads/leaders', filename)
            os.makedirs(os.path.dirname(photo_path), exist_ok=True)
            photo_file.save(photo_path)
            leader.photo = photo_path

        db.session.commit()
        flash('Leader updated successfully!', 'success')
        return redirect(url_for('manage_leaders'))

    return render_template('admin/edit_leader.html', form=form, leader=leader)


@app.route('/admin/delete_leader/<int:leader_id>', methods=['POST'])
@login_required
def delete_leader(leader_id):
    redirect_resp = _require_leader_manager()
    if redirect_resp:
        return redirect_resp

    leader = Leader.query.get_or_404(leader_id)
    db.session.delete(leader)
    db.session.commit()
    flash('Leader deleted successfully!', 'danger')
    return redirect(url_for('manage_leaders'))


@app.route('/grades/add', methods=['POST'])
@login_required
def add_grade():
    # 1. Access Control: Restrict to teachers only
    if normalize_role(current_user) != 'teacher':
        flash("Unauthorized.", "danger")
        return redirect(url_for('login'))

    # 2. Strict Session Safety Check: Verify an active academic year exists
    active_year = get_active_academic_year()
    if not active_year:
        flash("No active academic year found. Please contact the administrator.", "danger")
        return redirect(url_for('login'))

    # 3. Extract and parse incoming form data safely
    student_id = request.form.get("student_id", type=int)
    subject_name = (request.form.get("subject_name") or request.form.get("subject") or "").strip()
    period_str = request.form.get("period")
    marking_period = request.form.get("marking_period", type=int)
    if marking_period is None:
        marking_period = request.form.get("period", type=int)
    activity_type = request.form.get("activity_type")
    score = request.form.get("score", type=float)
    submitted = bool(request.form.get("submitted"))

    # Extract continuous assessment and exam components
    ca_score = request.form.get("ca_score", type=float)
    exam_score = request.form.get("exam_score", type=float)

    # 4. Input Validation
    if not student_id or not subject_name or marking_period is None:
        flash("Student, subject, and marking period are required.", "danger")
        return redirect(url_for('teacher_dashboard'))

    if marking_period not in range(1, 9):
        flash("Invalid marking period selected.", "danger")
        return redirect(url_for('teacher_dashboard'))

    if not activity_type:
        activity_type = 'Semester Exam' if marking_period in (7, 8) else 'Period Assessment'

    student = db.session.get(Student, student_id)
    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for('teacher_dashboard'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash("Teacher profile not found.", "danger")
        return redirect(url_for('teacher_dashboard'))

    if not teacher_can_access_student(teacher_profile, current_user, student):
        flash("You may only enter grades for students in your assigned classes.", "danger")
        return redirect(url_for('teacher_dashboard'))

    student_class_id = get_student_class_id(student)
    allowed_subjects = get_teacher_subjects_for_class(teacher_profile, student_class_id)
    if subject_name not in allowed_subjects:
        flash("You are not assigned to teach that subject for this student's class.", "danger")
        return redirect(url_for('teacher_dashboard'))

    # 5. MoE Standard Calculations & Constraints Validation via SchoolEngine
    if marking_period in range(1, 7):
        if ca_score is None and exam_score is None and score is not None:
            ca_score = 0.0
            exam_score = score
        if ca_score is None or exam_score is None:
            flash("CA and Exam scores are required for period grades.", "danger")
            return redirect(url_for('teacher_dashboard'))
        total = SchoolEngine.calculate_period_total(ca_score, exam_score)
        if total is None:
            flash("Invalid scores! CA must be ≤ 60 and Exam ≤ 40 (MoE Standard).", "danger")
            return redirect(url_for('teacher_dashboard'))
        score = total
    else:
        exam_only = exam_score if exam_score is not None else score
        if exam_only is None:
            flash("Semester exam score is required.", "danger")
            return redirect(url_for('teacher_dashboard'))
        if exam_only < 0 or exam_only > 100:
            flash("Semester exam score must be between 0 and 100.", "danger")
            return redirect(url_for('teacher_dashboard'))
        ca_score = 0.0
        exam_score = exam_only
        score = exam_only

    grade = find_grade_record(
        student_id,
        subject_name,
        marking_period,
        class_id=student_class_id,
        academic_year_id=active_year.id,
    )
    if not grade:
        grade = Grade(
            student_id=student_id,
            teacher_id=teacher_profile.id,
            class_id=student_class_id,
            academic_year_id=active_year.id,
            subject_name=subject_name,
            subject=subject_name,
        )
        db.session.add(grade)

    if grade and grade.is_finalized:
        flash('This grade is finalized and cannot be changed.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    grade.teacher_id = teacher_profile.id
    grade.class_id = student_class_id
    grade.academic_year_id = active_year.id
    grade.subject_name = subject_name
    grade.subject = subject_name
    grade.period = marking_period
    grade.marking_period = marking_period
    grade.activity_type = activity_type
    grade.ca_score = ca_score if ca_score is not None else 0.0
    grade.exam_score = exam_score if exam_score is not None else 0.0
    grade.score = score
    grade.remarks = SchoolEngine.get_remarks(score)
    grade.submitted = submitted

    if 1 <= marking_period <= 6:
        setattr(grade, f"p{marking_period}", int(round(score)))

    if submitted and student_class_id:
        reconcile_grade_package_after_save(
            active_year.id, student_class_id, marking_period,
            published=True, actor_id=current_user.id,
        )
    elif student_class_id:
        reconcile_grade_package_after_save(
            active_year.id, student_class_id, marking_period,
            published=False, actor_id=current_user.id,
        )
    db.session.commit()

    if submitted:
        flash(f"Grade saved. {GRADE_RELEASE_TEACHER_FLASH}", "success")
    else:
        flash("Grade saved successfully.", "success")
    return_class_id = request.form.get('grade_class_id', type=int)
    if return_class_id:
        return redirect(url_for('teacher_dashboard', tab='grades', grade_class_id=return_class_id))
    return redirect(url_for('teacher_dashboard', tab='grades'))

@app.route('/teacher/assign-activity', methods=['POST'])
@login_required
def assign_activity():
    if (current_user.role or '').strip().lower() != 'teacher':
        flash('Only teachers can assign activities.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    klass_id = request.form.get('klass_id', type=int)
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    submission_mode = (request.form.get('submission_mode') or request.form.get('activity_type') or '').strip()
    subject_name = (request.form.get('subject_name') or request.form.get('subject') or '').strip()
    marking_period = request.form.get('marking_period', type=int) or request.form.get('period', type=int) or 1
    evaluation_type = (request.form.get('evaluation_type') or 'Assignment').strip()
    due_date = parse_activity_due_date(request.form.get('due_date'))
    scan_keywords = normalize_scan_keywords(request.form.get('scan_keywords'))
    notify_students = request.form.get('notify_students') == '1'

    def activities_redirect():
        return redirect(url_for(
            'teacher_dashboard',
            tab='activities',
            activity_class_id=klass_id,
        ))

    task_file = request.files.get('task_file') if 'task_file' in request.files else None
    has_file = task_file and task_file.filename

    if has_file and not allowed_activity_file(task_file.filename):
        allowed = ', '.join(sorted(ACTIVITY_ALLOWED_EXTENSIONS))
        flash(f'File type not allowed. Use: {allowed}', 'danger')
        return activities_redirect() if klass_id else redirect(url_for('teacher_dashboard', tab='activities'))

    if has_file and not title:
        title = title_from_activity_filename(task_file.filename)

    if not klass_id or not title or not subject_name:
        flash('Class, subject, and title (or file) are required.', 'danger')
        return activities_redirect() if klass_id else redirect(url_for('teacher_dashboard', tab='activities'))

    if not submission_mode:
        submission_mode = 'file_upload' if has_file else 'text_entry'

    if submission_mode not in {'file_upload', 'text_entry', 'in_class'}:
        flash('Choose how students should submit this activity.', 'danger')
        return activities_redirect()

    if evaluation_type not in MOE_ACTIVITY_TYPES:
        evaluation_type = 'Assignment'
    if marking_period not in {p for p, _ in MOE_GRADING_PERIODS}:
        marking_period = 1

    if not teacher_can_access_class(teacher_profile, current_user, klass_id):
        flash('You may only assign activities to your own classes.', 'danger')
        return redirect(url_for('teacher_dashboard', tab='activities'))

    allowed_subjects = get_assignable_subjects_for_class(teacher_profile, current_user, klass_id)
    if not allowed_subjects:
        flash('No subjects are available for this class. Ask the principal to set up class subjects.', 'danger')
        return activities_redirect()
    if subject_name not in allowed_subjects:
        flash(f'Choose a subject you teach in this class: {", ".join(allowed_subjects)}.', 'danger')
        return activities_redirect()

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return activities_redirect()

    klass = Class.query.get_or_404(klass_id)

    task_file_name = save_activity_upload_file(task_file, klass_id) if has_file else None

    try:
        create_assessment_record(
            title=title,
            description=description,
            evaluation_type=evaluation_type,
            submission_mode=submission_mode,
            subject_name=subject_name,
            marking_period=marking_period,
            active_year=active_year,
            teacher_profile=teacher_profile,
            klass_id=klass_id,
            task_file_name=task_file_name,
            due_date=due_date,
            scan_keywords=scan_keywords,
            notify_students=notify_students,
            klass=klass,
            teacher_user=current_user,
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to assign classroom activity: %s', exc, exc_info=True)
        flash('Could not save the activity. Please try again or contact support.', 'danger')
        return activities_redirect()

    flash(f'"{title}" assigned to {klass.name} — {subject_name} (Period {marking_period}).', 'success')
    return activities_redirect()


@app.route('/teacher/class/<int:class_id>/record-activity', methods=['GET', 'POST'])
@login_required
def record_classroom_activity(class_id):
    """Record an in-class activity (blackboard, verbal, or Google Drive link) for later grading."""
    role = normalize_role(current_user)
    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if role not in ('teacher', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    if role == 'teacher' and not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    if not can_enter_class_grades(current_user, teacher_profile, class_id):
        flash('You are not authorized to record activities for this class.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    klass = Class.query.get_or_404(class_id)
    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    subjects = (
        get_assignable_subjects_for_class(teacher_profile, current_user, class_id)
        if role == 'teacher'
        else get_class_subject_catalog(class_id)
    )
    if not subjects:
        flash('No subjects are available for this class. Ask the principal to set up class subjects.', 'warning')
        return redirect(url_for('teacher_dashboard', tab='activities', activity_class_id=class_id))

    form = RecordClassroomActivityForm()
    form.subject_name.choices = [(s, s) for s in subjects]
    form.marking_period.choices = [(p, label) for p, label in MOE_GRADING_PERIODS]

    prefill_subject = (request.args.get('subject') or '').strip()
    prefill_period = request.args.get('period', type=int)
    return_to = (request.args.get('return_to') or '').strip()

    if request.method == 'GET':
        if prefill_subject in subjects:
            form.subject_name.data = prefill_subject
        elif subjects:
            form.subject_name.data = subjects[0]
        if prefill_period in {p for p, _ in MOE_GRADING_PERIODS}:
            form.marking_period.data = prefill_period
        else:
            form.marking_period.data = 1

    if request.method == 'POST':
        if not form.validate_on_submit():
            if form.errors:
                flash('Could not create the activity — please fix the highlighted fields.', 'danger')
        else:
            title = (form.title.data or '').strip()
            subject_name = (form.subject_name.data or '').strip()
            marking_period = form.marking_period.data or 1

            if not title:
                flash('Activity title is required.', 'danger')
            elif not subject_name:
                flash('Subject is required.', 'danger')
            elif subject_name not in subjects:
                flash(f'Choose a subject for this class: {", ".join(subjects)}.', 'danger')
            elif marking_period not in {p for p, _ in MOE_GRADING_PERIODS}:
                flash('Choose a valid marking period.', 'danger')
            else:
                evaluation_type = (form.evaluation_type.data or 'Class Work').strip()
                if evaluation_type not in MOE_ACTIVITY_TYPES:
                    evaluation_type = 'Class Work'
                due_date = form.due_date.data.strftime('%Y-%m-%d') if form.due_date.data else None
                external_url = normalize_external_url(form.external_url.data)
                notes = (form.classroom_notes.data or '').strip() or None
                summary = classroom_notes_summary(notes)

                try:
                    assessment = create_assessment_record(
                        title=title,
                        description=summary,
                        evaluation_type=evaluation_type,
                        submission_mode='in_class',
                        subject_name=subject_name,
                        marking_period=marking_period,
                        active_year=active_year,
                        teacher_profile=teacher_profile,
                        klass_id=class_id,
                        due_date=due_date,
                        max_score=form.max_score.data,
                        external_url=external_url,
                        classroom_notes=notes,
                        notify_students=False,
                    )
                    db.session.commit()
                except Exception as exc:
                    db.session.rollback()
                    logger.error('Failed to record classroom activity: %s', exc, exc_info=True)
                    flash('Could not save the activity. Please try again.', 'danger')
                else:
                    flash(
                        f'Activity "{assessment.title}" created — now enter scores.',
                        'success',
                    )
                    return redirect(url_for(
                        'manual_activity_grades',
                        class_id=class_id,
                        subject=subject_name,
                        period=marking_period,
                        assessment_id=assessment.id,
                    ))

    return render_template(
        'teacher/record_classroom_activity.html',
        form=form,
        klass=klass,
        active_year=active_year,
        subjects=subjects,
        grading_periods=MOE_GRADING_PERIODS,
        moe_activity_types=MOE_ACTIVITY_TYPES,
        return_to=return_to,
        prefill_subject=prefill_subject,
        prefill_period=prefill_period,
    )


@app.route('/teacher/assign-activities-bulk', methods=['POST'])
@login_required
def assign_activities_bulk():
    if (current_user.role or '').strip().lower() != 'teacher':
        flash('Only teachers can assign activities.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    klass_id = request.form.get('klass_id', type=int)
    subject_name = (request.form.get('subject_name') or '').strip()
    marking_period = request.form.get('marking_period', type=int) or 1
    evaluation_type = (request.form.get('evaluation_type') or 'Assignment').strip()
    submission_mode = (request.form.get('submission_mode') or 'file_upload').strip()
    description = (request.form.get('description') or '').strip()
    due_date = parse_activity_due_date(request.form.get('due_date'))
    scan_keywords = normalize_scan_keywords(request.form.get('scan_keywords'))
    notify_students = request.form.get('notify_students') == '1'

    def activities_redirect():
        return redirect(url_for(
            'teacher_dashboard',
            tab='activities',
            activity_class_id=klass_id,
        ))

    upload_files = [
        f for f in request.files.getlist('task_files')
        if f and f.filename
    ]
    if not klass_id or not subject_name or not upload_files:
        flash('Class, subject, and at least one file are required for bulk upload.', 'danger')
        return activities_redirect() if klass_id else redirect(url_for('teacher_dashboard', tab='activities'))

    if submission_mode not in {'file_upload', 'text_entry', 'in_class'}:
        submission_mode = 'file_upload'
    if evaluation_type not in MOE_ACTIVITY_TYPES:
        evaluation_type = 'Assignment'
    if marking_period not in {p for p, _ in MOE_GRADING_PERIODS}:
        marking_period = 1

    if not teacher_can_access_class(teacher_profile, current_user, klass_id):
        flash('You may only assign activities to your own classes.', 'danger')
        return redirect(url_for('teacher_dashboard', tab='activities'))

    allowed_subjects = get_assignable_subjects_for_class(teacher_profile, current_user, klass_id)
    if subject_name not in allowed_subjects:
        flash(f'Choose a subject you teach in this class: {", ".join(allowed_subjects)}.', 'danger')
        return activities_redirect()

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return activities_redirect()

    klass = Class.query.get_or_404(klass_id)
    created = 0
    skipped = 0

    try:
        for task_file in upload_files:
            if not allowed_activity_file(task_file.filename):
                skipped += 1
                continue
            task_file_name = save_activity_upload_file(task_file, klass_id)
            if not task_file_name:
                skipped += 1
                continue
            title = title_from_activity_filename(task_file.filename)
            create_assessment_record(
                title=title,
                description=description,
                evaluation_type=evaluation_type,
                submission_mode=submission_mode,
                subject_name=subject_name,
                marking_period=marking_period,
                active_year=active_year,
                teacher_profile=teacher_profile,
                klass_id=klass_id,
                task_file_name=task_file_name,
                due_date=due_date,
                scan_keywords=scan_keywords,
                notify_students=notify_students,
                klass=klass,
                teacher_user=current_user,
            )
            created += 1
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('Bulk activity assign failed: %s', exc, exc_info=True)
        flash('Could not save all activities. Please try again.', 'danger')
        return activities_redirect()

    if created:
        msg = f'{created} activit{"y" if created == 1 else "ies"} assigned to {klass.name}.'
        if skipped:
            msg += f' {skipped} file(s) skipped (unsupported type).'
        flash(msg, 'success')
    else:
        allowed = ', '.join(sorted(ACTIVITY_ALLOWED_EXTENSIONS))
        flash(f'No files were uploaded. Allowed types: {allowed}', 'danger')
    return activities_redirect()


@app.route('/teacher/activity/<int:assessment_id>/edit', methods=['POST'])
@login_required
def edit_activity(assessment_id):
    if (current_user.role or '').strip().lower() != 'teacher':
        flash('Only teachers can edit activities.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    assessment = Assessment.query.get_or_404(assessment_id)
    if not teacher_profile or not teacher_owns_assessment(teacher_profile, current_user, assessment):
        flash('You are not authorized to edit this activity.', 'danger')
        return redirect(url_for('teacher_dashboard', tab='activities'))

    klass_id = assessment.klass_id
    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip()
    subject_name = (request.form.get('subject_name') or '').strip()
    marking_period = request.form.get('marking_period', type=int) or assessment.marking_period or 1
    evaluation_type = (request.form.get('evaluation_type') or assessment.activity_type or 'Assignment').strip()
    submission_mode = (request.form.get('submission_mode') or assessment.submission_mode or 'file_upload').strip()
    due_date = parse_activity_due_date(request.form.get('due_date'))
    scan_keywords = normalize_scan_keywords(request.form.get('scan_keywords'))
    external_url = normalize_external_url(request.form.get('external_url'))
    classroom_notes = (request.form.get('classroom_notes') or '').strip() or None
    max_score_raw = request.form.get('max_score', type=float)

    def activities_redirect():
        return redirect(url_for(
            'teacher_dashboard',
            tab='activities',
            activity_class_id=klass_id,
        ))

    if not title or not subject_name:
        flash('Title and subject are required.', 'danger')
        return activities_redirect()

    allowed_subjects = get_assignable_subjects_for_class(teacher_profile, current_user, klass_id)
    if subject_name not in allowed_subjects:
        flash(f'Choose a subject you teach: {", ".join(allowed_subjects)}.', 'danger')
        return activities_redirect()

    if evaluation_type not in MOE_ACTIVITY_TYPES:
        evaluation_type = 'Assignment'
    if submission_mode not in {'file_upload', 'text_entry', 'in_class'}:
        submission_mode = assessment.submission_mode or 'file_upload'
    if marking_period not in {p for p, _ in MOE_GRADING_PERIODS}:
        marking_period = assessment.marking_period or 1

    assessment.title = title
    assessment.description = description
    assessment.subject_name = subject_name
    assessment.marking_period = marking_period
    assessment.activity_type = evaluation_type
    assessment.submission_mode = submission_mode
    assessment.due_date = due_date
    assessment.scan_keywords = scan_keywords
    assessment.external_url = external_url
    assessment.classroom_notes = classroom_notes
    if max_score_raw and max_score_raw > 0:
        assessment.max_score = max_score_raw
    if classroom_notes and not description:
        assessment.description = classroom_notes_summary(classroom_notes)

    try:
        db.session.commit()
        flash(f'"{title}" updated.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Edit activity failed: %s', exc, exc_info=True)
        flash('Could not update activity.', 'danger')
    return activities_redirect()


@app.route('/teacher/activity/<int:assessment_id>/delete', methods=['POST'])
@login_required
def delete_activity(assessment_id):
    if (current_user.role or '').strip().lower() != 'teacher':
        flash('Only teachers can delete activities.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    assessment = Assessment.query.get_or_404(assessment_id)
    if not teacher_profile or not teacher_owns_assessment(teacher_profile, current_user, assessment):
        flash('You are not authorized to delete this activity.', 'danger')
        return redirect(url_for('teacher_dashboard', tab='activities'))

    klass_id = assessment.klass_id
    title = assessment.title
    delete_activity_upload_file(assessment.file_name)

    try:
        db.session.delete(assessment)
        db.session.commit()
        flash(f'"{title}" deleted.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Delete activity failed: %s', exc, exc_info=True)
        flash('Could not delete activity.', 'danger')

    return redirect(url_for(
        'teacher_dashboard',
        tab='activities',
        activity_class_id=klass_id,
    ))


@app.route('/teacher/activity/<int:assessment_id>/duplicate', methods=['POST'])
@login_required
def duplicate_activity(assessment_id):
    if (current_user.role or '').strip().lower() != 'teacher':
        flash('Only teachers can duplicate activities.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    source = Assessment.query.get_or_404(assessment_id)
    if not teacher_profile or not teacher_owns_assessment(teacher_profile, current_user, source):
        flash('You are not authorized to duplicate this activity.', 'danger')
        return redirect(url_for('teacher_dashboard', tab='activities'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('teacher_dashboard', tab='activities', activity_class_id=source.klass_id))

    klass = source.klass
    copy_title = f"{source.title} (Copy)"
    try:
        create_assessment_record(
            title=copy_title,
            description=source.description,
            evaluation_type=source.activity_type or 'Assignment',
            submission_mode=source.submission_mode or 'file_upload',
            subject_name=source.subject_name,
            marking_period=source.marking_period or 1,
            active_year=active_year,
            teacher_profile=teacher_profile,
            klass_id=source.klass_id,
            task_file_name=source.file_name,
            due_date=source.due_date,
            scan_keywords=source.scan_keywords,
            max_score=source.max_score,
            external_url=source.external_url,
            classroom_notes=source.classroom_notes,
            notify_students=False,
        )
        db.session.commit()
        flash(f'"{copy_title}" created.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Duplicate activity failed: %s', exc, exc_info=True)
        flash('Could not duplicate activity.', 'danger')

    return redirect(url_for(
        'teacher_dashboard',
        tab='activities',
        activity_class_id=source.klass_id,
    ))


@app.route('/teacher/dashboard', methods=['GET'])
@login_required
def teacher_dashboard():
    """
    Assembles data for the comprehensive cyber-themed instructor panel,
    encompassing student rosters, active terms, and system historical ledgers.
    """
    # Strict role verification barrier
    if (current_user.role or '').strip().lower() != 'teacher':
        logger.warning(f"Unauthorized dashboard access attempt by User ID: {current_user.id}")
        abort(403, description="Access restricted to authorized faculty members only.")

    # Define common header context required by dashboard_teacher.html
    header = {
        "school": "Future Leaders Preparatory Academy",
        "sheet_title": "Teacher Dashboard",
        "status": "Active Session",
        "academic_year": "",
        "logo_left": "images/logo1.png",
        "logo_right": "images/logo2.png"
    }

    try:
        display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
            session_key=TEACHER_YEAR_SESSION_KEY,
        )
        header["academic_year"] = (
            display_year.name if display_year else (active_year.name if active_year else "")
        )
        work_year_id = display_year.id if display_year else None

        # Fetch active faculty roster for display contexts that need it
        teachers_list = Teacher.query.filter_by(status='ACTIVE').order_by(Teacher.first_name.asc(), Teacher.last_name.asc()).all()

        # Get or create teacher profile for current user
        teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
        
        if not teacher_profile:
            logger.warning(f"Auto-creating teacher profile for user {current_user.id}")
            try:
                name_parts = (current_user.full_name or '').strip().split(None, 1)
                first_name = name_parts[0].strip() if name_parts else current_user.full_name
                last_name = name_parts[1].strip() if len(name_parts) > 1 else ''
                
                teacher_profile = Teacher(
                    user_id=current_user.id,
                    first_name=first_name or 'Unknown',
                    last_name=last_name or current_user.full_name,
                    status='ACTIVE'
                )
                db.session.add(teacher_profile)
                db.session.commit()
            except Exception as e:
                logger.error(f"Failed to auto-create teacher profile: {e}")
                db.session.rollback()

        dashboard_ctx = build_teacher_dashboard_context(
            teacher_profile,
            current_user,
            work_year_id,
            viewing_archived=viewing_archived,
        )
        class_cards = dashboard_ctx['class_cards']
        valid_class_ids = {card['id'] for card in class_cards}
        grade_class_id = (
            request.args.get('grade_class_id', type=int)
            or request.args.get('class_id', type=int)
        )
        if class_cards:
            if grade_class_id not in valid_class_ids:
                remembered_class = session.get('teacher_grade_class_id')
                if remembered_class in valid_class_ids:
                    grade_class_id = remembered_class
                else:
                    preferred_card = next(
                        (card for card in class_cards if card.get('student_count', 0) > 0),
                        class_cards[0],
                    )
                    grade_class_id = preferred_card['id']
        else:
            grade_class_id = None

        selected_grade_class = next(
            (card for card in class_cards if card['id'] == grade_class_id),
            None,
        )
        grade_entry_students = []
        grade_entry_subjects = []
        grade_subject = ''
        grade_period = 1
        grade_rows = {}
        period_label = grading_period_label(1)
        grade_student_count = 0
        grade_graded_count = 0
        grade_published_count = 0
        grade_pending_count = 0
        if grade_class_id:
            grade_entry_students = get_class_students_for_year(
                grade_class_id, display_year, viewing_archived=viewing_archived,
            )
            grade_entry_subjects = get_assignable_subjects_for_class(
                teacher_profile, current_user, grade_class_id
            )
            grade_subject = (
                request.args.get('grade_subject')
                or request.args.get('subject')
                or ''
            ).strip()
            if not grade_subject and session.get('teacher_grade_class_id') == grade_class_id:
                grade_subject = (session.get('teacher_grade_subject') or '').strip()
            if grade_subject not in grade_entry_subjects:
                grade_subject = grade_entry_subjects[0] if grade_entry_subjects else ''
            grade_period = (
                request.args.get('grade_period', type=int)
                or request.args.get('period', type=int)
            )
            if grade_period is None and session.get('teacher_grade_class_id') == grade_class_id:
                grade_period = session.get('teacher_grade_period')
            if grade_period not in {p for p, _ in MOE_GRADING_PERIODS}:
                grade_period = 1
            period_label = grading_period_label(grade_period)
            session['teacher_grade_class_id'] = grade_class_id
            if grade_subject:
                session['teacher_grade_subject'] = grade_subject
            session['teacher_grade_period'] = grade_period
            if grade_subject and display_year:
                student_ids = {s.id for s in grade_entry_students}
                existing_grades = Grade.query.filter_by(
                    class_id=grade_class_id,
                    subject=grade_subject,
                    academic_year_id=display_year.id,
                ).all()
                for grade in existing_grades:
                    period_num = grade.marking_period or normalize_grade_period(grade.period)
                    if period_num == grade_period and grade.student_id in student_ids:
                        grade_rows[grade.student_id] = grade
            grade_student_count = len(grade_entry_students)
            for student in grade_entry_students:
                existing = grade_rows.get(student.id)
                if not existing:
                    continue
                has_scores = (
                    existing.ca_score is not None
                    or existing.exam_score is not None
                    or existing.score is not None
                )
                if has_scores:
                    grade_graded_count += 1
                if existing.submitted:
                    grade_published_count += 1
            grade_pending_count = max(grade_student_count - grade_graded_count, 0)

        requested_tab = request.args.get('tab')
        if requested_tab == 'grades' and grade_class_id:
            return redirect(
                url_for(
                    'grade_entry_class',
                    class_id=grade_class_id,
                    subject=grade_subject or None,
                    period=grade_period,
                )
            )

        active_tab = request.args.get('tab')
        if not active_tab:
            if request.args.get('activity_class_id', type=int):
                active_tab = 'activities'
            elif request.args.get('grade_class_id', type=int) or request.args.get('ledger_class_id', type=int):
                active_tab = 'grades'
            else:
                active_tab = 'classes'
        if active_tab not in ('classes', 'grades', 'activities'):
            active_tab = 'classes'

        activity_class_id = request.args.get('activity_class_id', type=int)
        if activity_class_id and activity_class_id not in valid_class_ids:
            activity_class_id = None

        selected_activity_class = next(
            (card for card in class_cards if card['id'] == activity_class_id),
            None,
        )
        activity_subjects = []
        class_activity_items = []
        activity_count_by_class = {}
        total_activity_count = 0
        activity_stats = {}
        activity_grading_inbox = []
        class_sizes_by_id = {card['id']: card.get('student_count', 0) for card in class_cards}
        pending_grading_count = dashboard_ctx.get('pending_grading_count', 0)
        if teacher_profile and valid_class_ids and display_year:
            try:
                all_teacher_activities = (
                    Assessment.query.filter(
                        Assessment.klass_id.in_(valid_class_ids),
                        Assessment.teacher_id == teacher_profile.id,
                        Assessment.academic_year_id == display_year.id,
                    )
                    .order_by(Assessment.id.desc())
                    .all()
                )
                activity_stats = compute_activity_submission_stats(
                    all_teacher_activities, class_sizes_by_id
                )
                activity_grading_inbox = build_activity_grading_inbox(
                    all_teacher_activities, activity_stats, class_cards
                )
                pending_grading_count = sum(
                    stats.get('pending_grade_count', 0)
                    for stats in activity_stats.values()
                )
                for act in all_teacher_activities:
                    if is_quick_entry_assessment(act):
                        continue
                    activity_count_by_class[act.klass_id] = activity_count_by_class.get(act.klass_id, 0) + 1
                    pending_for_class = activity_stats.get(act.id, {}).get('pending_grade_count', 0)
                    if pending_for_class:
                        activity_count_by_class.setdefault(f'pending_{act.klass_id}', 0)
                        activity_count_by_class[f'pending_{act.klass_id}'] = (
                            activity_count_by_class.get(f'pending_{act.klass_id}', 0) + pending_for_class
                        )
                total_activity_count = sum(
                    1 for act in all_teacher_activities if not is_quick_entry_assessment(act)
                )
                if activity_class_id:
                    activity_subjects = get_assignable_subjects_for_class(
                        teacher_profile, current_user, activity_class_id
                    )
                    class_activity_items = [
                        act for act in all_teacher_activities
                        if act.klass_id == activity_class_id and not is_quick_entry_assessment(act)
                    ]
            except Exception as exc:
                logger.warning('Could not load class activities: %s', exc)

        published_grade_count = sum(1 for g in dashboard_ctx['grades'] if g.submitted)

        ledger_ctx = build_teacher_grade_ledger(
            teacher_profile,
            class_cards,
            display_year,
            ledger_class_id=request.args.get('ledger_class_id', type=int),
            ledger_subject=(request.args.get('ledger_subject') or '').strip(),
            grade_class_id=grade_class_id,
        )

        return render_template(
            'dashboard_teacher.html',
            header=header,  # Added header object
            students=dashboard_ctx['students'],
            teachers=teachers_list,
            active_year=active_year,
            display_year=display_year,
            years=years,
            viewing_archived=viewing_archived,
            teaching_classes=dashboard_ctx['teaching_classes'],
            class_cards=class_cards,
            sponsored_classes=dashboard_ctx['sponsored_classes'],
            grades=dashboard_ctx['grades'],
            assigned_subjects=dashboard_ctx['assigned_subjects'],
            grading_periods=dashboard_ctx['grading_periods'],
            grade_class_id=grade_class_id,
            selected_grade_class=selected_grade_class,
            grade_entry_students=grade_entry_students,
            grade_entry_subjects=grade_entry_subjects,
            grade_subject=grade_subject,
            grade_period=grade_period,
            grade_rows=grade_rows,
            component_rows=build_grade_component_rows(grade_rows),
            period_component_specs=PERIOD_COMPONENT_SPECS,
            period_scheme_note=PERIOD_COMPONENT_SCHEME_NOTE,
            period_component_ceilings=PERIOD_COMPONENT_CEILINGS,
            period_component_field_max=PERIOD_COMPONENT_FIELD_MAX,
            period_total_listed_max=PERIOD_TOTAL_LISTED_MAX,
            period_total_extra_max=PERIOD_TOTAL_EXTRA_CREDIT_MAX,
            period_label=period_label,
            published_grade_count=published_grade_count,
            active_tab=active_tab,
            grade_student_count=grade_student_count,
            grade_graded_count=grade_graded_count,
            grade_published_count=grade_published_count,
            grade_pending_count=grade_pending_count,
            grade_release=(
                GradeRelease.query.filter_by(
                    academic_year_id=display_year.id,
                    class_id=grade_class_id,
                    period=grade_period,
                ).first()
                if display_year and grade_class_id else None
            ),
            activity_class_id=activity_class_id,
            selected_activity_class=selected_activity_class,
            activity_subjects=activity_subjects,
            class_activity_items=class_activity_items,
            activity_count_by_class=activity_count_by_class,
            total_activity_count=total_activity_count,
            activity_stats=activity_stats,
            activity_grading_inbox=activity_grading_inbox,
            pending_grading_count=pending_grading_count,
            moe_activity_types=MOE_ACTIVITY_TYPES,
            activity_allowed_extensions=sorted(ACTIVITY_ALLOWED_EXTENSIONS),
            grade_ledger_by_class=ledger_ctx['grade_ledger_by_class'],
            ledger_class_id=ledger_ctx['ledger_class_id'],
            selected_ledger_class=ledger_ctx['selected_ledger_class'],
            ledger_class_data=ledger_ctx['ledger_class_data'],
            ledger_student_rows=ledger_ctx['ledger_student_rows'],
            ledger_subjects=ledger_ctx['ledger_subjects'],
            ledger_stats=ledger_ctx['ledger_stats'],
            ledger_subject=ledger_ctx['ledger_subject'],
        )
    
    except Exception as e:
        logger.error(f"Teacher dashboard error: {str(e)}", exc_info=True)
        abort(500, description="Internal Data Layer Synthesis Failure.")    
        
    return render_template(
        'dashboard_teacher.html',
        header=header,  # Added header object to fallback route
        students=[],
        teachers=[],
        active_year=None,
        display_year=None,
        years=[],
        viewing_archived=False,
        teaching_classes=[],
        class_cards=[],
        sponsored_classes=[],
        grades=[],
        assigned_subjects=[],
        grading_periods=GRADING_PERIODS,
        grade_class_id=None,
        selected_grade_class=None,
        grade_entry_students=[],
        grade_entry_subjects=[],
        grade_subject='',
        grade_period=1,
        grade_rows={},
        period_label=grading_period_label(1),
        published_grade_count=0,
        active_tab='grades',
        grade_student_count=0,
        grade_graded_count=0,
        grade_published_count=0,
        grade_pending_count=0,
        activity_class_id=None,
        selected_activity_class=None,
        activity_subjects=[],
        class_activity_items=[],
        activity_count_by_class={},
        total_activity_count=0,
        activity_stats={},
        activity_grading_inbox=[],
        pending_grading_count=0,
        moe_activity_types=MOE_ACTIVITY_TYPES,
        activity_allowed_extensions=sorted(ACTIVITY_ALLOWED_EXTENSIONS),
        grade_ledger_by_class={},
        ledger_class_id=None,
        selected_ledger_class=None,
        ledger_class_data={},
        ledger_student_rows=[],
        ledger_subjects=[],
        ledger_stats={},
        ledger_subject='',
    )
    
@app.route('/teacher/class/<int:class_id>')
@login_required
def teacher_class_folder(class_id):
    """Class folder view: roster and quick links for an assigned class."""
    if (current_user.role or '').strip().lower() != 'teacher':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile or not teacher_can_access_class(teacher_profile, current_user, class_id):
        flash('You are not assigned to this class.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    klass = db.session.get(Class, class_id)
    if not klass:
        flash('Class not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    subjects = [
        a.subject_name
        for a in ClassSubjectTeacher.query.filter_by(
            teacher_id=teacher_profile.id, class_id=class_id
        ).all()
    ]
    active_year = resolve_teacher_attendance_year()
    students = get_class_students_for_year(class_id, active_year)

    is_sponsor = teacher_is_class_sponsor(teacher_profile, current_user, class_id)

    return render_template(
        'teacher_class_folder.html',
        klass=klass,
        students=students,
        subjects=sorted(set(subjects)),
        active_year=active_year,
        is_sponsor=is_sponsor,
    )


@app.route('/teacher/attendance', methods=['GET'])
@login_required
def teacher_attendance_picker():
    """Pick a class before opening the attendance roll."""
    role = normalize_role(current_user)
    if role not in {'teacher', 'admin'}:
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if role == 'teacher' and not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    active_year = resolve_teacher_attendance_year()
    if not active_year:
        flash('No active academic year is configured. Contact your administrator.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    class_cards = get_teacher_class_cards(
        teacher_profile,
        current_user,
        active_year.id if active_year else None,
    ) if teacher_profile else []

    if role == 'admin' and not class_cards:
        class_cards = [
            {
                'id': klass.id,
                'name': klass.name,
                'grade_level': klass.grade_level,
                'stream': klass.stream,
                'student_count': (
                    len(_principal_students_for_class(klass, active_year, viewing_archived=False))
                    if active_year else 0
                ),
                'role_labels': ['Administrator'],
                'subjects': [],
            }
            for klass in Class.query.order_by(Class.name.asc()).all()
        ]

    if len(class_cards) == 1:
        return redirect(url_for('teacher_class_attendance', class_id=class_cards[0]['id']))

    attendance_date = request.args.get('date') or date.today().strftime('%Y-%m-%d')
    return render_template(
        'teacher_attendance_picker.html',
        class_cards=class_cards,
        attendance_date=attendance_date,
        active_year=active_year,
    )


@app.route('/teacher/class/<int:class_id>/attendance', methods=['GET', 'POST'])
@login_required
def teacher_class_attendance(class_id):
    """Daily attendance roll for an assigned class."""
    role = normalize_role(current_user)
    if role not in {'teacher', 'admin'}:
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if role == 'teacher' and not can_take_class_attendance(current_user, teacher_profile, class_id):
        flash('You are not assigned to this class.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    klass = db.session.get(Class, class_id)
    if not klass:
        flash('Class not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    active_year = resolve_teacher_attendance_year()
    if not active_year:
        flash('No active academic year is configured. Contact your administrator.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    attendance_date = (
        request.form.get('attendance_date')
        or request.args.get('date')
        or date.today().strftime('%Y-%m-%d')
    ).strip()

    if request.method == 'POST':
        try:
            saved = save_class_attendance_bulk(
                class_id,
                teacher_profile.id if teacher_profile else None,
                attendance_date,
                request.form,
                active_year,
            )
            db.session.commit()
            flash(f'Attendance saved for {saved} students on {attendance_date}.', 'success')
        except Exception as exc:
            db.session.rollback()
            logger.error('Teacher attendance save failed: %s', exc, exc_info=True)
            flash('Could not save attendance.', 'danger')
        return redirect(url_for('teacher_class_attendance', class_id=class_id, date=attendance_date))

    ctx = build_teacher_attendance_context(
        teacher_profile,
        current_user,
        klass,
        active_year,
        attendance_date=attendance_date,
    )
    return render_template('teacher_attendance.html', **ctx)


@app.route('/attendance/overview', methods=['GET'])
@login_required
def attendance_overview():
    """Multi-role attendance reporting hub (admin, principal, registrar, business, VPI)."""
    role = normalize_role(current_user)
    back_map = {
        'admin': (url_for('dashboard'), 'Admin Dashboard'),
        'principal': (url_for('principal_dashboard'), 'Principal Dashboard'),
        'registrar': (url_for('dashboard'), 'Registrar Dashboard'),
        'business': (url_for('business_dashboard'), 'Business Dashboard'),
        'vpi': (url_for('vpi_dashboard'), 'VPI Finance Dashboard'),
        'vpa': (url_for('vpa_dashboard'), 'VPA Academic Dashboard'),
        'dean': (url_for('dean_dashboard'), 'Dean Dashboard'),
    }
    back_url, back_label = back_map.get(role, (url_for('dashboard'), 'Dashboard'))
    return render_attendance_overview(back_url, back_label, 'Attendance Overview')


@app.route('/principal/attendance', methods=['GET'])
@login_required
def principal_attendance():
    """Principal executive attendance overview."""
    if normalize_role(current_user) not in ('principal', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    return render_attendance_overview(
        url_for('principal_dashboard'),
        'Principal Dashboard',
        'Principal Attendance Overview',
    )


def can_principal_enter_class_grades(user):
    """Principal or admin may enter backup grades on any class roster."""
    return normalize_role(user) in PRINCIPAL_GRADE_ENTRY_ROLES


def get_subject_teacher_for_class(class_id, subject_name):
    """Return the Teacher assigned to a subject in a class, if allocated."""
    if not class_id or not subject_name:
        return None
    for row in ClassSubjectTeacher.query.filter_by(class_id=class_id).all():
        if subjects_match(row.subject_name, subject_name):
            return row.teacher_node
    return None


def get_class_teacher_allocations(class_id):
    """Faculty roster: subject → assigned teacher for a class."""
    if not class_id:
        return []
    allocations = []
    seen = set()
    for row in ClassSubjectTeacher.query.filter_by(class_id=class_id).order_by(
        ClassSubjectTeacher.subject_name.asc()
    ).all():
        key = _subject_key(row.subject_name)
        if key in seen:
            continue
        seen.add(key)
        teacher = row.teacher_node
        allocations.append({
            'subject': row.subject_name,
            'teacher_id': row.teacher_id,
            'teacher_name': teacher.full_name if teacher else 'Unassigned',
        })
    return allocations


def grade_entry_attribution(grade):
    """Short label for who entered a grade row (audit display)."""
    if not grade:
        return None
    role = (grade.entered_by_role or '').strip().lower()
    if role == 'principal':
        name = grade.entered_by_user.full_name if grade.entered_by_user else 'Principal'
        return f'Principal ({name})'
    if role == 'admin':
        name = grade.entered_by_user.full_name if grade.entered_by_user else 'Admin'
        return f'Admin ({name})'
    if role == 'teacher':
        return 'Teacher'
    return None


def build_principal_grade_class_cards(display_year, search_class='', *, viewing_archived=False):
    """Class portfolio summaries for principal grade-entry landing."""
    if not display_year:
        return []
    cards = []
    for klass in Class.query.order_by(Class.name.asc()).all():
        if search_class:
            term = search_class.strip().lower()
            haystack = ' '.join(filter(None, [
                klass.name,
                klass.stream,
                str(klass.grade_level or ''),
            ])).lower()
            if term not in haystack:
                continue
        try:
            student_count = len(get_class_students_for_year(
                klass.id, display_year, viewing_archived=viewing_archived,
            ))
        except Exception:
            student_count = 0
        subjects = get_class_subject_catalog(klass.id)
        allocations = get_class_teacher_allocations(klass.id)
        cards.append({
            'klass': klass,
            'student_count': student_count,
            'subject_count': len(subjects),
            'teacher_count': len({a['teacher_id'] for a in allocations if a['teacher_id']}),
            'allocations': allocations,
        })
    cards.sort(key=lambda card: class_sort_key_from_klass(card.get('klass')))
    return cards


@app.route('/principal/grade-entry', methods=['GET'])
@login_required
def principal_grade_entry():
    """Principal backup grade entry — class roster picker."""
    if not can_principal_enter_class_grades(current_user):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=PRINCIPAL_YEAR_SESSION_KEY,
    )
    if not display_year:
        flash('No academic year is configured.', 'danger')
        return redirect(url_for('principal_dashboard'))

    search_class = (request.args.get('search_class') or '').strip()
    class_cards = build_principal_grade_class_cards(
        display_year, search_class, viewing_archived=viewing_archived,
    )
    class_cards_by_division = group_items_by_class(
        class_cards, lambda card: card.get('klass'),
    )
    if not class_cards_by_division and class_cards:
        class_cards_by_division = [{
            'key': 'all',
            'label': 'Classes',
            'classes': class_cards,
        }]

    return render_template(
        'principal_grade_entry.html',
        active_year=active_year,
        display_year=display_year,
        viewing_archived=viewing_archived,
        years=years,
        search_class=search_class,
        class_cards=class_cards,
        class_cards_by_division=class_cards_by_division,
    )


@app.route('/principal/grade-entry/class/<int:class_id>', methods=['GET'])
@login_required
def principal_class_grading(class_id):
    """Principal MoE period grade sheet for a class roster (teacher backup)."""
    if not can_principal_enter_class_grades(current_user):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year is configured.', 'danger')
        return redirect(url_for('principal_grade_entry'))

    subjects = get_class_subject_catalog(class_id)
    selected_subject = (request.args.get('subject') or '').strip()
    if selected_subject not in subjects:
        selected_subject = subjects[0] if subjects else ''

    selected_period = request.args.get('period', 1, type=int)
    if selected_period not in range(1, 9):
        selected_period = 1

    students = get_class_students_for_year(class_id, active_year)
    student_ids = {s.id for s in students}

    grade_rows = {}
    if selected_subject:
        existing_grades = Grade.query.filter_by(
            class_id=class_id,
            subject=selected_subject,
            academic_year_id=active_year.id,
        ).all()
        for grade in existing_grades:
            period_num = grade.marking_period or normalize_grade_period(grade.period)
            if period_num == selected_period and grade.student_id in student_ids:
                grade_rows[grade.student_id] = grade

    subject_teacher = (
        get_subject_teacher_for_class(class_id, selected_subject)
        if selected_subject else None
    )
    allocations = get_class_teacher_allocations(class_id)
    period_label = grading_period_label(selected_period)
    is_semester_exam = selected_period in (7, 8)
    publish_stats = (
        get_class_period_publish_stats(
            class_id,
            selected_subject,
            selected_period,
            active_year.id,
            student_ids=student_ids,
        )
        if selected_subject
        else {'total': 0, 'published': 0, 'draft': 0}
    )

    return render_template(
        'principal_class_grading_hub.html',
        klass=klass,
        students=students,
        grade_rows=grade_rows,
        active_year=active_year,
        subjects=subjects,
        selected_subject=selected_subject,
        selected_period=selected_period,
        period_label=period_label,
        grading_periods=MOE_GRADING_PERIODS,
        is_semester_exam=is_semester_exam,
        subject_teacher=subject_teacher,
        allocations=allocations,
        publish_stats=publish_stats,
        grade_entry_attribution=grade_entry_attribution,
        grade_release=GradeRelease.query.filter_by(
            academic_year_id=active_year.id,
            class_id=class_id,
            period=selected_period,
        ).first() if active_year else None,
    )


@app.route('/principal/grade-entry/class/<int:class_id>/save', methods=['POST'])
@login_required
def principal_save_grades(class_id):
    """Persist principal-entered MoE period grades."""
    if not can_principal_enter_class_grades(current_user):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    Class.query.get_or_404(class_id)
    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year is configured.', 'danger')
        return redirect(url_for('principal_grade_entry'))

    subject_name = (request.form.get('subject') or '').strip()
    period = request.form.get('period', type=int)
    publish_action = (request.form.get('publish_action') or 'draft').strip().lower()
    publish_to_report = publish_action == 'publish'

    if not subject_name:
        flash('Please select a subject before saving grades.', 'danger')
        return redirect(url_for('principal_class_grading', class_id=class_id))
    if period not in range(1, 9):
        flash('Invalid marking period selected.', 'danger')
        return redirect(url_for('principal_class_grading', class_id=class_id))

    allowed_subjects = get_class_subject_catalog(class_id)
    if subject_name not in allowed_subjects:
        flash('That subject is not configured for this class.', 'danger')
        return redirect(url_for('principal_class_grading', class_id=class_id))

    assigned_teacher = get_subject_teacher_for_class(class_id, subject_name)
    teacher_id = assigned_teacher.id if assigned_teacher else None
    entry_role = normalize_role(current_user)
    period_label = grading_period_label(period)
    saved_count, error = _persist_period_grades_from_form(
        class_id,
        subject_name,
        period,
        publish_to_report,
        teacher_id=teacher_id,
        entered_by_user_id=current_user.id,
        entered_by_role=entry_role,
    )
    if error:
        flash(error, 'danger')
        return redirect(
            url_for(
                'principal_class_grading',
                class_id=class_id,
                subject=subject_name,
                period=period,
            )
        )

    if saved_count:
        if publish_to_report:
            flash(
                f'Principal backup: {period_label} grades published for {subject_name}. '
                f'{GRADE_RELEASE_TEACHER_FLASH}',
                'success',
            )
        else:
            flash(
                f'Principal backup: {period_label} draft saved for {subject_name}.',
                'success',
            )
    else:
        flash('No grade values were entered.', 'warning')

    return redirect(
        url_for(
            'principal_class_grading',
            class_id=class_id,
            subject=subject_name,
            period=period,
        )
    )


@app.route('/principal/grade-entry/class/<int:class_id>/publish', methods=['POST'])
@login_required
def principal_publish_period_grades(class_id):
    """Publish draft period grades entered by principal."""
    if not can_principal_enter_class_grades(current_user):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    Class.query.get_or_404(class_id)
    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year is configured.', 'danger')
        return redirect(url_for('principal_grade_entry'))

    subject_name = (request.form.get('subject') or '').strip()
    period = request.form.get('period', type=int)
    if not subject_name or period not in range(1, 9):
        flash('Subject and marking period are required.', 'danger')
        return redirect(url_for('principal_class_grading', class_id=class_id))

    students = get_class_students_for_year(class_id, active_year)
    student_ids = {s.id for s in students}
    published_count = 0

    for grade in Grade.query.filter_by(
        class_id=class_id,
        subject=subject_name,
        academic_year_id=active_year.id,
    ).all():
        period_num = grade.marking_period or normalize_grade_period(grade.period)
        if period_num != period or grade.student_id not in student_ids:
            continue
        if grade.is_finalized or grade.submitted or not _grade_has_entered_scores(grade):
            continue
        grade.submitted = True
        published_count += 1

    if published_count:
        reconcile_grade_package_after_save(
            active_year.id, class_id, period, published=True, actor_id=current_user.id,
        )
    db.session.commit()
    period_label = grading_period_label(period)
    if published_count:
        flash(
            f'Published {published_count} {period_label} grade{"s" if published_count != 1 else ""} '
            f'for {subject_name}. {GRADE_RELEASE_TEACHER_FLASH}',
            'success',
        )
    else:
        flash('No draft grades with scores were found to publish.', 'warning')

    return redirect(
        url_for(
            'principal_class_grading',
            class_id=class_id,
            subject=subject_name,
            period=period,
        )
    )


@app.route('/dean/attendance', methods=['GET'])
@login_required
def dean_attendance():
    """Dean attendance & truancy oversight."""
    if normalize_role(current_user) != 'dean':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    return render_attendance_overview(
        url_for('dean_dashboard'),
        'Dean Dashboard',
        'Dean Attendance & Truancy Overview',
    )


@app.route('/registrar/attendance', methods=['GET'])
@login_required
def registrar_attendance():
    """Read-only registrar attendance lookup."""
    if normalize_role(current_user) not in ('registrar', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    return render_attendance_overview(
        url_for('dashboard'),
        'Registrar Dashboard',
        'Registrar Attendance Lookup',
    )


@app.route('/attendance/class/<int:class_id>/day/<date_str>', methods=['GET'])
@login_required
def attendance_class_day_detail(class_id, date_str):
    """Drill-down roster for a class on a specific date."""
    scope = get_attendance_visibility_scope(current_user)
    if scope == ATTENDANCE_SCOPE_SUMMARY:
        flash('Detailed student attendance is restricted for your role.', 'warning')
        return redirect(url_for('attendance_overview'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not can_view_class_attendance_detail(current_user, class_id, teacher_profile):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    klass = db.session.get(Class, class_id)
    if not klass:
        flash('Class not found.', 'danger')
        return redirect(url_for('attendance_overview'))

    session_key = _attendance_overview_session_key(normalize_role(current_user))
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=session_key,
    )
    ctx = build_attendance_class_day_detail(
        klass, date_str, display_year, viewing_archived=viewing_archived,
    )
    role = normalize_role(current_user)
    if role == 'principal':
        back_url = url_for('principal_attendance', **request.args.to_dict())
    elif role == 'registrar':
        back_url = url_for('registrar_attendance', **request.args.to_dict())
    elif role == 'dean':
        back_url = url_for('dean_attendance', **request.args.to_dict())
    else:
        back_url = url_for('attendance_overview', **request.args.to_dict())

    return render_template(
        'attendance/class_day.html',
        back_url=back_url,
        active_year=active_year,
        viewing_archived=viewing_archived,
        read_only=scope in (ATTENDANCE_SCOPE_READ, ATTENDANCE_SCOPE_SUMMARY),
        can_take_attendance=can_take_class_attendance(current_user, teacher_profile, class_id),
        **ctx,
    )


@app.route('/teacher/class/<int:class_id>/grading', methods=['GET'])
@login_required
def class_grading_hub(class_id):
    """Legacy grading hub endpoint.

    Professional workflow policy: send teachers directly to the official
    report-card style entry sheet.
    """
    if normalize_role(current_user) != 'teacher':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher = Teacher.query.filter_by(user_id=current_user.id).first()
    klass = Class.query.get_or_404(class_id)
    if not teacher or not teacher_can_access_class(teacher, current_user, class_id):
        flash('You are not assigned to this class.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    subjects = get_assignable_subjects_for_class(teacher, current_user, class_id)
    selected_subject = (request.args.get('subject') or '').strip()
    if selected_subject not in subjects:
        selected_subject = subjects[0] if subjects else ''

    selected_period = request.args.get('period', 1, type=int)
    if selected_period not in range(1, 9):
        selected_period = 1

    return redirect(
        url_for(
            'grade_entry_class',
            class_id=class_id,
            subject=selected_subject,
            period=selected_period,
        )
    )


@app.route('/teacher/sponsor/<int:class_id>', methods=['GET'])
@login_required
def sponsor_class_hub(class_id):
    """Class Sponsor & Form Teacher command center."""
    if normalize_role(current_user) != 'teacher':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile or not teacher_is_class_sponsor(teacher_profile, current_user, class_id):
        flash('This command center is only for assigned class sponsors and form teachers.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    klass = db.session.get(Class, class_id)
    if not klass:
        flash('Class not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    active_year = resolve_teacher_attendance_year()
    if not active_year:
        flash('No active academic year is configured. Contact your administrator.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    attendance_date = request.args.get('date') or date.today().strftime('%Y-%m-%d')
    ctx = build_sponsor_hub_context(
        teacher_profile, current_user, klass, active_year, attendance_date=attendance_date
    )
    return render_template('sponsor_class_hub.html', **ctx)


@app.route('/teacher/sponsor/<int:class_id>/attendance', methods=['POST'])
@login_required
def sponsor_save_attendance(class_id):
    if normalize_role(current_user) != 'teacher':
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile or not teacher_is_class_sponsor(teacher_profile, current_user, class_id):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    attendance_date = (request.form.get('attendance_date') or date.today().strftime('%Y-%m-%d')).strip()
    active_year = resolve_teacher_attendance_year()
    if not active_year:
        flash('No active academic year is configured. Contact your administrator.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    try:
        saved = save_class_attendance_bulk(
            class_id,
            teacher_profile.id,
            attendance_date,
            request.form,
            active_year,
        )
        db.session.commit()
        flash(f'Attendance saved for {saved} students on {attendance_date}.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Sponsor attendance save failed: %s', exc, exc_info=True)
        flash('Could not save attendance.', 'danger')
    return _sponsor_hub_redirect(class_id, date=attendance_date)


@app.route('/teacher/sponsor/<int:class_id>/incident', methods=['POST'])
@login_required
def sponsor_log_incident(class_id):
    if normalize_role(current_user) != 'teacher':
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile or not teacher_is_class_sponsor(teacher_profile, current_user, class_id):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    student_id = request.form.get('student_id', type=int)
    offense = (request.form.get('offense') or '').strip()
    action_taken = (request.form.get('action_taken') or '').strip() or 'Referred to Dean of Students'
    notes = (request.form.get('notes') or '').strip()

    if not student_id or not offense:
        flash('Student and offense description are required.', 'danger')
        return _sponsor_hub_redirect(class_id)

    student = db.session.get(Student, student_id)
    roster_ids = {
        s.id for s in get_class_students_for_year(class_id, resolve_teacher_attendance_year())
    }
    if not student or student.id not in roster_ids:
        flash('Student not found in this class.', 'danger')
        return _sponsor_hub_redirect(class_id)

    db.session.add(Discipline(
        student_id=student_id,
        offense=offense,
        action_taken=action_taken,
        notes=notes or None,
        logged_by_id=current_user.id,
    ))
    try:
        db.session.commit()
        flash(f'Conduct incident logged for {student.full_name}. Dean has been notified via the record.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Sponsor incident log failed: %s', exc, exc_info=True)
        flash('Could not save incident.', 'danger')
    return _sponsor_hub_redirect(class_id)


@app.route('/teacher/sponsor/<int:class_id>/welfare-note', methods=['POST'])
@login_required
def sponsor_welfare_note(class_id):
    if normalize_role(current_user) != 'teacher':
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile or not teacher_is_class_sponsor(teacher_profile, current_user, class_id):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    student_id = request.form.get('student_id', type=int) or None
    note_type = (request.form.get('note_type') or 'welfare').strip()
    content = (request.form.get('content') or '').strip()

    if not content:
        flash('Welfare note content is required.', 'danger')
        return _sponsor_hub_redirect(class_id)

    if student_id:
        student = db.session.get(Student, student_id)
        roster_ids = {
            s.id for s in get_class_students_for_year(class_id, resolve_teacher_attendance_year())
        }
        if not student or student.id not in roster_ids:
            flash('Invalid student for this class.', 'danger')
            return _sponsor_hub_redirect(class_id)

    db.session.add(SponsorWelfareNote(
        class_id=class_id,
        student_id=student_id,
        teacher_id=teacher_profile.id,
        note_type=note_type,
        content=content,
    ))
    try:
        db.session.commit()
        flash('Welfare note recorded.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Welfare note save failed: %s', exc, exc_info=True)
        flash('Could not save welfare note.', 'danger')
    return _sponsor_hub_redirect(class_id)


@app.route('/teacher/sponsor/<int:class_id>/announce', methods=['POST'])
@login_required
def sponsor_class_announce(class_id):
    if normalize_role(current_user) != 'teacher':
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile or not teacher_is_class_sponsor(teacher_profile, current_user, class_id):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    title = (request.form.get('title') or '').strip()
    content = (request.form.get('content') or '').strip()
    audience = (request.form.get('audience') or 'students').strip()

    if not title or not content:
        flash('Announcement title and message are required.', 'danger')
        return _sponsor_hub_redirect(class_id)

    db.session.add(ClassAnnouncement(
        class_id=class_id,
        author_id=current_user.id,
        title=title,
        content=content,
        audience=audience if audience in {'students', 'parents', 'both'} else 'students',
    ))
    try:
        db.session.commit()
        flash('Class announcement posted.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Class announcement failed: %s', exc, exc_info=True)
        flash('Could not post announcement.', 'danger')
    return _sponsor_hub_redirect(class_id)


# ----------------------------------------------------------------------
# 2. NEURAL VISION INFERENCE ENGINE (OCR GRADING PIPELINE)
# ----------------------------------------------------------------------
def _run_activity_ocr_scan(assessment, student, teacher_profile, file_stream):
    """Shared OCR scan logic for activity grading."""
    if not ocr_engine_ready():
        return {
            'status': 'Error',
            'message': (
                'AI Scanner is not ready. Install Tesseract OCR on this computer '
                '(see README) and restart the server.'
            ),
        }, 503

    if not teacher_can_access_student(teacher_profile, current_user, student):
        return {'status': 'Error', 'message': 'Access denied for this student.'}, 403

    if get_student_class_id(student) != assessment.klass_id:
        return {'status': 'Error', 'message': 'Student is not in this activity class.'}, 400

    try:
        text = extract_text_from_stream(file_stream)
    except Exception as exc:
        logger.error('OCR scan failed: %s', exc, exc_info=True)
        return {'status': 'Error', 'message': f'Scan failed: {exc}'}, 422

    if not text.strip():
        return {
            'status': 'Error',
            'message': 'Scan failed: the image appears blank or unreadable. Retake the photo in good light.',
        }, 422

    keywords = parse_scan_keywords(assessment.scan_keywords)
    result = build_scan_result(text, keywords, assessment.max_score or 100.0)
    payload = {
        'status': 'Success',
        'student_id': student.id,
        'assessment_id': assessment.id,
        'suggested_grade': (
            f"{result['suggested_score']}/{result['max_score']}"
            if result['suggested_score'] is not None else None
        ),
        **result,
    }
    if not keywords:
        payload['hint'] = (
            'No answer keywords configured — review the extracted text and enter a score manually.'
        )
    return payload, 200


@app.route('/teacher/activity/<int:assessment_id>/scan/<int:student_id>', methods=['POST'])
@login_required
def scan_activity_submission(assessment_id, student_id):
    """Scan a photographed assignment and suggest a score from OCR keywords."""
    if normalize_role(current_user) != 'teacher':
        return jsonify({'status': 'Error', 'message': 'Only teachers can use the AI scanner.'}), 403

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        return jsonify({'status': 'Error', 'message': 'Teacher profile not found.'}), 403

    assessment = Assessment.query.get_or_404(assessment_id)
    student = Student.query.get_or_404(student_id)
    if not teacher_owns_assessment(teacher_profile, current_user, assessment):
        return jsonify({'status': 'Error', 'message': 'You are not authorized to scan this activity.'}), 403

    use_submission = request.form.get('use_submission') == '1'
    if use_submission:
        submission = Submission.query.filter_by(
            assessment_id=assessment.id,
            student_id=student.id,
        ).first()
        if not submission or not submission.file_path:
            return jsonify({'status': 'Error', 'message': 'No uploaded submission file to scan.'}), 400
        path = resolve_static_upload_path(submission.file_path)
        if not os.path.isfile(path):
            return jsonify({'status': 'Error', 'message': 'Submission file not found on server.'}), 404
        ext = os.path.splitext(path)[1].lower()
        if ext not in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff'}:
            return jsonify({
                'status': 'Error',
                'message': 'Submission is not a scannable image. Photograph the paper or upload a JPG/PNG.',
            }), 400
        with open(path, 'rb') as handle:
            payload, status_code = _run_activity_ocr_scan(
                assessment, student, teacher_profile, handle
            )
        return jsonify(payload), status_code

    if 'assignment' not in request.files:
        return jsonify({'status': 'Error', 'message': 'Upload a photo of the student work to scan.'}), 400

    file = request.files['assignment']
    if not file or not file.filename:
        return jsonify({'status': 'Error', 'message': 'Choose an image file to scan.'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff'}:
        return jsonify({'status': 'Error', 'message': 'Use a photo (JPG, PNG, etc.) for AI scanning.'}), 400

    payload, status_code = _run_activity_ocr_scan(
        assessment, student, teacher_profile, file.stream
    )
    return jsonify(payload), status_code


@app.route('/teacher/activity/<int:assessment_id>/scan-keywords', methods=['POST'])
@login_required
def update_activity_scan_keywords(assessment_id):
    """Save comma-separated OCR answer keywords for an activity."""
    if normalize_role(current_user) != 'teacher':
        flash('Only teachers can update scan settings.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    assessment = Assessment.query.get_or_404(assessment_id)
    if not teacher_profile or not teacher_owns_assessment(teacher_profile, current_user, assessment):
        flash('You are not authorized to edit this activity.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    assessment.scan_keywords = normalize_scan_keywords(request.form.get('scan_keywords'))
    try:
        db.session.commit()
        flash('AI scan keywords saved.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Scan keywords update failed: %s', exc, exc_info=True)
        flash('Could not save scan keywords.', 'danger')

    return redirect(url_for('activity_detail', assessment_id=assessment.id))


@app.route('/teacher/scan-assignment/<int:student_id>', methods=['POST'])
@login_required
def scan_assignment(student_id):
    """Legacy scan endpoint — forwards to activity-aware scanner when possible."""
    assessment_id = request.form.get('assessment_id', type=int)
    if assessment_id:
        return scan_activity_submission(assessment_id, student_id)

    if normalize_role(current_user) != 'teacher':
        return jsonify({'status': 'Error', 'message': 'Only teachers can use the AI scanner.'}), 403

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    student = Student.query.get_or_404(student_id)
    if not teacher_profile or not teacher_can_access_student(teacher_profile, current_user, student):
        return jsonify({'status': 'Error', 'message': 'Access denied.'}), 403

    if 'assignment' not in request.files or not request.files['assignment'].filename:
        return jsonify({'status': 'Error', 'message': 'Upload a photo to scan.'}), 400

    fallback_keywords = parse_scan_keywords(request.form.get('scan_keywords') or 'Liberia, Monrovia, 1847')
    try:
        text = extract_text_from_stream(request.files['assignment'].stream)
    except Exception as exc:
        return jsonify({'status': 'Error', 'message': str(exc)}), 422

    if not text.strip():
        return jsonify({'status': 'Error', 'message': 'Scan failed: unreadable image.'}), 422

    result = build_scan_result(text, fallback_keywords, 30.0)
    return jsonify({
        'status': 'Success',
        'suggested_grade': (
            f"{result['suggested_score']}/30" if result['suggested_score'] is not None else None
        ),
        'detected_text_snippet': result['detected_text_snippet'],
        **result,
    })


def _apply_activity_score(teacher_profile, assessment, student, score, feedback=None):
    """Save or update a student's score for an activity and refresh draft period grade."""
    submission = Submission.query.filter_by(
        assessment_id=assessment.id,
        student_id=student.id,
    ).first()
    if not submission:
        submission = Submission(
            assessment_id=assessment.id,
            student_id=student.id,
        )
        db.session.add(submission)

    submission.score = score
    submission.is_graded = True
    submission.score_published = True
    if feedback:
        submission.teacher_feedback = feedback

    sync_draft_period_grade(
        student,
        assessment.subject_name,
        assessment.marking_period or 1,
        teacher_id=teacher_profile.id if teacher_profile else None,
    )
    return submission


@app.route('/teacher/grade-submission/<int:submission_id>', methods=['POST'])
@login_required
def grade_submission(submission_id):
    if normalize_role(current_user) != 'teacher':
        flash('Only teachers can grade submissions.', 'danger')
        return redirect(url_for('login'))

    submission = Submission.query.get_or_404(submission_id)
    assessment = submission.assessment
    student = submission.student
    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    klass = assessment.klass if assessment else None
    if not klass or not teacher_can_access_class(teacher_profile, current_user, klass.id):
        flash('You are not authorized to grade this submission.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    try:
        score = float(request.form.get('score'))
    except (TypeError, ValueError):
        flash('Invalid score provided.', 'danger')
        return redirect(url_for('activity_detail', assessment_id=assessment.id))

    max_score = assessment.max_score or 100.0
    if score < 0 or score > max_score:
        flash(f'Score must be between 0 and {max_score}.', 'danger')
        return redirect(url_for('activity_detail', assessment_id=assessment.id))

    feedback = request.form.get('feedback', '').strip() or None
    _apply_activity_score(teacher_profile, assessment, student, score, feedback=feedback)

    db.session.commit()
    flash('Score saved. Draft period grade updated for the student dashboard.', 'success')
    return redirect(request.referrer or url_for('activity_detail', assessment_id=assessment.id))


@app.route('/teacher/grade-activity/<int:assessment_id>/<int:student_id>', methods=['POST'])
@login_required
def grade_activity_student(assessment_id, student_id):
    """Let teachers set activity scores for any student in the class roster."""
    if normalize_role(current_user) != 'teacher':
        flash('Only teachers can grade activities.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    assessment = Assessment.query.get_or_404(assessment_id)
    student = Student.query.get_or_404(student_id)
    klass = assessment.klass
    if not klass or not teacher_can_access_class(teacher_profile, current_user, klass.id):
        flash('You are not authorized to grade this activity.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    if get_student_class_id(student) != klass.id:
        flash('This student is not in the activity class.', 'danger')
        return redirect(url_for('activity_detail', assessment_id=assessment.id))

    try:
        score = float(request.form.get('score'))
    except (TypeError, ValueError):
        flash('Invalid score provided.', 'danger')
        return redirect(url_for('activity_detail', assessment_id=assessment.id))

    max_score = assessment.max_score or 100.0
    if score < 0 or score > max_score:
        flash(f'Score must be between 0 and {max_score}.', 'danger')
        return redirect(url_for('activity_detail', assessment_id=assessment.id))

    feedback = request.form.get('feedback', '').strip() or None
    _apply_activity_score(teacher_profile, assessment, student, score, feedback=feedback)

    db.session.commit()
    flash(f'Score saved for {student.full_name}.', 'success')
    return redirect(url_for('activity_detail', assessment_id=assessment.id))


@app.route('/teacher/grade-activity/<int:assessment_id>/bulk', methods=['POST'])
@login_required
def bulk_grade_activity(assessment_id):
    """Save scores for multiple students on one activity in a single submit."""
    role = normalize_role(current_user)
    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if role not in ('teacher', 'admin'):
        flash('Only teachers can grade activities.', 'danger')
        return redirect(url_for('login'))
    if role == 'teacher' and not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    assessment = Assessment.query.get_or_404(assessment_id)
    klass = assessment.klass
    if not klass or not can_enter_class_grades(current_user, teacher_profile, klass.id):
        flash('You are not authorized to grade this activity.', 'danger')
        return redirect(url_for('teacher_dashboard', tab='grades'))

    max_score = assessment.max_score or 100.0
    active_year = get_active_academic_year()
    year_id = active_year.id if active_year else None
    roster_ids = {
        s.id for s in get_students_for_class_ids([klass.id], academic_year_id=year_id)
    }
    saved_count = 0
    errors = []

    for student_id in roster_ids:
        score_raw = request.form.get(f'score_{student_id}', '').strip()
        if score_raw == '':
            continue
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            errors.append(f'Invalid score for student #{student_id}')
            continue
        if score < 0 or score > max_score:
            errors.append(f'Score for student #{student_id} must be 0–{max_score}')
            continue

        student = db.session.get(Student, student_id)
        if not student:
            continue
        feedback = request.form.get(f'feedback_{student_id}', '').strip() or None
        _apply_activity_score(
            teacher_profile,
            assessment,
            student,
            score,
            feedback=feedback,
        )
        saved_count += 1

    if errors:
        for msg in errors[:3]:
            flash(msg, 'danger')
        if not saved_count:
            db.session.rollback()
            return redirect(url_for('activity_detail', assessment_id=assessment.id))

    db.session.commit()
    if saved_count:
        flash(f'Saved {saved_count} score{"s" if saved_count != 1 else ""} for {assessment.title}.', 'success')
    else:
        flash('No scores entered. Fill in at least one score field.', 'warning')

    return_to = (request.form.get('return_to') or '').strip()
    if return_to == 'manual_activity_grades' and klass:
        return redirect(url_for(
            'manual_activity_grades',
            class_id=klass.id,
            subject=assessment.subject_name,
            period=assessment.marking_period or 1,
            assessment_id=assessment.id,
        ))
    return redirect(url_for('activity_detail', assessment_id=assessment.id))


@app.route('/teacher/class/<int:class_id>/quick-activity-grades', methods=['POST'])
@login_required
def save_quick_activity_grades(class_id):
    """Save per-student activity scores without requiring a pre-created named activity."""
    role = normalize_role(current_user)
    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if role not in ('teacher', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    if role == 'teacher' and not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    if not can_enter_class_grades(current_user, teacher_profile, class_id):
        flash('You are not authorized to enter grades for this class.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    subject_name = (request.form.get('subject') or '').strip()
    period = request.form.get('period', type=int)
    if not subject_name:
        flash('Please select a subject before saving scores.', 'danger')
        return redirect(url_for('manual_activity_grades', class_id=class_id))
    if period not in range(1, 9):
        flash('Invalid marking period selected.', 'danger')
        return redirect(url_for('manual_activity_grades', class_id=class_id, subject=subject_name))

    if role == 'teacher':
        allowed_subjects = get_assignable_subjects_for_class(
            teacher_profile, current_user, class_id
        )
        if subject_name not in allowed_subjects:
            flash('You are not assigned to teach that subject in this class.', 'danger')
            return redirect(url_for('manual_activity_grades', class_id=class_id))

    assessment = get_or_create_quick_entry_assessment(
        class_id, subject_name, period, active_year, teacher_profile
    )
    max_score = assessment.max_score or 100.0
    roster_ids = {
        s.id for s in get_students_for_class_ids([class_id], academic_year_id=active_year.id)
    }
    saved_count = 0
    errors = []

    for student_id in roster_ids:
        score_raw = request.form.get(f'score_{student_id}', '').strip()
        if score_raw == '':
            continue
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            errors.append(f'Invalid score for student #{student_id}')
            continue
        if score < 0 or score > max_score:
            errors.append(f'Score for student #{student_id} must be 0–{max_score}')
            continue

        student = db.session.get(Student, student_id)
        if not student:
            continue
        feedback = request.form.get(f'feedback_{student_id}', '').strip() or None
        _apply_activity_score(
            teacher_profile,
            assessment,
            student,
            score,
            feedback=feedback,
        )
        saved_count += 1

    if errors:
        for msg in errors[:3]:
            flash(msg, 'danger')
        if not saved_count:
            db.session.rollback()
            return redirect(url_for(
                'manual_activity_grades',
                class_id=class_id,
                subject=subject_name,
                period=period,
            ))

    db.session.commit()
    if saved_count:
        flash(
            f'Saved {saved_count} activity score{"s" if saved_count != 1 else ""} '
            f'for {subject_name} · {grading_period_label(period)}.',
            'success',
        )
    else:
        flash('No scores entered. Fill in at least one score field.', 'warning')

    return redirect(url_for(
        'manual_activity_grades',
        class_id=class_id,
        subject=subject_name,
        period=period,
    ))


@app.route('/teacher/class/<int:class_id>/activity-grades', methods=['GET'])
@login_required
def manual_activity_grades(class_id):
    """Manual activity score entry: class → subject → period → activity → student roster."""
    role = normalize_role(current_user)
    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if role not in ('teacher', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    if role == 'teacher' and not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    klass = Class.query.get_or_404(class_id)
    if not can_enter_class_grades(current_user, teacher_profile, class_id):
        flash('You are not authorized to enter grades for this class.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year found.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if role == 'admin':
        class_cards = [{
            'id': klass.id,
            'name': klass.name,
            'grade_level': klass.grade_level,
            'stream': klass.stream,
            'student_count': Student.query.filter_by(
                klass_id=klass.id, academic_year_id=active_year.id
            ).count(),
        }]
    else:
        class_cards = get_teacher_class_cards(
            teacher_profile, current_user, active_year.id
        )

    subjects = (
        get_assignable_subjects_for_class(teacher_profile, current_user, class_id)
        if role == 'teacher'
        else get_class_subject_catalog(class_id)
    )
    selected_subject = (request.args.get('subject') or '').strip()
    if selected_subject not in subjects:
        selected_subject = subjects[0] if subjects else ''

    valid_periods = {p for p, _ in MOE_GRADING_PERIODS}
    selected_period = request.args.get('period', 1, type=int)
    if selected_period not in valid_periods:
        selected_period = 1

    students = get_class_students_for_year(class_id, active_year)

    assessment_id = request.args.get('assessment_id', type=int)

    activity_options = []
    quick_entry_assessment = None
    quick_entry_submissions = {}
    quick_entry_graded_count = 0
    quick_entry_max_score = 100.0
    if selected_subject:
        activity_options = [
            act for act in Assessment.query.filter_by(
                klass_id=class_id,
                subject_name=selected_subject,
                marking_period=selected_period,
                academic_year_id=active_year.id,
            )
            .order_by(Assessment.id.desc())
            .all()
            if not is_quick_entry_assessment(act)
        ]
        if not assessment_id:
            quick_entry_assessment = find_quick_entry_assessment(
                class_id, selected_subject, selected_period, active_year.id
            )
            if quick_entry_assessment:
                quick_entry_max_score = quick_entry_assessment.max_score or 100.0
                subs = Submission.query.filter_by(
                    assessment_id=quick_entry_assessment.id
                ).all()
                quick_entry_submissions = {sub.student_id: sub for sub in subs}
                quick_entry_graded_count = sum(1 for sub in subs if sub.is_graded)
    selected_assessment = None
    class_students = []
    submission_by_student = {}
    graded_count = 0
    pending_count = 0

    if assessment_id:
        selected_assessment = Assessment.query.get(assessment_id)
        if selected_assessment:
            year_ok = selected_assessment.academic_year_id == active_year.id
            class_ok = selected_assessment.klass_id == class_id
            if not year_ok or not class_ok:
                selected_assessment = None
                assessment_id = None
            elif not can_enter_class_grades(current_user, teacher_profile, selected_assessment.klass_id):
                flash('You are not authorized to grade this activity.', 'danger')
                return redirect(url_for('teacher_dashboard'))
            else:
                selected_subject = selected_assessment.subject_name or selected_subject
                selected_period = selected_assessment.marking_period or selected_period
                class_students = students
                subs = Submission.query.filter_by(assessment_id=selected_assessment.id).all()
                submission_by_student = {sub.student_id: sub for sub in subs}
                graded_count = sum(1 for sub in subs if sub.is_graded)
                pending_count = max(len(class_students) - graded_count, 0)

    period_label = grading_period_label(selected_period)
    publish_stats = (
        get_class_period_publish_stats(
            class_id,
            selected_subject,
            selected_period,
            active_year.id,
            student_ids={s.id for s in students},
        )
        if selected_subject
        else {'total': 0, 'published': 0, 'draft': 0}
    )

    grade_rows = {}
    if selected_subject:
        student_ids = {s.id for s in students}
        existing_grades = Grade.query.filter_by(
            class_id=class_id,
            subject=selected_subject,
            academic_year_id=active_year.id,
        ).all()
        for grade in existing_grades:
            period_num = grade.marking_period or normalize_grade_period(grade.period)
            if period_num == selected_period and grade.student_id in student_ids:
                grade_rows[grade.student_id] = grade

    return render_template(
        'teacher_manual_activity_grades.html',
        klass=klass,
        class_cards=class_cards,
        active_year=active_year,
        subjects=subjects,
        selected_subject=selected_subject,
        selected_period=selected_period,
        period_label=period_label,
        grading_periods=MOE_GRADING_PERIODS,
        activity_options=activity_options,
        selected_assessment=selected_assessment,
        assessment_id=assessment_id,
        students=students,
        class_students=class_students,
        submission_by_student=submission_by_student,
        graded_count=graded_count,
        pending_count=pending_count,
        roster_size=len(students),
        grade_rows=grade_rows,
        publish_stats=publish_stats,
        quick_entry_assessment=quick_entry_assessment,
        quick_entry_submissions=quick_entry_submissions,
        quick_entry_graded_count=quick_entry_graded_count,
        quick_entry_max_score=quick_entry_max_score,
    )


@app.route('/teacher/download-submission/<int:submission_id>')
@login_required
def teacher_download_submission(submission_id):
    """Download a student's submitted file for review."""
    if normalize_role(current_user) != 'teacher':
        flash('Only teachers can download student submissions.', 'danger')
        return redirect(url_for('login'))

    teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher_profile:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('login'))

    submission = Submission.query.get_or_404(submission_id)
    assessment = submission.assessment
    klass = assessment.klass if assessment else None
    if not klass or not teacher_can_access_class(teacher_profile, current_user, klass.id):
        flash('You are not authorized to access this submission.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if not submission.file_path:
        flash('This submission has no uploaded file.', 'warning')
        return redirect(url_for('activity_detail', assessment_id=assessment.id))

    rel_path = submission.file_path.replace('\\', '/').lstrip('/')
    if rel_path.startswith('static/'):
        rel_path = rel_path[len('static/'):]
    return safe_send_upload_file(os.path.dirname(rel_path), os.path.basename(rel_path))
# -------------------------- DISCIPLINE & SUSPENSION ---------------------------
@app.route('/student/<int:student_id>/suspend', methods=['POST'])
@login_required
@role_required('Dean', 'admin')
def suspend_student(student_id):
    days = request.form.get('days', type=int)
    reason = request.form.get('reason')
    if not days or not reason:
        flash("Days and reason are required for suspension.", "danger")
        return redirect(url_for('dean_dashboard'))
    
    msg = SchoolEngine.suspend_student(student_id, days, reason)
    log_security_event(f"Student {student_id} suspended. Reason: {reason}")
    flash(msg, "warning")
    return redirect(url_for('dean_dashboard'))

# -------------------------- CLASS MANAGEMENT ---------------------------

RESET_ROLE_GROUPS = [
    {
        'key': 'teacher',
        'label': 'Teachers',
        'icon': 'fa-chalkboard-teacher',
        'browse': 'list',
        'roles': {'teacher'},
    },
    {
        'key': 'student',
        'label': 'Students',
        'icon': 'fa-user-graduate',
        'browse': 'class_folders',
        'roles': {'student'},
    },
    {
        'key': 'staff',
        'label': 'Staff',
        'icon': 'fa-briefcase',
        'browse': 'list',
        'roles': {'registrar', 'business', 'vpa', 'vpi', 'dean', 'principal', 'parent', 'sponsor'},
    },
    {
        'key': 'admin',
        'label': 'Administrators',
        'icon': 'fa-user-shield',
        'browse': 'list',
        'roles': {'admin'},
        'admin_only': True,
    },
]


def _reset_operator_can_target(operator, target_user):
    """Whether the logged-in operator may reset target_user's password."""
    if not operator or not target_user:
        return False
    op_role = (operator.role or '').lower()
    if op_role == 'admin':
        return True
    if op_role == 'principal':
        if target_user.id == operator.id:
            return False
        return (target_user.role or '').lower() != 'admin'
    return False


def _reset_role_groups_for_operator(operator):
    groups = []
    op_role = (operator.role or '').lower()
    for group in RESET_ROLE_GROUPS:
        if group.get('admin_only') and op_role != 'admin':
            continue
        groups.append(group)
    return groups


def _reset_group_by_key(role_key):
    for group in RESET_ROLE_GROUPS:
        if group['key'] == role_key:
            return group
    return RESET_ROLE_GROUPS[0]


def _reset_build_class_folders():
    folders = []
    active_year = get_active_academic_year()
    for klass in Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all():
        students = (
            _principal_students_for_class(klass, active_year, viewing_archived=False)
            if active_year else []
        )
        portal_count = sum(1 for student in students if student.user_id)
        folders.append({
            'klass': klass,  
            'student_count': len(students),
            'portal_count': portal_count,
        })
    return folders

def _reset_build_class_students(klass, search_q, operator):
    rows = []
    active_year = get_active_academic_year()
    students = (
        _principal_students_for_class(klass, active_year, viewing_archived=False)
        if active_year else []
    )
    for student in students:
        user = db.session.get(User, student.user_id) if student.user_id else None
        if search_q:
            haystack = ' '.join(filter(None, [
                student.first_name,
                student.last_name,
                student.student_id,
                user.email if user else '',
            ])).lower()
            if search_q.lower() not in haystack:
                continue
        rows.append({
            'student': student,
            'user': user,
            'can_reset': _reset_operator_can_target(operator, user) if user else False,
        })
    return rows


def _reset_build_role_users(role_keys, search_q, operator):
    rows = []
    for user in User.query.order_by(User.full_name.asc()).all():
        if (user.role or '').lower() not in role_keys:
            continue
        if not _reset_operator_can_target(operator, user):
            continue
        if search_q:
            haystack = f"{user.full_name or ''} {user.email or ''} {user.role or ''}".lower()
            if search_q.lower() not in haystack:
                continue
        teacher = (
            Teacher.query.filter_by(user_id=user.id).first()
            if (user.role or '').lower() == 'teacher'
            else None
        )
        rows.append({'user': user, 'teacher': teacher})
    return rows


@app.route('/admin/account/override-reset', methods=['GET', 'POST'])
@login_required
def administrative_password_reset():
    if not current_user.role or current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access matrix. Insufficient clearance permissions.", "danger")
        return redirect(url_for('login'))

    role_groups = _reset_role_groups_for_operator(current_user)
    selected_role = request.args.get('role') or request.form.get('return_role') or role_groups[0]['key']
    selected_group = _reset_group_by_key(selected_role)
    if selected_group.get('admin_only') and current_user.role.lower() != 'admin':
        selected_role = role_groups[0]['key']
        selected_group = role_groups[0]

    search_q = (request.args.get('q') or request.form.get('return_q') or '').strip()
    class_id = request.args.get('class_id', type=int) or request.form.get('return_class_id', type=int)
    target_user_id = request.args.get('target_user_id', type=int)
    selected_class = db.session.get(Class, class_id) if class_id else None
    selected_target = db.session.get(User, target_user_id) if target_user_id else None

    if selected_target and not _reset_operator_can_target(current_user, selected_target):
        flash("Security Exception: You cannot reset this account.", "danger")
        selected_target = None
        target_user_id = None

    if request.method == 'POST':
        post_target_id = request.form.get('target_user_id', type=int)
        new_password = (request.form.get('new_password') or '').strip()
        confirm_password = (request.form.get('confirm_password') or '').strip()
        return_role = request.form.get('return_role') or selected_role
        return_class_id = request.form.get('return_class_id', type=int)
        return_q = (request.form.get('return_q') or '').strip()

        def _reset_redirect(target_id=None):
            params = {'role': return_role}
            if return_class_id:
                params['class_id'] = return_class_id
            if return_q:
                params['q'] = return_q
            if target_id:
                params['target_user_id'] = target_id
            return redirect(url_for('administrative_password_reset', **params))

        if not post_target_id or not new_password:
            flash("Missing mandatory transmission parameters.", "danger")
            return _reset_redirect(post_target_id)

        if new_password != confirm_password:
            flash("Passwords do not match. Enter the same password in both fields.", "danger")
            return _reset_redirect(post_target_id)

        if len(new_password) < 6:
            flash("Security policy violation: Password string must be at least 6 characters.", "danger")
            return _reset_redirect(post_target_id)

        target_user = db.session.get(User, post_target_id)
        if not target_user:
            flash("Target identity record node could not be pulled from system ledger.", "danger")
            return _reset_redirect()

        if not _reset_operator_can_target(current_user, target_user):
            flash("Security Exception: You cannot reset this account.", "danger")
            return _reset_redirect()

        try:
            target_user.set_password(new_password)
            db.session.commit()
            flash(
                f"Credentials for {target_user.full_name or target_user.username} successfully overwritten. "
                f"They can sign in immediately with the new password.",
                "success",
            )
            return _reset_redirect()
        except Exception as e:
            db.session.rollback()
            logger.error("Password reset commit failed: %s", e, exc_info=True)
            flash("An internal transactional ledger exception aborted password commitment.", "danger")
            return _reset_redirect(post_target_id)

    class_folders = _reset_build_class_folders() if selected_group['browse'] == 'class_folders' else []
    class_students = (
        _reset_build_class_students(selected_class, search_q, current_user)
        if selected_class
        else []
    )
    role_users = (
        _reset_build_role_users(selected_group['roles'], search_q, current_user)
        if selected_group['browse'] == 'list'
        else []
    )

    return render_template(
        'administrative_reset.html',
        role_groups=role_groups,
        selected_role=selected_role,
        selected_group=selected_group,
        class_folders=class_folders,
        selected_class=selected_class,
        class_students=class_students,
        role_users=role_users,
        search_q=search_q,
        class_id=class_id,
        target_user_id=target_user_id,
        selected_target=selected_target,
    )

@app.route('/class/edit/<int:class_id>', methods=['GET', 'POST'])
@login_required
def class_edit(class_id):
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES | {'vpi'})
    if blocked:
        return blocked

    # Modern SQLAlchemy 2.0 implementation fallback for query
    klass = Class.query.get_or_404(class_id)
    form = CreateClassForm(obj=klass)
    
    teachers = Teacher.query.order_by(Teacher.first_name, Teacher.last_name).all()
    teacher_choices = [
        (t.id, (f"{(t.first_name or '').strip()} {(t.last_name or '').strip()}".strip() or (t.user.full_name if t.user else f"Teacher {t.id}")))
        for t in teachers
    ]
    sponsor_choices = [(0, "— No Sponsor —")] + teacher_choices

    form.teacher_id.choices = [(0, "— Select Teacher —")] + teacher_choices
    form.sponsor_id.choices = sponsor_choices

    if request.method == 'GET':
        form.teacher_id.data = klass.teacher_id or 0
        if klass.sponsor_id:
            sponsor_teacher = Teacher.query.filter_by(user_id=klass.sponsor_id).first()
            form.sponsor_id.data = sponsor_teacher.id if sponsor_teacher else 0
        else:
            form.sponsor_id.data = 0
        form.ca_weight.data = (klass.grading_scheme or {}).get('ca_weight') if klass.grading_scheme else None
        form.exam_weight.data = (klass.grading_scheme or {}).get('exam_weight') if klass.grading_scheme else None

    if form.validate_on_submit():
        raw_teacher_id = form.teacher_id.data
        raw_sponsor_id = form.sponsor_id.data

        teacher_id = None if raw_teacher_id in (0, '0', '', None) else int(raw_teacher_id)
        sponsor_teacher_id = None if raw_sponsor_id in (0, '0', '', None) else int(raw_sponsor_id)

        sponsor_id = None
        if sponsor_teacher_id:
            # Modernized SQLAlchemy 2.0 Safe Lookup
            sponsor_teacher = db.session.get(Teacher, sponsor_teacher_id)
            sponsor_id = sponsor_teacher.user_id if sponsor_teacher else None

        klass.name = form.name.data
        klass.grade_level = form.grade_level.data
        klass.stream = form.stream.data.strip() if form.stream.data else None
        klass.description = form.description.data
        klass.yearly_fee = parse_currency_amount_optional(form.yearly_fee.data)
        klass.teacher_id = teacher_id
        klass.sponsor_id = sponsor_id

        if form.ca_weight.data is not None or form.exam_weight.data is not None:
            ca_weight = form.ca_weight.data if form.ca_weight.data is not None else (klass.grading_scheme or {}).get('ca_weight', 60)
            exam_weight = form.exam_weight.data if form.exam_weight.data is not None else (klass.grading_scheme or {}).get('exam_weight', 40)
            try:
                ca_weight = int(ca_weight)
                exam_weight = int(exam_weight)
            except (TypeError, ValueError):
                raise ValueError('Grading weights must be whole numbers.')
            if ca_weight < 0 or exam_weight < 0:
                raise ValueError('Grading weights must be zero or positive.')
            if ca_weight + exam_weight > 0:
                klass.grading_scheme = {
                    'ca_weight': ca_weight,
                    'exam_weight': exam_weight,
                }
            else:
                klass.grading_scheme = None

        try:
            db.session.commit()
            flash(f"Class '{klass.name}' updated successfully.", "success")
            return redirect(url_for('class_create'))
        except Exception as e:
            db.session.rollback()
            print(f"[-] Database Error during class update: {str(e)}")
            flash("Database error occurred while updating class data.", "danger")

    return render_template('class_edit.html', form=form, klass=klass)


def _build_class_sponsor_matrix(classes):
    """Map each class to its assigned homeroom sponsor teacher."""
    rows = []
    for klass in classes:
        sponsor_name = None
        sponsor_user_id = None
        if klass.sponsor_id:
            sponsor_user = db.session.get(User, klass.sponsor_id)
            if sponsor_user:
                sponsor_name = sponsor_user.full_name
                sponsor_user_id = sponsor_user.id
        rows.append({
            'klass': klass,
            'sponsor_name': sponsor_name,
            'sponsor_user_id': sponsor_user_id,
        })
    return rows


@app.route('/principal/class-sponsors', methods=['GET'])
@login_required
def principal_class_sponsors():
    """Full class sponsor command center for principal/admin."""
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked

    classes = Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all()
    teachers = Teacher.query.filter_by(status='ACTIVE').order_by(
        Teacher.first_name.asc(), Teacher.last_name.asc()
    ).all()
    return render_template(
        'principal_class_sponsors.html',
        classes=classes,
        teachers=teachers,
        sponsor_matrix=_build_class_sponsor_matrix(classes),
    )


@app.route('/class/<int:class_id>/sponsor', methods=['POST'])
@login_required
def class_set_sponsor(class_id):
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked

    klass = Class.query.get_or_404(class_id)
    sponsor_id = request.form.get('sponsor_id', type=int)
    teacher_id = request.form.get('teacher_id', type=int)
    next_page = (request.form.get('next') or 'class_create').strip()

    if not sponsor_id and teacher_id:
        teacher_profile = db.session.get(Teacher, teacher_id)
        if teacher_profile and teacher_profile.user_id:
            sponsor_id = teacher_profile.user_id

    if sponsor_id:
        # Modernized SQLAlchemy 2.0 Safe Lookup
        sponsor = db.session.get(User, sponsor_id)
        teacher_profile = Teacher.query.filter_by(user_id=sponsor_id).first()
        
        if not sponsor or not teacher_profile:
            flash("Invalid sponsor selection. Only teachers can be sponsors.", "danger")
            return redirect(url_for(next_page) if next_page in current_app.view_functions else url_for('class_create'))
            
        klass.sponsor_id = sponsor.id
        flash(f"Assigned teacher {sponsor.full_name} as sponsor to {klass.name}.", "success")
    else:
        klass.sponsor_id = None
        flash(f"Sponsor cleared for {klass.name}.", "info")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[-] Database Error during assigning sponsor: {str(e)}")
        flash("Failed to commit database modifications.", "danger")

    if next_page in current_app.view_functions:
        return redirect(url_for(next_page))
    return redirect(url_for('class_create'))

# ------------------------ ACADEMIC YEAR ROLLOVER WIZARD ---------------------------
def _parse_grade_level(grade_level):
    """Return an integer grade 1–12 from stored labels (10, '10th', 'Grade 12')."""
    if grade_level is None or grade_level == '':
        return None
    if isinstance(grade_level, bool):
        return None
    return parse_grade_number(grade_level)


def _grades_match(grade_a, grade_b):
    """True when two grade labels refer to the same tier (e.g. 10 == 'Grade 10')."""
    if grade_a is None or grade_b is None:
        return grade_a == grade_b
    parsed_a = _parse_grade_level(grade_a)
    parsed_b = _parse_grade_level(grade_b)
    if parsed_a is not None and parsed_b is not None:
        return parsed_a == parsed_b
    canon_a = canonical_grade_value(grade_a)
    canon_b = canonical_grade_value(grade_b)
    if canon_a and canon_b:
        return canon_a == canon_b
    return str(grade_a).strip().lower() == str(grade_b).strip().lower()


def _student_grade_level(student):
    """Resolve a student's grade tier from stored grade_level or assigned class."""
    if student.grade_level:
        parsed = _parse_grade_level(student.grade_level)
        return parsed if parsed is not None else student.grade_level
    if student.klass_id:
        klass = student.assigned_class or db.session.get(Class, student.klass_id)
        if klass:
            parsed = _parse_grade_level(klass.grade_level)
            return parsed if parsed is not None else klass.grade_level
    return None


def _subject_yearly_averages_for_decision(grades, visible_periods=None, division_key=None):
    """Printed YRLY AVE per academic subject (not CONDUCT, not footer AVERAGE)."""
    grouped = {}
    for grade in grades or []:
        raw_name = (grade.subject or grade.subject_name or '').strip()
        if not raw_name:
            continue
        official = canonical_subject_name(raw_name, division_key) or raw_name
        if is_report_summary_subject(official) or is_conduct_subject(official):
            continue
        key = subject_match_key(official)
        if not key:
            continue
        grouped.setdefault(key, []).append(grade)

    averages = []
    for sub_grades in grouped.values():
        scores = _collect_official_period_scores(sub_grades, visible_periods)
        if not scores:
            continue
        row = official_subject_score_row('', scores, division_key)
        yearly = numeric_report_score(row.get('final_avg') or row.get('yearly'))
        if yearly is not None:
            averages.append(float(yearly))
    return averages


def _yearly_averages_from_subject_rows(subjects):
    """YRLY AVE values from printed academic rows only (skip AVERAGE / CONDUCT)."""
    averages = []
    for subject in subjects or []:
        if not isinstance(subject, dict):
            continue
        if subject.get('is_summary') or is_report_summary_subject(subject.get('name')):
            continue
        yearly = numeric_report_score(subject.get('final_avg') or subject.get('yearly'))
        if yearly is not None:
            averages.append(float(yearly))
    return averages


def _promotion_decision_record(
    *,
    passed,
    code,
    decision,
    label,
    reason,
    overall_average,
    failing_count,
    subject_count,
    promoted_to=None,
):
    return {
        'passed': passed,
        'code': code,
        'decision': decision,
        'label': label,
        'reason': reason,
        'overall_average': overall_average,
        'failing_subject_count': failing_count,
        'subject_count': subject_count,
        'promoted_to': promoted_to,
    }


def _incomplete_promotion_record():
    return _promotion_decision_record(
        passed=False,
        code='INCOMPLETE',
        decision='repeat',
        label='Incomplete record',
        reason=(
            'No subject scores are on file for this academic year. '
            'Promotion cannot be certified until a complete grade record is posted.'
        ),
        overall_average=None,
        failing_count=0,
        subject_count=0,
    )


def _year_promotion_from_averages(averages, student, academic_year_id=None):
    """Apply MoE red-mark rules to printed subject YRLY AVE values."""
    empty = _incomplete_promotion_record()
    if not student or not averages:
        return empty

    pass_score = promotion_pass_score()
    summer_failing = max_failing_subjects_for_promotion()
    repeat_failing = repeat_class_failing_subject_threshold()
    overall_average = sum(averages) / len(averages)
    failing_count = sum(1 for avg in averages if avg < pass_score)
    avg_txt = f'{overall_average:.1f}%'
    fail_txt = (
        f'{failing_count} subject yearly average(s) below {pass_score:.0f}%'
        if failing_count
        else f'all recorded subjects at or above {pass_score:.0f}%'
    )
    grade_level_numeric = _parse_grade_level(_student_grade_level(student))
    is_grade_12 = grade_level_numeric == 12
    stats = {
        'overall_average': round(overall_average, 2),
        'failing_count': failing_count,
        'subject_count': len(averages),
    }

    if failing_count >= repeat_failing:
        if is_grade_12:
            reason = (
                f'{failing_count} subject yearly averages are below the Ministry of Education '
                f'passing mark of {pass_score:.0f}%. The student is not eligible to graduate '
                f'and must repeat class, regardless of the overall yearly average ({avg_txt}).'
            )
        else:
            reason = (
                f'{failing_count} subject yearly averages are below the Ministry of Education '
                f'passing mark of {pass_score:.0f}%. The student must repeat class, '
                f'regardless of the overall yearly average ({avg_txt}).'
            )
        return _promotion_decision_record(
            passed=False,
            code='REPEAT',
            decision='repeat',
            label='Repeat class',
            reason=reason,
            **stats,
        )

    if failing_count == summer_failing:
        if is_grade_12:
            reason = (
                f'Two subject yearly averages are below the Ministry of Education passing mark '
                f'of {pass_score:.0f}% (year average {avg_txt}; {fail_txt}). '
                'The student is assigned to Summer School and is not eligible to graduate.'
            )
        else:
            reason = (
                f'Two subject yearly averages are below the Ministry of Education passing mark '
                f'of {pass_score:.0f}% (year average {avg_txt}; {fail_txt}). '
                'The student is assigned to Summer School and is not promoted to the next class.'
            )
        return _promotion_decision_record(
            passed=False,
            code='SUMMER_SCHOOL',
            decision='summer_school',
            label='Summer School',
            reason=reason,
            **stats,
        )

    if overall_average < pass_score:
        return _promotion_decision_record(
            passed=False,
            code='REPEAT',
            decision='repeat',
            label='Repeat class',
            reason=(
                f'Did not meet the Ministry of Education promotion standard of {pass_score:.0f}%. '
                f'Year average {avg_txt}; {fail_txt}. The student is retained in the same class.'
            ),
            **stats,
        )

    if is_grade_12:
        return _promotion_decision_record(
            passed=True,
            code='GRADUATED',
            decision='graduate',
            label='Graduated',
            reason=(
                f'Met the promotion standard (year average {avg_txt}; {fail_txt}) '
                'and completed Grade 12.'
            ),
            **stats,
        )

    promoted_to = None
    current_class = get_student_class_for_year(student, academic_year_id)
    if current_class:
        target_id = build_default_promotion_map(Class.query.all()).get(current_class.id)
        if isinstance(target_id, int):
            target_class = db.session.get(Class, target_id)
            if target_class:
                promoted_to = target_class.name
                if target_class.stream:
                    promoted_to = f'{promoted_to} ({target_class.stream})'

    return _promotion_decision_record(
        passed=True,
        code='PROMOTED',
        decision='promote',
        label='Promoted',
        reason=(
            f'Met the Ministry of Education promotion standard of {pass_score:.0f}% '
            f'(year average {avg_txt}; {fail_txt}). Eligible to advance to the next class.'
        ),
        promoted_to=promoted_to,
        **stats,
    )


def evaluate_year_promotion_from_subject_rows(subjects, student, academic_year_id=None):
    """Promotion Statement from the YRLY AVE cells printed on the sheet."""
    return _year_promotion_from_averages(
        _yearly_averages_from_subject_rows(subjects),
        student,
        academic_year_id=academic_year_id,
    )


def evaluate_year_promotion_decision(student, academic_year=None):
    """
    Official year-end decision from each subject's printed YRLY AVE cell.

    Outcomes: promote | summer_school | repeat | graduate.

    Red marks are academic subjects whose yearly average is below the MoE
    pass mark (default 70%). CONDUCT and the footer AVERAGE row do not count.

    - 0 or 1 failing YRLY AVE subjects: promote (or graduate in Grade 12)
      only if the overall yearly average also meets the MoE pass mark.
    - Exactly 2 failing YRLY AVE subjects: Summer School — retained in the
      current class, not promoted, and Grade 12 does not graduate.
    - 3 or more failing YRLY AVE subjects: Repeat class, regardless of the
      overall yearly average.
    """
    empty = _incomplete_promotion_record()
    if not student:
        return empty
    if academic_year is None:
        academic_year = get_active_academic_year()
    if not academic_year:
        return empty

    grades = official_grade_records(student.id, academic_year.id)
    if not grades:
        return empty

    klass = get_student_class_for_year(student, academic_year.id)
    division_key = resolve_from_class(
        klass,
        getattr(student, 'level', None),
        getattr(student, 'grade_level', None),
    )
    averages = _subject_yearly_averages_for_decision(grades, division_key=division_key)
    return _year_promotion_from_averages(averages, student, academic_year_id=academic_year.id)


def check_promotion_criteria(student, academic_year=None):
    """True if the student is promoted or graduated (not summer school or repeat)."""
    return bool(evaluate_year_promotion_decision(student, academic_year).get('passed'))


def _next_academic_year_name(name):
    """Advance labels like 2025-2026, 2035–36, or 2099/00 to the next span."""
    return next_academic_year_label(name)


def _students_eligible_for_rollover(academic_year):
    """Students still on the year roster, including REPEAT/FAILED/SUSPENDED."""
    if not academic_year:
        return []
    return Student.query.filter(
        Student.academic_year_id == academic_year.id,
        Student.status.in_(list(ACTIVE_ENROLLMENT_STATUSES)),
    ).all()


def _resolve_or_create_next_academic_year(active_year):
    """End the current year and activate (or create) the next academic year."""
    if not active_year:
        return None

    next_name = _next_academic_year_name(active_year.name)
    if not next_name:
        if active_year.start_date:
            y = active_year.start_date.year
            next_name = f"{y + 1}-{y + 2}"
        else:
            next_name = f"{active_year.name} (Next)"
    else:
        next_name = normalize_academic_year_name(next_name)

    active_year.is_active = False
    if not active_year.end_date:
        active_year.end_date = datetime.now(timezone.utc).date()

    existing = find_academic_year_by_name(next_name)
    if existing:
        _set_active_academic_year(existing)
        return existing

    if active_year.start_date:
        try:
            start_date = active_year.start_date.replace(year=active_year.start_date.year + 1)
        except ValueError:
            start_date = active_year.start_date + timedelta(days=365)
    else:
        start_date = datetime.now(timezone.utc).date()

    end_date = None
    if active_year.end_date:
        try:
            end_date = active_year.end_date.replace(year=active_year.end_date.year + 1)
        except ValueError:
            end_date = active_year.end_date + timedelta(days=365)

    target_year = AcademicYear(
        name=next_name,
        start_date=start_date,
        end_date=end_date,
        is_active=True,
        created_by=current_user.id,
    )
    db.session.add(target_year)
    db.session.flush()
    _set_active_academic_year(target_year)
    return target_year


def _rollover_already_run_today(from_year_id):
    """Soft guard: block duplicate rollover for the same source year on the same UTC day."""
    if not from_year_id:
        return False
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return RolloverLog.query.filter(
        RolloverLog.from_year_id == from_year_id,
        RolloverLog.created_at >= today_start,
    ).first() is not None


def record_rollover_audit(
    *,
    mode,
    from_year,
    to_year,
    promoted,
    retained,
    graduated,
    re_registration=0,
    summer_school=0,
):
    """Persist rollover counts and a general activity audit entry."""
    log = RolloverLog(
        user_id=current_user.id,
        from_year_id=from_year.id if from_year else None,
        from_year_name=from_year.name if from_year else None,
        to_year_id=to_year.id if to_year else None,
        to_year_name=to_year.name if to_year else None,
        promoted=promoted,
        retained=retained + summer_school,
        graduated=graduated,
        re_registration=re_registration,
        rollover_mode=mode,
    )
    db.session.add(log)

    from_label = from_year.name if from_year else '—'
    to_label = to_year.name if to_year else '—'
    activity = Activity(
        user_id=current_user.id,
        action=(
            f"Academic rollover ({mode}): {from_label} → {to_label} — "
            f"{promoted} promoted, {summer_school} summer school, "
            f"{retained} repeat class, {graduated} graduated"
        ),
        module='Academic',
        ip_address=request.remote_addr,
    )
    db.session.add(activity)
    return log


def _compute_next_year_label(active_year):
    """Return the label the quick rollover would use for the next academic year."""
    if not active_year:
        return None
    next_name = _next_academic_year_name(active_year.name)
    if next_name:
        return next_name
    if active_year.start_date:
        y = active_year.start_date.year
        return f"{y + 1}-{y + 2}"
    return f"{active_year.name} (Next)"


def preview_moe_academic_rollover(active_year=None):
    """Dry-run summary for the one-click MoE promotion rollover."""
    if active_year is None:
        active_year = get_active_academic_year()

    preview = {
        'active_year': active_year,
        'next_year_name': _compute_next_year_label(active_year),
        'promoted': 0,
        'retained': 0,
        'failed': 0,
        'summer_school': 0,
        'graduated': 0,
        're_registration': 0,
        'student_total': 0,
        'no_active_year': active_year is None,
        'no_students': True,
        'already_rolled_today': False,
        'pass_score': promotion_pass_score(),
        'max_failing': max_failing_subjects_for_promotion(),
        'repeat_failing': repeat_class_failing_subject_threshold(),
        'warnings': [],
        'can_execute': False,
    }

    if not active_year:
        preview['warnings'].append(
            'No active academic year found. Create and activate a year first.'
        )
        return preview

    preview['already_rolled_today'] = _rollover_already_run_today(active_year.id)
    if preview['already_rolled_today']:
        preview['warnings'].append(
            'A rollover for this academic year was already recorded today. '
            'Proceed only if you intend to run it again.'
        )

    students = _students_eligible_for_rollover(active_year)
    preview['student_total'] = len(students)
    preview['no_students'] = len(students) == 0
    if preview['no_students']:
        preview['warnings'].append(
            'No enrolled students (active, repeating, or suspended) are tagged to the current academic year.'
        )

    classes = Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all()
    promotion_map = build_default_promotion_map(classes)

    for student in students:
        decision = evaluate_year_promotion_decision(student, active_year)
        code = decision.get('code')
        grade_level_numeric = _parse_grade_level(_student_grade_level(student))

        if code == 'GRADUATED':
            preview['graduated'] += 1
        elif code == 'SUMMER_SCHOOL':
            preview['summer_school'] += 1
        elif decision.get('passed'):
            target_class = promotion_map.get(student.klass_id) if student.klass_id else None
            if target_class == 'graduate' or grade_level_numeric == 12:
                preview['graduated'] += 1
            else:
                preview['promoted'] += 1
        else:
            preview['retained'] += 1

        preview['re_registration'] += 1

    preview['failed'] = preview['retained']

    preview['can_execute'] = (
        not preview['no_active_year']
        and not preview['no_students']
    )
    return preview


def _retain_student_in_current_class(student, target_year, status='REPEAT'):
    """Keep the student in the same class for the next year (repeat or summer school)."""
    student.status = status
    student.registration_type = 'Returning'
    student.tuition_cleared = False
    if target_year is not None:
        student.academic_year_id = target_year.id
    if student.klass_id and target_year is not None:
        record_student_class_enrollment(
            student, student.klass_id, academic_year_id=target_year.id,
        )
    sync_student_class_assignment(student)


def execute_moe_academic_rollover(active_year=None, *, allow_repeat_today=False):
    """
    One-click academic year rollover with MoE-based student promotion.
    Returns result dict; raises ValueError on guard failures.
    """
    if active_year is None:
        active_year = get_active_academic_year()
    if not active_year:
        raise ValueError('No active academic year found. Create and activate a year first.')

    if _rollover_already_run_today(active_year.id) and not allow_repeat_today:
        raise ValueError(
            'A rollover for this academic year was already run today. '
            'Check the audit log or confirm to run again.'
        )

    students = _students_eligible_for_rollover(active_year)
    if not students:
        raise ValueError(
            'No enrolled students (active, repeating, or suspended) are tagged to the current academic year.'
        )

    target_year = _resolve_or_create_next_academic_year(active_year)
    classes = Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all()
    promotion_map = build_default_promotion_map(classes)
    class_cache = {c.id: c for c in classes}

    promoted = retained = graduated = re_registration = summer_school = 0

    for student in students:
        decision = evaluate_year_promotion_decision(student, active_year)
        code = decision.get('code')
        passed = bool(decision.get('passed'))
        grade_level = _student_grade_level(student)
        grade_level_numeric = _parse_grade_level(grade_level)

        if grade_level_numeric == 12:
            if code == 'GRADUATED' or passed:
                mark_student_alumni(student, active_year.id)
                graduated += 1
            elif code == 'SUMMER_SCHOOL':
                _retain_student_in_current_class(student, target_year, 'SUMMER_SCHOOL')
                summer_school += 1
                re_registration += 1
            else:
                _retain_student_in_current_class(student, target_year, 'REPEAT')
                retained += 1
                re_registration += 1
            continue

        student.registration_type = 'Returning'
        student.tuition_cleared = False
        student.academic_year_id = target_year.id
        re_registration += 1
        if passed:
            mark_student_promoted_pending_fee(student)

        if passed:
            old_klass_id = student.klass_id
            old_stream = None
            if old_klass_id:
                old_klass = class_cache.get(old_klass_id)
                old_stream = old_klass.stream if old_klass else None
            target_class = promotion_map.get(student.klass_id) if student.klass_id else None
            if isinstance(target_class, int):
                student.klass_id = target_class
                promoted_class = class_cache.get(target_class)
                if promoted_class:
                    student.grade_level = promoted_class.grade_level
                record_student_class_enrollment(
                    student, target_class, academic_year_id=target_year.id,
                )
            elif grade_level_numeric and grade_level_numeric < 12:
                new_grade = grade_level_numeric + 1
                student.grade_level = new_grade
                new_klass = find_class_for_student_grade(
                    new_grade,
                    stream=old_stream,
                    old_class_id=old_klass_id,
                )
                if new_klass:
                    student.klass_id = new_klass.id
                    student.grade_level = new_klass.grade_level
                    record_student_class_enrollment(
                        student, new_klass.id, academic_year_id=target_year.id,
                    )
                else:
                    student.klass_id = None
            else:
                nxt = next_canonical_grade(grade_level)
                if nxt and nxt != 'Graduation':
                    student.grade_level = nxt
                    new_klass = find_class_for_student_grade(
                        nxt,
                        stream=old_stream,
                        old_class_id=old_klass_id,
                    )
                    if new_klass:
                        student.klass_id = new_klass.id
                        student.grade_level = new_klass.grade_level
                        record_student_class_enrollment(
                            student, new_klass.id, academic_year_id=target_year.id,
                        )
                    else:
                        student.klass_id = None
            student.status = 'ACTIVE'
            sync_student_class_assignment(student)
            promoted += 1
        elif code == 'SUMMER_SCHOOL':
            student.status = 'SUMMER_SCHOOL'
            if student.klass_id:
                record_student_class_enrollment(
                    student, student.klass_id, academic_year_id=target_year.id,
                )
            sync_student_class_assignment(student)
            summer_school += 1
        else:
            student.status = 'REPEAT'
            if student.klass_id:
                record_student_class_enrollment(
                    student, student.klass_id, academic_year_id=target_year.id,
                )
            sync_student_class_assignment(student)
            retained += 1

    repair_stale_student_class_assignments(commit=False)
    record_rollover_audit(
        mode='quick',
        from_year=active_year,
        to_year=target_year,
        promoted=promoted,
        retained=retained,
        graduated=graduated,
        re_registration=re_registration,
        summer_school=summer_school,
    )
    reset_dashboard_year_sessions(target_year)
    db.session.commit()

    return {
        'target_year_name': target_year.name,
        'promoted': promoted,
        'retained': retained,
        'summer_school': summer_school,
        'graduated': graduated,
        're_registration': re_registration,
    }


def format_rollover_flash_summary(results):
    """Build a detailed post-rollover flash message."""
    retained = results.get('retained', results.get('repeat', 0))
    summer_school = results.get('summer_school', 0)
    parts = [
        (
            f"Rollover complete: {results.get('promoted', 0)} promoted, "
            f"{summer_school} summer school, {retained} repeat class, "
            f"{results.get('graduated', 0)} graduated."
        ),
        f"New year: {results.get('target_year_name', '—')}",
    ]
    if results.get('re_registration'):
        parts.append(f"{results['re_registration']} students marked for re-registration")
    if results.get('re_enrolled'):
        parts.append(f"{results['re_enrolled']} students re-enrolled")
    if results.get('fees_configured'):
        parts.append(f"{results['fees_configured']} class registration fees saved")
    if results.get('fees_recorded'):
        parts.append(f"{results['fees_recorded']} registration payments posted to business income")
    if results.get('ended_year_name'):
        parts.insert(0, f"Ended {results['ended_year_name']}.")
    return ' '.join(parts)


def _rollover_role_guard():
    if current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))
    return None


def _pick_promotion_target(candidates, stream=None):
    if not candidates:
        return 'repeat'
    if stream:
        stream_matches = [klass for klass in candidates if klass.stream == stream]
        if stream_matches:
            return stream_matches[0].id
    return candidates[0].id


def build_default_promotion_map(classes):
    """Suggest next-class targets from grade level (+1), KG sequence, and stream."""
    classes = list(classes or [])
    by_grade = {}
    by_canonical = {}
    numeric_classes = []
    for klass in classes:
        canon = canonical_grade_value(klass.grade_level, klass.name)
        if canon:
            by_canonical.setdefault(canon, []).append(klass)
        grade_numeric = _parse_grade_level(klass.grade_level)
        if grade_numeric is None:
            continue
        by_grade.setdefault(grade_numeric, []).append(klass)
        numeric_classes.append((klass, grade_numeric))

    promotion_map = {}
    for klass, grade_numeric in numeric_classes:
        next_grade = grade_numeric + 1
        if next_grade > 12:
            promotion_map[klass.id] = 'graduate'
            continue
        promotion_map[klass.id] = _pick_promotion_target(
            by_grade.get(next_grade, []),
            klass.stream,
        )

    for klass in classes:
        if klass.id in promotion_map:
            continue
        nxt = next_canonical_grade(klass.grade_level, klass.name)
        if nxt == 'Graduation':
            promotion_map[klass.id] = 'graduate'
            continue
        if not nxt:
            continue
        promotion_map[klass.id] = _pick_promotion_target(
            by_canonical.get(nxt, []),
            klass.stream,
        )
    return promotion_map


def build_rollover_preview(active_year, classes, students):
    """Summarize rollover impact: MoE pass standard first, then class map."""
    promotion_map = build_default_promotion_map(classes)
    counts = {
        'promote': 0,
        'graduate': 0,
        'repeat': 0,
        'summer_school': 0,
        'unassigned': 0,
        'incomplete': 0,
    }
    for student in students:
        status = (student.status or 'ACTIVE').upper()
        if status in ALUMNI_STATUSES:
            continue
        decision = evaluate_year_promotion_decision(student, active_year)
        code = decision.get('code')
        if code == 'INCOMPLETE':
            counts['repeat'] += 1
            counts['incomplete'] += 1
            continue
        if code == 'SUMMER_SCHOOL':
            counts['summer_school'] += 1
            continue
        if not decision.get('passed'):
            counts['repeat'] += 1
            continue
        if code == 'GRADUATED':
            counts['graduate'] += 1
            continue
        if not student.klass_id:
            counts['unassigned'] += 1
            continue
        target = promotion_map.get(student.klass_id, 'repeat')
        if target == 'graduate':
            counts['graduate'] += 1
        elif target == 'repeat':
            counts['repeat'] += 1
        else:
            counts['promote'] += 1
    return {
        'promotion_map': promotion_map,
        'counts': counts,
        'student_total': len(students),
        'pass_score': promotion_pass_score(),
        'max_failing': max_failing_subjects_for_promotion(),
        'repeat_failing': repeat_class_failing_subject_threshold(),
    }


def parse_rollover_promotion_map(classes):
    """Read per-class promotion targets submitted from the wizard form."""
    promotion_map = {}
    valid_class_ids = {str(c.id) for c in classes}
    for klass in classes:
        field_name = f'promotion_{klass.id}'
        raw_value = (request.form.get(field_name) or '').strip()
        if raw_value == 'graduate':
            promotion_map[klass.id] = 'graduate'
        elif raw_value == 'repeat':
            promotion_map[klass.id] = 'repeat'
        elif raw_value in valid_class_ids:
            promotion_map[klass.id] = int(raw_value)
        else:
            promotion_map[klass.id] = build_default_promotion_map(classes).get(klass.id, 'repeat')
    return promotion_map


def parse_rollover_class_fees(classes):
    """
    Read per-class inclusion and registration fee amounts from the wizard form.
    Returns (included_class_ids, class_registration_fees).
    """
    included_class_ids = set()
    class_registration_fees = {}
    for klass in classes:
        if request.form.get(f'include_class_{klass.id}') == '1':
            included_class_ids.add(klass.id)
            raw_fee = (request.form.get(f'reg_fee_{klass.id}') or '').strip()
            class_registration_fees[klass.id] = money(raw_fee) if raw_fee else 0.0
    return included_class_ids, class_registration_fees


def get_class_registration_fee(class_id, academic_year_id):
    """Return the configured registration fee for a class in an academic year."""
    if not class_id or not academic_year_id:
        return 0.0
    fee = SchoolFee.query.filter_by(
        academic_year_id=academic_year_id,
        class_id=class_id,
        fee_type='registration',
    ).first()
    return money(fee.amount) if fee and fee.amount else 0.0


def get_registration_fee_for_student(student, academic_year_id):
    """Resolve registration fee from year/class schedule, then student metadata."""
    if not student or not academic_year_id:
        return 0.0
    if student.klass_id:
        scheduled = get_class_registration_fee(student.klass_id, academic_year_id)
        if scheduled > 0:
            return scheduled
    return parse_currency_amount_optional(getattr(student, 'registration_fees', 0))


def save_class_registration_fees(academic_year_id, class_registration_fees, included_class_ids=None):
    """
    Upsert per-class registration fee rows for an academic year.
    Removes stale registration fee rows for classes no longer included.
    """
    if not academic_year_id:
        return 0

    included = included_class_ids if included_class_ids is not None else set(class_registration_fees.keys())
    saved = 0

    for class_id in included:
        amount = money(class_registration_fees.get(class_id, 0))
        existing = SchoolFee.query.filter_by(
            academic_year_id=academic_year_id,
            class_id=class_id,
            fee_type='registration',
        ).first()
        if amount <= 0:
            if existing:
                db.session.delete(existing)
            continue
        if existing:
            existing.amount = amount
        else:
            db.session.add(SchoolFee(
                academic_year_id=academic_year_id,
                class_id=class_id,
                fee_type='registration',
                amount=amount,
            ))
        saved += 1

    stale = SchoolFee.query.filter_by(
        academic_year_id=academic_year_id,
        fee_type='registration',
    ).all()
    for row in stale:
        if row.class_id and row.class_id not in included:
            db.session.delete(row)

    return saved


def execute_academic_rollover(
    *,
    end_current_year,
    target_mode,
    target_year_id,
    new_year_name,
    new_year_start,
    new_year_end,
    apply_promotions,
    promotion_map,
    reset_tuition_cleared,
    charge_registration_fee,
    class_registration_fees,
    included_class_ids,
    exclude_statuses,
):
    """Run the full academic year rollover cycle in one database transaction."""
    results = {
        'ended_year_name': None,
        'target_year_name': None,
        'promoted': 0,
        'graduated': 0,
        'repeat': 0,
        'summer_school': 0,
        're_enrolled': 0,
        'fees_recorded': 0,
        'fees_configured': 0,
        'tuition_reset': 0,
        'skipped': 0,
    }

    active_year = get_active_academic_year()
    source_year_id = active_year.id if active_year else None

    if end_current_year and active_year:
        active_year.is_active = False
        if not active_year.end_date:
            active_year.end_date = datetime.now(timezone.utc).date()
        results['ended_year_name'] = active_year.name

    if target_mode == 'new':
        if not new_year_name or not new_year_start:
            raise ValueError("New academic year requires a name and start date.")
        new_year_name = normalize_academic_year_name(new_year_name)
        if find_academic_year_by_name(new_year_name):
            raise ValueError(f"Academic year '{new_year_name}' already exists.")
        target_year = AcademicYear(
            name=new_year_name,
            start_date=new_year_start,
            end_date=new_year_end,
            is_active=True,
            created_by=current_user.id,
        )
        db.session.add(target_year)
        db.session.flush()
    else:
        if not target_year_id:
            raise ValueError("Select an existing academic year to activate.")
        target_year = db.session.get(AcademicYear, target_year_id)
        if not target_year:
            raise ValueError("Selected target academic year was not found.")

    _set_active_academic_year(target_year)
    results['target_year_name'] = target_year.name

    if included_class_ids or class_registration_fees:
        results['fees_configured'] = save_class_registration_fees(
            target_year.id,
            class_registration_fees,
            included_class_ids=included_class_ids,
        )

    if source_year_id:
        students_query = Student.query.filter_by(academic_year_id=source_year_id)
    else:
        students_query = Student.query.filter(
            or_(Student.academic_year_id.is_(None), Student.academic_year_id != target_year.id)
        )
    if exclude_statuses:
        students_query = students_query.filter(~Student.status.in_(list(exclude_statuses)))
    students = students_query.all()

    class_cache = {c.id: c for c in Class.query.all()}
    source_year = db.session.get(AcademicYear, source_year_id) if source_year_id else None

    for student in students:
        if exclude_statuses and student.status in exclude_statuses:
            results['skipped'] += 1
            continue

        # Preserve the student's current class enrollment in the source year before moving
        # the live Student record forward. This guarantees archived year views can still
        # resolve the student's class history after rollover.
        if source_year_id and student.klass_id:
            record_student_class_enrollment(
                student,
                student.klass_id,
                academic_year_id=source_year_id,
            )

        meets_standard = True
        if apply_promotions and source_year:
            decision = evaluate_year_promotion_decision(student, source_year)
            if not decision.get('passed'):
                if decision.get('code') == 'SUMMER_SCHOOL':
                    student.status = 'SUMMER_SCHOOL'
                    results['summer_school'] += 1
                else:
                    student.status = 'REPEAT'
                    results['repeat'] += 1
                if student.klass_id:
                    record_student_class_enrollment(
                        student, student.klass_id, academic_year_id=target_year.id,
                    )
                meets_standard = False

        if apply_promotions and meets_standard and student.klass_id:
            target_class = promotion_map.get(student.klass_id, 'repeat')
            if target_class == 'graduate':
                mark_student_alumni(student, source_year_id)
                results['graduated'] += 1
                continue
            if target_class == 'repeat':
                student.status = 'REPEAT'
                results['repeat'] += 1
                if student.klass_id:
                    record_student_class_enrollment(
                        student, student.klass_id, academic_year_id=target_year.id,
                    )
            elif target_class:
                student.status = 'ACTIVE'
                student.klass_id = int(target_class)
                promoted_class = class_cache.get(int(target_class))
                if promoted_class:
                    student.grade_level = promoted_class.grade_level
                record_student_class_enrollment(
                    student, student.klass_id, academic_year_id=target_year.id,
                )
                results['promoted'] += 1
        elif apply_promotions and meets_standard and not student.klass_id:
            grade_level = _student_grade_level(student)
            if grade_level:
                new_klass = find_class_for_student_grade(grade_level)
                if new_klass:
                    student.status = 'ACTIVE'
                    student.klass_id = new_klass.id
                    student.grade_level = new_klass.grade_level
                    record_student_class_enrollment(
                        student, new_klass.id, academic_year_id=target_year.id,
                    )
                    results['promoted'] += 1

        if apply_promotions and (student.status or '').upper() in ACTIVE_ENROLLMENT_STATUSES:
            sync_student_class_assignment(student)

        if student_is_alumni(student):
            results['skipped'] += 1
            continue

        student.academic_year_id = target_year.id
        student.registration_type = 'Returning'

        if reset_tuition_cleared:
            if student.tuition_cleared:
                results['tuition_reset'] += 1
            student.tuition_cleared = False

        if (student.status or '').upper() not in ('REPEAT', 'SUMMER_SCHOOL'):
            mark_student_promoted_pending_fee(student)

        if charge_registration_fee and student.klass_id and student.klass_id in included_class_ids:
            fee_amount = money(class_registration_fees.get(student.klass_id, 0))
            if fee_amount <= 0:
                fee_amount = get_class_registration_fee(student.klass_id, target_year.id)
            if fee_amount > 0:
                klass_name = class_cache.get(student.klass_id)
                class_label = klass_name.name if klass_name else f"Class {student.klass_id}"
                record_student_payment_with_income(
                    student,
                    target_year.id,
                    term=1,
                    amount_paid=fee_amount,
                    description=f"Registration fee — {class_label} — {target_year.name} rollover",
                )
                student.registration_fees = fee_amount
                results['fees_recorded'] += 1

        results['re_enrolled'] += 1

    repair_stale_student_class_assignments(commit=False)
    retained_count = results.get('repeat', 0)
    record_rollover_audit(
        mode='wizard',
        from_year=db.session.get(AcademicYear, source_year_id) if source_year_id else None,
        to_year=target_year,
        promoted=results['promoted'],
        retained=retained_count,
        graduated=results['graduated'],
        re_registration=results['re_enrolled'],
        summer_school=results.get('summer_school', 0),
    )
    reset_dashboard_year_sessions(target_year)
    db.session.commit()
    return results


@app.route('/admin/academic-rollover', methods=['GET', 'POST'])
@login_required
@role_required(ROLE_ADMIN)
def academic_rollover():
    """Preview and execute one-click academic year rollover with MoE-based promotion."""
    preview = preview_moe_academic_rollover()

    if request.method == 'GET':
        return render_template(
            'academic_rollover_preview.html',
            preview=preview,
            wizard_url=url_for('academic_year_rollover'),
        )

    if request.form.get('preview'):
        preview = preview_moe_academic_rollover()
        if request.form.get('format') == 'json' or request.accept_mimetypes.best == 'application/json':
            return jsonify({
                'promoted': preview['promoted'],
                'retained': preview['retained'],
                'summer_school': preview['summer_school'],
                'graduated': preview['graduated'],
                're_registration': preview['re_registration'],
                'student_total': preview['student_total'],
                'next_year_name': preview['next_year_name'],
                'pass_score': preview['pass_score'],
                'max_failing': preview['max_failing'],
                'repeat_failing': preview.get('repeat_failing'),
                'warnings': preview['warnings'],
                'can_execute': preview['can_execute'],
            })
        return render_template(
            'academic_rollover_preview.html',
            preview=preview,
            wizard_url=url_for('academic_year_rollover'),
            show_preview=True,
        )

    if not preview['can_execute']:
        flash(preview['warnings'][0] if preview['warnings'] else 'Rollover cannot be executed.', 'warning')
        return redirect(url_for('academic_rollover'))

    allow_repeat = request.form.get('allow_repeat_today') == '1'
    if preview['already_rolled_today'] and not allow_repeat:
        flash(
            'A rollover for this academic year was already run today. '
            'Acknowledge the warning on the preview page to proceed.',
            'warning',
        )
        return redirect(url_for('academic_rollover'))

    try:
        results = execute_moe_academic_rollover(allow_repeat_today=allow_repeat)
        flash(format_rollover_flash_summary(results), 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f"Rollover failed: {exc}", "danger")

    return redirect(url_for('login'))


@app.route('/academic-years/rollover', methods=['GET', 'POST'])
@login_required
def academic_year_rollover():
    denied = _rollover_role_guard()
    if denied:
        return denied

    form = RolloverWizardForm()
    classes = Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all()
    inactive_years = AcademicYear.query.filter_by(is_active=False).order_by(
        AcademicYear.start_date.desc()
    ).all()
    active_year = get_active_academic_year()
    all_years = all_academic_years()

    form.target_year_id.choices = [(0, '-- Select Year --')] + [
        (y.id, y.name) for y in inactive_years
    ]

    if active_year:
        source_students = Student.query.filter_by(academic_year_id=active_year.id).all()
    else:
        source_students = Student.query.filter(
            or_(Student.academic_year_id.is_(None), Student.status == 'ACTIVE')
        ).all()

    promotion_defaults = build_default_promotion_map(classes)
    preview = build_rollover_preview(active_year, classes, source_students)

    class_choices = [(c.id, c.name) for c in classes]

    if request.method == 'POST':
        if not form.validate_on_submit():
            flash("Please complete all required fields and confirm the rollover.", "warning")
        else:
            exclude_statuses = set()
            if form.exclude_graduated.data:
                exclude_statuses.add('GRADUATED')
            if form.exclude_withdrawn.data:
                exclude_statuses.add('WITHDRAWN')
            if form.exclude_suspended.data:
                exclude_statuses.add('SUSPENDED')

            if form.target_mode.data == 'existing' and not form.target_year_id.data:
                flash("Select an existing academic year to activate.", "warning")
            elif form.target_mode.data == 'new' and (
                not (form.new_year_name.data or '').strip() or not form.new_year_start.data
            ):
                flash("Provide a name and start date for the new academic year.", "warning")
            else:
                included_class_ids, class_registration_fees = parse_rollover_class_fees(classes)
                fee_validation_failed = False
                if form.charge_registration_fee.data:
                    if not included_class_ids:
                        flash(
                            "Select at least one class when posting registration fees to business income.",
                            "warning",
                        )
                        fee_validation_failed = True
                    elif not any(money(amt) > 0 for cid, amt in class_registration_fees.items() if cid in included_class_ids):
                        flash(
                            "Enter a registration fee greater than zero for at least one selected class.",
                            "warning",
                        )
                        fee_validation_failed = True

                if not fee_validation_failed:
                    promotion_map = parse_rollover_promotion_map(classes)
                    try:
                        results = execute_academic_rollover(
                            end_current_year=form.end_current_year.data,
                            target_mode=form.target_mode.data,
                            target_year_id=form.target_year_id.data,
                            new_year_name=form.new_year_name.data,
                            new_year_start=form.new_year_start.data,
                            new_year_end=form.new_year_end.data,
                            apply_promotions=form.apply_promotions.data,
                            promotion_map=promotion_map,
                            reset_tuition_cleared=form.reset_tuition_cleared.data,
                            charge_registration_fee=form.charge_registration_fee.data,
                            class_registration_fees=class_registration_fees,
                            included_class_ids=included_class_ids,
                            exclude_statuses=exclude_statuses,
                        )
                        flash(format_rollover_flash_summary(results), 'success')
                        return redirect(url_for('academic_years'))
                    except Exception as exc:
                        db.session.rollback()
                        flash(f"Rollover failed: {exc}", "danger")

    # Default registration fee hints per class (from active year schedule or class metadata)
    default_registration_fees = {}
    if active_year:
        reg_rows = SchoolFee.query.filter_by(
            academic_year_id=active_year.id,
            fee_type='registration',
        ).all()
        for row in reg_rows:
            if row.class_id:
                default_registration_fees[row.class_id] = money(row.amount)
    for klass in classes:
        if klass.id not in default_registration_fees:
            default_registration_fees[klass.id] = 0.0

    stats = {
        'active_students': len(source_students),
        'active_classes': len(classes),
        'inactive_years': len(inactive_years),
        'total_years': len(all_years),
    }

    return render_template(
        'academic_rollover_wizard.html',
        form=form,
        active_year=active_year,
        classes=classes,
        class_choices=class_choices,
        promotion_defaults=promotion_defaults,
        preview=preview,
        stats=stats,
        all_years=all_years,
        default_registration_fees=default_registration_fees,
    )


# ------------------------ ACADEMIC YEARS ---------------------------
def _count_records_by_academic_year(model, fk_column, year_ids):
    """Return {year_id: count} for one linked model."""
    if not year_ids:
        return {}
    rows = (
        db.session.query(fk_column, func.count())
        .filter(fk_column.in_(year_ids))
        .group_by(fk_column)
        .all()
    )
    return {year_id: count for year_id, count in rows if year_id is not None}


def _build_academic_year_links(years):
    """Per-year linked record counts for academic_years.html purge UI."""
    year_ids = [year.id for year in years]
    if not year_ids:
        return {}

    link_keys = ('grades', 'students', 'payments', 'fees', 'assessments', 'media')
    buckets = {
        'grades': _count_records_by_academic_year(Grade, Grade.academic_year_id, year_ids),
        'students': _count_records_by_academic_year(Student, Student.academic_year_id, year_ids),
        'payments': _count_records_by_academic_year(
            StudentPayment, StudentPayment.academic_year_id, year_ids
        ),
        'fees': _count_records_by_academic_year(SchoolFee, SchoolFee.academic_year_id, year_ids),
        'assessments': _count_records_by_academic_year(
            Assessment, Assessment.academic_year_id, year_ids
        ),
        'media': _count_records_by_academic_year(
            SchoolMedia, SchoolMedia.academic_year_id, year_ids
        ),
    }

    year_links = {}
    for year_id in year_ids:
        links = {key: buckets[key].get(year_id, 0) for key in link_keys}
        links['total'] = sum(links[key] for key in link_keys)
        year_links[year_id] = links
    return year_links


def _purge_academic_year_linked_records(year_id):
    """Remove records tied to an ended year; students are kept with year tag cleared."""
    Grade.query.filter_by(academic_year_id=year_id).delete(synchronize_session=False)
    StudentPayment.query.filter_by(academic_year_id=year_id).delete(synchronize_session=False)
    SchoolFee.query.filter_by(academic_year_id=year_id).delete(synchronize_session=False)
    Assessment.query.filter_by(academic_year_id=year_id).delete(synchronize_session=False)
    SchoolMedia.query.filter_by(academic_year_id=year_id).delete(synchronize_session=False)
    Student.query.filter_by(academic_year_id=year_id).update(
        {'academic_year_id': None},
        synchronize_session=False,
    )


@app.route('/academic-years', methods=['GET', 'POST'])
@login_required
def academic_years():
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked

    form = AcademicYearForm()

    if form.validate_on_submit():
        year_name = normalize_academic_year_name(form.name.data)
        if find_academic_year_by_name(year_name):
            flash(f"Academic year '{year_name}' already exists.", "warning")
            years = all_academic_years()
            year_links = _build_academic_year_links(years)
            return render_template(
                'academic_years.html',
                form=form,
                years=years,
                year_links=year_links,
            )
        year = AcademicYear(
            name=year_name,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            is_active=False,
            created_by=current_user.id
        )
        db.session.add(year)
        db.session.flush()
        other_active = AcademicYear.query.filter(
            AcademicYear.id != year.id,
            AcademicYear.is_active.is_(True),
        ).count()
        if form.is_active.data or other_active == 0:
            _set_active_academic_year(year)
        db.session.commit()
        if has_app_context() and hasattr(g, '_flpa_active_year'):
            delattr(g, '_flpa_active_year')
        if has_request_context() and hasattr(g, '_flpa_all_years'):
            delattr(g, '_flpa_all_years')
        flash(
            f"Academic year {year.name} is ready as its own folder. "
            "Grades, attendance, and fees for other years stay in those years.",
            "success",
        )
        return redirect(url_for('academic_years'))

    years = all_academic_years()
    year_links = _build_academic_year_links(years)

    return render_template(
        'academic_years.html',
        form=form,
        years=years,
        year_links=year_links,
    )

@app.route('/academic-years/<int:year_id>/end', methods=['POST'])
@login_required
def end_academic_year(year_id):
    # ✨ Secured role authentication matrix
    if current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    # ✨ Modern, crash-proof database query fetch
    year = db.first_or_404(db.select(AcademicYear).filter_by(id=year_id))
    
    if not year.is_active:
        flash("Academic year is already inactive.", "info")
        return redirect(url_for('academic_years'))

    # Change operational state variables
    year.is_active = False
    
    # Safely extract the date object from your tracking timestamp framework
    if not year.end_date:
        year.end_date = datetime.now(timezone.utc).date()
        
    try:
        db.session.commit()
        flash(f"Academic year {year.name} has been marked as ended successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Database sync fault: {str(e)}", "danger")
        
    return redirect(url_for('academic_years'))


@app.route('/academic-years/<int:year_id>/activate', methods=['POST'])
@login_required
def activate_academic_year(year_id):
    if current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    year = db.first_or_404(db.select(AcademicYear).filter_by(id=year_id))
    try:
        _set_active_academic_year(year)
        db.session.commit()
        flash(f"Academic year {year.name} is now active.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Could not activate academic year: {e}", "danger")

    return redirect(url_for('academic_years'))


@app.route('/academic-years/edit/<int:year_id>', methods=['GET', 'POST'])
@login_required
def edit_academic_year(year_id):
    # ✨ Fixed: Clean multi-role checking with lowercase protection
    if current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    # ✨ Fixed: Modern Flask-SQLAlchemy lookup to avoid deprecation warnings
    year = db.first_or_404(db.select(AcademicYear).filter_by(id=year_id))
    
    # Initialize the form with data from the existing database object
    form = AcademicYearForm(obj=year)

    if form.validate_on_submit():
        try:
            # If this year is being switched from Inactive to Active
            year_name = normalize_academic_year_name(form.name.data)
            existing = find_academic_year_by_name(year_name)
            if existing and existing.id != year.id:
                flash(f"Academic year '{year_name}' already exists.", "warning")
                return render_template('academy_year_edit.html', form=form, year=year)
            year.name = year_name
            year.start_date = form.start_date.data
            year.end_date = form.end_date.data
            if form.is_active.data:
                _set_active_academic_year(year)
            else:
                year.is_active = False
            
            # Commit transactional changes safely to the ledger
            db.session.commit()
            flash(f"Academic year '{year.name}' updated successfully.", "success")
            return redirect(url_for('academic_years'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"System sync fault during save operations: {str(e)}", "danger")

    return render_template('academy_year_edit.html', form=form, year=year)
@app.route('/academic-years/reregister-students', methods=['POST'])
@login_required
def reregister_students():
    if current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    active_year = get_active_academic_year()
    if not active_year:
        flash("No active academic year found to re-register students to.", "warning")
        return redirect(url_for('academic_years'))

    # Update all students who are not in the current active year
    students = Student.query.filter(Student.academic_year_id != active_year.id).all()
    count = 0
    for student in students:
        student.academic_year_id = active_year.id
        student.registration_type = 'Returning'
        count += 1

    repair_stale_student_class_assignments(commit=False)
    db.session.commit()
    flash(f"Successfully re-registered {count} students to {active_year.name}.", "success")
    return redirect(url_for('academic_years'))

@app.route('/academic-years/delete/<int:year_id>', methods=['POST'])
@login_required
def delete_academic_year(year_id):
    if current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    year = AcademicYear.query.get_or_404(year_id)

    if year.is_active:
        flash("Cannot delete an active academic year. End it first.", "warning")
        return redirect(url_for('academic_years'))

    links = _build_academic_year_links([year]).get(year.id, {})
    confirm_cascade = request.form.get('confirm_cascade') == '1'
    link_total = links.get('total', 0)

    if link_total > 0 and not confirm_cascade:
        flash(
            f"Cannot delete '{year.name}' — linked records exist. "
            "Use the purge flow on this page to permanently remove them.",
            "warning",
        )
        return redirect(url_for('academic_years'))

    try:
        if link_total > 0:
            _purge_academic_year_linked_records(year.id)
        db.session.delete(year)
        db.session.commit()
        flash(f"Academic year '{year.name}' deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to delete academic year: {str(e)}", "danger")

    return redirect(url_for('academic_years'))

# ------------------------ STUDENT REGISTER -------------------------
def build_student_financials_business_summary(student, academic_year):
    """
    Aggregates all ledger payments for a student. Combines registration fees
    and tuition fees so they accurately show on the business management layout.
    """
    if not student or not academic_year:
        return {
            "tuition_paid": Decimal('0.00'),
            "registration_paid": Decimal('0.00'),
            "total_collected": Decimal('0.00'),
            "yearly_fee": Decimal('0.00'),
        }

    # Fetch the benchmark class fee safely
    yearly_fee = Decimal(str(get_yearly_fee_for_student(student, academic_year)))

    # Query all ledger payment documents associated with this student's ledger file
    payments = StudentPayment.query.filter_by(
        student_id=student.id,
        academic_year_id=academic_year.id
    ).all()

    # Distinguish transaction types via their ledger audit descriptions
    registration_paid = sum(
        Decimal(str(p.amount_paid)) for p in payments 
        if "registration" in (p.description or "").lower()
    )
    
    tuition_paid = sum(
        Decimal(str(p.amount_paid)) for p in payments 
        if "tuition" in (p.description or "").lower()
    )

    total_collected = sum(Decimal(str(p.amount_paid)) for p in payments)

    return {
        "tuition_paid": tuition_paid,
        "registration_paid": registration_paid,
        "total_collected": total_collected,
        "yearly_fee": yearly_fee,
    }


def get_running_business_balance():
    """Return the latest running balance from the business ledger."""
    last_tx = (
        BusinessTransaction.query.filter_by(is_deleted=False)
        .order_by(BusinessTransaction.id.desc())
        .first()
    )
    return money(last_tx.balance_after if last_tx and last_tx.balance_after is not None else 0.0)


def categorize_fee_payment(description):
    """Map a student payment description to a business income category."""
    desc = (description or "").strip().lower()
    if "registration" in desc:
        return "Registration Fees"
    if any(keyword in desc for keyword in ("tuition", "school fee", "yearly", "annual")):
        return "Tuition"
    if "uniform" in desc:
        return "Uniform"
    if "graduation" in desc:
        return "Graduation"
    return "Student Fees"


def find_registration_fee_payment(student, academic_year_id):
    """Latest registration StudentPayment for a student in a given year."""
    if not student or not getattr(student, 'id', None) or not academic_year_id:
        return None
    return (
        StudentPayment.query.filter_by(
            student_id=student.id,
            academic_year_id=academic_year_id,
            term=1,
        )
        .filter(StudentPayment.description.ilike('%registration%'))
        .order_by(StudentPayment.id.desc())
        .first()
    )


def _latest_registration_payments_map(student_ids, academic_year_id=None):
    """Map student_id → latest registration payment (batched for roster folders)."""
    if not student_ids:
        return {}
    query = StudentPayment.query.filter(
        StudentPayment.student_id.in_(list(student_ids)),
        StudentPayment.description.ilike('%registration%'),
    )
    if academic_year_id:
        query = query.filter(StudentPayment.academic_year_id == academic_year_id)
    latest = {}
    for payment in query.order_by(StudentPayment.id.asc()).all():
        latest[payment.student_id] = payment
    return latest


def _registration_fee_payment_description(payment_status=None, receipt_reference=None):
    status = (payment_status or '').strip().lower()
    if status == 'partial':
        base = 'Partial Registration Fee Payment'
    else:
        base = 'Initial Registration Fee Payment (Auto-Generated)'
    ref = (receipt_reference or '').strip()
    if ref:
        return f'{base} (Ref: {ref})'
    return base


def _form_registration_payment_status(form):
    field = getattr(form, 'registration_payment_status', None)
    return ((field.data if field is not None else '') or '').strip().lower()


def _form_receipt_reference(form):
    field = getattr(form, 'receipt_reference', None)
    return ((field.data if field is not None else '') or '').strip()


def _registration_receipt_meta(payment, student):
    """Display fields for the official registration receipt."""
    fee_amount = money(getattr(student, 'registration_fees', 0) if student else 0)
    amount_paid = money(payment.amount_paid if payment else 0)
    remaining = max(0.0, round(fee_amount - amount_paid, 2))
    description = payment.description or '' if payment else ''
    desc_lower = description.lower()
    if 'partial' in desc_lower or remaining > 0.004:
        fee_status = 'Partial'
    else:
        fee_status = 'Paid'
    receipt_reference = None
    marker = '(Ref: '
    start = description.find(marker)
    if start >= 0:
        rest = description[start + len(marker):]
        end = rest.find(')')
        receipt_reference = (rest[:end] if end >= 0 else rest).strip() or None
    return {
        'fee_amount': fee_amount,
        'amount_paid': amount_paid,
        'remaining': remaining,
        'fee_status': fee_status,
        'receipt_reference': receipt_reference,
        'receipt_no': 'SP-{}'.format(payment.id) if payment else '—',
    }


def _is_registration_fee_payment(payment):
    return 'registration' in ((payment.description or '') if payment else '').lower()


def _render_registrar_registration_receipt(payment):
    """Official registration receipt page (shared by registrar and business print routes)."""
    student = db.session.get(Student, payment.student_id) if payment else None
    year = db.session.get(AcademicYear, payment.academic_year_id) if payment else None
    meta = _registration_receipt_meta(payment, student)
    return render_template(
        'registrar_registration_receipt.html',
        payment=payment,
        student=student,
        display_year=year,
        class_label=format_student_class_name(student, payment.academic_year_id) if student else '—',
        collected_by=current_user.full_name or current_user.email,
        registered_by=getattr(student, 'registrar', None),
        remaining=meta['remaining'],
        fee_amount=meta['fee_amount'],
        fee_status=meta['fee_status'],
        receipt_reference=meta['receipt_reference'],
        receipt_no=meta['receipt_no'],
        default_avatar_url=default_static_photo_url(),
    )


def collect_registration_fee_payment(student, form, academic_year_id, fee_value, *, update_existing=True):
    """
    Create/update the registration ledger row.

    New unpaid registrations do not post income. Existing rows are still updated
    when the fee amount changes. Returns (payment, offer_print_receipt).
    """
    status = _form_registration_payment_status(form)
    collected = status in {'paid', 'partial'}
    existing = find_registration_fee_payment(student, academic_year_id)
    if not collected and not existing:
        return None, False
    payment = sync_registration_fee_ledger(
        student,
        academic_year_id,
        fee_value,
        update_existing=update_existing,
        payment_status=status if collected else None,
        receipt_reference=_form_receipt_reference(form) or None,
    )
    return payment, bool(collected and payment)


def sync_registration_fee_ledger(
    student,
    academic_year_id,
    fee_amount,
    *,
    update_existing=True,
    payment_status=None,
    receipt_reference=None,
):
    """Create or update the registration fee payment row for a student.

    Returns the StudentPayment row, or None when no ledger row is written.
    """
    fee_amount = parse_currency_amount_optional(fee_amount)
    if not student or not academic_year_id or fee_amount <= 0:
        return None

    description = _registration_fee_payment_description(payment_status, receipt_reference)
    existing_reg_payment = find_registration_fee_payment(student, academic_year_id)

    if existing_reg_payment:
        if update_existing:
            old_amount = parse_currency_amount_optional(existing_reg_payment.amount_paid)
            if old_amount != fee_amount:
                existing_reg_payment.amount_paid = fee_amount
                marker = f"[SP-{existing_reg_payment.id}]"
                income_tx = BusinessTransaction.query.filter(
                    BusinessTransaction.description.like(f"%{marker}%"),
                    BusinessTransaction.is_deleted.is_(False),
                ).first()
                if income_tx:
                    income_tx.amount = fee_amount
            if payment_status or receipt_reference:
                existing_reg_payment.description = description
        return existing_reg_payment

    return record_student_payment_with_income(
        student,
        academic_year_id,
        term=1,
        amount_paid=fee_amount,
        description=description,
        installment=1,
    )


def record_student_payment_with_income(
    student,
    academic_year_id,
    term,
    amount_paid,
    description,
    *,
    installment=None,
    paid_on=None,
):
    """
    Record a student fee and mirror it as business income in one atomic ledger cycle.
    Returns the StudentPayment row, or None when amount is zero/invalid.
    """
    amount = parse_currency_amount_optional(amount_paid)
    if amount <= 0 or not student:
        return None

    academic_year = db.session.get(AcademicYear, academic_year_id) if academic_year_id else None
    year_name = academic_year.name if academic_year else None
    payment_description = (description or "Tuition Payment").strip()
    category = categorize_fee_payment(payment_description)
    paid_at = paid_on or datetime.now(timezone.utc)

    payment = StudentPayment(
        student_id=student.id,
        academic_year_id=academic_year_id,
        term=term,
        installment=installment,
        amount_paid=amount,
        description=payment_description,
        paid_on=paid_at,
    )
    db.session.add(payment)
    db.session.flush()

    student_name = student.full_name
    marker = f"[SP-{payment.id}]"
    prev_balance = get_running_business_balance()
    income_tx = BusinessTransaction(
        date=paid_at.strftime("%Y-%m-%d"),
        type="income",
        amount=amount,
        category=category,
        description=(
            f"{marker} Fee payment from {student_name} "
            f"({student.student_id}): {payment_description}"
        ),
        balance_after=parse_currency_amount_optional(prev_balance) + amount,
        academic_year=year_name,
    )
    db.session.add(income_tx)
    maybe_activate_registration_from_payment(student, payment_description)
    return payment


def backfill_student_payments_to_income_ledger():
    """Mirror any historical student payments missing from the business income ledger."""
    created = 0
    for payment in StudentPayment.query.order_by(StudentPayment.id.asc()).all():
        marker = f"[SP-{payment.id}]"
        existing = BusinessTransaction.query.filter(
            BusinessTransaction.description.like(f"%{marker}%"),
            BusinessTransaction.is_deleted.is_(False),
        ).first()
        if existing:
            continue

        student = db.session.get(Student, payment.student_id)
        if not student:
            continue

        academic_year = db.session.get(AcademicYear, payment.academic_year_id)
        amount = parse_currency_amount_optional(payment.amount_paid)
        if amount <= 0:
            continue

        paid_at = payment.paid_on or datetime.now(timezone.utc)
        category = categorize_fee_payment(payment.description)
        prev_balance = get_running_business_balance()
        income_tx = BusinessTransaction(
            date=paid_at.strftime("%Y-%m-%d"),
            type="income",
            amount=amount,
            category=category,
            description=(
                f"{marker} Fee payment from {student.full_name} "
                f"({student.student_id}): {payment.description or 'Student Fee'}"
            ),
            balance_after=parse_currency_amount_optional(prev_balance) + amount,
            academic_year=academic_year.name if academic_year else None,
        )
        db.session.add(income_tx)
        created += 1

    if created:
        db.session.commit()
    return created


def sum_business_ledger(tx_type, active_year=None):
    """Sum business ledger amounts, optionally scoped to the active academic year."""
    query = db.session.query(func.sum(BusinessTransaction.amount)).filter(
        BusinessTransaction.type == tx_type,
        BusinessTransaction.is_deleted.is_(False),
    )
    if active_year:
        query = query.filter(BusinessTransaction.academic_year == active_year.name)
    return money(query.scalar() or 0)


# =========================================================================
# BUSINESS DASHBOARD CONTEXT
# =========================================================================
def populate_business_payment_form(
    payment_form, active_year, years, class_id=None, student_id=None, *, viewing_archived=False,
):
    """Fill payment form choices for the tuition collection workspace."""
    payment_form.academic_year.choices = [(y.id, y.name) for y in years]
    if class_id:
        klass = db.session.get(Class, class_id)
        if klass and active_year:
            students = _principal_students_for_class(
                klass, active_year, viewing_archived=viewing_archived,
            )
        else:
            students = []
        payment_form.student.choices = [(s.id, f"{s.full_name} ({s.student_id})") for s in students] or [
            (0, "No students in this class")
        ]
    else:
        payment_form.student.choices = [(0, "Select a class first")]

    if request.method == "GET":
        if active_year:
            payment_form.academic_year.data = active_year.id
        if student_id:
            payment_form.student.data = student_id
        if not payment_form.description.data:
            payment_form.description.data = "Tuition Payment"
        if payment_form.term.data is None:
            payment_form.term.data = 1


def build_business_class_roster(klass_id, active_year, *, viewing_archived=False):
    """Students in a class with tuition balances for the payment wizard."""
    if not klass_id or not active_year:
        return []
    klass = db.session.get(Class, klass_id)
    if not klass:
        return []
    roster = []
    for student in _principal_students_for_class(
        klass, active_year, viewing_archived=viewing_archived,
    ):
        financials = build_student_financials(student, active_year)
        roster.append({
            "id": student.id,
            "full_name": student.full_name,
            "student_id": student.student_id,
            "yearly_fee": money(financials["yearly_fee"]),
            "total_paid": money(financials["total_paid"]),
            "balance": money(financials["tuition_balance"]),
            "tuition_cleared": student.tuition_cleared,
            "is_registered": student.is_registered,
            "is_promoted": student.is_promoted,
        })
    return roster


def build_business_dashboard_context(
    display_year,
    stats,
    years,
    selected_year_name,
    search_class=None,
    payment_form=None,
    *,
    viewing_archived=False,
):
    """Build template context for the business role dashboard."""
    search_class = (search_class or request.args.get("search_class", "") or "").strip()
    search_student = (request.args.get("search_student") or "").strip()
    active_tab = (request.args.get("tab") or "tuition").strip().lower()
    if active_tab not in {"tuition", "summary", "ledger"}:
        active_tab = "tuition"
    ledger_filter = (request.args.get("ledger_filter") or "all").strip().lower()
    if ledger_filter not in {"all", "flagged"}:
        ledger_filter = "all"

    selected_class_id = request.args.get("class_id", type=int) or request.form.get("class_id", type=int)
    selected_student_id = request.args.get("student_id", type=int) or request.form.get("student_id", type=int)

    if payment_form is None:
        payment_form = PaymentForm()
    populate_business_payment_form(
        payment_form,
        display_year,
        years,
        class_id=selected_class_id,
        student_id=selected_student_id,
        viewing_archived=viewing_archived,
    )

    selected_student = None
    if selected_student_id:
        selected_student = db.session.get(Student, selected_student_id)
    selected_class = db.session.get(Class, selected_class_id) if selected_class_id else None
    class_roster = build_business_class_roster(
        selected_class_id, display_year, viewing_archived=viewing_archived,
    )
    if search_student:
        needle = search_student.lower()
        class_roster = [
            row for row in class_roster
            if needle in (row.get("full_name") or "").lower()
            or needle in str(row.get("student_id") or "").lower()
        ]
    selected_student_summary = next(
        (row for row in class_roster if row["id"] == selected_student_id),
        None,
    )
    if selected_student_id and not selected_student_summary:
        selected_student_summary = next(
            (
                row for row in build_business_class_roster(
                    selected_class_id, display_year, viewing_archived=viewing_archived,
                )
                if row["id"] == selected_student_id
            ),
            None,
        )

    selected_student_payments = []
    if selected_student_id and display_year:
        selected_student_payments = (
            StudentPayment.query.filter_by(
                student_id=selected_student_id,
                academic_year_id=display_year.id,
            )
            .order_by(StudentPayment.paid_on.desc(), StudentPayment.id.desc())
            .limit(12)
            .all()
        )

    class_query = Class.query.order_by(Class.name.asc())
    if search_class:
        class_query = class_query.filter(Class.name.ilike(f"%{search_class}%"))

    classes_list = []
    for klass in class_query.all():
        student_count = len(
            _principal_students_for_class(
                klass, display_year, viewing_archived=viewing_archived,
            )
        ) if display_year else 0

        payment_query = (
            db.session.query(func.sum(StudentPayment.amount_paid))
            .join(Student, StudentPayment.student_id == Student.id)
            .filter(StudentPayment.academic_year_id == display_year.id)
        ) if display_year else db.session.query(func.sum(StudentPayment.amount_paid)).filter(False)
        class_student_ids = [
            s.id for s in _principal_students_for_class(
                klass, display_year, viewing_archived=viewing_archived,
            )
        ] if display_year else []
        if class_student_ids:
            payment_query = payment_query.filter(StudentPayment.student_id.in_(class_student_ids))
        else:
            payment_query = payment_query.filter(False)
        total_paid = payment_query.scalar() or 0
        yearly_fees = float(klass.yearly_fees or 0)
        expected = yearly_fees * student_count

        classes_list.append({
            "id": klass.id,
            "name": klass.name,
            "description": klass.stream or f"Grade {klass.grade_level}",
            "student_count": student_count,
            "total_paid": float(total_paid),
            "yearly_fees": yearly_fees,
            "balance": max(0.0, expected - float(total_paid)),
        })

    total_revenue = sum_business_ledger("income", display_year)
    total_expenses = sum_business_ledger("expense", display_year)
    fee_income_total = 0.0
    if display_year:
        fee_income_total = money(
            db.session.query(func.sum(StudentPayment.amount_paid))
            .filter_by(academic_year_id=display_year.id)
            .scalar()
            or 0
        )

    recent_payments_q = StudentPayment.query
    if display_year:
        recent_payments_q = recent_payments_q.filter_by(academic_year_id=display_year.id)
    recent_payments = []
    for payment in recent_payments_q.order_by(StudentPayment.paid_on.desc()).limit(12).all():
        student = db.session.get(Student, payment.student_id)
        recent_payments.append({
            "id": payment.id,
            "student_name": student.full_name if student else "Unknown",
            "student_code": student.student_id if student else "-",
            "amount": money(payment.amount_paid),
            "description": payment.description or "Tuition",
            "paid_on": payment.paid_on,
            "term": payment.term,
        })

    recent_query = BusinessTransaction.query.filter_by(is_deleted=False)
    if display_year:
        recent_query = recent_query.filter(BusinessTransaction.academic_year == display_year.name)

    year_students = []
    if display_year:
        year_students = (
            _students_for_display_year(display_year, history_mode=viewing_archived)
            .order_by(Student.last_name, Student.first_name)
            .all()
        )

    recent_candidates = (
        recent_query.order_by(BusinessTransaction.date.desc(), BusinessTransaction.id.desc())
        .limit(80)
        .all()
    )

    tx_flags_by_id = {}

    def _mark_tx_flag(tx_id, code):
        tx_flags_by_id.setdefault(tx_id, set()).add(code)

    # Rule 1: Missing category
    for tx in recent_candidates:
        if not (tx.category or '').strip():
            _mark_tx_flag(tx.id, 'Missing category')

    # Rule 2: Repeated amount/type same day (3+)
    repeat_map = {}
    for tx in recent_candidates:
        key = (
            (tx.date or '').strip(),
            (tx.type or '').strip().lower(),
            parse_currency_amount_optional(tx.amount).quantize(Decimal('0.01')),
        )
        repeat_map.setdefault(key, []).append(tx.id)
    for _, tx_ids in repeat_map.items():
        if len(tx_ids) >= 3:
            for tx_id in tx_ids:
                _mark_tx_flag(tx_id, 'Repeated amount pattern')

    # Rule 3: Large expense threshold based on recent pattern
    expense_values = [
        parse_currency_amount_optional(tx.amount)
        for tx in recent_candidates
        if (tx.type or '').strip().lower() == 'expense'
    ]
    avg_expense = (
        sum(expense_values, Decimal('0.00')) / Decimal(len(expense_values))
        if expense_values else Decimal('0.00')
    )
    large_expense_threshold = max(Decimal('500.00'), (avg_expense * Decimal('2.50')).quantize(Decimal('0.01')))
    for tx in recent_candidates:
        if (tx.type or '').strip().lower() != 'expense':
            continue
        if parse_currency_amount_optional(tx.amount) >= large_expense_threshold:
            _mark_tx_flag(tx.id, 'Large expense')

    # Rule 4: Running balance drift (> 1 cent)
    chron_tx = list(reversed(recent_candidates))
    for idx in range(1, len(chron_tx)):
        prev_tx = chron_tx[idx - 1]
        tx = chron_tx[idx]
        tx_type = (tx.type or '').strip().lower()
        if tx_type not in {'income', 'expense'}:
            continue
        prev_balance = parse_currency_amount_optional(prev_tx.balance_after)
        curr_balance = parse_currency_amount_optional(tx.balance_after)
        amount = parse_currency_amount_optional(tx.amount)
        expected = prev_balance + amount if tx_type == 'income' else prev_balance - amount
        if abs((curr_balance - expected).quantize(Decimal('0.01'))) > Decimal('0.01'):
            _mark_tx_flag(tx.id, 'Balance drift')

    flagged_tx_ids = {tx_id for tx_id, tags in tx_flags_by_id.items() if tags}
    ledger_flagged_count = len(flagged_tx_ids)

    recent_transactions = recent_candidates
    if ledger_filter == 'flagged':
        recent_transactions = [tx for tx in recent_candidates if tx.id in flagged_tx_ids]

    recent_transactions = recent_transactions[:10]
    tx_flags_by_id = {tx_id: sorted(list(tags)) for tx_id, tags in tx_flags_by_id.items()}

    return {
        "payment_form": payment_form,
        "active_tab": active_tab,
        "selected_class_id": selected_class_id,
        "selected_student_id": selected_student_id,
        "selected_class": selected_class,
        "selected_student": selected_student,
        "class_roster": class_roster,
        "selected_student_summary": selected_student_summary,
        "selected_student_payments": selected_student_payments,
        "recent_payments": recent_payments,
        "search_class": search_class,
        "search_student": search_student,
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_profit": total_revenue - total_expenses,
        "fee_income_total": fee_income_total,
        "recent_transactions": recent_transactions,
        "ledger_filter": ledger_filter,
        "ledger_flagged_count": ledger_flagged_count,
        "tx_flags_by_id": tx_flags_by_id,
        "students": year_students,
        "classes": classes_list,
        "stats": stats,
        "counts": stats,
        "years": years,
        "all_years": years,
        "selected_year": selected_year_name,
        "display_year": display_year,
        "viewing_archived": viewing_archived,
    }


# =========================================================================
# STUDENT EMAIL LOOKUP (public self-registration + registrar dashboard)
# =========================================================================

LOOKUP_RATE_LIMIT = 30
LOOKUP_RATE_WINDOW_MINUTES = 15


def _client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr)


def check_student_lookup_rate_limit(ip):
    """Throttle public email lookup to reduce enumeration abuse."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKUP_RATE_WINDOW_MINUTES)
    recent = SecurityLog.query.filter(
        SecurityLog.ip_address == ip,
        SecurityLog.event == 'STUDENT_LOOKUP',
        SecurityLog.timestamp >= cutoff,
    ).count()
    return recent >= LOOKUP_RATE_LIMIT


def log_student_lookup(ip):
    db.session.add(SecurityLog(
        ip_address=ip,
        event='STUDENT_LOOKUP',
        timestamp=datetime.now(timezone.utc),
    ))
    db.session.commit()


def looks_like_student_id(value):
    """Return True when the input appears to be a student ID rather than email."""
    raw = (value or '').strip()
    if not raw or '@' in raw:
        return False
    if re.match(r'^\d{4}-\d{1,5}$', raw):
        return True
    return raw.replace('-', '').isdigit() and len(raw.replace('-', '')) >= 4


def validate_student_id_format(student_id_value):
    """Validate registrar/student ID lookup format. Returns (ok, error_message)."""
    raw = (student_id_value or '').strip()
    if not raw:
        return False, 'Student ID is required.'
    if '@' in raw:
        return False, 'Enter a student ID (e.g. 2526-00001), not an email address.'
    if re.match(r'^\d{4}-\d{1,5}$', raw) or raw.isdigit():
        return True, None
    if '-' in raw and all(part.isdigit() for part in raw.split('-', 1) if part):
        return True, None
    return False, 'Invalid student ID format. Use format like 2526-00001.'


def find_student_by_student_id(student_id_value):
    """Resolve a Student record from a permanent student ID (exact or normalized)."""
    raw = (student_id_value or '').strip()
    if not raw:
        return None

    student = Student.query.filter_by(student_id=raw).first()
    if student:
        return student

    if '-' in raw:
        prefix, suffix = raw.split('-', 1)
        if suffix.isdigit():
            for candidate in (
                f"{prefix}-{int(suffix):05d}",
                f"{prefix}-{int(suffix):04d}",
                f"{prefix}-{int(suffix)}",
            ):
                student = Student.query.filter_by(student_id=candidate).first()
                if student:
                    return student

    return None


def resolve_user_for_login(identifier):
    """Resolve a User from portal email or permanent student ID."""
    raw = (identifier or '').strip()
    if not raw:
        return None

    if looks_like_student_id(raw):
        student = find_student_by_student_id(raw)
        if student and student.user_id:
            return db.session.get(User, student.user_id)
        user = User.query.filter(func.lower(User.username) == raw.lower()).first()
        if user:
            return user
        return None

    return User.query.filter(func.lower(User.email) == raw.lower()).first() or (
        User.query.filter(func.lower(User.username) == raw.lower()).first()
    )


def find_student_by_email(email):
    """
    Resolve a student record from a portal or parent/guardian email.
    Returns (student, match_kind) where match_kind is 'portal' or 'parent'.
    """
    normalized = (email or '').strip().lower()
    if not normalized or '@' not in normalized:
        return None, None

    user = User.query.filter(func.lower(User.email) == normalized).first()
    if user:
        student = Student.query.filter_by(user_id=user.id).first()
        if not student and getattr(user, 'student_profile', None):
            student = user.student_profile
        if student and not student_is_alumni(student):
            return student, 'portal'

    student = (
        Student.query.filter(func.lower(Student.parent_email) == normalized)
        .filter(~Student.status.in_(list(ALUMNI_STATUSES)))
        .order_by(Student.id.desc())
        .first()
    )
    if student:
        return student, 'parent'

    return None, None


_RETENTION_PLACEMENT_CODES = frozenset({'REPEAT', 'SUMMER_SCHOOL'})
_RETENTION_PLACEMENT_LABELS = {
    'REPEAT': 'Repeat class',
    'SUMMER_SCHOOL': 'Summer School',
}


def find_prior_academic_year(year):
    """Year that rolls into `year` (e.g. 2025-2026 → 2026-2027)."""
    if year is None:
        return None
    target_name = (getattr(year, 'name', None) or '').strip()
    if not target_name:
        return None
    for candidate in AcademicYear.query.filter(AcademicYear.id != year.id).all():
        if _next_academic_year_name(candidate.name) == target_name:
            return candidate
    return None


def returning_student_retention_info(student):
    """
    Repeat class / Summer School placement for registrar re-registration.

    Uses enrollment status set by rollover, then last-year promotion
    (evaluate_year_promotion_decision). Does not invent new status codes.
    """
    if not student:
        return None

    code = (getattr(student, 'status', None) or '').upper()
    if code not in _RETENTION_PLACEMENT_CODES:
        years_to_check = []
        if getattr(student, 'academic_year', None):
            years_to_check.append(student.academic_year)
        active = get_active_academic_year()
        if active:
            years_to_check.append(active)
        prior = find_prior_academic_year(active or getattr(student, 'academic_year', None))
        if prior:
            years_to_check.append(prior)

        seen = set()
        code = ''
        for year in years_to_check:
            year_id = getattr(year, 'id', None)
            if not year or year_id in seen:
                continue
            seen.add(year_id)
            decision = evaluate_year_promotion_decision(student, year)
            decision_code = (decision.get('code') or '').upper()
            if decision_code in _RETENTION_PLACEMENT_CODES:
                code = decision_code
                break
        if code not in _RETENTION_PLACEMENT_CODES:
            return None

    label = _RETENTION_PLACEMENT_LABELS[code]
    klass = getattr(student, 'assigned_class', None) or getattr(student, 'klass', None)
    if klass is None and student.klass_id:
        klass = db.session.get(Class, student.klass_id)
    klass_name = ''
    if klass is not None:
        klass_name = klass.name or ''
        stream = getattr(klass, 'stream', None)
        if stream:
            klass_name = f'{klass_name} ({stream})'.strip()
    if not klass_name:
        formatted = format_student_class_name(student)
        if formatted and formatted not in ('Not Assigned',):
            klass_name = formatted

    lock_class = bool(student.klass_id)
    detail = 'They stay in the same grade, not promoted.'
    return {
        'code': code,
        'label': label,
        'klass_id': student.klass_id,
        'klass_name': klass_name,
        'lock_class': lock_class,
        'detail': detail,
        'message': f'{label} — they stay in the same grade, not promoted.',
    }


def apply_returning_retention_class(student, form):
    """Keep a repeater / summer-school student in the class rollover assigned."""
    info = returning_student_retention_info(student)
    if not info:
        return info
    if info.get('lock_class') and info.get('klass_id') and form is not None:
        form.klass.data = info['klass_id']
    if (student.status or '').upper() not in _RETENTION_PLACEMENT_CODES:
        student.status = info['code']
    return info


def build_student_lookup_payload(student, match_kind, *, staff=False):
    """Shared lookup response for enrollment auto-fill APIs."""
    user = student.user
    has_photo = bool(student.has_id_photo)
    klass = getattr(student, 'assigned_class', None) or getattr(student, 'klass', None)
    klass_name = (klass.name if klass is not None else '') or ''
    payload = {
        'found': True,
        'is_returning': True,
        'match_kind': match_kind,
        'first_name': student.first_name,
        'last_name': student.last_name,
        'dob': student.dob.isoformat() if student.dob else None,
        'gender': student.gender,
        'level': academic_level_for_student(student),
        'parent_email': student.parent_email or '',
        'parent_phone': student.parent_phone or '',
        'guardian_name': resolve_parent_guardian_name(student) or '',
        'klass_id': student.klass_id,
        'klass_name': klass_name,
        'status': (student.status or 'ACTIVE').upper(),
        'student_id': student.student_id,
        'email': (user.email if user else '') or '',
        'telephone_number': (user.telephone_number if user else '') or '',
        'home_address': (user.home_address if user else '') or '',
        'has_id_photo': has_photo,
        'photo_url': student.photo_url if has_photo else '',
        'retention': None,
        'promotion_status': None,
    }

    if staff:
        fee_value = float(student.registration_fees or 0)
        payload['registration_fees'] = f'{fee_value:,.2f}' if fee_value else '0.00'
        retention = returning_student_retention_info(student)
        payload['retention'] = retention
        if retention:
            payload['promotion_status'] = retention['code']
            class_bit = ''
            if retention.get('klass_name'):
                locked = ' (locked)' if retention.get('lock_class') else ''
                class_bit = f" Class: {retention['klass_name']}{locked}."
            payload['welcome_message'] = (
                f"{retention['label']}: {student.first_name} {student.last_name} "
                f"stays in the same grade, not promoted.{class_bit}"
            )
        else:
            payload['welcome_message'] = (
                f'Returning student found: {student.first_name} {student.last_name}. '
                'Identity fields are locked — assign class and academic year, then commit.'
            )
    else:
        parent_contact = student.parent_email or ''
        if not parent_contact and student.user:
            parent_contact = student.user.telephone_number or student.user.email or ''
        payload['parent_contact'] = parent_contact
        payload['welcome_message'] = (
            f'Welcome back, {student.first_name}! We found your record. '
            'Confirm your details below to complete re-registration for the new academic year.'
        )

    return payload


def _class_division_label_map(classes=None):
    rows = classes if classes is not None else Class.query.order_by(Class.name.asc()).all()
    return {klass.id: division_label_for_class(klass) for klass in rows}


def _populate_self_registration_form(form):
    """Load class choices for the public self-registration form."""
    classes = Class.query.order_by(Class.name.asc()).all()
    form.klass.choices = [(0, '— Select Class (optional) —')] + [
        (klass.id, klass.name) for klass in classes
    ]
    return classes


def _apply_self_registration_to_student(student, form, academic_year, *, registration_type):
    """Persist SelfRegistrationForm fields onto a Student record."""
    active_year_id = academic_year.id if academic_year else None
    klass_id = form.klass.data or None
    if klass_id in (0, '0', '', None):
        klass_id = None

    student.first_name = form.first_name.data.strip()
    student.last_name = form.last_name.data.strip()
    student.dob = form.dob.data
    student.gender = form.gender.data
    student.parent_email = (form.parent_email.data or '').strip() or None
    student.klass_id = klass_id
    student.academic_year_id = active_year_id
    student.level = form.level.data
    student.registrar = 'Self-Service'
    student.status = student.status or 'ACTIVE'
    student.registration_type = registration_type

    if klass_id:
        assigned_class = db.session.get(Class, klass_id)
        if assigned_class:
            student.grade_level = assigned_class.grade_level
            division = division_label_for_class(assigned_class)
            if division and division != 'Other':
                student.level = division

    if student.student_id:
        student.student_id_code = student.student_id

    return get_registration_fee_for_student(student, active_year_id)


@app.route('/student/enrollment', methods=['GET'])
def student_enrollment():
    """Public self-service enrollment form."""
    form = SelfRegistrationForm()
    classes = _populate_self_registration_form(form)
    return render_template(
        'student/self_registration.html',
        form=form,
        class_division_labels=_class_division_label_map(classes),
    )


@app.route('/student/enrollment/submit', methods=['POST'])
def submit_registration():
    """Process public self-registration submissions."""
    form = SelfRegistrationForm()
    classes = _populate_self_registration_form(form)
    self_reg_ctx = {'form': form, 'class_division_labels': _class_division_label_map(classes)}

    if not form.validate_on_submit():
        flash('Please correct the highlighted errors before submitting.', 'danger')
        return render_template('student/self_registration.html', **self_reg_ctx), 400

    active_year = get_active_academic_year()
    if not active_year:
        flash('Enrollment is closed — no active academic year is configured.', 'danger')
        return redirect(url_for('student_enrollment'))

    email = (form.email.data or '').strip().lower()
    is_returning = bool(form.is_returning.data)

    try:
        existing_student, _match_kind = find_student_by_email(email)
        registration_type = 'Returning' if is_returning else 'New'

        if is_returning:
            if not existing_student:
                flash('No matching record found for that email. Uncheck returning student or use a different email.', 'danger')
                return render_template('student/self_registration.html', **self_reg_ctx)
            if student_same_year_fully_enrolled(existing_student, active_year.id):
                flash(f'You are already enrolled for {active_year.name}. Sign in to access your portal.', 'info')
                return redirect(url_for('login'))
            student = existing_student
            registration_type = 'Returning'
        elif existing_student:
            if not _same_student_identity(existing_student, form):
                flash('That email is already linked to another student record.', 'danger')
                return render_template('student/self_registration.html', **self_reg_ctx)
            student = existing_student
            registration_type = 'Returning'
        else:
            student = Student(
                student_id=generate_next_student_id(active_year),
                registration_type='New',
            )
            db.session.add(student)

        registration_fee = _apply_self_registration_to_student(
            student,
            form,
            active_year,
            registration_type=registration_type,
        )

        if email:
            chosen_password = (form.password.data or '').strip() or None
            portal_user = link_student_portal_from_form(
                student,
                email,
                password=chosen_password,
                must_change_password=not bool(chosen_password),
            )
            if not portal_user:
                flash(
                    'Enrollment saved, but a portal account could not be created for that email. '
                    'Contact the registrar for assistance.',
                    'warning',
                )
            else:
                issued = getattr(portal_user, '_issued_initial_password', None)
                if issued and not chosen_password:
                    flash(
                        f'Your portal login password is {issued}. Change it after you sign in.',
                        'info',
                    )

        mark_student_promoted_pending_fee(student)
        sync_student_class_assignment(student)
        db.session.commit()

        return render_template(
            'student/payment_gate.html',
            student=student,
            active_year=active_year,
            registration_fee=registration_fee,
            pending={'returning': registration_type == 'Returning'},
        )
    except Exception as exc:
        db.session.rollback()
        logger.error('Self-registration failed: %s', exc, exc_info=True)
        flash('Registration could not be completed. Please try again or visit the registrar.', 'danger')
        return render_template('student/self_registration.html', **self_reg_ctx)


@app.route('/api/lookup-student', methods=['POST'])
@csrf.exempt
def api_lookup_student():
    """Lookup student by email for self-registration auto-fill (rate-limited)."""
    ip = _client_ip()
    if check_student_lookup_rate_limit(ip):
        return jsonify({
            'found': False,
            'error': 'Too many lookup attempts. Please wait a few minutes and try again.',
        }), 429

    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or request.form.get('email') or '').strip().lower()

    if not email or '@' not in email or len(email) > 120:
        return jsonify({'found': False, 'error': 'A valid email address is required.'}), 400

    log_student_lookup(ip)

    student, match_kind = find_student_by_email(email)
    if not student:
        return jsonify({
            'found': False,
            'is_returning': False,
            'welcome_message': (
                'No existing record found for this email. '
                'Please complete the form below to register as a new student.'
            ),
        })

    if student_registration_gate_active(student):
        return jsonify({
            'found': True,
            'is_returning': True,
            'already_pending': True,
            'welcome_message': (
                f'Welcome back, {student.first_name}! Your re-registration is already on file. '
                'Proceed to the payment step to complete enrollment.'
            ),
            **build_student_lookup_payload(student, match_kind, staff=False),
        })

    return jsonify(build_student_lookup_payload(student, match_kind, staff=False))


@app.route('/api/registrar/lookup-student', methods=['POST'])
@login_required
def api_registrar_lookup_student():
    """Staff-only student lookup for registrar dashboard enrollment auto-fill."""
    if normalize_role(current_user) not in {'admin', 'principal', 'registrar'}:
        return jsonify({'found': False, 'error': 'Unauthorized.'}), 403

    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or request.form.get('email') or '').strip().lower()
    student_id_input = (payload.get('student_id') or request.form.get('student_id') or '').strip()

    student = None
    match_kind = None

    if student_id_input or (email and looks_like_student_id(email)):
        lookup_id = student_id_input or email
        ok, format_error = validate_student_id_format(lookup_id)
        if not ok:
            return jsonify({'found': False, 'error': format_error}), 400

        student = find_student_by_student_id(lookup_id)
        if not student:
            return jsonify({
                'found': False,
                'is_returning': False,
                'welcome_message': (
                    f'No existing record for student ID {lookup_id.strip()}. '
                    'Complete the form below to register a new student.'
                ),
            })

        match_kind = 'student_id'
    elif email:
        if '@' not in email or len(email) > 120:
            return jsonify({'found': False, 'error': 'A valid email address is required.'}), 400
        student, match_kind = find_student_by_email(email)
        if not student:
            return jsonify({
                'found': False,
                'is_returning': False,
                'welcome_message': (
                    'No existing record for this email. Complete the form below to register a new student.'
                ),
            })
    else:
        return jsonify({
            'found': False,
            'error': 'Enter a student email or student ID (e.g. 2526-00001) to search.',
        }), 400

    if student_is_alumni(student):
        return jsonify({
            'found': False,
            'is_alumni': True,
            'error': (
                f'{student.full_name} is an alumni record. '
                'Use alumni workflows instead of new registration.'
            ),
        }), 400

    return jsonify(build_student_lookup_payload(student, match_kind, staff=True))


@app.route('/api/registrar/check-student-id', methods=['POST'])
@login_required
def api_registrar_check_student_id():
    """Staff-only live duplicate check for registrar enrollment student IDs."""
    if normalize_role(current_user) not in {'admin', 'principal', 'registrar'}:
        return jsonify({'available': False, 'error': 'Unauthorized.'}), 403

    payload = request.get_json(silent=True) or {}
    student_id = (payload.get('student_id') or request.form.get('student_id') or '').strip()

    if not student_id:
        return jsonify({
            'available': True,
            'blank': True,
            'message': 'Leave blank to auto-generate the next available ID.',
        })

    existing = Student.query.filter_by(student_id=student_id).first()
    if not existing:
        return jsonify({
            'available': True,
            'student_id': student_id,
            'message': f'Student ID {student_id} is available.',
        })

    return jsonify({
        'available': False,
        'student_id': student_id,
        'assigned_to': existing.full_name,
        'message': (
            f'Student ID {student_id} is already assigned to {existing.full_name}. '
            'Use email lookup to re-register returning students.'
        ),
        'hint': 'Go back to Step 1 and search by their portal email.',
    })


# =========================================================================
# 2. OPTIMIZED STUDENT REGISTRATION & LEDGER COMMIT ROUTE
# =========================================================================
REGISTRAR_YEAR_SESSION_KEY = 'registrar_display_year_id'
ADMIN_YEAR_SESSION_KEY = 'admin_display_year_id'
PRINCIPAL_YEAR_SESSION_KEY = 'principal_display_year_id'
BUSINESS_YEAR_SESSION_KEY = 'business_display_year_id'
DEAN_YEAR_SESSION_KEY = 'dean_display_year_id'
VPI_YEAR_SESSION_KEY = 'vpi_display_year_id'
VPA_YEAR_SESSION_KEY = 'vpa_display_year_id'
TEACHER_YEAR_SESSION_KEY = 'teacher_display_year_id'


def all_academic_years():
    """All academic years, newest first — used for dashboard year dropdowns."""
    if has_request_context() and hasattr(g, '_flpa_all_years'):
        return g._flpa_all_years
    years = AcademicYear.query.order_by(
        AcademicYear.start_date.desc(),
        AcademicYear.name.desc(),
        AcademicYear.id.desc(),
    ).all()
    if has_request_context():
        g._flpa_all_years = years
    return years


def dashboard_year_session_key(role=None):
    """Session key for the current role's dashboard year picker."""
    role = (role or (current_user.role if current_user.is_authenticated else '') or '').lower()
    if role == 'admin':
        return ADMIN_YEAR_SESSION_KEY
    if role == 'principal':
        return PRINCIPAL_YEAR_SESSION_KEY
    if role == 'dean':
        return DEAN_YEAR_SESSION_KEY
    if role == 'vpi':
        return VPI_YEAR_SESSION_KEY
    if role == 'vpa':
        return VPA_YEAR_SESSION_KEY
    if role in ('business',):
        return BUSINESS_YEAR_SESSION_KEY
    if role == 'teacher':
        return TEACHER_YEAR_SESSION_KEY
    return REGISTRAR_YEAR_SESSION_KEY


def reset_dashboard_year_sessions(target_year=None):
    """Reset dashboard year session keys so views default to the new active academic year."""
    if not target_year:
        return
    for role in ('admin', 'principal', 'dean', 'business', 'vpa', 'vpi', 'teacher', 'registrar'):
        session[dashboard_year_session_key(role)] = target_year.id


def students_for_academic_year(year_id, *, registered_only=False, **filters):
    """Strict year-scoped student query — no NULL academic_year_id bleed."""
    if not year_id:
        return Student.query.filter(Student.id < 0)
    query = Student.query.filter(Student.academic_year_id == year_id)
    if registered_only:
        query = query.filter(Student.is_registered.is_(True))
    if filters:
        query = query.filter_by(**filters)
    return query


def list_payment_students_for_year(academic_year):
    """Students selectable when posting a payment for one academic-year folder."""
    if not academic_year:
        return []
    year_id = academic_year.id if hasattr(academic_year, 'id') else academic_year
    if not year_id:
        return []
    return (
        students_for_academic_year(year_id, registered_only=True)
        .filter(~Student.status.in_(list(ALUMNI_STATUSES)))
        .order_by(Student.last_name.asc(), Student.first_name.asc())
        .all()
    )


def _students_pending_year_registration(display_year):
    """Promoted students tagged to a year but awaiting registrar re-registration."""
    if not display_year:
        return Student.query.filter(Student.id < 0)
    return Student.query.filter(
        Student.academic_year_id == display_year.id,
        Student.is_promoted.is_(True),
        Student.is_registered.is_(False),
        ~Student.status.in_(list(ALUMNI_STATUSES)),
    )


def _student_ids_with_year_history(year_id):
    """Student IDs with any academic footprint in a year (union, one round-trip)."""
    if not year_id:
        return []
    queries = [
        db.session.query(Student.id.label('sid')).filter(Student.academic_year_id == year_id),
        db.session.query(Grade.student_id.label('sid')).filter(
            Grade.academic_year_id == year_id, Grade.student_id.isnot(None)
        ),
        db.session.query(StudentPayment.student_id.label('sid')).filter(
            StudentPayment.academic_year_id == year_id, StudentPayment.student_id.isnot(None)
        ),
        db.session.query(Attendance.student_id.label('sid')).filter(
            Attendance.academic_year_id == year_id, Attendance.student_id.isnot(None)
        ),
        db.session.query(Enrollment.student_id.label('sid')).filter(
            Enrollment.academic_year_id == year_id, Enrollment.student_id.isnot(None)
        ),
    ]
    union_q = queries[0].union(queries[1], queries[2], queries[3], queries[4])
    return [row[0] for row in union_q.all() if row[0]]


def adjacent_academic_years(display_year, years=None):
    """Older and newer neighbors of the displayed year (list is newest-first)."""
    years = list(years) if years is not None else all_academic_years()
    if not display_year or not years:
        return None, None
    ids = [year.id for year in years]
    try:
        index = ids.index(display_year.id)
    except ValueError:
        return None, None
    newer = years[index - 1] if index > 0 else None
    older = years[index + 1] if index + 1 < len(years) else None
    return older, newer


def resolve_dashboard_academic_year(session_key=None):
    """
    Resolve the academic year shown on role dashboards.
    Priority: ?academic_year_id= query param -> session -> active year.
    Session selections persist so staff can move back and forth across years.
    """
    if session_key is None:
        session_key = dashboard_year_session_key()
    active_year = get_active_academic_year()
    years = all_academic_years()
    valid_year_ids = {year.id for year in years}

    requested_id = (
        request.args.get('academic_year_id', type=int)
        or request.form.get('academic_year_id', type=int)
    )
    display_year = None

    if requested_id and requested_id in valid_year_ids:
        session[session_key] = requested_id
        display_year = db.session.get(AcademicYear, requested_id)
    else:
        session_year_id = session.get(session_key)
        if session_year_id in valid_year_ids:
            display_year = db.session.get(AcademicYear, session_year_id)
        elif active_year:
            display_year = active_year
            session[session_key] = active_year.id
        elif years:
            display_year = years[0]
            session[session_key] = display_year.id

    viewing_archived = bool(
        display_year
        and active_year
        and display_year.id != active_year.id
    )

    return display_year, active_year, years, viewing_archived


def dashboard_redirect_kwargs(session_key=None, **extra):
    """Preserve dashboard display year (and roster tab) across redirects."""
    if session_key is None:
        session_key = dashboard_year_session_key()
    params = {key: value for key, value in extra.items() if value is not None}
    year_id = (
        request.args.get('academic_year_id', type=int)
        or request.form.get('academic_year_id', type=int)
        or session.get(session_key)
    )
    if year_id and 'academic_year_id' not in params:
        params['academic_year_id'] = year_id
    roster_view = request.args.get('view') or request.form.get('view')
    if roster_view == 'alumni' and 'view' not in params:
        params['view'] = 'alumni'
    return params


def registrar_dashboard_redirect_kwargs(**extra):
    """Preserve registrar year (and roster tab) across redirects."""
    return dashboard_redirect_kwargs(session_key=REGISTRAR_YEAR_SESSION_KEY, **extra)


def _students_for_display_year(display_year, *, alumni_only=False, history_mode=False):
    """
    Year-scoped student query for dashboards.
    Active year: always strict registered enrollment (``history_mode`` is ignored).
    Archived years with ``history_mode=True``: include students with grade/payment/
    attendance footprints in that year even after rollover moved their live enrollment
    forward.
    """
    if not display_year:
        return Student.query.filter(Student.id < 0)

    active_year = get_active_academic_year()
    use_history_union = (
        history_mode
        and active_year is not None
        and display_year.id != active_year.id
    )

    if use_history_union:
        student_ids = _student_ids_with_year_history(display_year.id)
        query = (
            Student.query.filter(Student.id.in_(student_ids))
            if student_ids else
            Student.query.filter(Student.id < 0)
        )
        if alumni_only:
            return query.filter(Student.status.in_(list(ALUMNI_STATUSES)))
        return query

    query = students_for_academic_year(display_year.id, registered_only=True)
    if alumni_only:
        return query.filter(Student.status.in_(list(ALUMNI_STATUSES)))
    return query.filter(~Student.status.in_(list(ALUMNI_STATUSES)))


def _student_class_map_for_display_year(display_year, *, viewing_archived=False):
    """Map student_id -> class_id for roster and attendance (SQL, year-scoped)."""
    if not display_year:
        return {}
    year_id = display_year.id
    mapping = {}
    if viewing_archived:
        for sid, cid in (
            db.session.query(Enrollment.student_id, Enrollment.class_id)
            .filter(Enrollment.academic_year_id == year_id, Enrollment.class_id.isnot(None))
            .all()
        ):
            mapping[sid] = cid
        for sid, cid in (
            db.session.query(Grade.student_id, Grade.class_id)
            .filter(
                Grade.academic_year_id == year_id,
                Grade.student_id.isnot(None),
                Grade.class_id.isnot(None),
            )
            .distinct()
            .all()
        ):
            mapping.setdefault(sid, cid)
    for sid, cid in (
        _students_for_display_year(display_year, history_mode=viewing_archived)
        .filter(Student.klass_id.isnot(None))
        .with_entities(Student.id, Student.klass_id)
        .all()
    ):
        mapping.setdefault(sid, cid)
    return mapping


def _roster_sizes_for_display_year(display_year, *, viewing_archived=False):
    """Count students per class for the display year."""
    sizes = {}
    for class_id in _student_class_map_for_display_year(
        display_year, viewing_archived=viewing_archived,
    ).values():
        if class_id:
            sizes[class_id] = sizes.get(class_id, 0) + 1
    return sizes


def _attach_display_class(students, display_year, *, viewing_archived=False):
    """Set display_klass on students without per-row class lookups."""
    if not students:
        return students
    if not display_year or not viewing_archived:
        for student in students:
            student.display_klass = student.klass
        return students
    mapping = _student_class_map_for_display_year(display_year, viewing_archived=True)
    class_ids = {cid for cid in mapping.values() if cid}
    classes = {
        klass.id: klass
        for klass in (Class.query.filter(Class.id.in_(class_ids)).all() if class_ids else [])
    }
    for student in students:
        cid = mapping.get(student.id) or student.klass_id
        student.display_klass = classes.get(cid) or student.klass
    return students


def _registrar_counts_for_year(display_year, *, viewing_archived=False):
    """Year-scoped registrar dashboard counters."""
    if not display_year:
        return {
            'students': 0,
            'new_students': 0,
            'returning_students': 0,
            'alumni': 0,
            'teachers': Teacher.query.count(),
            'classes': Class.query.count(),
            'payments': 0,
        }

    year_id = display_year.id
    active_students = _students_for_display_year(
        display_year,
        alumni_only=False,
        history_mode=viewing_archived,
    )
    alumni_students = _students_for_display_year(
        display_year,
        alumni_only=True,
        history_mode=viewing_archived,
    )
    return {
        'students': active_students.count(),
        'new_students': active_students.filter_by(registration_type='New').count(),
        'returning_students': active_students.filter_by(registration_type='Returning').count(),
        'alumni': alumni_students.count(),
        'pending_registration': (
            _students_pending_year_registration(display_year).count()
            if not viewing_archived else 0
        ),
        'teachers': Teacher.query.count(),
        'classes': Class.query.count(),
        'payments': StudentPayment.query.filter_by(academic_year_id=year_id).count(),
    }


def _build_homeroom_matrix():
    rows = []
    for klass in Class.query.order_by(Class.name.asc()).all():
        homeroom_teacher = db.session.get(Teacher, klass.teacher_id) if klass.teacher_id else None
        rows.append({
            'klass': klass,
            'homeroom_teacher': homeroom_teacher,
        })
    return rows


def _build_registrar_year_lifecycle_status(display_year, active_year):
    """Quick checklist for academic year lifecycle on the registrar dashboard."""
    items = []
    if not active_year:
        items.append({
            'label': 'Active academic year',
            'ok': False,
            'hint': 'Create and activate a year in Academic Years',
        })
        return items

    items.append({
        'label': f'Active year: {active_year.name}',
        'ok': True,
        'hint': 'Registrar views default to this session',
    })

    if display_year and display_year.id == active_year.id:
        pending_reg = (
            _students_for_display_year(display_year, alumni_only=False)
            .filter(Student.is_promoted.is_(True), Student.is_registered.is_(False))
            .count()
        )
        items.append({
            'label': 'Re-registration queue',
            'ok': pending_reg == 0,
            'hint': (
                f'{pending_reg} student(s) awaiting registration fee'
                if pending_reg
                else 'No pending re-registrations'
            ),
        })

        last_rollover = (
            RolloverLog.query.filter_by(to_year_id=active_year.id)
            .order_by(RolloverLog.created_at.desc())
            .first()
        )
        if last_rollover:
            rolled_on = last_rollover.created_at.date() if last_rollover.created_at else '—'
            items.append({
                'label': 'Year rollover',
                'ok': True,
                'hint': f'Completed {rolled_on}',
            })
        else:
            items.append({
                'label': 'Year rollover',
                'ok': None,
                'hint': 'Not recorded for this year — run when ready to promote',
            })

    return items


def _registrar_roster_class_for_student(student, display_year, *, viewing_archived=False):
    """Resolve the class folder a roster student belongs to for the display year.

    Live years use ``klass_id`` (plus year enrollment if the live FK is empty).
    Archived years use historical grade/enrollment resolution so rollover does
    not dump every student into Unassigned or the current class.
    """
    if not student:
        return None
    year_id = display_year.id if display_year else None
    if viewing_archived:
        return get_student_class_for_year(student, year_id)
    if student.klass_id:
        return student.assigned_class or db.session.get(Class, student.klass_id)
    if year_id:
        enrolled_id = _class_id_from_year_enrollment(student.id, year_id)
        if enrolled_id:
            return db.session.get(Class, enrolled_id)
    return None


def _student_roster_search_haystack(student):
    """Name, ID, and contact text used to find a student inside class folders."""
    parent_user = getattr(student, 'parent_user', None)
    user = getattr(student, 'user', None)
    parts = [
        getattr(student, 'full_name', None),
        student.first_name,
        student.last_name,
        student.student_id,
        student.parent_phone,
        student.parent_email,
        getattr(student, 'guardian_name', None),
        getattr(parent_user, 'full_name', None) if parent_user else None,
        getattr(user, 'email', None) if user else None,
        getattr(user, 'telephone_number', None) if user else None,
    ]
    return ' '.join(str(part).strip() for part in parts if part).lower()


def _student_matches_roster_search(student, needle):
    if not needle:
        return True
    return needle in _student_roster_search_haystack(student)


def _build_registrar_roster_folders(
    display_year,
    *,
    alumni_only=False,
    viewing_archived=False,
    search_class='',
    search_student='',
    open_class_id=None,
    open_student_id=None,
):
    """File-explorer class folders with a nested folder per student."""
    roster_students = []
    if display_year:
        roster_students = (
            _students_for_display_year(
                display_year,
                alumni_only=alumni_only,
                history_mode=viewing_archived,
            )
            .options(
                joinedload(Student.user),
                joinedload(Student.parent_user),
                joinedload(Student.assigned_class),
                joinedload(Student.academic_year),
                selectinload(Student.registry_documents),
            )
            .order_by(Student.last_name.asc(), Student.first_name.asc())
            .all()
        )

    class_needle = (search_class or '').strip().lower()
    student_needle = (search_student or '').strip().lower()
    class_rows = Class.query.all()
    if class_needle:
        class_rows = [
            klass for klass in class_rows
            if class_needle in (klass.name or '').lower()
            or class_needle in (klass.stream or '').lower()
            or class_needle in str(klass.grade_level or '').lower()
        ]
    class_rows = sorted(class_rows, key=class_sort_key_from_klass)
    class_ids = {klass.id for klass in class_rows}

    students_by_class = {klass.id: [] for klass in class_rows}
    unassigned = []
    for student in roster_students:
        if not _student_matches_roster_search(student, student_needle):
            continue
        klass = _registrar_roster_class_for_student(
            student, display_year, viewing_archived=viewing_archived,
        )
        if klass and klass.id in class_ids:
            students_by_class[klass.id].append(student)
        elif klass and not class_needle:
            students_by_class.setdefault(klass.id, []).append(student)
        elif not class_needle:
            unassigned.append(student)

    folders = []
    for klass in class_rows:
        students = students_by_class.get(klass.id, [])
        if student_needle and not students:
            continue
        folders.append({
            'id': klass.id,
            'name': klass.name,
            'grade_level': klass.grade_level,
            'stream': klass.stream,
            'division_label': division_label_for_class(klass),
            'student_count': len(students),
            'students': students,
            'klass': klass,
            'id_download_filename': id_cards_pdf_filename(klass, display_year),
        })

    extra_ids = [
        class_id for class_id in students_by_class
        if class_id not in class_ids and students_by_class[class_id]
    ]
    for class_id in extra_ids:
        klass = db.session.get(Class, class_id)
        if not klass:
            continue
        students = students_by_class[class_id]
        folders.append({
            'id': klass.id,
            'name': klass.name,
            'grade_level': klass.grade_level,
            'stream': klass.stream,
            'division_label': division_label_for_class(klass),
            'student_count': len(students),
            'students': students,
            'klass': klass,
            'id_download_filename': id_cards_pdf_filename(klass, display_year),
        })

    folders.sort(key=lambda folder: class_sort_key_from_klass(folder['klass']))
    if not open_student_id and student_needle:
        for folder in folders:
            if folder['students']:
                open_class_id = open_class_id or folder['id']
                open_student_id = folder['students'][0].id
                break
        if not open_student_id and unassigned:
            open_student_id = unassigned[0].id
    elif open_student_id and not open_class_id:
        for folder in folders:
            if any(student.id == open_student_id for student in folder['students']):
                open_class_id = folder['id']
                break

    year_id = display_year.id if display_year else None
    receipt_map = _latest_registration_payments_map(
        [student.id for student in roster_students],
        academic_year_id=year_id,
    )
    for student in roster_students:
        payment = receipt_map.get(student.id)
        if payment:
            student.registration_fee_status = _registration_receipt_meta(payment, student)['fee_status']
        elif parse_currency_amount_optional(getattr(student, 'registration_fees', 0)) > 0:
            student.registration_fee_status = 'Unpaid'

    _refresh_id_card_flags(roster_students, academic_year=display_year, commit=False)

    return {
        'roster_folders': folders,
        'roster_folders_by_division': group_items_by_class(folders, lambda folder: folder['klass']),
        'unassigned_roster_students': unassigned,
        'open_class_id': open_class_id,
        'open_student_id': open_student_id,
        'search_student': (search_student or '').strip(),
        'registration_receipt_payments': receipt_map,
        'roster_record_count': (
            sum(folder['student_count'] for folder in folders) + len(unassigned)
            if (class_needle or student_needle)
            else len(roster_students)
        ),
    }


def build_registrar_dashboard_context(form=None, search_class=None):
    """Shared template context for registrar dashboard and registration views."""
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=REGISTRAR_YEAR_SESSION_KEY,
    )
    search_class = (search_class or request.args.get('search_class') or '').strip()
    search_student = (request.args.get('search_student') or '').strip()
    roster_view = 'alumni' if request.args.get('view') == 'alumni' else 'active'
    history_mode = viewing_archived

    all_class_rows = list_assignable_registration_classes()
    registration_class_groups = registration_class_select_groups(all_class_rows)
    # Enrollment class picker must list every class. Search only filters the roster sidebar.
    class_rows = all_class_rows
    if search_class:
        needle = search_class.lower()
        class_rows = [klass for klass in class_rows if needle in (klass.name or '').lower()]

    classes = []
    for klass in class_rows:
        student_count = 0
        if display_year:
            if viewing_archived:
                student_count = len(
                    _principal_students_for_class(
                        klass, display_year, viewing_archived=True,
                    )
                )
            else:
                student_count = (
                    _students_for_display_year(
                        display_year,
                        alumni_only=False,
                        history_mode=False,
                    )
                    .filter_by(klass_id=klass.id)
                    .count()
                )
        classes.append({
            'id': klass.id,
            'name': klass.name,
            'description': getattr(klass, 'description', None) or klass.stream,
            'student_count': student_count,
            'division_label': division_label_for_class(klass),
            'klass': klass,
        })

    if form is None:
        form = RegisterStudentForm()

    form.klass.choices = [(0, '-- Select Class --')] + [
        (klass.id, klass.name) for klass in all_class_rows
    ]
    form.academic_year.choices = [(0, '-- Select Academic Year --')] + [(y.id, y.name) for y in years]
    suggested_student_id = generate_next_student_id(display_year or active_year)
    already_bound = bool(form.first_name.data or form.last_name.data)
    if request.method == 'GET' and not already_bound:
        if display_year:
            form.academic_year.default = display_year.id
        form.process()

    students_query = _students_for_display_year(
        display_year,
        alumni_only=(roster_view == 'alumni'),
        history_mode=history_mode,
    )

    page = request.args.get('page', 1, type=int)
    per_page = 100
    students_pagination = students_query.order_by(Student.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    students = students_pagination.items
    year_id = display_year.id if display_year else None
    student_class_labels = {
        student.id: format_student_class_name(student, year_id) for student in students
    }
    stats = _registrar_counts_for_year(display_year, viewing_archived=viewing_archived)
    selected_year_name = display_year.name if display_year else (
        active_year.name if active_year else 'No Active Year Setup'
    )

    active_teachers = Teacher.query.filter(
        func.upper(Teacher.status) == 'ACTIVE'
    ).order_by(Teacher.first_name.asc(), Teacher.last_name.asc()).all()

    pending_registration_students = []
    if display_year and not viewing_archived and roster_view == 'active':
        pending_registration_students = (
            _students_pending_year_registration(display_year)
            .order_by(Student.last_name.asc(), Student.first_name.asc())
            .all()
        )
        for pending_student in pending_registration_students:
            student_class_labels[pending_student.id] = format_student_class_name(
                pending_student, year_id,
            )

    roster_folder_ctx = _build_registrar_roster_folders(
        display_year,
        alumni_only=(roster_view == 'alumni'),
        viewing_archived=viewing_archived,
        search_class=search_class,
        search_student=search_student,
        open_student_id=request.args.get('open_student_id', type=int),
    )

    prev_display_year, next_display_year = adjacent_academic_years(display_year, years)
    year_nav_extra = {}
    if roster_view == 'alumni':
        year_nav_extra['view'] = 'alumni'
    if search_class:
        year_nav_extra['search_class'] = search_class
    if search_student:
        year_nav_extra['search_student'] = search_student
    prev_year_url = (
        url_for('registrar_dashboard', academic_year_id=prev_display_year.id, **year_nav_extra)
        if prev_display_year else None
    )
    next_year_url = (
        url_for('registrar_dashboard', academic_year_id=next_display_year.id, **year_nav_extra)
        if next_display_year else None
    )

    return {
        'form': form,
        'students': students,
        'student_class_labels': student_class_labels,
        'students_pagination': students_pagination,
        'suggested_student_id': suggested_student_id,
        'classes': classes,
        'classes_by_division': group_classes(all_class_rows),
        'registration_class_groups': registration_class_groups,
        'years': years,
        'all_years': years,
        'active_year': active_year,
        'display_year': display_year,
        'viewing_archived': viewing_archived,
        'roster_view': roster_view,
        'counts': stats,
        'stats': stats,
        'search_class': search_class,
        'selected_year': selected_year_name,
        'selected_year_name': selected_year_name,
        'homeroom_matrix': _build_homeroom_matrix(),
        'class_division_labels': {
            klass.id: division_label_for_class(klass) for klass in all_class_rows
        },
        'active_teachers': active_teachers,
        'year_lifecycle_status': _build_registrar_year_lifecycle_status(display_year, active_year),
        'pending_registration_students': pending_registration_students,
        'prev_display_year': prev_display_year,
        'next_display_year': next_display_year,
        'prev_year_url': prev_year_url,
        'next_year_url': next_year_url,
        **roster_folder_ctx,
    }


def persist_student_guardian_name(student, form=None, raw=None):
    """Write Student.guardian_name from POST, WTForms, or an explicit value.

    Prefer the raw request so registrar HTML inputs are not dropped when the
    WTForms field exists but was not bound to the posted name.
    """
    if not student:
        return None
    if raw is None and has_request_context() and request.form is not None and 'guardian_name' in request.form:
        raw = request.form.get('guardian_name')
    elif raw is None and form is not None and getattr(form, 'guardian_name', None) is not None:
        raw = form.guardian_name.data
    if raw is None:
        return getattr(student, 'guardian_name', None)
    student.guardian_name = (str(raw).strip() if raw else '') or None
    return student.guardian_name


def persist_student_portal_contact_fields(student):
    """Copy registrar HTML phone/address fields onto the student portal user.

    These inputs live on the registrar form but are not WTForms fields, so they
    were previously dropped on save.
    """
    if not student or not has_request_context() or request.form is None:
        return
    user = student.user or (db.session.get(User, student.user_id) if student.user_id else None)
    if not user:
        return
    if 'telephone_number' in request.form:
        phone = (request.form.get('telephone_number') or '').strip()
        user.telephone_number = phone[:20] if phone else None
    if 'home_address' in request.form:
        address = (request.form.get('home_address') or '').strip()
        user.home_address = address[:255] if address else None


def apply_student_form_to_record(student, form, *, registrar_name, registration_type=None):
    """Persist RegisterStudentForm fields onto a Student record."""
    klass_id = form.klass.data or None
    academic_year_id = form.academic_year.data or None
    if not academic_year_id:
        active_year = get_active_academic_year()
        academic_year_id = active_year.id if active_year else None

    registration_fee_value = parse_currency_amount_optional(form.registration_fees.data)

    student.first_name = form.first_name.data.strip()
    student.last_name = form.last_name.data.strip()
    student.dob = form.dob.data
    student.gender = form.gender.data
    if has_request_context() and request.form is not None and 'parent_email' in request.form:
        student.parent_email = (request.form.get('parent_email') or '').strip() or None
    elif getattr(form, 'parent_email', None) is not None and (form.parent_email.data or '').strip():
        student.parent_email = form.parent_email.data.strip()
    student.parent_phone = (getattr(form, 'parent_phone', None) and (form.parent_phone.data or '').strip()) or None
    persist_student_guardian_name(student, form)
    if getattr(form, 'parent_report_pin', None) and (form.parent_report_pin.data or '').strip():
        if not set_parent_report_pin(student, form.parent_report_pin.data):
            raise ValueError('Parent report PIN must be 4–6 digits.')
    student.klass_id = klass_id
    student.academic_year_id = academic_year_id
    student.level = form.level.data
    student.registrar = registrar_name
    student.registration_fees = registration_fee_value
    student.status = student.status or 'ACTIVE'

    if registration_type:
        student.registration_type = registration_type

    if klass_id:
        assigned_class = db.session.get(Class, klass_id)
        if assigned_class:
            student.grade_level = assigned_class.grade_level
            division = division_label_for_class(assigned_class)
            if division and division != 'Other':
                student.level = division

    if form.student_id.data:
        student.student_id = form.student_id.data.strip()

    if student.student_id:
        student.student_id_code = student.student_id

    ensure_student_secure_qr_token(student)
    ensure_parent_report_token(student)
    link_student_parent_account(student)

    year = db.session.get(AcademicYear, academic_year_id) if academic_year_id else None
    _sync_student_id_card(student, academic_year=year)
    persist_student_portal_contact_fields(student)

    return registration_fee_value, academic_year_id


@app.route('/admin/repair-alumni', methods=['POST'])
@login_required
def admin_repair_alumni_bulk():
    """Mark misclassified Grade 12 students in the active year as alumni."""
    if normalize_role(current_user) not in ('admin', 'registrar', 'principal'):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    active_year = get_active_academic_year()
    if not active_year:
        flash('No active academic year configured.', 'warning')
        return redirect(url_for('login'))

    candidates = Student.query.filter(
        Student.academic_year_id == active_year.id,
        Student.klass_id.isnot(None),
    ).all()

    repaired = 0
    try:
        for student in candidates:
            if repair_misclassified_alumni(student):
                repaired += 1
        db.session.commit()
        if repaired:
            flash(f'Repaired {repaired} misclassified alumni record(s).', 'success')
        else:
            flash('No misclassified Grade 12 students found in the active year.', 'info')
    except Exception as exc:
        db.session.rollback()
        flash(f'Alumni repair failed: {exc}', 'danger')

    return redirect(url_for('dashboard', **registrar_dashboard_redirect_kwargs()))


@app.route('/registrar/class/<int:class_id>/reassign-teacher', methods=['POST'])
@login_required
def registrar_reassign_class_teacher(class_id):
    if normalize_role(current_user) not in {'admin', 'principal', 'registrar'}:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard', **registrar_dashboard_redirect_kwargs()))

    teacher_id = request.form.get('teacher_id', type=int)
    try:
        reassign_class_homeroom(class_id, teacher_id)
        db.session.commit()
        flash('Homeroom teacher assignment updated.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Could not update homeroom teacher: {exc}', 'danger')

    return redirect(url_for('dashboard', **registrar_dashboard_redirect_kwargs()))


@app.route('/register-student', methods=['GET', 'POST'])
@app.route('/registrar/dashboard', methods=['GET', 'POST'], endpoint='registrar_dashboard')
@login_required
def register_student():
    # 1. Authorize user permissions (aliases like registry → registrar)
    if canonical_role(current_user) not in {"admin", "principal", "registrar"}:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    form = RegisterStudentForm()
    context = build_registrar_dashboard_context(form=form)

    # 4. Handle POST requests: Process form submissions
    if request.method == 'POST':
        if not form.validate():
            flash("Please correct the highlighted errors before saving.", "danger")
            return render_template('dashboard_registrar.html', **context)

        try:
            academic_year = None
            if form.academic_year.data:
                academic_year = db.session.get(AcademicYear, form.academic_year.data)
            if not academic_year:
                academic_year = get_active_academic_year()

            is_returning = bool(form.is_returning.data)
            ok, id_error, existing_student, student_id_value = validate_student_id_for_registration(
                form.student_id.data,
                form,
                academic_year,
                is_returning=is_returning,
            )

            if not ok:
                flash(id_error, 'danger')
                if existing_student and not (
                    is_returning or _same_student_identity(existing_student, form)
                ):
                    flash(
                        'Go back to Step 1 and search by their portal email or student ID.',
                        'info',
                    )
                form.student_id.errors.append(id_error)
                context['form'] = form
                return render_template('dashboard_registrar.html', **context)

            if existing_student:
                student = existing_student
                apply_returning_retention_class(student, form)
                registration_fee_value, academic_year_id = apply_student_form_to_record(
                    student,
                    form,
                    registrar_name=current_user.full_name,
                    registration_type='Returning',
                )
                student.student_id = existing_student.student_id or student_id_value
                activate_student_registration(student, actor_id=current_user.id)
                flash(
                    f"Returning student {student.full_name} re-registered for "
                    f"{academic_year.name if academic_year else 'the selected academic year'} successfully.",
                    "success",
                )
            else:
                student = Student(
                    student_id=student_id_value,
                    registration_type='New',
                )
                registration_fee_value, academic_year_id = apply_student_form_to_record(
                    student,
                    form,
                    registrar_name=current_user.full_name,
                )
                student.student_id = student_id_value
                db.session.add(student)
                flash(
                    f"New student {student.first_name} {student.last_name} registered successfully "
                    f"(ID: {student_id_value}).",
                    "success",
                )

            if form.photo.data and hasattr(form.photo.data, 'filename') and form.photo.data.filename:
                photo_file = form.photo.data
                filename = secure_filename(photo_file.filename)
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
                filename = f"{timestamp}_{filename}"

                upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'students')
                os.makedirs(upload_dir, exist_ok=True)

                file_path = os.path.join(upload_dir, filename)
                photo_file.save(file_path)

                student.photo = os.path.join('uploads', 'students', filename).replace('\\', '/')
                student.photo_filename = filename

            issued_password = None
            if form.email.data:
                portal_user = link_student_portal_from_form(
                    student,
                    form.email.data,
                    password=form.password.data or None,
                    must_change_password=True,
                )
                if portal_user:
                    issued_password = getattr(portal_user, '_issued_initial_password', None)
                    if issued_password:
                        flash(
                            "Student portal account created. Print the credential slip and give it to the student.",
                            "success",
                        )
                    else:
                        flash(
                            "Student portal account linked. No new password was issued.",
                            "info",
                        )
                else:
                    flash(
                        f"Could not link portal account for '{form.email.data}'. "
                        "That email may already belong to another student account.",
                        "warning",
                    )

            persist_student_portal_contact_fields(student)

            registration_payment = None
            offer_receipt = False
            if registration_fee_value > 0 and academic_year_id:
                db.session.flush()
                registration_payment, offer_receipt = collect_registration_fee_payment(
                    student,
                    form,
                    academic_year_id,
                    registration_fee_value,
                    update_existing=False,
                )

            _sync_student_id_card(student, academic_year=academic_year)
            db.session.commit()
            if issued_password:
                stash_registrar_credential_password(student.id, issued_password)
                return redirect(url_for(
                    'print_registrar_credential_slip',
                    student_id=student.id,
                ))
            if offer_receipt and registration_payment:
                return redirect(url_for(
                    'print_registrar_registration_receipt',
                    payment_id=registration_payment.id,
                ))
            return redirect(url_for('dashboard', **registrar_dashboard_redirect_kwargs()))

        except Exception as e:
            db.session.rollback()
            flash(f"Could not save student record: {str(e)}", "danger")

    return render_template('dashboard_registrar.html', **context)


@app.route('/registrar/students/<int:student_id>/print', methods=['GET'], endpoint='print_registrar_student')
@login_required
def print_registrar_student(student_id):
    """Printable official student file from a registrar class/student folder."""
    if canonical_role(current_user) not in {"admin", "principal", "registrar"}:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    student = Student.query.get_or_404(student_id)
    display_year, _active_year, _years, _archived = resolve_dashboard_academic_year(
        session_key=REGISTRAR_YEAR_SESSION_KEY,
    )
    year_id = display_year.id if display_year else student.academic_year_id
    return render_template(
        'registrar_student_print.html',
        student=student,
        display_year=display_year,
        class_label=format_student_class_name(student, year_id),
        printed_by=current_user.full_name or current_user.email,
        printed_at=datetime.now(timezone.utc),
        default_avatar_url=default_static_photo_url(),
    )


@app.route('/registrar/payments/<int:payment_id>/receipt', methods=['GET'], endpoint='print_registrar_registration_receipt')
@login_required
def print_registrar_registration_receipt(payment_id):
    """Printable official registration-fee receipt for registrar, principal, and admin."""
    if canonical_role(current_user) not in {"admin", "principal", "registrar"}:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    payment = StudentPayment.query.get_or_404(payment_id)
    if not _is_registration_fee_payment(payment):
        flash("That payment is not a registration fee receipt.", "warning")
        return redirect(url_for('dashboard', **registrar_dashboard_redirect_kwargs()))
    return _render_registrar_registration_receipt(payment)


@app.route('/registrar/students/<int:student_id>/credential-slip', methods=['GET'], endpoint='print_registrar_credential_slip')
@login_required
def print_registrar_credential_slip(student_id):
    """Printable portal login slip. Initial password is shown once from session."""
    if canonical_role(current_user) not in {"admin", "principal", "registrar"}:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    student = Student.query.get_or_404(student_id)
    portal_user = student.user
    issued_password = pop_registrar_credential_password(student.id)
    must_change = bool(getattr(portal_user, 'must_change_password', False)) if portal_user else False
    if issued_password:
        password_state = 'issued'
    elif not portal_user:
        password_state = 'no_portal'
    elif must_change:
        password_state = 'issued_once'
    else:
        password_state = 'already_set'

    display_year, _active_year, _years, _archived = resolve_dashboard_academic_year(
        session_key=REGISTRAR_YEAR_SESSION_KEY,
    )
    year_id = display_year.id if display_year else student.academic_year_id
    year = display_year or student.academic_year
    receipt_payment = find_registration_fee_payment(student, year_id) if year_id else None
    login_username = (
        (portal_user.username if portal_user else None)
        or student.student_id
        or student.student_id_code
    )
    return render_template(
        'registrar_credential_slip.html',
        student=student,
        portal_user=portal_user,
        display_year=year,
        class_label=format_student_class_name(student, year_id),
        login_username=login_username,
        issued_password=issued_password,
        password_state=password_state,
        receipt_payment=receipt_payment,
        printed_by=current_user.full_name or current_user.email,
        printed_at=datetime.now(timezone.utc),
        default_avatar_url=default_static_photo_url(),
    )


@app.route('/business/payments/<int:payment_id>/receipt', methods=['GET'], endpoint='print_business_payment_receipt')
@login_required
def print_business_payment_receipt(payment_id):
    access = _require_business_dashboard_access()
    if access:
        return access
    payment = StudentPayment.query.get_or_404(payment_id)
    if _is_registration_fee_payment(payment):
        return _render_registrar_registration_receipt(payment)
    student = db.session.get(Student, payment.student_id)
    year = db.session.get(AcademicYear, payment.academic_year_id)
    financials = build_student_financials(student, year) if student and year else {}
    return render_template(
        'business_payment_receipt.html',
        payment=payment,
        student=student,
        display_year=year,
        class_label=format_student_class_name(student, payment.academic_year_id) if student else '—',
        collected_by=current_user.full_name or current_user.email,
        remaining=financials.get('tuition_balance', 0),
        receipt_no='SP-{}'.format(payment.id),
    )


REGISTRAR_DOC_ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf'}
REGISTRAR_DOC_MAX_BYTES = 12 * 1024 * 1024
ID_CARD_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
ID_CARD_MAX_BYTES = 8 * 1024 * 1024
ID_PHOTO_OUTPUT_PX = 800
ID_PHOTO_WHITE = (255, 255, 255)
ID_PHOTO_REMBG_FAIL_MESSAGE = 'Background could not be removed — install/check rembg'
ID_PHOTO_REMBG_LOADING_MESSAGE = (
    'Background removal is still starting. Wait, then tap Save ID files again — '
    'the outdoor photo was not saved as the ID.'
)
ID_PHOTO_SKIP_REMBG_WARNING = (
    'Background removal is turned off (SKIP_REMBG). Outdoor photos will keep their backdrop.'
)
ID_PHOTO_PRINT_STILL_PROCESSING = (
    'Photo still processing — Save ID or wait. Outdoor backdrops cannot be cleaned by Print alone.'
)
_REMBG_SESSION = None
_REMBG_UNAVAILABLE = False
_REMBG_LOAD_THREAD = None
_REMBG_LOAD_BOX = []
_REMBG_LOCK = None
_REMBG_LOAD_TIMEOUT_SECONDS = 120  # wait once on Save ID; preload starts this at boot
_REMBG_CUTOUT_TIMEOUT_SECONDS = 90  # warm session; fail the save rather than store outdoor
_PRINT_REMBG_TIMEOUT_SECONDS = 12  # print/PDF must not wait on rembg for a class
_PRINT_REMBG_MAX_PHOTOS = 2  # at most two outdoor rembg attempts per print/PDF request
_U2NET_MIN_BYTES = 150 * 1024 * 1024  # complete u2net / u2net_human_seg is ~176MB
_ID_PHOTO_ALPHA_CLEAR = 40  # fully transparent; never hard-cut interior dark skin
_ID_PHOTO_ALPHA_OPAQUE = 180  # at/above this, keep the person fully
_ID_PHOTO_ERODE_PX = 0  # do not eat into the face; 0–1px outer edge only if ever needed
_ID_PHOTO_FEATHER_PX = 1.5  # 1–2px Gaussian onto white only
_ID_PHOTO_DENOISE_MIX = 0.0  # keep rembg RGB; median/L-blur posterizes dark skin
_ID_PHOTO_UNSHARP_PERCENT = 70
_ID_PHOTO_JPEG_QUALITY = 92
_ID_PHOTO_WHITE_LUMA = 245  # JPEG-safe studio white; 255 would keep letterbox as "subject"
_ID_PHOTO_SUBJECT_FRINGE = 0.01  # tiny inset so rembg halo is not kept as gutters
_ID_PHOTO_HEAD_SHOULDERS_RATIO = 1.22  # H&S window height / bust width before cover-by-width
_ID_PHOTO_HEADROOM_FRAC = 0.10  # 8–12% of square side above the crown; never put bbox.top at y=0


def _require_registrar_office():
    if canonical_role(current_user) not in {"admin", "principal", "registrar"}:
        flash("Unauthorized access.", "danger")
        return False
    return True


def _registrar_office_denied_redirect():
    if getattr(current_user, "is_authenticated", False):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


def _registrar_office_guard():
    """None when registrar/admin/principal; otherwise a redirect response."""
    if _require_registrar_office():
        return None
    return _registrar_office_denied_redirect()


def _require_staff_id_office():
    """Staff/teacher ID cards: registrar office plus VPI and VPA, who manage staff records."""
    if canonical_role(current_user) not in {"admin", "principal", "registrar", "vpi", "vpa"}:
        flash("Unauthorized access.", "danger")
        return False
    return True


def _staff_id_office_guard():
    """None when authorized for staff ID cards; otherwise a redirect response."""
    if _require_staff_id_office():
        return None
    return _registrar_office_denied_redirect()


def _registrar_student_folder_redirect(student_id):
    return redirect(
        url_for('dashboard', **registrar_dashboard_redirect_kwargs(open_student_id=student_id))
        + f'#student-folder-{int(student_id)}'
    )


def _default_id_expiration_date(academic_year=None):
    """ID cards expire at the academic-year end, or 31 July of that session."""
    if academic_year and getattr(academic_year, 'end_date', None):
        return academic_year.end_date
    span = parse_academic_year_span(
        getattr(academic_year, 'name', None) if academic_year else None
    )
    if span:
        return date(span[1], 7, 31)
    start = getattr(academic_year, 'start_date', None) if academic_year else None
    if start:
        return date(start.year + 1, 7, 31)
    today = datetime.now(timezone.utc).date()
    year = today.year + 1 if today.month >= 8 else today.year
    return date(year, 7, 31)


def _id_photo_resample():
    return getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', Image.LANCZOS)


def _downscale_id_photo(img, max_side=1800):
    """Keep rembg/crop work at print-enough resolution without huge originals."""
    width, height = img.size
    longest = max(width, height)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    return img.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        _id_photo_resample(),
    )


def _color_close(left, right, tol=32):
    return all(abs(a - b) <= tol for a, b in zip(left[:3], right[:3]))


def _looks_like_skin_rgb(rgb):
    red, green, blue = rgb[:3]
    return (
        red > 95 and green > 40 and blue > 20
        and red > green and red > blue
        and abs(red - green) > 15
        and (max(red, green, blue) - min(red, green, blue)) > 15
    )


def _corner_patch_uniform(img, xy, radius=10, spread=48):
    width, height = img.size
    x0 = max(0, xy[0] - radius)
    y0 = max(0, xy[1] - radius)
    x1 = min(width, xy[0] + radius + 1)
    y1 = min(height, xy[1] + radius + 1)
    extrema = img.crop((x0, y0, x1, y1)).getextrema()
    if not extrema:
        return False
    channels = extrema if isinstance(extrema[0], tuple) else (extrema,)
    return all((high - low) <= spread for low, high in channels[:3])


def _skip_rembg_requested():
    return (os.environ.get('SKIP_REMBG') or '').strip().lower() in ('1', 'true', 'yes')


def _rembg_lock():
    global _REMBG_LOCK
    import threading
    if _REMBG_LOCK is None:
        _REMBG_LOCK = threading.RLock()
    return _REMBG_LOCK


def _id_photo_needs_background_removal(img):
    """True when this is not already a white-studio ID (outdoor / colored corners)."""
    return not _top_corners_near_white(img)


def _flash_id_photo_notice(message, category='warning'):
    if has_request_context():
        flash(message, category)


def _raise_id_photo_rembg_failure(reason, message=None):
    logger.error(
        'ID photo rembg failed (%s). Not saving an outdoor/busy backdrop as the ID JPEG.',
        reason,
    )
    raise ValueError(message or ID_PHOTO_REMBG_FAIL_MESSAGE)


def _u2net_model_paths(model_name):
    home = os.path.expanduser('~')
    filename = '%s.onnx' % model_name
    return (
        os.path.join(home, '.u2net', filename),
        os.path.join(home, '.rembg', 'models', model_name, filename),
    )


def _u2net_model_status(model_name):
    """complete / incomplete / missing for a rembg ONNX on disk."""
    saw_complete = False
    saw_incomplete = False
    for path in _u2net_model_paths(model_name):
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size >= _U2NET_MIN_BYTES:
            saw_complete = True
        else:
            saw_incomplete = True
    if saw_complete:
        return 'complete'
    if saw_incomplete:
        return 'incomplete'
    return 'missing'


def _preferred_rembg_model_names():
    """Human-focused first. Skip only known-partial ONNX files (missing may download)."""
    preferred = ('u2net_human_seg', 'u2net')
    return tuple(name for name in preferred if _u2net_model_status(name) != 'incomplete')


def _rembg_models_unusable():
    """True only when every preferred model file exists but is a partial download."""
    names = ('u2net_human_seg', 'u2net')
    statuses = [_u2net_model_status(name) for name in names]
    if any(status == 'complete' for status in statuses):
        return False
    if any(status == 'missing' for status in statuses):
        return False
    return True


def _run_rembg_with_timeout(fn, timeout):
    """Run fn in a daemon thread. Returns (status, value) where status is ok/timeout/err."""
    import threading
    box = []

    def _target():
        try:
            box.append(('ok', fn()))
        except (Exception, SystemExit) as exc:
            box.append(('err', exc))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return 'timeout', None
    if not box:
        return 'err', None
    return box[0]


def _disable_rembg(reason):
    """Do not call on timeout. Outdoor photos must error, not fall back forever."""
    global _REMBG_SESSION, _REMBG_UNAVAILABLE
    _REMBG_SESSION = None
    _REMBG_UNAVAILABLE = True
    logger.warning(
        'ID photo rembg disabled (%s). Outdoor/busy backdrops will not be removed.',
        reason,
    )


def _harvest_rembg_load_box():
    """Return a finished session from a load thread that completed after a timeout."""
    global _REMBG_SESSION, _REMBG_LOAD_BOX, _REMBG_LOAD_THREAD
    if _REMBG_SESSION is not None:
        return _REMBG_SESSION
    if not _REMBG_LOAD_BOX:
        return None
    status, value = _REMBG_LOAD_BOX[0]
    if status == 'ok' and value is not None:
        _REMBG_SESSION = value
        logger.info('ID photo rembg session ready.')
        return _REMBG_SESSION
    logger.warning('ID photo rembg session load failed (%s); will retry on the next photo.', value)
    _REMBG_LOAD_BOX = []
    _REMBG_LOAD_THREAD = None
    return None


def _load_rembg_session_sync():
    """Blocking ONNX session create. Prefer u2net_human_seg for outdoor people."""
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    import onnxruntime  # noqa: F401  # rembg sys.exits if this backend cannot load
    from rembg import new_session
    model_names = _preferred_rembg_model_names() or ('u2net_human_seg',)
    last_error = None
    for name in model_names:
        try:
            try:
                session = new_session(model_name=name)
            except TypeError:
                session = new_session(name)
            logger.info('ID photo rembg loaded model %s.', name)
            return session
        except Exception as exc:
            last_error = exc
            logger.warning('ID photo rembg could not load %s (%s).', name, exc)
            continue
    try:
        return new_session()
    except Exception:
        if last_error is not None:
            raise last_error
        raise


def _start_rembg_session_load():
    """Start the daemon ONNX load if needed. Never waits (boot preload)."""
    global _REMBG_LOAD_THREAD, _REMBG_LOAD_BOX
    if _skip_rembg_requested() or _REMBG_UNAVAILABLE:
        return None
    if _REMBG_SESSION is not None:
        return _REMBG_SESSION
    harvested = _harvest_rembg_load_box()
    if harvested is not None:
        return harvested
    import threading
    lock = _rembg_lock()
    with lock:
        if _REMBG_SESSION is not None:
            return _REMBG_SESSION
        harvested = _harvest_rembg_load_box()
        if harvested is not None:
            return harvested
        if _REMBG_LOAD_THREAD is not None and _REMBG_LOAD_THREAD.is_alive():
            return None
        _REMBG_LOAD_BOX = []

        def _target():
            global _REMBG_SESSION
            try:
                session = _load_rembg_session_sync()
                _REMBG_LOAD_BOX.append(('ok', session))
                _REMBG_SESSION = session
                logger.info('ID photo rembg session ready.')
            except (Exception, SystemExit) as exc:
                _REMBG_LOAD_BOX.append(('err', exc))
                logger.warning('ID photo rembg session load failed (%s); will retry.', exc)

        _REMBG_LOAD_THREAD = threading.Thread(target=_target, daemon=True, name='id-photo-rembg-preload')
        _REMBG_LOAD_THREAD.start()
        logger.info(
            'ID photo rembg session loading in background (models: %s).',
            ', '.join(_preferred_rembg_model_names() or ('u2net_human_seg',)),
        )
    return None


def _start_rembg_session_preload():
    """App startup: warm rembg so the first Save ID is not a 2-minute cold start."""
    if _skip_rembg_requested():
        logger.warning('ID photo rembg preload skipped (SKIP_REMBG is set).')
        return
    _start_rembg_session_load()


def _get_rembg_session(wait_seconds=None):
    """Cache one rembg session. Preload at boot; Save ID waits once (default 120s).

    Timeouts do not permanently disable rembg: a late-finishing Windows ONNX load is
    harvested on the next photo instead of silently falling back to outdoor JPEGs.
    """
    if _skip_rembg_requested():
        logger.warning('ID photo rembg skipped (SKIP_REMBG is set).')
        return None
    if _REMBG_UNAVAILABLE:
        return None
    if _REMBG_SESSION is not None:
        return _REMBG_SESSION
    harvested = _harvest_rembg_load_box()
    if harvested is not None:
        return harvested
    _start_rembg_session_load()
    wait = _REMBG_LOAD_TIMEOUT_SECONDS if wait_seconds is None else max(0, int(wait_seconds))
    thread = _REMBG_LOAD_THREAD
    if wait > 0 and thread is not None:
        thread.join(wait)
    harvested = _harvest_rembg_load_box()
    if harvested is not None:
        return harvested
    if thread is not None and thread.is_alive():
        logger.warning(
            'ID photo rembg session still loading after %ss; not disabling — next photo will wait again.',
            wait,
        )
    return None


def _id_photo_alpha_feather_lut():
    """<40 clear, 40–180 ramp, >=180 opaque. Interior holes are filled separately."""
    clear = _ID_PHOTO_ALPHA_CLEAR
    opaque = _ID_PHOTO_ALPHA_OPAQUE
    span = float(max(1, opaque - clear))
    lut = []
    for value in range(256):
        if value < clear:
            lut.append(0)
        elif value >= opaque:
            lut.append(255)
        else:
            lut.append(int(round((value - clear) * 255.0 / span)))
    return lut


def _fill_mask_holes(mask):
    """Fill enclosed transparent regions so dark skin/hair are not punched out."""
    binary = mask.point(lambda pixel: 255 if pixel >= 128 else 0)
    if ImageFilter is not None and hasattr(ImageFilter, 'MaxFilter') and hasattr(ImageFilter, 'MinFilter'):
        # 1px close seals hairline cracks without shrinking the outer silhouette.
        binary = binary.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    if ImageDraw is None or ImageChops is None:
        return binary
    inverted = ImageChops.invert(binary)
    flood = inverted.copy()
    width, height = flood.size
    if width < 2 or height < 2:
        return binary
    for seed in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        try:
            ImageDraw.floodfill(flood, seed, 0)
        except Exception:
            continue
    return ImageChops.lighter(binary, flood)


def _edge_safe_id_photo_matte(alpha, erode_px=_ID_PHOTO_ERODE_PX):
    """Keep interior alpha; threshold and feather only at the silhouette edge."""
    mapped = alpha.point(_id_photo_alpha_feather_lut())
    silhouette = alpha.point(lambda pixel: 255 if pixel >= _ID_PHOTO_ALPHA_CLEAR else 0)
    silhouette = _fill_mask_holes(silhouette)
    erode_px = max(0, min(int(erode_px or 0), 1))
    if erode_px > 0 and ImageFilter is not None and hasattr(ImageFilter, 'MinFilter'):
        silhouette = silhouette.filter(ImageFilter.MinFilter(3))
    interior = silhouette
    if ImageFilter is not None and hasattr(ImageFilter, 'MinFilter'):
        # ~2px inset: face/hair stay fully opaque even when rembg was uncertain.
        interior = silhouette.filter(ImageFilter.MinFilter(5))
    if ImageChops is not None:
        matte = ImageChops.lighter(mapped, interior)
        matte = ImageChops.multiply(matte, silhouette)
    else:
        matte = silhouette
    return silhouette, _feather_id_photo_mask(matte)


def _feather_id_photo_mask(mask, radius=_ID_PHOTO_FEATHER_PX):
    """Soft 1–2px Gaussian onto white only. Do not restore backdrop."""
    if ImageFilter is None or radius <= 0:
        return mask
    return mask.filter(ImageFilter.GaussianBlur(radius=float(radius)))


def _composite_id_cutout_on_white(rgba, alpha_cut=None, erode_px=_ID_PHOTO_ERODE_PX):
    """Paste rembg RGB onto #FFFFFF. Interior dark skin stays; only the edge is matted."""
    rgba = rgba.convert('RGBA')
    red, green, blue, alpha = rgba.split()
    silhouette, soft = _edge_safe_id_photo_matte(alpha, erode_px=erode_px)
    subject_rgb = Image.merge('RGB', (red, green, blue))
    white = Image.new('RGB', rgba.size, ID_PHOTO_WHITE)
    # Stamp outside to white first so the feather samples white, not leftover wall.
    stamped = Image.composite(subject_rgb, white, silhouette)
    return Image.composite(stamped, white, soft)


def _corners_near_white(img, tol=22, radius=8):
    """True when each corner patch is already near #FFFFFF (backdrop gone)."""
    return _listed_corners_near_white(
        img,
        None,
        tol=tol,
        radius=radius,
    )


def _top_corners_near_white(img, tol=22, radius=8):
    """True when the top corners are studio white (processed ID on a white backdrop).

    A forehead-fill crop can put skin in the bottom corners, so all-four-corners
    is too strict for 'already processed' detection.
    """
    rgb = img.convert('RGB')
    width, height = rgb.size
    return _listed_corners_near_white(
        rgb,
        ((1, 1), (width - 2, 1)),
        tol=tol,
        radius=radius,
    )


def _listed_corners_near_white(img, corners, tol=22, radius=8):
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 8 or height < 8:
        return True
    if corners is None:
        corners = (
            (1, 1),
            (width - 2, 1),
            (1, height - 2),
            (width - 2, height - 2),
        )
    for cx, cy in corners:
        x0 = max(0, cx - radius)
        y0 = max(0, cy - radius)
        x1 = min(width, cx + radius + 1)
        y1 = min(height, cy + radius + 1)
        extrema = rgb.crop((x0, y0, x1, y1)).getextrema()
        if not extrema:
            continue
        channels = extrema if isinstance(extrema[0], tuple) else (extrema,)
        if any(low < 255 - tol for low, _high in channels[:3]):
            return False
    return True


def _rembg_session_already_ready():
    """True when a rembg session is in memory. Does not start a 180s ONNX load."""
    if _skip_rembg_requested() or _REMBG_UNAVAILABLE:
        return False
    if _REMBG_SESSION is not None:
        return True
    return _harvest_rembg_load_box() is not None


def _rembg_cutout_rgba(img, disable_on_fail=True, timeout=None, *, load_session=True):
    """RGBA subject matte from rembg. None if rembg is unavailable or times out.

    Timeouts and cutout errors no longer permanently disable rembg — the next photo
    retries. Outdoor photos must not be saved as ID JPEGs when this returns None.
    Print/PDF must pass load_session=False and a short timeout so a cold session
    cannot stall the whole class.
    """
    if load_session:
        session = _get_rembg_session()
    elif _REMBG_SESSION is not None:
        session = _REMBG_SESSION
    else:
        session = _harvest_rembg_load_box()
    if session is None:
        return None
    try:
        from rembg import remove
    except (Exception, SystemExit):
        logger.warning('ID photo rembg import failed during cutout; will retry on the next photo.')
        return None

    source = img.convert('RGB') if img.mode not in ('RGB', 'RGBA') else img
    incoming = BytesIO()
    source.save(incoming, format='PNG')
    payload = incoming.getvalue()

    def _cut():
        cutout = remove(payload, session=session)
        return Image.open(BytesIO(cutout)).convert('RGBA')

    cutout_timeout = _REMBG_CUTOUT_TIMEOUT_SECONDS if timeout is None else timeout
    with _rembg_lock():
        status, value = _run_rembg_with_timeout(_cut, cutout_timeout)
    if status == 'ok' and value is not None:
        return value
    logger.warning(
        'ID photo rembg cutout failed (%s) after %ss; session kept for retry. disable_on_fail=%s',
        status,
        cutout_timeout,
        disable_on_fail,
    )
    return None


def _floodfill_studio_backdrop(img):
    """Last resort: flood a flat studio wall to white. Cannot remove outdoor scenes."""
    if ImageDraw is None:
        return img.convert('RGB')
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 8 or height < 8:
        return rgb
    corners = (
        (1, 1),
        (width - 2, 1),
        (1, height - 2),
        (width - 2, height - 2),
    )
    samples = [rgb.getpixel(point) for point in corners]
    average = tuple(sum(channel[idx] for channel in samples) // 4 for idx in range(3))
    if _looks_like_skin_rgb(average):
        return rgb
    if any(not _color_close(sample, average, 42) for sample in samples):
        return rgb
    if any(not _corner_patch_uniform(rgb, point) for point in corners):
        return rgb
    for point in corners:
        try:
            ImageDraw.floodfill(rgb, point, ID_PHOTO_WHITE, thresh=30)
        except Exception:
            continue
    return rgb


def _replace_id_photo_background(img):
    """White #FFFFFF. Always run rembg unless SKIP_REMBG is set.

    Outdoor / colored-corner photos raise if rembg cannot run. Already-white studio
    photos may use PIL flood-fill as a last-resort helper.
    """
    if _skip_rembg_requested():
        logger.warning(
            'ID photo rembg skipped because SKIP_REMBG is set. size=%s needs_cutout=%s',
            getattr(img, 'size', None),
            _id_photo_needs_background_removal(img),
        )
        _flash_id_photo_notice(ID_PHOTO_SKIP_REMBG_WARNING, 'warning')
        return _floodfill_studio_backdrop(img)

    rgba = _rembg_cutout_rgba(img)
    if rgba is not None:
        result = _composite_id_cutout_on_white(rgba)
        if _corners_near_white(result):
            return result
        logger.info('ID photo corners still not white after rembg; retrying rembg once (same gentle matte).')
        rgba_retry = _rembg_cutout_rgba(img, disable_on_fail=False)
        if rgba_retry is not None:
            result = _composite_id_cutout_on_white(rgba_retry)
        return result
    if _id_photo_needs_background_removal(img):
        thread = _REMBG_LOAD_THREAD
        if thread is not None and thread.is_alive() and not _rembg_session_already_ready():
            _raise_id_photo_rembg_failure(
                'rembg session still loading after wait; corners are not studio white',
                ID_PHOTO_REMBG_LOADING_MESSAGE,
            )
        _raise_id_photo_rembg_failure(
            'rembg unavailable or timed out; corners are not studio white'
        )
    logger.warning(
        'ID photo rembg unavailable; PIL flood-fill last resort on an already-white studio photo. '
        'Install rembg with a complete u2net model, or unset SKIP_REMBG.'
    )
    return _floodfill_studio_backdrop(img)


def _estimate_portrait_focus(img):
    """Skin-tone centroid in the upper 70% — used when a face detector is not installed."""
    rgb = img.convert('RGB')
    sample = rgb.copy()
    sample.thumbnail((160, 160), _id_photo_resample())
    width, height = sample.size
    pixels = sample.load()
    xs = []
    ys = []
    for y in range(max(1, int(height * 0.70))):
        for x in range(width):
            if _looks_like_skin_rgb(pixels[x, y]):
                xs.append(x)
                ys.append(y)
    if len(xs) < 40:
        return None
    xs_sorted = sorted(xs)
    ys_sorted = sorted(ys)
    low = int(len(xs_sorted) * 0.10)
    high = max(low + 1, int(len(xs_sorted) * 0.90))
    trimmed_x = xs_sorted[low:high]
    trimmed_y = ys_sorted[low:high]
    x_span = trimmed_x[-1] - trimmed_x[0]
    y_span = trimmed_y[-1] - trimmed_y[0]
    scale_x = rgb.size[0] / float(width)
    scale_y = rgb.size[1] / float(height)
    # Trimmed mean — do not let outlier skin pixels pull the crop left.
    return (
        (sum(trimmed_x) / len(trimmed_x)) * scale_x,
        (sum(trimmed_y) / len(trimmed_y)) * scale_y,
        max(x_span * scale_x, y_span * scale_y),
    )


def _luma_below_white_mask(rgb, white_threshold=_ID_PHOTO_WHITE_LUMA):
    """255 where Rec. 601 luminance is below studio white. Dark clothes stay subject."""
    return rgb.convert('L').point(lambda pixel: 255 if pixel < white_threshold else 0)


def _subject_bbox(img, white_threshold=_ID_PHOTO_WHITE_LUMA):
    """Bounding box of the person: non-white luma or visible alpha (not 255-exact)."""
    width, height = img.size
    if width < 2 or height < 2:
        return None
    if img.mode in ('RGBA', 'LA'):
        rgba = img.convert('RGBA')
        rgb = Image.merge('RGB', rgba.split()[:3])
        mask = _luma_below_white_mask(rgb, white_threshold)
        alpha = rgba.split()[-1].point(
            lambda pixel: 255 if pixel >= _ID_PHOTO_ALPHA_CLEAR else 0
        )
        if ImageChops is not None:
            mask = ImageChops.lighter(mask, alpha)
        else:
            mask = alpha
    else:
        mask = _luma_below_white_mask(img.convert('RGB'), white_threshold)
    return mask.getbbox()


def _letterbox_on_white_square(img, size=ID_PHOTO_OUTPUT_PX):
    """Scale img to fit inside size×size and paste it centered on white."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    canvas = Image.new('RGB', (size, size), ID_PHOTO_WHITE)
    if width < 1 or height < 1:
        return canvas
    scale = min(size / float(width), size / float(height))
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    if (new_w, new_h) != (width, height):
        rgb = rgb.resize((new_w, new_h), _id_photo_resample())
    canvas.paste(rgb, ((size - new_w) // 2, (size - new_h) // 2))
    return canvas


def _mask_channel_count(mask, value=255):
    hist = mask.histogram()
    if value >= len(hist):
        return 0
    return hist[value]


def _trim_solid_white_margins(img, white_threshold=_ID_PHOTO_WHITE_LUMA):
    """Crop L/R/top/bottom columns that are solid studio white. Ignore rembg/JPEG dust."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 4 or height < 4:
        return rgb
    mask = _luma_below_white_mask(rgb, white_threshold)
    col_allow = max(2, int(height * 0.025))
    row_allow = max(2, int(width * 0.025))

    def col_content(x):
        return _mask_channel_count(mask.crop((x, 0, x + 1, height)))

    def row_content(y):
        return _mask_channel_count(mask.crop((0, y, width, y + 1)))

    x0 = 0
    while x0 < width - 2 and col_content(x0) <= col_allow:
        x0 += 1
    x1 = width
    while x1 > x0 + 2 and col_content(x1 - 1) <= col_allow:
        x1 -= 1
    y0 = 0
    while y0 < height - 2 and row_content(y0) <= row_allow:
        y0 += 1
    y1 = height
    while y1 > y0 + 2 and row_content(y1 - 1) <= row_allow:
        y1 -= 1
    if x1 - x0 < 2 or y1 - y0 < 2:
        return rgb
    return rgb.crop((x0, y0, x1, y1))


def _content_x_span(img, y0, y1, white_threshold=_ID_PHOTO_WHITE_LUMA, min_col_frac=0.18):
    """Left/right of columns in [y0, y1) that are really the person, not a stray speck."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 2:
        return None
    top = max(0, min(height - 1, int(y0)))
    bottom = max(top + 1, min(height, int(y1)))
    band = _luma_below_white_mask(rgb.crop((0, top, width, bottom)), white_threshold)
    band_h = band.size[1]
    need = max(2, int(round(band_h * min_col_frac)))
    left = None
    right = None
    for x in range(width):
        if _mask_channel_count(band.crop((x, 0, x + 1, band_h))) < need:
            continue
        if left is None:
            left = x
        right = x + 1
    if left is None:
        return None
    return left, right


def _content_y_span(img, x0, x1, white_threshold=_ID_PHOTO_WHITE_LUMA, min_row_frac=0.10):
    """Top/bottom of rows in [x0, x1) that are really the person, not a stray speck."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 2:
        return None
    left = max(0, min(width - 1, int(x0)))
    right = max(left + 1, min(width, int(x1)))
    band = _luma_below_white_mask(rgb.crop((left, 0, right, height)), white_threshold)
    band_w = band.size[0]
    need = max(2, int(round(band_w * min_row_frac)))
    top = None
    bottom = None
    for y in range(height):
        if _mask_channel_count(band.crop((0, y, band_w, y + 1))) < need:
            continue
        if top is None:
            top = y
        bottom = y + 1
    if top is None:
        return None
    return top, bottom


def _id_photo_edge_white_frac(img, from_left=True, px=3, white_threshold=_ID_PHOTO_WHITE_LUMA):
    """Fraction of the leftmost or rightmost px columns that are studio white."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 2:
        return 1.0
    n = min(max(1, int(px)), width)
    xs = range(n) if from_left else range(width - 1, width - 1 - n, -1)
    pixels = rgb.load()
    white = 0
    total = 0
    for x in xs:
        for y in range(height):
            red, green, blue = pixels[x, y]
            total += 1
            if (0.299 * red + 0.587 * green + 0.114 * blue) >= white_threshold:
                white += 1
    return white / float(total) if total else 1.0


def _edge_columns_uniformly_white(img, px=3, min_white_frac=0.82):
    """True when either side's 3-pixel strip is mostly leftover studio white."""
    return (
        _id_photo_edge_white_frac(img, True, px) >= min_white_frac
        or _id_photo_edge_white_frac(img, False, px) >= min_white_frac
    )


def _lower_third_side_columns_white(img, px=3, min_white_frac=0.82, white_threshold=_ID_PHOTO_WHITE_LUMA):
    """True when the lower third (shirt/chest) still has white gutters at the sides."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 4:
        return True
    y0 = int(height * 2 / 3.0)
    n = min(max(1, int(px)), width)
    pixels = rgb.load()

    def _side_frac(xs):
        white = 0
        total = 0
        for x in xs:
            for y in range(y0, height):
                red, green, blue = pixels[x, y]
                total += 1
                if (0.299 * red + 0.587 * green + 0.114 * blue) >= white_threshold:
                    white += 1
        return white / float(total) if total else 1.0

    left = _side_frac(range(n))
    right = _side_frac(range(width - 1, width - 1 - n, -1))
    return left >= min_white_frac or right >= min_white_frac


def _lower_third_white_frac(img, white_threshold=_ID_PHOTO_WHITE_LUMA):
    """Fraction of the lower third that is studio white."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 4:
        return 1.0
    y0 = int(height * 2 / 3.0)
    band = rgb.crop((0, y0, width, height))
    hist = band.convert('L').histogram()
    white = sum(hist[int(white_threshold):]) if hist else 0
    total = width * max(1, height - y0)
    return white / float(total)


def _widest_dense_row_span(img, y0, y1, white_threshold=_ID_PHOTO_WHITE_LUMA, min_run=8, min_fill=0.35):
    """Shoulder/chest span: widest row whose first-to-last content is actually filled.

    First-to-last keeps a white shirt between two sleeves. A density floor
    ignores a left speck plus a right speck pretending to be full width.
    Returns (left, right, y) or None.
    """
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 2:
        return None
    top = max(0, min(height - 1, int(y0)))
    bottom = max(top + 1, min(height, int(y1)))
    band = _luma_below_white_mask(rgb.crop((0, top, width, bottom)), white_threshold)
    pixels = band.load()
    band_h, band_w = band.size[1], band.size[0]
    candidates = []
    for y in range(band_h):
        left = None
        right = None
        filled = 0
        for x in range(band_w):
            if pixels[x, y] < 128:
                continue
            filled += 1
            if left is None:
                left = x
            right = x + 1
        if left is None:
            continue
        span_w = right - left
        if span_w < min_run or filled / float(span_w) < min_fill:
            continue
        candidates.append((span_w, top + y, left, right))
    if not candidates:
        return None
    max_w = max(item[0] for item in candidates)
    need = max_w * 0.85
    best = None
    for span_w, row_y, left, right in candidates:
        if span_w < need:
            continue
        if best is None or row_y < best[2]:
            best = (left, right, row_y)
    return best


def _widest_row_x_span(img, y0, y1, white_threshold=_ID_PHOTO_WHITE_LUMA, min_run=4):
    """Shoulder width from the single widest content row (not the union of a tall band)."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 2:
        return None
    top = max(0, min(height - 1, int(y0)))
    bottom = max(top + 1, min(height, int(y1)))
    band = _luma_below_white_mask(rgb.crop((0, top, width, bottom)), white_threshold)
    pixels = band.load()
    band_h, band_w = band.size[1], band.size[0]
    best = None
    best_w = 0
    for y in range(band_h):
        left = None
        right = None
        for x in range(band_w):
            if pixels[x, y] < 128:
                continue
            if left is None:
                left = x
            right = x + 1
        if left is None:
            continue
        span_w = right - left
        if span_w < min_run:
            continue
        if span_w > best_w:
            best_w = span_w
            best = (left, right)
    return best


def _cover_subject_keep_head(img, size=ID_PHOTO_OUTPUT_PX):
    """Fill size×size by WIDTH only; keep headroom above the crown; extra from the bottom."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 1 or height < 1:
        return Image.new('RGB', (size, size), ID_PHOTO_WHITE)
    scale = size / float(width)
    new_w = size
    new_h = max(1, int(round(height * scale)))
    if (new_w, new_h) != (width, height):
        rgb = rgb.resize((new_w, new_h), _id_photo_resample())
        width, height = new_w, new_h
    bbox = _subject_bbox(rgb)
    crown = bbox[1] if bbox else 0
    headroom = int(round(size * _ID_PHOTO_HEADROOM_FRAC))
    pad_t = max(0, headroom - int(crown))
    if pad_t:
        padded = Image.new('RGB', (width, height + pad_t), ID_PHOTO_WHITE)
        padded.paste(rgb, (0, pad_t))
        rgb = padded
        width, height = rgb.size
    if height >= size:
        return rgb.crop((0, 0, size, size))
    # Rare landscape leftover: pin to top. Do not crop L/R (that re-opens white pillars).
    canvas = Image.new('RGB', (size, size), ID_PHOTO_WHITE)
    canvas.paste(rgb, (0, 0))
    return canvas


def _bust_width_box(img):
    """Crop box whose WIDTH is the shoulders — not the forehead, not full-body hips."""
    rgb = _trim_solid_white_margins(img)
    width, height = rgb.size
    if width < 2 or height < 2:
        return rgb, None
    bbox = _subject_bbox(rgb)
    if not bbox:
        span = _content_x_span(rgb, 0, height)
        if span is None:
            return rgb, None
        return rgb, (span[0], 0, span[1], height)
    _x0, y0, _x1, y1 = bbox
    subj_h = max(1, y1 - y0)
    subj_w = max(1, _x1 - _x0)
    # Full-body cutouts are widest at the hips. Guess H&S width from the upper body.
    guess_w = min(subj_w, max(8, int(round(subj_h * 0.42))))
    hs_bottom = min(y1, y0 + max(8, int(round(guess_w * 1.25))))
    shoulder_top = y0 + int((hs_bottom - y0) * 0.38)
    span = _widest_row_x_span(rgb, shoulder_top, hs_bottom)
    if span is None:
        span = _content_x_span(rgb, shoulder_top, hs_bottom, min_col_frac=0.15)
    if span is None:
        span = _content_x_span(rgb, y0, hs_bottom, min_col_frac=0.12)
    if span is None:
        span = _content_x_span(rgb, 0, height)
    if span is None:
        span = (_x0, _x1)
    return rgb, (span[0], y0, span[1], y1)


def _subject_fill_box(img):
    """Tight person box after solid-white trim (no rembg dust inflating the width)."""
    _src, box = _bust_width_box(img)
    return box


def _crop_id_square_fill(img, mid_x, crop_top, side):
    """Shoulder-width square: shift L/R (no side pillars); pad white above/below, never clip the crown."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    if width < 2 or height < 2:
        return rgb
    side = max(2, int(round(side)))
    # Never shrink the square to the source height — that would put the crown at y=0.
    if side > width:
        side = max(2, width)
        left = 0
    else:
        left = int(round(mid_x - side / 2.0))
        left = max(0, min(left, width - side))
    top = int(round(crop_top))
    pad_t = max(0, -top)
    pad_b = max(0, top + side - height)
    if pad_t or pad_b:
        canvas = Image.new('RGB', (width, height + pad_t + pad_b), ID_PHOTO_WHITE)
        canvas.paste(rgb, (0, pad_t))
        rgb = canvas
        width, height = rgb.size
        top += pad_t
    top = max(0, min(top, max(0, height - side)))
    return rgb.crop((left, top, left + side, top + side))


def _crop_subject_width_square(rgb, x0, x1, top):
    """1:1 crop whose width is the shoulders. Pad white above the crown; never pad L/R."""
    rgb = rgb.convert('RGB')
    side = max(2, int(round(float(x1) - float(x0))))
    mid_x = (float(x0) + float(x1)) / 2.0
    return _crop_id_square_fill(rgb, mid_x, top, side)


def _fit_subject_on_white_square(img, size=ID_PHOTO_OUTPUT_PX):
    """800×800 head-and-shoulders: shoulder-width square, headroom above the crown, chest at bottom.

    Trim white, take the subject, set WIDTH from the widest dense row (shoulders,
    including a white shirt between sleeves). Start the square 8–12% of the side
    above the silhouette top. If that is off-canvas, pad white above — never clip.
    """
    rgb = _trim_solid_white_margins(img)
    width, height = rgb.size
    if width < 2 or height < 2:
        return Image.new('RGB', (size, size), ID_PHOTO_WHITE)
    if _id_photo_already_usable_hs(img.convert('RGB') if img.mode != 'RGB' else img):
        src = img.convert('RGB')
        if src.size != (size, size):
            src = src.resize((size, size), _id_photo_resample())
        return src
    bbox = _subject_bbox(rgb)
    if bbox:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    else:
        x0, y0, x1, y1 = 0.0, 0.0, float(width), float(height)
    span_x = _content_x_span(rgb, y0, y1, min_col_frac=0.12)
    if span_x:
        x0, x1 = float(span_x[0]), float(span_x[1])
    span_y = _content_y_span(rgb, x0, x1, min_row_frac=0.10)
    if span_y:
        y0, y1 = float(span_y[0]), float(span_y[1])
    hit = _widest_dense_row_span(rgb, y0, y1)
    if hit:
        x0, x1 = float(hit[0]), float(hit[1])
    fringe = max(0.0, (x1 - x0) * _ID_PHOTO_SUBJECT_FRINGE)
    x0 += fringe
    x1 -= fringe
    if x1 - x0 < 2:
        x0, x1 = 0.0, float(width)

    out = None
    for _attempt in range(5):
        if x1 - x0 < 2:
            break
        side = max(2.0, x1 - x0)
        # Always start above the crown. Never place bbox.top at y=0 of the square.
        top = y0 - side * _ID_PHOTO_HEADROOM_FRAC
        square = _crop_subject_width_square(rgb, x0, x1, top)
        out = square.resize((size, size), _id_photo_resample())
        if not _lower_third_side_columns_white(out) and not _id_photo_is_face_only_square(out):
            return out
        pad = max(2.0, (x1 - x0) * 0.04)
        x0 += pad
        x1 -= pad
        if x1 - x0 < 8:
            break
    covered = _cover_subject_keep_head(rgb, size)
    if out is None or _id_photo_is_face_only_square(out) or _lower_third_side_columns_white(out):
        return covered
    return out


def _crop_square_centered(img, center_x, center_y, side):
    """Crop a square centered on a point. Pad with white if the box hangs off the photo."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    side = max(2, int(side))
    left = int(round(center_x - side / 2.0))
    top = int(round(center_y - side / 2.0))
    pad_l = max(0, -left)
    pad_t = max(0, -top)
    pad_r = max(0, left + side - width)
    pad_b = max(0, top + side - height)
    if pad_l or pad_t or pad_r or pad_b:
        canvas = Image.new('RGB', (width + pad_l + pad_r, height + pad_t + pad_b), ID_PHOTO_WHITE)
        canvas.paste(rgb, (pad_l, pad_t))
        rgb = canvas
        left += pad_l
        top += pad_t
    return rgb.crop((left, top, left + side, top + side))


def _square_id_crop(img, focus=None):
    """Head-and-shoulders square from silhouette/bust width (no face-only zoom)."""
    src, box = _bust_width_box(img)
    width, height = src.size
    min_side = min(width, height)
    if min_side < 2:
        return src
    if box:
        x0, y0, x1, _y1 = box
        box_w = max(1.0, float(x1 - x0))
        mid_x = (x0 + x1) / 2.0
        inset = box_w * _ID_PHOTO_SUBJECT_FRINGE
        side = max(2.0, box_w - 2.0 * inset)
        return _crop_id_square_fill(src, mid_x, y0 - side * _ID_PHOTO_HEADROOM_FRAC, side)
    if focus:
        center_x, center_y, spread = focus
        side = int(spread * 3.15) if spread else min_side
        side = max(int(min_side * 0.55), min(side, min_side))
        return _crop_id_square_fill(src, center_x, center_y - side / 2.0, side)
    return _crop_id_square_fill(src, width / 2.0, (height - min_side) / 2.0, min_side)


def _id_photo_nonwhite_mask(rgb, white_threshold=248):
    """L mask of the person after the white cutout (backdrop stays 0)."""
    red, green, blue = rgb.split()
    darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
    return darkest.point(lambda pixel: 255 if pixel < white_threshold else 0)


def _histogram_percentile(hist, pct):
    """Return the intensity at percentile pct from a 256-bin histogram."""
    total = sum(hist)
    if total < 1:
        return None
    need = total * (max(0.0, min(100.0, float(pct))) / 100.0)
    seen = 0
    for value, count in enumerate(hist):
        seen += count
        if seen >= need:
            return value
    return 255


def _id_photo_skin_like_mask(rgb, subject_mask):
    """Skin-like subject pixels, including dark skin in shadow. Hair (dark + low chroma) is out."""
    hsv = rgb.convert('HSV')
    hue, sat, val = hsv.split()
    red, green, blue = rgb.split()
    # PIL HSV hue is 0–255. Skin stays in red–orange (wraps through deep red).
    hue_ok = hue.point(lambda pixel: 255 if pixel <= 34 or pixel >= 238 else 0)
    sat_ok = sat.point(lambda pixel: 255 if 22 <= pixel <= 200 else 0)
    val_ok = val.point(lambda pixel: 255 if pixel >= 16 else 0)
    # Black/brown hair is dark and nearly neutral; shadowed skin keeps warm chroma.
    chroma = ImageChops.subtract(
        ImageChops.lighter(ImageChops.lighter(red, green), blue),
        ImageChops.darker(ImageChops.darker(red, green), blue),
    )
    chroma_ok = chroma.point(lambda pixel: 255 if pixel >= 12 else 0)
    # Deepest shadows can be V<30; require extra warm chroma so hair stays out.
    deep_ok = ImageChops.lighter(
        val.point(lambda pixel: 255 if pixel >= 30 else 0),
        chroma.point(lambda pixel: 255 if pixel >= 18 else 0),
    )
    not_hair = ImageChops.lighter(
        val.point(lambda pixel: 255 if pixel >= 28 else 0),
        sat.point(lambda pixel: 255 if pixel >= 42 else 0),
    )
    # Skin is warm: red leads green (allow a 2-count tie for underexposure).
    not_cool = ImageChops.subtract(green, red).point(lambda pixel: 0 if pixel > 2 else 255)
    mask = subject_mask
    for layer in (hue_ok, sat_ok, val_ok, chroma_ok, deep_ok, not_hair, not_cool):
        mask = ImageChops.multiply(mask, layer)
    if ImageFilter is not None:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=1.1))
        mask = ImageChops.multiply(mask, subject_mask)
    return mask


def _studio_even_light_lut(p20, p50, p90, gap):
    """Identity. Shadow-lift posterized dark skin into brown blocks; keep rembg RGB."""
    return list(range(256))


def _studio_even_light_id_photo(img):
    """No-op: original rembg RGB is kept. Shadow-lift / L-blur spoiled portraits."""
    if Image is None:
        return img
    return img.convert('RGB')


def _id_photo_inset_mask(mask, px=1):
    """Erode the denoise/deband mask so white does not bleed into the silhouette."""
    if ImageFilter is None or px < 1 or not hasattr(ImageFilter, 'MinFilter'):
        return mask
    inset = mask
    for _ in range(max(1, min(int(px), 3))):
        inset = inset.filter(ImageFilter.MinFilter(3))
    return inset


def _refine_id_photo_surface(img):
    """No-op. Median + dark-region L-blur posterized skin; keep rembg RGB."""
    if Image is None:
        return img
    return img.convert('RGB')


def _finish_id_portrait(img):
    """Mild print punch. Unsharp at 70% so pores stay without amplifying matte jaggies."""
    rgb = img.convert('RGB')
    if ImageEnhance is not None:
        rgb = ImageEnhance.Contrast(rgb).enhance(1.02)
        rgb = ImageEnhance.Color(rgb).enhance(1.03)
    if ImageFilter is not None and hasattr(ImageFilter, 'UnsharpMask'):
        rgb = rgb.filter(
            ImageFilter.UnsharpMask(radius=1.0, percent=_ID_PHOTO_UNSHARP_PERCENT, threshold=4)
        )
    return rgb


def _save_id_photo_jpeg(img, buffer):
    """800×800 JPEG, quality 92, 4:4:4 when Pillow supports it (no chroma banding)."""
    rgb = img.convert('RGB')
    try:
        rgb.save(
            buffer,
            format='JPEG',
            quality=_ID_PHOTO_JPEG_QUALITY,
            optimize=True,
            subsampling=0,
        )
    except (TypeError, ValueError, OSError):
        buffer.seek(0)
        buffer.truncate(0)
        rgb.save(buffer, format='JPEG', quality=_ID_PHOTO_JPEG_QUALITY, optimize=True)


def _process_id_photo(img):
    """Professional square ID: rembg on white, trim gutters, 800×800 subject-width crop."""
    if img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGB')
    logger.info(
        'ID photo pipeline start size=%s skip_rembg=%s needs_cutout=%s',
        img.size,
        _skip_rembg_requested(),
        _id_photo_needs_background_removal(img),
    )
    img = _downscale_id_photo(img)
    img = _replace_id_photo_background(img)
    img = _fit_subject_on_white_square(img, ID_PHOTO_OUTPUT_PX)
    return _finish_id_portrait(img)


def _crop_id_photo_without_rembg(img):
    """Square crop + print punch when rembg/full pipeline throws. Still crops — never skip."""
    rgb = img.convert('RGB') if img.mode not in ('RGB', 'RGBA') else img
    return _finish_id_portrait(_fit_subject_on_white_square(rgb, ID_PHOTO_OUTPUT_PX))


def _process_id_card_image_bytes(payload, kind, ext):
    """Normalize an ID photo (white bg + square crop) or shrink a signature. Falls back to original bytes."""
    if Image is None:
        return payload, ext
    try:
        img = Image.open(BytesIO(payload))
        if ImageOps is not None:
            img = ImageOps.exif_transpose(img)
    except Exception:
        logger.exception('ID photo could not open uploaded bytes')
        return payload, ext
    try:
        if kind == 'photo':
            try:
                img = _process_id_photo(img)
            except ValueError:
                raise
            except Exception:
                logger.exception('ID photo pipeline failed')
                if _id_photo_needs_background_removal(img):
                    _raise_id_photo_rembg_failure('pipeline exception on a non-white-studio photo')
                logger.exception('ID photo pipeline failed; square-cropping a white-studio photo without rembg')
                img = _crop_id_photo_without_rembg(img)
            buffer = BytesIO()
            _save_id_photo_jpeg(img, buffer)
            return buffer.getvalue(), '.jpg'
        # Signature: keep transparency when possible, cap longest side.
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA')
        longest = max(img.size)
        if longest > 900:
            scale = 900 / float(longest)
            img = img.resize(
                (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale))),
                _id_photo_resample(),
            )
        buffer = BytesIO()
        out_ext = ext if ext in {'.png', '.jpg', '.webp'} else '.png'
        if out_ext == '.jpg':
            img = img.convert('RGB')
            img.save(buffer, format='JPEG', quality=90)
        elif out_ext == '.webp':
            img.save(buffer, format='WEBP', quality=90)
        else:
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            img.save(buffer, format='PNG')
            out_ext = '.png'
        return buffer.getvalue(), out_ext
    except ValueError:
        raise
    except Exception:
        logger.exception('ID card image process failed for kind=%s', kind)
        if kind == 'photo':
            _raise_id_photo_rembg_failure('unhandled photo process exception')
        return payload, ext


def _id_photos_relpath(filename):
    return os.path.join('uploads', 'id_photos', filename).replace('\\', '/')


def _save_id_card_image(file_storage, subdir, student_id, kind, student=None):
    """Save an ID photo or signature under static/uploads/<subdir>/. Returns (filename, rel_path)."""
    if not file_storage or not (file_storage.filename or '').strip():
        return None
    original = secure_filename(file_storage.filename) or kind
    ext = os.path.splitext(original)[1].lower()
    if ext not in ID_CARD_IMAGE_EXT:
        raise ValueError('Use a photo file (JPG, PNG, WEBP, or GIF).')
    payload = file_storage.read()
    if not payload:
        raise ValueError('That file was empty. Please try again.')
    if len(payload) > ID_CARD_MAX_BYTES:
        raise ValueError('That file is too large. Maximum size is 8 MB.')
    original_ext = ext
    if kind == 'photo' and student is not None:
        _store_id_photo_original_bytes(student, payload, original_ext)
    payload, ext = _process_id_card_image_bytes(payload, kind, ext)
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', subdir)
    os.makedirs(upload_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    filename = f"{kind}_{int(student_id)}_{timestamp}{ext}"
    with open(os.path.join(upload_dir, filename), 'wb') as handle:
        handle.write(payload)
    rel_path = os.path.join('uploads', subdir, filename).replace('\\', '/')
    return filename, rel_path


def _is_processed_id_photo_path(path):
    """True when this file lives under static/uploads/id_photos/."""
    if not path:
        return False
    norm = os.path.normcase(os.path.abspath(str(path)))
    marker = os.path.normcase(os.path.join('uploads', 'id_photos') + os.sep)
    return marker in norm.replace('/', os.sep)


def _cache_busted_photo_url(student, disk_path=None):
    """Static photo URL with mtime so a recropped JPEG is not served from browser cache."""
    url = getattr(student, 'photo_url', None)
    path = disk_path or _student_id_photo_disk_path(student)
    if not url or not path:
        return url
    try:
        stamp = int(os.path.getmtime(path))
    except OSError:
        return url
    sep = '&' if '?' in url else '?'
    return '%s%sv=%s' % (url, sep, stamp)


def _write_processed_id_photo_jpeg(student, img):
    """Write a NEW 800×800 JPEG under id_photos (new timestamp) and point student.photo at it."""
    buffer = BytesIO()
    _save_id_photo_jpeg(img, buffer)
    payload = buffer.getvalue()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    student_pk = int(getattr(student, 'id', 0) or 0)
    filename = 'photo_%s_%s.jpg' % (student_pk, timestamp)
    upload_dir = _id_photos_dir_from_student(student)
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), 'wb') as handle:
        handle.write(payload)
    rel_path = _id_photos_relpath(filename)
    student.photo = rel_path
    student.photo_filename = filename
    return True


def _id_photo_disk_paths(student):
    """Absolute photo files for this student, processed ID JPEGs first."""
    paths = []
    seen = set()
    if not student:
        return paths
    for source in student._id_photo_sources():
        path = _resolve_static_abs_path(source)
        if not path or path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _id_photo_pixel_area(path):
    try:
        with Image.open(path) as opened:
            return opened.size[0] * opened.size[1]
    except Exception:
        return 0


def _id_photo_student_pk(student):
    return int(getattr(student, 'id', 0) or 0)


def _is_id_photo_original_filename(path):
    return os.path.basename(str(path or '')).lower().startswith('original_')


def _existing_processed_id_photo_path(student):
    """On-disk processed id_photos JPEG (not original_*). None if only a camera file exists."""
    for path in _id_photo_disk_paths(student):
        if _is_processed_id_photo_path(path) and not _is_id_photo_original_filename(path):
            return path
    pk = _id_photo_student_pk(student)
    if pk:
        files = _glob_id_photo_dir(student, 'photo_%s_*' % pk)
        if files:
            return files[0]
    return None


def _id_photos_dir_from_student(student):
    """Folder for processed/original ID JPEGs. Prefers the student's current id_photos dir."""
    current = None
    try:
        current = _student_id_photo_disk_path(student)
    except Exception:
        current = None
    if current and _is_processed_id_photo_path(current):
        return os.path.dirname(current)
    if has_app_context() and getattr(current_app, 'static_folder', None):
        return os.path.join(current_app.static_folder, 'uploads', 'id_photos')
    if has_app_context() and getattr(current_app, 'root_path', None):
        return os.path.join(current_app.root_path, 'static', 'uploads', 'id_photos')
    return os.path.join(BASE_DIR, 'static', 'uploads', 'id_photos')


def _glob_id_photo_dir(student, pattern):
    folder = _id_photos_dir_from_student(student)
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(glob.glob(os.path.join(folder, pattern)), reverse=True)


def _unique_existing_photo_paths(paths):
    seen = set()
    out = []
    for path in paths:
        if not path:
            continue
        abs_path = os.path.abspath(str(path))
        key = os.path.normcase(abs_path)
        if key in seen or not os.path.isfile(abs_path):
            continue
        seen.add(key)
        out.append(abs_path)
    return out


def _id_photo_is_processed_square(img):
    """True when this looks like an 800×800 processed ID JPEG."""
    width, height = img.size
    return abs(width - height) <= 8 and abs(min(width, height) - ID_PHOTO_OUTPUT_PX) <= 50


def _id_photo_is_face_only_square(img):
    """True when a processed 800×800 JPEG is already a face/forehead crop — not a rembg source.

    Camera originals are not 800×800-on-white, so they return False. A full
    head-and-shoulders ID (shoulders wider than the head) also returns False.
    """
    rgb = img.convert('RGB') if img.mode != 'RGB' else img
    if not _id_photo_is_processed_square(rgb):
        return False
    if not _top_corners_near_white(rgb):
        return False
    width, height = rgb.size
    bbox = _subject_bbox(rgb)
    if not bbox:
        return True
    x0, y0, x1, y1 = bbox
    if y1 <= height * 0.40:
        return True
    subj_h = max(1.0, float(y1 - y0))
    upper = _widest_dense_row_span(rgb, y0, y0 + subj_h * 0.40)
    lower = _widest_dense_row_span(rgb, y0 + subj_h * 0.55, y1)
    upper_w = float(upper[1] - upper[0]) if upper else float(x1 - x0)
    lower_w = float(lower[1] - lower[0]) if lower else 0.0
    if lower_w >= upper_w * 1.35:
        return False
    fills = y0 <= height * 0.12 and y1 >= height * 0.88
    if fills and lower_w <= upper_w * 1.32:
        return True
    if y1 <= height * 0.55 and _lower_third_white_frac(rgb) >= 0.75:
        return True
    return False


def _id_photo_already_usable_hs(img):
    """True when an 800×800 ID already shows head and shoulders on a white studio backdrop.

    Outdoor / colored-corner squares are never treated as finished — rembg must run.
    """
    rgb = img.convert('RGB') if img.mode != 'RGB' else img
    if not _id_photo_is_processed_square(rgb) or _id_photo_is_face_only_square(rgb):
        return False
    if not _top_corners_near_white(rgb):
        return False
    bbox = _subject_bbox(rgb)
    if not bbox:
        return False
    x0, y0, x1, y1 = bbox
    height = rgb.size[1]
    if y0 <= height * 0.015:
        return False
    if (y1 - y0) < height * 0.68:
        return False
    first = _widest_dense_row_span(rgb, y0, y0 + max(4, int((y1 - y0) * 0.05)))
    widest = _widest_dense_row_span(rgb, y0, y1)
    if first and widest:
        first_w = float(first[1] - first[0])
        max_w = float(widest[1] - widest[0])
        if max_w >= 1 and first_w >= max_w * 0.68:
            return False
    return True


def _id_photo_path_is_face_only(path):
    try:
        img = _open_id_photo_for_process(path)
        return _id_photo_is_face_only_square(img)
    except Exception:
        return False


def _gather_id_photo_recrop_paths(student):
    """Candidate recrop sources: originals and camera uploads first, processed last."""
    paths = []
    pk = _id_photo_student_pk(student)
    if pk:
        paths.extend(_glob_id_photo_dir(student, 'original_%s_*' % pk))
    user = getattr(student, 'user', None)
    if user is not None:
        user_photo = getattr(user, 'photo', None)
        if user_photo:
            raw = str(user_photo).strip()
            if os.path.isabs(raw) and os.path.isfile(raw):
                paths.append(raw)
            else:
                resolved = _resolve_static_abs_path(raw)
                if resolved:
                    paths.append(resolved)
    for path in _id_photo_disk_paths(student):
        if not _is_processed_id_photo_path(path) or _is_id_photo_original_filename(path):
            paths.append(path)
    if pk:
        photo_files = _glob_id_photo_dir(student, 'photo_%s_*' % pk)
        photo_files.sort(key=_id_photo_pixel_area, reverse=True)
        paths.extend(photo_files)
    paths.extend(_id_photo_disk_paths(student))
    return _unique_existing_photo_paths(paths)


def _choose_id_photo_recrop_source(student):
    """First non-face-only source. Never rembg a destroyed 800×800 forehead JPEG."""
    for path in _gather_id_photo_recrop_paths(student):
        if _id_photo_path_is_face_only(path):
            logger.info(
                'ID photo skip face-only source %s for student %s',
                path,
                getattr(student, 'id', None),
            )
            continue
        return path
    return None


def _store_id_photo_original_bytes(student, payload, ext):
    """Keep the camera upload as id_photos/original_{id}_{timestamp}.* before first crop."""
    if not student or not payload:
        return None
    ext = (ext or '.jpg').lower()
    if ext not in ID_CARD_IMAGE_EXT:
        ext = '.jpg'
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    filename = 'original_%s_%s%s' % (_id_photo_student_pk(student), timestamp, ext)
    upload_dir = _id_photos_dir_from_student(student)
    os.makedirs(upload_dir, exist_ok=True)
    dest = os.path.join(upload_dir, filename)
    with open(dest, 'wb') as handle:
        handle.write(payload)
    return dest


def _ensure_id_photo_original_copy(student, path):
    """Copy a camera original into id_photos/original_* if none is stored yet."""
    if not path or not os.path.isfile(path):
        return None
    if _is_id_photo_original_filename(path):
        return path
    pk = _id_photo_student_pk(student)
    existing = _glob_id_photo_dir(student, 'original_%s_*' % pk) if pk else []
    if existing:
        return existing[0]
    try:
        img = _open_id_photo_for_process(path)
        if _id_photo_is_processed_square(img) and _corners_near_white(img):
            return None
    except Exception:
        logger.exception('ID photo original copy could not inspect %s', path)
        return None
    upload_dir = _id_photos_dir_from_student(student)
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(path)[1].lower() or '.jpg'
    if ext not in ID_CARD_IMAGE_EXT:
        ext = '.jpg'
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    filename = 'original_%s_%s%s' % (pk, timestamp, ext)
    dest = os.path.join(upload_dir, filename)
    shutil.copy2(path, dest)
    return dest


def _id_photo_looks_unusable_id_crop(img):
    """True when L/R gutters remain or the lower third has no shirt at the sides (eyes-only)."""
    return _edge_columns_uniformly_white(img) or _lower_third_side_columns_white(img)


def _open_id_photo_for_process(path):
    img = Image.open(path)
    if ImageOps is not None:
        img = ImageOps.exif_transpose(img)
    return img


def _reprocess_student_id_photo(student):
    """Recrop from the camera original when possible. Writes a new id_photos filename.

    Face-only / forehead 800×800 JPEGs are never used as rembg sources. Already-white
    studio H&S JPEGs are refit in-process (no rembg). Outdoor / colored-corner photos
    always run rembg from the camera original — never skip just because the file is 800×800.
    Returns True when DB paths changed.
    """
    if Image is None or not student:
        return False
    path = _choose_id_photo_recrop_source(student)
    if not path:
        logger.warning(
            'ID photo recrop has no usable original for student %s; leaving current JPEG',
            getattr(student, 'id', None),
        )
        return False
    _ensure_id_photo_original_copy(student, path)
    try:
        img = _open_id_photo_for_process(path)
    except Exception:
        logger.exception('ID photo recrop could not open %s', path)
        return False
    out = None
    try:
        already_white_studio = (
            _top_corners_near_white(img) and not _id_photo_is_face_only_square(img)
        )
        if already_white_studio:
            logger.info(
                'ID photo recrop skip rembg (already white studio) path=%s student=%s size=%s',
                path,
                getattr(student, 'id', None),
                img.size,
            )
            out = _finish_id_portrait(_fit_subject_on_white_square(img, ID_PHOTO_OUTPUT_PX))
        else:
            logger.info(
                'ID photo recrop running rembg path=%s student=%s size=%s processed_square=%s corners_white=%s',
                path,
                getattr(student, 'id', None),
                img.size,
                _id_photo_is_processed_square(img),
                _corners_near_white(img),
            )
            out = _process_id_photo(img)
    except ValueError:
        logger.exception(
            'ID photo recrop rembg failed for student %s; leaving current JPEG (not saving outdoor crop)',
            getattr(student, 'id', None),
        )
        return False
    except Exception:
        logger.exception(
            'ID photo recrop failed for student %s',
            getattr(student, 'id', None),
        )
        if _id_photo_needs_background_removal(img):
            logger.error(
                'ID photo recrop will not square-crop an outdoor photo without rembg for student %s',
                getattr(student, 'id', None),
            )
            return False
        try:
            out = _crop_id_photo_without_rembg(img)
        except Exception:
            logger.exception(
                'ID photo recrop fallback also failed for student %s',
                getattr(student, 'id', None),
            )
            return False
    if out is not None and _id_photo_looks_unusable_id_crop(out):
        try:
            out = _finish_id_portrait(_fit_subject_on_white_square(out, ID_PHOTO_OUTPUT_PX))
        except Exception:
            logger.exception(
                'ID photo gutter refit failed for student %s',
                getattr(student, 'id', None),
            )
    if out is not None and (
        _id_photo_looks_unusable_id_crop(out) or _id_photo_is_face_only_square(out)
    ):
        source_is_camera = not (
            _id_photo_is_processed_square(img) and _top_corners_near_white(img)
        )
        for alt in _gather_id_photo_recrop_paths(student):
            if alt == path or _id_photo_path_is_face_only(alt):
                continue
            if source_is_camera and _is_processed_id_photo_path(alt) and not _is_id_photo_original_filename(alt):
                continue
            logger.warning(
                'ID photo crop still has gutters/face-zoom; retrying from original %s for student %s',
                alt,
                getattr(student, 'id', None),
            )
            try:
                src = _open_id_photo_for_process(alt)
                if _id_photo_is_processed_square(src) and _top_corners_near_white(src):
                    continue
                retry = _process_id_photo(src)
            except Exception:
                logger.exception('ID photo original retry failed for %s', alt)
                continue
            if _id_photo_is_face_only_square(retry) or _id_photo_looks_unusable_id_crop(retry):
                continue
            out = retry
            break
    if out is not None and (
        _id_photo_looks_unusable_id_crop(out) or _id_photo_is_face_only_square(out)
    ):
        for alt in _gather_id_photo_recrop_paths(student):
            if alt == path or _id_photo_path_is_face_only(alt):
                continue
            if not _is_processed_id_photo_path(alt) or _is_id_photo_original_filename(alt):
                continue
            try:
                src = _open_id_photo_for_process(alt)
                if not _id_photo_already_usable_hs(src):
                    continue
                retry = _finish_id_portrait(src.convert('RGB'))
            except Exception:
                logger.exception('ID photo H&S fallback failed for %s', alt)
                continue
            if _id_photo_is_face_only_square(retry):
                continue
            logger.warning(
                'ID photo using stored head-and-shoulders JPEG %s for student %s',
                alt,
                getattr(student, 'id', None),
            )
            out = retry
            break
    return _write_processed_id_photo_jpeg(student, out)


def _prepare_id_photo_for_print(student, rembg_budget=None):
    """Print/PDF photo prep: reuse processed JPEGs. Never wait on rembg for a class.

    White-studio files may be PIL-recropped (no rembg). Outdoor / colored-corner
    files try rembg from original_* only when a session is already loaded and it
    finishes within _PRINT_REMBG_TIMEOUT_SECONDS; otherwise the existing photo is kept.
    Returns True when DB photo paths changed.
    """
    if Image is None or not student:
        return False
    path = _existing_processed_id_photo_path(student) or _student_id_photo_disk_path(student)
    if not path:
        return False
    try:
        img = _open_id_photo_for_process(path)
    except Exception:
        logger.exception('ID print photo could not open %s', path)
        return False

    outdoor = _id_photo_needs_background_removal(img)
    if outdoor:
        allow = rembg_budget is None or rembg_budget.get('allow', True)
        if rembg_budget is not None and 'remaining' in rembg_budget:
            allow = allow and int(rembg_budget.get('remaining') or 0) > 0
        if allow and _rembg_session_already_ready():
            source_path = _choose_id_photo_recrop_source(student) or path
            try:
                source = _open_id_photo_for_process(source_path)
            except Exception:
                logger.exception('ID print rembg could not open source %s', source_path)
                source = img
            source = _downscale_id_photo(source)
            rgba = _rembg_cutout_rgba(
                source,
                disable_on_fail=False,
                timeout=_PRINT_REMBG_TIMEOUT_SECONDS,
                load_session=False,
            )
            if rembg_budget is not None:
                if 'remaining' in rembg_budget:
                    rembg_budget['remaining'] = max(0, int(rembg_budget.get('remaining') or 0) - 1)
                    rembg_budget['allow'] = rembg_budget['remaining'] > 0
                else:
                    rembg_budget['allow'] = False
            if rgba is not None:
                try:
                    composed = _composite_id_cutout_on_white(rgba)
                    out = _finish_id_portrait(
                        _fit_subject_on_white_square(composed, ID_PHOTO_OUTPUT_PX)
                    )
                    return _write_processed_id_photo_jpeg(student, out)
                except Exception:
                    logger.exception(
                        'ID print rembg finish failed for student %s; keeping existing JPEG',
                        getattr(student, 'id', None),
                    )
                    return False
            logger.warning(
                'ID print rembg timed out or failed for student %s after %ss; keeping existing JPEG',
                getattr(student, 'id', None),
                _PRINT_REMBG_TIMEOUT_SECONDS,
            )
        else:
            logger.info(
                'ID print using existing photo without rembg student=%s path=%s',
                getattr(student, 'id', None),
                path,
            )
        return False

    if _id_photo_already_usable_hs(img) and not _id_photo_looks_unusable_id_crop(img):
        return False
    try:
        out = _crop_id_photo_without_rembg(img)
        return _write_processed_id_photo_jpeg(student, out)
    except Exception:
        logger.exception(
            'ID print PIL recrop failed for student %s; keeping existing JPEG',
            getattr(student, 'id', None),
        )
        return False


def _student_id_photo_is_outdoor(student):
    """True when the stored ID JPEG still has colored (outdoor) corners."""
    path = _existing_processed_id_photo_path(student) or _student_id_photo_disk_path(student)
    if not path:
        return False
    try:
        img = _open_id_photo_for_process(path)
    except Exception:
        return False
    return _id_photo_needs_background_removal(img)


def _refresh_ready_card_photo(card, student):
    photo_path = _student_id_photo_disk_path(student)
    card['photo_path'] = photo_path
    card['photo_url'] = _cache_busted_photo_url(student, photo_path)


def _prepare_ready_card_photos_for_print(ready_cards, *, flash_remaining=False):
    """PIL-recrop white JPEGs. At most two warm rembg cutouts from original_*.

    Does not start a cold ONNX load. Remaining outdoor photos keep the stored JPEG.
    Returns True when any student.photo path changed.
    """
    rembg_budget = {'allow': True, 'remaining': _PRINT_REMBG_MAX_PHOTOS}
    dirty = False
    outdoor_names = []
    for card in ready_cards or []:
        student = card.get('student') if isinstance(card, dict) else None
        if not student:
            continue
        try:
            if _prepare_id_photo_for_print(student, rembg_budget=rembg_budget):
                dirty = True
                _refresh_ready_card_photo(card, student)
        except Exception:
            logger.exception(
                'ID print photo prep failed for student %s; card will use the existing file',
                getattr(student, 'id', None),
            )
        if _student_id_photo_is_outdoor(student):
            outdoor_names.append(getattr(student, 'full_name', None) or 'a student')
    if flash_remaining and outdoor_names:
        listed = ', '.join(outdoor_names[:6])
        extra = '' if len(outdoor_names) <= 6 else ' and others'
        flash(
            '%s (%s%s).' % (ID_PHOTO_PRINT_STILL_PROCESSING.rstrip('.'), listed, extra),
            'warning',
        )
    return dirty


def _student_has_class_for_id_card(student, academic_year=None):
    """True when the student can be printed onto a class ID card."""
    if not student:
        return False
    if student.klass_id or student.assigned_class:
        return True
    year_id = getattr(academic_year, 'id', None) or student.academic_year_id
    if year_id:
        return bool(_class_id_from_year_enrollment(student.id, year_id))
    return False


def _sync_student_id_card(student, academic_year=None):
    """Set expiration (if missing) and id_card_ready from photo + signature + class + student ID."""
    if not student:
        return False
    if student.student_id and not (student.student_id_code or '').strip():
        student.student_id_code = student.student_id
    default_exp = _default_id_expiration_date(academic_year)
    existing_exp = student.id_expiration_date
    year_start = getattr(academic_year, 'start_date', None) if academic_year else None
    if existing_exp is None or (year_start and existing_exp < year_start):
        student.id_expiration_date = default_exp
    student.id_card_ready = bool(
        (student.student_id or '').strip()
        and _student_has_class_for_id_card(student, academic_year)
        and student.has_id_photo
        and student.has_signature
    )
    return student.id_card_ready


def _refresh_id_card_flags(students, academic_year=None, *, commit=False):
    """Recompute id_card_ready for many students; optionally commit if anything changed."""
    dirty = False
    for student in students or []:
        before_ready = student.id_card_ready
        before_exp = student.id_expiration_date
        before_code = student.student_id_code
        year = academic_year or student.academic_year
        _sync_student_id_card(student, academic_year=year)
        if (
            student.id_card_ready != before_ready
            or student.id_expiration_date != before_exp
            or student.student_id_code != before_code
        ):
            dirty = True
    if dirty and commit:
        db.session.commit()
    return dirty


def _id_card_students_for_year(display_year):
    """Year roster with ID-ready flags refreshed from photo, signature, class, and ID number."""
    students = []
    if display_year:
        students = (
            _students_for_display_year(display_year)
            .options(joinedload(Student.assigned_class))
            .order_by(Student.last_name.asc(), Student.first_name.asc())
            .all()
        )
    _refresh_id_card_flags(students, academic_year=display_year, commit=False)
    return students


def _id_card_print_payload(student, display_year):
    """Front/back print row for one ready student (CR80 + portal QR).

    Does not recrop or rembg. Photos load from stored /static/uploads/id_photos files.
    """
    year_id = display_year.id if display_year else getattr(student, 'academic_year_id', None)
    token = None
    portal_url = None
    qr_uri = None
    photo_path = None
    try:
        if student.student_id and not (student.student_id_code or '').strip():
            student.student_id_code = student.student_id
        ensure_student_secure_qr_token(student)
        token = (getattr(student, 'secure_qr_token', None) or '').strip()
        base_url = get_site_base_url()
        portal_url = build_student_portal_qr_url(student, base_url=base_url)
        try:
            qr_uri = generate_student_scanner_code(student, base_url=base_url)
        except Exception:
            logger.exception('ID card QR failed for student %s', getattr(student, 'id', None))
        photo_path = _student_id_photo_disk_path(student)
    except Exception:
        logger.exception('ID card print payload failed for student %s', getattr(student, 'id', None))
    return {
        'student': student,
        'parent_name': resolve_parent_guardian_name(student) or '',
        'qr_code_data_uri': qr_uri,
        'student_portal_qr_url': portal_url,
        'portal_path': f'/student/id-portal/{token}' if token else None,
        'class_label': format_student_class_name(student, year_id),
        'photo_path': photo_path,
        'photo_url': _cache_busted_photo_url(student, photo_path),
        'signature_path': _student_signature_disk_path(student),
    }


def _resolve_static_abs_path(relative_path):
    """Map a stored static-relative photo/logo path to an absolute file."""
    from models import _looks_like_raster_image, _photo_candidate_filenames

    if not relative_path:
        return None
    raw = str(relative_path).strip()
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    candidates = _photo_candidate_filenames(raw) or [raw.replace('\\', '/').lstrip('/')]
    roots = []
    static_root = getattr(current_app, 'static_folder', None)
    if static_root:
        roots.append(static_root)
    if getattr(current_app, 'root_path', None):
        roots.append(os.path.join(current_app.root_path, 'static'))
    seen = set()
    for candidate in candidates:
        if not candidate or candidate.startswith(('http://', 'https://', 'data:')):
            continue
        rel = candidate.replace('/', os.sep)
        for root in roots:
            full = os.path.normpath(os.path.join(root, rel))
            if full in seen:
                continue
            seen.add(full)
            try:
                if os.path.isfile(full) and _looks_like_raster_image(full):
                    return full
            except (OSError, ValueError):
                continue
    return None


def _school_logo_disk_path():
    from models import SCHOOL_LOGO_FILENAME

    for name in (SCHOOL_LOGO_FILENAME, 'images/logo.png', 'images/logo1.png'):
        path = _resolve_static_abs_path(name)
        if path:
            return path
    return None


def _liberia_seal_disk_path():
    from models import LIBERIA_SEAL_FILENAMES

    for name in LIBERIA_SEAL_FILENAMES:
        path = _resolve_static_abs_path(name)
        if path:
            return path
    return None


def _student_id_photo_disk_path(student):
    if not student:
        return None
    for source in student._id_photo_sources():
        path = _resolve_static_abs_path(source)
        if path:
            return path
    return None


def _student_signature_disk_path(student):
    filename = (getattr(student, 'signature_filename', None) or '').strip().replace('\\', '/')
    if not filename:
        return None
    sources = [filename] if '/' in filename else [f'uploads/signatures/{filename}', filename]
    for source in sources:
        path = _resolve_static_abs_path(source)
        if path:
            return path
    return None


def _collect_class_id_cards(class_id):
    """Ready CR80 payloads for one class folder; skips students who are not ID-ready."""
    klass = Class.query.get_or_404(class_id)
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    query = Student.query.filter_by(klass_id=class_id)
    if display_year:
        query = _students_for_display_year(display_year).filter(Student.klass_id == class_id)
    students = (
        query.options(
            joinedload(Student.assigned_class),
            joinedload(Student.parent_user),
            joinedload(Student.user),
        )
        .order_by(Student.last_name.asc(), Student.first_name.asc())
        .all()
    )
    ready_cards = []
    skipped = []
    dirty = False
    for student in students:
        before_ready = student.id_card_ready
        before_exp = student.id_expiration_date
        _sync_student_id_card(student, academic_year=display_year or student.academic_year)
        if student.id_card_ready != before_ready or student.id_expiration_date != before_exp:
            dirty = True
        if student.id_card_ready:
            before_photo = (student.photo, student.photo_filename)
            try:
                ready_cards.append(_id_card_print_payload(student, display_year))
            except Exception:
                logger.exception(
                    'ID print payload failed for student %s; emitting a placeholder card',
                    getattr(student, 'id', None),
                )
                ready_cards.append({
                    'student': student,
                    'parent_name': resolve_parent_guardian_name(student) or '',
                    'qr_code_data_uri': None,
                    'student_portal_qr_url': None,
                    'portal_path': None,
                    'class_label': '',
                    'photo_path': None,
                    'photo_url': getattr(student, 'photo_url', None),
                    'signature_path': None,
                })
            if (student.photo, student.photo_filename) != before_photo:
                dirty = True
        else:
            skipped.append(student)
    if dirty:
        db.session.commit()
    return klass, display_year, ready_cards, skipped


def _stream_id_cards_pdf(klass, display_year, ready_cards, *, single=False):
    """Build a complete PDF of ready ID cards, then send it as a finished attachment.

    Never rembg the whole class. PIL-recrop existing JPEGs; up to
    _PRINT_REMBG_MAX_PHOTOS short rembg attempts are allowed only when the
    session is already loaded. Photo failures still emit a card so the HTTP
    body is always a valid complete PDF.
    """
    dirty = False
    try:
        dirty = _prepare_ready_card_photos_for_print(ready_cards, flash_remaining=False)
    except Exception:
        logger.exception('ID PDF photo prep failed; continuing with stored JPEGs')
    if dirty:
        try:
            db.session.commit()
        except Exception:
            logger.exception('ID PDF photo path commit failed')
            db.session.rollback()
    try:
        buffer = build_class_id_cards_pdf(
            ready_cards,
            klass=klass,
            display_year=display_year,
            brand=school_print_brand(),
            logo_path=_school_logo_disk_path(),
            seal_path=_liberia_seal_disk_path(),
        )
    except Exception:
        logger.exception('ID card PDF folder failed; retrying a complete PDF without logos')
        try:
            buffer = build_class_id_cards_pdf(
                ready_cards,
                klass=klass,
                display_year=display_year,
                brand=school_print_brand(),
            )
        except Exception:
            logger.exception('ID card PDF fallback failed')
            flash(
                'The ID card folder could not be prepared. Use Print class IDs, then choose Download / Save PDF.',
                'danger',
            )
            if klass:
                return redirect(url_for('print_class_id_cards', class_id=klass.id))
            return redirect(url_for('id_cards_folder_hub'))
    filename = id_cards_pdf_filename(klass, display_year, single=single)
    return _id_cards_pdf_attachment_response(buffer, filename)


def _id_cards_pdf_attachment_response(buffer, filename):
    """Force the browser to save a finished PDF. Never stream a partial file."""
    if hasattr(buffer, 'seek'):
        buffer.seek(0)
    payload = buffer.getvalue() if hasattr(buffer, 'getvalue') else buffer.read()
    if not payload or not payload.startswith(b'%PDF'):
        logger.error('ID card PDF buffer was empty or not a PDF; building a one-page fallback')
        fallback = build_class_id_cards_pdf([], klass=None, display_year=None, brand={})
        payload = fallback.getvalue()
    finished = BytesIO(payload)
    finished.seek(0)
    safe_name = (filename or 'FLPA_ID_Cards.pdf').replace('"', '').replace('\r', '').replace('\n', '')
    response = send_file(
        finished,
        as_attachment=True,
        download_name=safe_name,
        mimetype='application/pdf',
        max_age=0,
        conditional=False,
        etag=False,
    )
    response.headers['Content-Type'] = 'application/pdf'
    # Quoted filename so Chrome/Edge save as FLPA_ID_Cards_....pdf instead of opening the viewer.
    response.headers['Content-Disposition'] = f'attachment; filename="{safe_name}"'
    response.headers['Content-Length'] = str(len(payload))
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.pop('Accept-Ranges', None)
    response.direct_passthrough = False
    return response


def _id_cards_none_ready_response(klass, *, from_download=False):
    flash(
        f'No ready ID cards in {klass.name}. Add a photo on each student folder first '
        '(signature is generated from the name).',
        'warning',
    )
    if from_download:
        return redirect(url_for('dashboard') + f'#folder-{klass.id}')
    return redirect(url_for('id_cards_folder_hub'))


def _id_cards_qr_localhost_warning(cards):
    return any(site_url_is_loopback(card.get('student_portal_qr_url')) for card in cards)


@app.route('/registrar/students/<int:student_id>/documents', methods=['POST'], endpoint='upload_registrar_student_document')
@login_required
def upload_registrar_student_document(student_id):
    """Scan or upload a paper into the student's registrar folder."""
    if not _require_registrar_office():
        return redirect(url_for('login'))

    student = Student.query.get_or_404(student_id)
    upload = request.files.get('scan_file') or request.files.get('upload_file') or request.files.get('document')
    if not upload or not (upload.filename or '').strip():
        flash("Choose a scan or file to place in this student's folder.", "warning")
        return _registrar_student_folder_redirect(student.id)

    original = secure_filename(upload.filename) or 'document'
    ext = os.path.splitext(original)[1].lower()
    if ext not in REGISTRAR_DOC_ALLOWED_EXT:
        flash("Use a photo (JPG, PNG, WEBP) or a PDF.", "warning")
        return _registrar_student_folder_redirect(student.id)

    payload = upload.read()
    if not payload:
        flash("That scan was empty. Please try again.", "warning")
        return _registrar_student_folder_redirect(student.id)
    if len(payload) > REGISTRAR_DOC_MAX_BYTES:
        flash("That file is too large. Maximum size is 12 MB.", "warning")
        return _registrar_student_folder_redirect(student.id)

    doc_type = (request.form.get('doc_type') or 'other').strip().lower()
    if doc_type not in StudentRegistryDocument.DOC_TYPE_LABELS:
        doc_type = 'other'
    title = (request.form.get('title') or '').strip() or StudentRegistryDocument.DOC_TYPE_LABELS[doc_type]

    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    rel_dir = os.path.join('uploads', 'student_docs', str(student.id))
    abs_dir = os.path.join(BASE_DIR, 'static', rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}{ext}"
    abs_path = os.path.join(abs_dir, stored_name)
    with open(abs_path, 'wb') as handle:
        handle.write(payload)

    ocr_text = None
    if ext != '.pdf' and ocr_engine_ready():
        try:
            ocr_text = (extract_text_from_stream(BytesIO(payload)) or '').strip() or None
        except Exception:
            ocr_text = None

    record = StudentRegistryDocument(
        student_id=student.id,
        uploaded_by_id=current_user.id,
        academic_year_id=display_year.id if display_year else student.academic_year_id,
        title=title[:200],
        doc_type=doc_type,
        original_filename=original[:255],
        file_path=os.path.join(rel_dir, stored_name).replace('\\', '/'),
        mime_type=upload.mimetype or None,
        ocr_text=ocr_text,
    )
    db.session.add(record)
    db.session.commit()
    if ocr_text:
        flash("Document scanned and filed in this student's folder.", "success")
    else:
        flash("Document filed in this student's folder.", "success")
    return _registrar_student_folder_redirect(student.id)


@app.route(
    '/registrar/students/<int:student_id>/documents/<int:document_id>/file',
    methods=['GET'],
    endpoint='view_registrar_student_document',
)
@login_required
def view_registrar_student_document(student_id, document_id):
    if not _require_registrar_office():
        return redirect(url_for('login'))

    document = StudentRegistryDocument.query.filter_by(id=document_id, student_id=student_id).first_or_404()
    rel = (document.file_path or '').replace('\\', '/').lstrip('/')
    if rel.startswith('static/'):
        rel = rel[7:]
    directory = os.path.dirname(rel)
    filename = os.path.basename(rel)
    base_dir = os.path.realpath(os.path.join(BASE_DIR, 'static', directory.replace('/', os.sep)))
    file_path = os.path.realpath(os.path.join(base_dir, filename))
    if not filename or not file_path.startswith(base_dir) or not os.path.isfile(file_path):
        abort(404)
    return send_from_directory(base_dir, filename, as_attachment=False, download_name=document.original_filename or filename)


@app.route(
    '/registrar/students/<int:student_id>/documents/<int:document_id>/delete',
    methods=['POST'],
    endpoint='delete_registrar_student_document',
)
@login_required
def delete_registrar_student_document(student_id, document_id):
    if not _require_registrar_office():
        return redirect(url_for('login'))

    document = StudentRegistryDocument.query.filter_by(id=document_id, student_id=student_id).first_or_404()
    rel = (document.file_path or '').replace('\\', '/').lstrip('/')
    if rel.startswith('static/'):
        rel = rel[7:]
    abs_path = os.path.join(BASE_DIR, 'static', rel.replace('/', os.sep))
    try:
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except OSError:
        pass
    db.session.delete(document)
    db.session.commit()
    flash("Document removed from this student's folder.", "success")
    return _registrar_student_folder_redirect(student_id)


@app.route(
    '/registrar/students/<int:student_id>/setup-id',
    methods=['POST'],
    endpoint='setup_student_id_card',
)
@login_required
def setup_student_id_card(student_id):
    """Upload or replace the ID-card photo and signature for one student."""
    denied = _registrar_office_guard()
    if denied:
        return denied

    student = Student.query.get_or_404(student_id)
    photo = request.files.get('photo') or request.files.get('id_photo')
    signature = request.files.get('signature')
    try:
        photo_saved = False
        if photo and (photo.filename or '').strip():
            saved = _save_id_card_image(photo, 'id_photos', student.id, 'photo', student=student)
            if saved:
                filename, rel_path = saved
                student.photo = rel_path
                student.photo_filename = filename
                photo_saved = True
        if not photo_saved and student.has_id_photo:
            _reprocess_student_id_photo(student)
        if signature and (signature.filename or '').strip():
            saved = _save_id_card_image(signature, 'signatures', student.id, 'signature')
            if saved:
                _filename, rel_path = saved
                student.signature_filename = rel_path
    except ValueError as exc:
        flash(str(exc), 'warning')
        return _registrar_student_folder_redirect(student.id)

    persist_student_guardian_name(student)

    expires_raw = (request.form.get('id_expiration_date') or '').strip()
    if expires_raw:
        try:
            student.id_expiration_date = datetime.strptime(expires_raw, '%Y-%m-%d').date()
        except ValueError:
            flash('Expiration date must be YYYY-MM-DD.', 'warning')
            return _registrar_student_folder_redirect(student.id)

    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    _sync_student_id_card(student, academic_year=display_year or student.academic_year)
    db.session.commit()

    if student.id_card_ready:
        flash(f'ID card ready for {student.full_name}.', 'success')
    else:
        missing = []
        if not (student.student_id or '').strip():
            missing.append('student ID')
        if not _student_has_class_for_id_card(student, display_year or student.academic_year):
            missing.append('class assignment')
        if not student.has_id_photo:
            missing.append('photo')
        if not (student.signature_url or student.official_signature_mark):
            missing.append('signature')
        flash(
            'ID files saved, but still needs: {}.'.format(', '.join(missing) or 'a complete record'),
            'warning',
        )
    return _registrar_student_folder_redirect(student.id)


@app.route('/id-cards', methods=['GET'], endpoint='id_cards_folder_hub')
@login_required
def id_cards_folder_hub():
    """Class-folder hub for issuing and batch-printing student ID cards."""
    denied = _registrar_office_guard()
    if denied:
        return denied

    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    class_rows = sorted(Class.query.all(), key=class_sort_key_from_klass)
    students = _id_card_students_for_year(display_year)
    by_class = {}
    for student in students:
        klass = _registrar_roster_class_for_student(student, display_year)
        if klass:
            by_class.setdefault(klass.id, []).append(student)

    class_stats = {}
    ready_total = 0
    roster_total = 0
    for klass in class_rows:
        roster = by_class.get(klass.id, [])
        ready = sum(1 for row in roster if row.id_card_ready)
        class_stats[klass.id] = {
            'total': len(roster),
            'ready': ready,
            'download_filename': id_cards_pdf_filename(klass, display_year),
        }
        roster_total += len(roster)
        ready_total += ready

    return render_template(
        'id_cards/folder_hub.html',
        display_year=display_year,
        groups=group_classes(class_rows),
        class_stats=class_stats,
        ready_total=ready_total,
        roster_total=roster_total,
    )


@app.route('/id-cards/print/class/<int:class_id>', methods=['GET'], endpoint='print_class_id_cards')
@login_required
def print_class_id_cards(class_id):
    """CR80 batch sheet for every ID-ready student in a class."""
    if not _require_registrar_office():
        return redirect(url_for('login'))

    klass, display_year, ready_cards, skipped = _collect_class_id_cards(class_id)
    if not ready_cards:
        return _id_cards_none_ready_response(klass)

    dirty = _prepare_ready_card_photos_for_print(ready_cards, flash_remaining=True)
    if dirty:
        try:
            db.session.commit()
        except Exception:
            logger.exception('ID print photo path commit failed')
            db.session.rollback()

    if str(request.args.get('download') or '').strip().lower() in {'1', 'true', 'yes', 'pdf'}:
        return _stream_id_cards_pdf(klass, display_year, ready_cards)

    return render_template(
        'id_cards/print_batch.html',
        klass=klass,
        display_year=display_year,
        cards=ready_cards,
        skipped=skipped,
        printed_at=datetime.now(timezone.utc),
        printed_by=current_user.full_name or current_user.email,
        liberia_seal_url=liberia_seal_static_url(),
        qr_localhost_warning=_id_cards_qr_localhost_warning(ready_cards),
        download_url=url_for('download_class_id_cards', class_id=klass.id),
        download_filename=id_cards_pdf_filename(klass, display_year),
        refresh_photos_url=url_for('refresh_class_id_photos', class_id=klass.id),
    )


@app.route('/id-cards/download/class/<int:class_id>', methods=['GET'], endpoint='download_class_id_cards')
@login_required
def download_class_id_cards(class_id):
    """One PDF folder of ready class ID cards (front + back). Registrar / admin / principal."""
    if not _require_registrar_office():
        return redirect(url_for('login'))

    klass, display_year, ready_cards, _skipped = _collect_class_id_cards(class_id)
    if not ready_cards:
        return _id_cards_none_ready_response(klass, from_download=True)
    return _stream_id_cards_pdf(klass, display_year, ready_cards)


def _refresh_outdoor_id_photos_for_students(students, max_photos=_PRINT_REMBG_MAX_PHOTOS):
    """Full rembg from original_* for outdoor ID JPEGs, a few at a time.

    Returns (changed_count, remaining_outdoor, status) where status is ok/not_ready.
    """
    if _skip_rembg_requested():
        return 0, sum(1 for row in students if _student_id_photo_is_outdoor(row)), 'skipped'
    session = _get_rembg_session(wait_seconds=60)
    if session is None:
        remaining = sum(1 for row in students if _student_id_photo_is_outdoor(row))
        return 0, remaining, 'not_ready'
    changed = 0
    attempted = 0
    for student in students:
        if not _student_id_photo_is_outdoor(student):
            continue
        attempted += 1
        try:
            if _reprocess_student_id_photo(student):
                changed += 1
        except Exception:
            logger.exception(
                'ID photo refresh rembg failed for student %s',
                getattr(student, 'id', None),
            )
        if attempted >= max_photos:
            break
    remaining = sum(1 for row in students if _student_id_photo_is_outdoor(row))
    return changed, remaining, 'ok'


@app.route(
    '/id-cards/print/class/<int:class_id>/refresh-photos',
    methods=['POST'],
    endpoint='refresh_class_id_photos',
)
@login_required
def refresh_class_id_photos(class_id):
    """Registrar: rembg outdoor ID photos one-by-one, then return to the print hub."""
    denied = _registrar_office_guard()
    if denied:
        return denied

    klass, _display_year, ready_cards, _skipped = _collect_class_id_cards(class_id)
    students = [card.get('student') for card in ready_cards if card.get('student')]
    changed, remaining, status = _refresh_outdoor_id_photos_for_students(students)
    if changed:
        db.session.commit()
    if status == 'skipped':
        flash(ID_PHOTO_SKIP_REMBG_WARNING, 'warning')
    elif status == 'not_ready':
        flash(ID_PHOTO_REMBG_LOADING_MESSAGE, 'warning')
    elif changed and remaining:
        flash(
            'Refreshed %s ID photo(s). %s still outdoor — tap Refresh ID photos again.'
            % (changed, remaining),
            'warning',
        )
    elif changed:
        flash('Refreshed %s ID photo(s). Reprint when ready.' % changed, 'success')
    elif remaining:
        flash(ID_PHOTO_PRINT_STILL_PROCESSING, 'warning')
    else:
        flash('ID photos already have a white studio backdrop.', 'success')
    return redirect(url_for('print_class_id_cards', class_id=klass.id))


@app.route(
    '/id-cards/print/student/<int:student_id>/refresh-photo',
    methods=['POST'],
    endpoint='refresh_student_id_photo',
)
@login_required
def refresh_student_id_photo(student_id):
    """Registrar: rembg one student's outdoor ID photo from original_*."""
    denied = _registrar_office_guard()
    if denied:
        return denied

    student = Student.query.get_or_404(student_id)
    changed, remaining, status = _refresh_outdoor_id_photos_for_students([student], max_photos=1)
    if changed:
        db.session.commit()
    if status == 'skipped':
        flash(ID_PHOTO_SKIP_REMBG_WARNING, 'warning')
    elif status == 'not_ready':
        flash(ID_PHOTO_REMBG_LOADING_MESSAGE, 'warning')
    elif changed:
        flash('ID photo refreshed for %s.' % student.full_name, 'success')
    elif remaining:
        flash(ID_PHOTO_PRINT_STILL_PROCESSING, 'warning')
    else:
        flash('ID photo already has a white studio backdrop.', 'success')
    return redirect(url_for('print_student_id_card', student_id=student.id))


STAFF_ID_CARD_ROLES = frozenset({
    'admin', 'principal', 'teacher', 'registrar', 'registry', 'vpa', 'vpi', 'dean', 'business',
})


def _staff_id_disk_path(stored_path):
    """Resolve a stored staff ID photo/signature to a real static image file."""
    return _resolve_static_abs_path(stored_path)


_SIGNATURE_HONORIFICS = frozenset({
    'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 'rev', 'reverend',
    'hon', 'honorable', 'sir', 'madam', 'madame', 'pastor', 'engr', 'eng', 'atty',
})
_SIGNATURE_NUMERALS = frozenset({'ii', 'iii', 'iv', 'v'})
_SIGNATURE_SUFFIXES = frozenset({'jr', 'sr'}) | _SIGNATURE_NUMERALS
# Written with the surname ("Grace van Dyke"), never shortened to an initial.
_SIGNATURE_PARTICLES = frozenset({
    'van', 'von', 'de', 'del', 'della', 'da', 'das', 'dos', 'di', 'du',
    'la', 'le', 'der', 'den', 'ter', 'ten', 'bin', 'ibn', 'al',
})


def _signature_case(word):
    """Title-case a name part without flattening McDonald, O'Brien, or Mensah-Doe."""
    if not word:
        return ''
    if ' ' in word:
        return ' '.join(_signature_case(part) for part in word.split())
    if any(char.isupper() for char in word) and any(char.islower() for char in word):
        return word  # Deliberate spelling such as McDonald or van Dyke.
    if word.lower() in _SIGNATURE_PARTICLES:
        return word.lower()
    pieces = re.split(r"([-'\u2019])", word.lower())
    return ''.join(piece if len(piece) == 1 and not piece.isalpha() else piece.capitalize()
                   for piece in pieces)


def _staff_signature_name_parts(user):
    """(first, middle, last, suffix) for the signature, ignoring titles like Rev. or Dr."""
    profile = getattr(user, 'teacher_profile', None)
    first = (getattr(profile, 'first_name', '') or '').strip() if profile else ''
    last = (getattr(profile, 'last_name', '') or '').strip() if profile else ''
    if first and last:
        return first, '', last, ''

    tokens = [
        token
        for token in (getattr(user, 'full_name', '') or '').replace(',', ' ').split()
        if token
    ]
    tokens = [token for token in tokens if token.strip('.').lower() not in _SIGNATURE_HONORIFICS]
    suffix = ''
    if len(tokens) > 1 and tokens[-1].strip('.').lower() in _SIGNATURE_SUFFIXES:
        suffix = tokens.pop()
    if not tokens:
        return '', '', '', ''
    if len(tokens) == 1:
        return tokens[0], '', '', suffix
    surname = [tokens.pop()]
    while len(tokens) > 1 and tokens[-1].lower() in _SIGNATURE_PARTICLES:
        surname.insert(0, tokens.pop())
    return tokens[0], ' '.join(tokens[1:]), ' '.join(surname), suffix


def _staff_signature_mark(user):
    """Signature written from the staff name when no handwritten one is uploaded.

    Prints as the person signs a paper card — given name, middle initial, surname
    (e.g. "Othello B. Gbarjuewaye") — in the card's script font.
    """
    first, middle, last, suffix = _staff_signature_name_parts(user)
    if not first and not last:
        return 'Authorized Staff'

    pieces = [_signature_case(first)] if first else []
    for part in middle.split():
        initial = part.strip('.')[:1]
        if initial:
            pieces.append(f'{initial.upper()}.')
    if last:
        pieces.append(_signature_case(last))
    if suffix:
        bare = suffix.strip('.')
        pieces.append(bare.upper() if bare.lower() in _SIGNATURE_NUMERALS else f'{bare.capitalize()}.')
    return ' '.join(piece for piece in pieces if piece) or 'Authorized Staff'


STAFF_ID_PHOTO_SUBDIR = 'staff_id_photos'


def _first_uploaded_file(field):
    """First non-empty upload for a field name (file picker and camera share one name)."""
    for storage in request.files.getlist(field):
        if storage and (storage.filename or '').strip():
            return storage
    return None


def _staff_id_photos_dir():
    return os.path.join(current_app.root_path, 'static', 'uploads', STAFF_ID_PHOTO_SUBDIR)


def _store_staff_id_photo_original(user, payload, ext):
    """Keep the camera upload as staff_id_photos/original_{id}_{timestamp}.* before cropping."""
    if not user or not payload:
        return None
    ext = (ext or '.jpg').lower()
    if ext not in ID_CARD_IMAGE_EXT:
        ext = '.jpg'
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    filename = 'original_%s_%s%s' % (int(user.id), timestamp, ext)
    upload_dir = _staff_id_photos_dir()
    os.makedirs(upload_dir, exist_ok=True)
    dest = os.path.join(upload_dir, filename)
    with open(dest, 'wb') as handle:
        handle.write(payload)
    return dest


def _staff_id_photo_original_path(user):
    """Newest stored camera original for this staff account, if one was kept."""
    if not user:
        return None
    pattern = os.path.join(_staff_id_photos_dir(), 'original_%s_*' % int(user.id))
    matches = [path for path in glob.glob(pattern) if os.path.isfile(path)]
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _staff_id_photo_url(user):
    """Card/preview URL: the processed cutout when uploaded, else the account avatar."""
    stored = getattr(user, 'id_card_photo_path', None)
    path = _staff_id_disk_path(stored)
    if not path:
        return user.photo_url
    url = url_for('static', filename=stored)
    try:
        return '%s%sv=%s' % (url, '&' if '?' in url else '?', int(os.path.getmtime(path)))
    except OSError:
        return url


def _write_processed_staff_id_photo(user, img):
    """Write a new 800×800 JPEG under staff_id_photos and point the staff card at it."""
    buffer = BytesIO()
    _save_id_photo_jpeg(img, buffer)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    filename = 'photo_%s_%s.jpg' % (int(user.id), timestamp)
    upload_dir = _staff_id_photos_dir()
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), 'wb') as handle:
        handle.write(buffer.getvalue())
    user.id_card_photo_path = os.path.join(
        'uploads', STAFF_ID_PHOTO_SUBDIR, filename
    ).replace('\\', '/')
    return True


def _process_staff_id_photo_from(user, source):
    """Run the ID pipeline on one source file and store the result as the card photo."""
    if Image is None or not user or not source:
        return False
    try:
        img = _open_id_photo_for_process(source)
    except Exception:
        logger.exception('Staff ID photo could not open %s', source)
        return False
    try:
        if _top_corners_near_white(img) and not _id_photo_is_face_only_square(img):
            out = _finish_id_portrait(_fit_subject_on_white_square(img, ID_PHOTO_OUTPUT_PX))
        else:
            out = _process_id_photo(img)
    except ValueError:
        logger.exception('Staff ID photo background removal failed for user %s', user.id)
        return False
    except Exception:
        logger.exception('Staff ID photo pipeline failed for user %s', user.id)
        return False
    return _write_processed_staff_id_photo(user, out)


def _reprocess_staff_id_photo(user):
    """Re-run the student background-removal pipeline on the stored staff photo."""
    if not user:
        return False
    source = _staff_id_photo_original_path(user) or _staff_id_disk_path(user.id_card_photo_path)
    return _process_staff_id_photo_from(user, source)


# The stock silhouette is not a portrait, so it must never become a card photo.
_DEFAULT_AVATAR_BASENAMES = frozenset({
    'default-avatar.png', 'default_avatar.png', 'default_student.png', 'default_user.png',
})


def _staff_profile_photo_source(user):
    """Absolute path of this account's own avatar, or None when it is the stock badge."""
    stored = (getattr(user, 'photo', None) or '').strip()
    if not stored:
        return None
    if os.path.basename(stored.replace('\\', '/')).lower() in _DEFAULT_AVATAR_BASENAMES:
        return None
    return _resolve_static_abs_path(stored)


def _adopt_profile_photo_as_staff_id(user):
    """Build the staff card photo from the account avatar, backdrop removed."""
    source = _staff_profile_photo_source(user)
    if not source or not _process_staff_id_photo_from(user, source):
        return False
    try:
        with open(source, 'rb') as handle:
            _store_staff_id_photo_original(
                user, handle.read(), os.path.splitext(source)[1].lower()
            )
    except OSError:
        logger.exception('Staff ID original copy failed for user %s', user.id)
    return True


def _sync_staff_id_card(user, academic_year=None):
    """Set staff ID expiration and readiness from the same files used on the card."""
    if not user:
        return False
    if user.id_expiration_date is None:
        user.id_expiration_date = _default_id_expiration_date(academic_year)
    user.staff_id_card_ready = bool(
        user.is_active
        and user.is_account_active()
        and canonical_role(user) in STAFF_ID_CARD_ROLES
        and _staff_id_disk_path(user.id_card_photo_path)
        and (
            _staff_id_disk_path(user.id_card_signature_path)
            or _staff_signature_mark(user)
        )
    )
    return user.staff_id_card_ready


def _staff_id_card_payload(user, display_year=None):
    """Front/back print row for one ready staff member, matching student card processing."""
    _sync_staff_id_card(user, academic_year=display_year)
    photo_path = _staff_id_disk_path(user.id_card_photo_path)
    signature_path = _staff_id_disk_path(user.id_card_signature_path)
    role = canonical_role(user)
    role_labels = {
        'admin': 'Administrator',
        'principal': 'Principal',
        'teacher': 'Teacher',
        'registrar': 'Registrar',
        'registry': 'Registrar',
        'vpa': 'Vice Principal Academics',
        'vpi': 'Vice Principal Operations',
        'dean': 'Dean',
        'business': 'Business Office',
    }
    return {
        'student': user,
        'card_kind': 'staff',
        'staff_id': f'FLPA-{int(user.id):04d}',
        'position': role_labels.get(role, (user.role or 'Staff').title()),
        'photo_path': photo_path,
        'photo_url': _staff_id_photo_url(user),
        'signature_path': signature_path,
        'signature_url': (
            url_for('static', filename=user.id_card_signature_path)
            if signature_path else None
        ),
        'signature_mark': _staff_signature_mark(user),
        'expiration_date': user.id_expiration_date,
        'qr_code_data_uri': None,
        'class_label': 'STAFF',
    }


def _staff_id_cards(display_year=None):
    users = User.query.filter(
        User.role.in_(list(STAFF_ID_CARD_ROLES)),
        User.is_active.is_(True),
    ).order_by(User.full_name.asc()).all()
    dirty = False
    cards = []
    for user in users:
        before_ready = user.staff_id_card_ready
        before_exp = user.id_expiration_date
        _sync_staff_id_card(user, academic_year=display_year)
        if user.staff_id_card_ready != before_ready or user.id_expiration_date != before_exp:
            dirty = True
        if user.staff_id_card_ready:
            cards.append(_staff_id_card_payload(user, display_year))
    if dirty:
        db.session.commit()
    return cards


def _stream_staff_id_cards_pdf(cards):
    try:
        buffer = build_class_id_cards_pdf(
            cards,
            brand=school_print_brand(),
            logo_path=_school_logo_disk_path(),
            seal_path=_liberia_seal_disk_path(),
        )
    except Exception:
        logger.exception('Staff ID card PDF failed; retrying without logos')
        buffer = build_class_id_cards_pdf(cards, brand=school_print_brand())
    return _id_cards_pdf_attachment_response(buffer, 'FLPA_Staff_ID_Cards.pdf')


@app.route('/id-cards/staff', methods=['GET'], endpoint='staff_id_cards_folder')
@login_required
def staff_id_cards_folder():
    """Registrar/VPI folder for active staff and teachers."""
    denied = _staff_id_office_guard()
    if denied:
        return denied
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    users = User.query.filter(
        User.role.in_(list(STAFF_ID_CARD_ROLES)),
        User.is_active.is_(True),
    ).order_by(User.full_name.asc()).all()
    ready_cards = _staff_id_cards(display_year)
    ready_ids = {card['student'].id for card in ready_cards}
    staff_cards = [_staff_id_card_payload(user, display_year) for user in users]
    buildable = sum(
        1 for user in users
        if not _staff_id_disk_path(user.id_card_photo_path)
        and _staff_profile_photo_source(user)
    )
    return render_template(
        'id_cards/staff_folder.html',
        staff_users=users,
        staff_cards=staff_cards,
        ready_ids=ready_ids,
        cards=ready_cards,
        staff_count=len(users),
        ready_count=len(ready_cards),
        buildable_count=buildable,
        printed_at=datetime.now(timezone.utc),
        download_url=url_for('download_staff_id_cards'),
    )


# rembg takes a few seconds per portrait, so a click builds a slice of the folder
# rather than risking a proxy timeout on a school-sized staff list.
_STAFF_ID_BUILD_BATCH = 6


@app.route('/id-cards/staff/build-from-accounts', methods=['POST'], endpoint='build_staff_ids_from_accounts')
@login_required
def build_staff_ids_from_accounts():
    """Fill missing staff card photos from the account avatars, background removed."""
    denied = _staff_id_office_guard()
    if denied:
        return denied
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    users = User.query.filter(
        User.role.in_(list(STAFF_ID_CARD_ROLES)),
        User.is_active.is_(True),
    ).order_by(User.full_name.asc()).all()

    built = []
    failed = []
    no_photo = []
    remaining = 0
    for user in users:
        if _staff_id_disk_path(user.id_card_photo_path):
            continue
        if not _staff_profile_photo_source(user):
            no_photo.append(user.full_name)
            continue
        if len(built) + len(failed) >= _STAFF_ID_BUILD_BATCH:
            remaining += 1
            continue
        if _adopt_profile_photo_as_staff_id(user):
            _sync_staff_id_card(user, academic_year=display_year)
            built.append(user.full_name)
        else:
            failed.append(user.full_name)

    if built:
        db.session.commit()
        flash(
            'Built %d staff ID card%s from account photos.'
            % (len(built), '' if len(built) == 1 else 's'),
            'success',
        )
    else:
        db.session.rollback()
    if remaining:
        flash(
            'run again to build the remaining %d.' % remaining,
            'info',
        )
    if failed:
        flash(
            'Background removal could not use the account photo for: %s. '
            'Upload a clearer head-and-shoulders photo for them.' % ', '.join(failed),
            'warning',
        )
    if no_photo:
        flash('No account photo on file for: %s.' % ', '.join(no_photo), 'warning')
    if not built and not failed and not no_photo:
        flash('Every active staff member already has an ID photo.', 'info')
    return redirect(url_for('staff_id_cards_folder'))


@app.route('/id-cards/staff/<int:user_id>/use-account-photo', methods=['POST'], endpoint='use_staff_account_photo')
@login_required
def use_staff_account_photo(user_id):
    """Build one staff card photo from that account's avatar instead of a new upload."""
    denied = _staff_id_office_guard()
    if denied:
        return denied
    user = db.session.get(User, user_id)
    if not user or canonical_role(user) not in STAFF_ID_CARD_ROLES:
        flash('That staff account was not found.', 'warning')
        return redirect(url_for('staff_id_cards_folder'))
    if not _staff_profile_photo_source(user):
        flash(
            f'{user.full_name} has no account photo yet. Upload the ID photo here instead.',
            'warning',
        )
        return redirect(url_for('setup_staff_id_card', user_id=user.id))
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    if not _adopt_profile_photo_as_staff_id(user):
        db.session.rollback()
        flash(ID_PHOTO_REMBG_FAIL_MESSAGE, 'danger')
        return redirect(url_for('setup_staff_id_card', user_id=user.id))
    _sync_staff_id_card(user, academic_year=display_year)
    db.session.commit()
    if user.staff_id_card_ready:
        flash(f'Staff ID card is ready for {user.full_name}.', 'success')
        return redirect(url_for('print_staff_id_card', user_id=user.id))
    flash('The account photo was prepared, but this account is not active for printing.', 'warning')
    return redirect(url_for('setup_staff_id_card', user_id=user.id))


@app.route('/id-cards/staff/download', methods=['GET'], endpoint='download_staff_id_cards')
@login_required
def download_staff_id_cards():
    """Download one PDF containing all ready staff and teacher cards."""
    denied = _staff_id_office_guard()
    if denied:
        return denied
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    cards = _staff_id_cards(display_year)
    if not cards:
        flash('No ready staff or teacher ID cards are available. Upload ID files first.', 'warning')
        return redirect(url_for('staff_id_cards_folder'))
    return _stream_staff_id_cards_pdf(cards)


@app.route('/id-cards/staff/<int:user_id>', methods=['GET'], endpoint='print_staff_id_card')
@login_required
def print_staff_id_card(user_id):
    """Preview or download one active staff or teacher ID card."""
    denied = _staff_id_office_guard()
    if denied:
        return denied
    user = db.session.get(User, user_id)
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    if not user or canonical_role(user) not in STAFF_ID_CARD_ROLES or not user.is_active:
        flash('That active staff account was not found.', 'warning')
        return redirect(url_for('staff_id_cards_folder'))
    _sync_staff_id_card(user, academic_year=display_year)
    db.session.commit()
    if not user.staff_id_card_ready:
        flash(
            f'ID card is not ready for {user.full_name}. Upload the staff photo and signature first.',
            'warning',
        )
        return redirect(url_for('setup_staff_id_card', user_id=user.id))
    card = _staff_id_card_payload(user, display_year)
    if str(request.args.get('download') or '').strip().lower() in {'1', 'true', 'yes', 'pdf'}:
        return _stream_staff_id_cards_pdf([card])
    # Same CR80 sheet the students use, so what the office sees is what the PDF prints.
    return render_template(
        'id_cards/print_batch.html',
        klass=None,
        display_year=display_year,
        cards=[card],
        skipped=[],
        scope_label=user.full_name,
        printed_at=datetime.now(timezone.utc),
        printed_by=current_user.full_name or current_user.email,
        liberia_seal_url=liberia_seal_static_url(),
        qr_localhost_warning=False,
        back_url=url_for('staff_id_cards_folder'),
        download_url=url_for('print_staff_id_card', user_id=user.id, download=1),
        download_filename=f'FLPA_Staff_ID_{user.id:04d}.pdf',
        refresh_photos_url=url_for('refresh_staff_id_photo', user_id=user.id),
    )


@app.route('/id-cards/staff/<int:user_id>/setup', methods=['GET', 'POST'], endpoint='setup_staff_id_card')
@login_required
def setup_staff_id_card(user_id):
    """Upload or replace the staff ID-card photo and signature, like the student setup route."""
    denied = _staff_id_office_guard()
    if denied:
        return denied
    user = db.session.get(User, user_id)
    if not user or canonical_role(user) not in STAFF_ID_CARD_ROLES:
        flash('That staff account was not found.', 'warning')
        return redirect(url_for('staff_id_cards_folder'))

    if request.method == 'POST':
        try:
            photo = _first_uploaded_file('photo')
            signature = _first_uploaded_file('signature')
            saved = False
            if photo and (photo.filename or '').strip():
                raw = photo.read()
                photo.seek(0)
                _filename, rel_path = _save_id_card_image(
                    photo, STAFF_ID_PHOTO_SUBDIR, user.id, 'photo'
                )
                _store_staff_id_photo_original(
                    user, raw, os.path.splitext(photo.filename or '')[1].lower()
                )
                user.id_card_photo_path = rel_path
                saved = True
            if signature and (signature.filename or '').strip():
                _filename, rel_path = _save_id_card_image(
                    signature, 'staff_signatures', user.id, 'signature'
                )
                user.id_card_signature_path = rel_path
                saved = True
            if not saved and not _staff_id_disk_path(user.id_card_photo_path):
                flash(
                    'Choose a staff photo before saving. A file picked before an error is not '
                    'kept by the browser, so select it again.',
                    'warning',
                )
                return redirect(url_for('setup_staff_id_card', user_id=user.id))
            display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
            _sync_staff_id_card(user, academic_year=display_year)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return redirect(url_for('setup_staff_id_card', user_id=user.id))
        except Exception:
            db.session.rollback()
            logger.exception('Staff ID file upload failed for user %s', user.id)
            flash('The staff ID files could not be saved. Please try again.', 'danger')
            return redirect(url_for('setup_staff_id_card', user_id=user.id))

        if user.staff_id_card_ready:
            flash(f'Staff ID card is ready for {user.full_name}.', 'success')
            return redirect(url_for('print_staff_id_card', user_id=user.id))
        # The signature is generated from the staff name, so only the photo can be missing.
        if not _staff_id_disk_path(user.id_card_photo_path):
            flash('Staff ID files saved, but the staff photo is still needed.', 'warning')
        else:
            flash('Staff ID files saved, but this account is not active for printing.', 'warning')
        return redirect(url_for('staff_id_cards_folder'))

    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    _sync_staff_id_card(user, academic_year=display_year)
    db.session.commit()
    return render_template(
        'id_cards/staff_setup.html',
        user=user,
        display_year=display_year,
        photo_url=_staff_id_photo_url(user),
        has_id_photo=bool(_staff_id_disk_path(user.id_card_photo_path)),
        can_use_account_photo=bool(_staff_profile_photo_source(user)),
        signature_url=(
            url_for('static', filename=user.id_card_signature_path)
            if user.id_card_signature_path else None
        ),
        signature_mark=_staff_signature_mark(user),
    )


@app.route(
    '/id-cards/staff/<int:user_id>/refresh-photo',
    methods=['POST'],
    endpoint='refresh_staff_id_photo',
)
@login_required
def refresh_staff_id_photo(user_id):
    """Re-run background removal on the stored staff photo, like the student refresh action."""
    denied = _staff_id_office_guard()
    if denied:
        return denied
    user = db.session.get(User, user_id)
    if not user or canonical_role(user) not in STAFF_ID_CARD_ROLES:
        flash('That staff account was not found.', 'warning')
        return redirect(url_for('staff_id_cards_folder'))
    if not _staff_id_disk_path(user.id_card_photo_path):
        flash('Upload the staff ID photo before printing.', 'warning')
        return redirect(url_for('setup_staff_id_card', user_id=user.id))
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    if _skip_rembg_requested():
        flash(ID_PHOTO_SKIP_REMBG_WARNING, 'warning')
    elif _reprocess_staff_id_photo(user):
        flash(f'ID photo refreshed for {user.full_name}.', 'success')
    else:
        flash(ID_PHOTO_PRINT_STILL_PROCESSING, 'warning')
    _sync_staff_id_card(user, academic_year=display_year)
    db.session.commit()
    if user.staff_id_card_ready:
        return redirect(url_for('print_staff_id_card', user_id=user.id))
    return redirect(url_for('setup_staff_id_card', user_id=user.id))


# ------------------------- STAFF FOLDERS (VPA / PRINCIPAL) -------------------------
# One folder per employee: employment record, school duties, payroll history, and
# filed papers. The academic office owns staff records, so the gate is the same
# ACADEMIC_COMMAND_ROLES used by the other VPA/Principal pages.
STAFF_FOLDER_ROLES = STAFF_ID_CARD_ROLES
STAFF_DOC_ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf'}
STAFF_DOC_MAX_BYTES = 12 * 1024 * 1024
STAFF_EMPLOYMENT_TYPES = ('Full-time', 'Part-time', 'Contract', 'Volunteer', 'Probation')


def _staff_folder_guard():
    """None when the viewer is the academic office; otherwise a redirect."""
    return deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)


def _staff_folder_query(search=None, role=None, include_inactive=False):
    query = User.query.filter(User.role.in_(list(STAFF_FOLDER_ROLES)))
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    if role and role in STAFF_FOLDER_ROLES:
        query = query.filter(User.role == role)
    term = (search or '').strip()
    if term:
        like = f'%{term}%'
        query = query.filter(db.or_(
            User.full_name.ilike(like),
            User.email.ilike(like),
            User.job_title.ilike(like),
            User.department.ilike(like),
        ))
    return query.order_by(User.full_name.asc())


def _staff_folder_record(user, display_year=None):
    """Everything the folder shows for one employee, gathered in one place."""
    teacher = getattr(user, 'teacher_profile', None)
    subjects = []
    homerooms = []
    if teacher:
        subjects = sorted({
            alloc.subject_name for alloc in (teacher.allocations or [])
            if alloc.subject_name
        }, key=str.lower)
        homerooms = Class.query.filter_by(teacher_id=teacher.id).order_by(Class.name.asc()).all()
    sponsored = Class.query.filter_by(sponsor_id=user.id).order_by(Class.name.asc()).all()
    payroll_records = (
        Payroll.query.filter_by(staff_id=user.id)
        .order_by(Payroll.created_on.desc())
        .limit(12)
        .all()
    )
    documents = (
        StaffDocument.query.filter_by(staff_id=user.id)
        .order_by(StaffDocument.created_at.desc())
        .all()
    )
    return {
        'user': user,
        'teacher': teacher,
        'role_label': dashboard_role_label(user),
        'staff_code': f'FLPA-{int(user.id):04d}',
        'subjects': subjects,
        'homerooms': homerooms,
        'sponsored_classes': sponsored,
        'payroll_records': payroll_records,
        'documents': documents,
        'document_count': len(documents),
        'display_year': display_year,
    }


def _staff_folder_or_redirect(user_id):
    """(user, None) when this account is a staff folder; (None, redirect) otherwise."""
    user = db.session.get(User, user_id)
    if not user or canonical_role(user) not in STAFF_FOLDER_ROLES:
        flash('That staff record was not found.', 'warning')
        return None, redirect(url_for('staff_folders'))
    return user, None


def _parse_staff_date(raw):
    value = (raw or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


@app.route('/staff/folders', methods=['GET'], endpoint='staff_folders')
@login_required
def staff_folders():
    """Directory of staff folders for the VPA and Principal offices."""
    blocked = _staff_folder_guard()
    if blocked:
        return blocked

    search = (request.args.get('q') or '').strip()
    role_filter = (request.args.get('role') or '').strip().lower()
    include_inactive = str(request.args.get('inactive') or '').strip().lower() in {'1', 'true', 'yes'}
    staff_users = _staff_folder_query(
        search=search, role=role_filter, include_inactive=include_inactive,
    ).all()

    doc_counts = dict(
        db.session.query(StaffDocument.staff_id, db.func.count(StaffDocument.id))
        .group_by(StaffDocument.staff_id)
        .all()
    )
    rows = [{
        'user': user,
        'role_label': dashboard_role_label(user),
        'staff_code': f'FLPA-{int(user.id):04d}',
        'document_count': doc_counts.get(user.id, 0),
        'incomplete': not (user.job_title and user.hire_date and user.telephone_number),
    } for user in staff_users]

    return render_template(
        'staff/folders.html',
        rows=rows,
        search=search,
        role_filter=role_filter,
        include_inactive=include_inactive,
        staff_roles=sorted(STAFF_FOLDER_ROLES),
        total_count=len(rows),
        incomplete_count=sum(1 for row in rows if row['incomplete']),
    )


@app.route('/staff/folders/<int:user_id>', methods=['GET'], endpoint='staff_folder_detail')
@login_required
def staff_folder_detail(user_id):
    """One employee's full folder."""
    blocked = _staff_folder_guard()
    if blocked:
        return blocked
    user, redirect_response = _staff_folder_or_redirect(user_id)
    if redirect_response:
        return redirect_response

    display_year, *_rest = resolve_dashboard_academic_year(session_key=VPA_YEAR_SESSION_KEY)
    return render_template(
        'staff/folder_detail.html',
        record=_staff_folder_record(user, display_year),
        employment_types=STAFF_EMPLOYMENT_TYPES,
        doc_type_labels=StaffDocument.DOC_TYPE_LABELS,
    )


@app.route('/staff/folders/<int:user_id>/employment', methods=['POST'], endpoint='update_staff_employment')
@login_required
def update_staff_employment(user_id):
    """Save the employment record on a staff folder."""
    blocked = _staff_folder_guard()
    if blocked:
        return blocked
    user, redirect_response = _staff_folder_or_redirect(user_id)
    if redirect_response:
        return redirect_response

    def field(name, limit):
        value = (request.form.get(name) or '').strip()
        return value[:limit] if value else None

    user.job_title = field('job_title', 120)
    user.department = field('department', 120)
    employment_type = (request.form.get('employment_type') or '').strip()
    user.employment_type = employment_type if employment_type in STAFF_EMPLOYMENT_TYPES else None
    user.hire_date = _parse_staff_date(request.form.get('hire_date'))
    user.date_of_birth = _parse_staff_date(request.form.get('date_of_birth'))
    user.gender = field('gender', 20)
    user.national_id_number = field('national_id_number', 60)
    user.highest_qualification = field('highest_qualification', 160)
    user.emergency_contact_name = field('emergency_contact_name', 120)
    user.emergency_contact_phone = field('emergency_contact_phone', 40)
    user.telephone_number = field('telephone_number', 20)
    user.home_address = field('home_address', 255)
    user.staff_notes = ((request.form.get('staff_notes') or '').strip() or None)

    db.session.commit()
    flash(f'Employment record saved for {user.full_name}.', 'success')
    return redirect(url_for('staff_folder_detail', user_id=user.id))


@app.route('/staff/folders/<int:user_id>/documents', methods=['POST'], endpoint='upload_staff_document')
@login_required
def upload_staff_document(user_id):
    """File a scan or document into this employee's folder."""
    blocked = _staff_folder_guard()
    if blocked:
        return blocked
    user, redirect_response = _staff_folder_or_redirect(user_id)
    if redirect_response:
        return redirect_response

    folder_url = url_for('staff_folder_detail', user_id=user.id)
    upload = request.files.get('scan_file') or request.files.get('upload_file') or request.files.get('document')
    if not upload or not (upload.filename or '').strip():
        flash("Choose a scan or file to place in this staff folder.", 'warning')
        return redirect(folder_url)

    original = secure_filename(upload.filename) or 'document'
    ext = os.path.splitext(original)[1].lower()
    if ext not in STAFF_DOC_ALLOWED_EXT:
        flash('Use a photo (JPG, PNG, WEBP) or a PDF.', 'warning')
        return redirect(folder_url)

    payload = upload.read()
    if not payload:
        flash('That scan was empty. Please try again.', 'warning')
        return redirect(folder_url)
    if len(payload) > STAFF_DOC_MAX_BYTES:
        flash('That file is too large. Maximum size is 12 MB.', 'warning')
        return redirect(folder_url)

    doc_type = (request.form.get('doc_type') or 'other').strip().lower()
    if doc_type not in StaffDocument.DOC_TYPE_LABELS:
        doc_type = 'other'
    title = (request.form.get('title') or '').strip() or StaffDocument.DOC_TYPE_LABELS[doc_type]

    rel_dir = os.path.join('uploads', 'staff_docs', str(user.id))
    abs_dir = os.path.join(BASE_DIR, 'static', rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}{ext}"
    with open(os.path.join(abs_dir, stored_name), 'wb') as handle:
        handle.write(payload)

    db.session.add(StaffDocument(
        staff_id=user.id,
        uploaded_by_id=current_user.id,
        title=title[:200],
        doc_type=doc_type,
        original_filename=original[:255],
        file_path=os.path.join(rel_dir, stored_name).replace('\\', '/'),
        mime_type=upload.mimetype or None,
    ))
    db.session.commit()
    flash(f"Document filed in {user.full_name}'s folder.", 'success')
    return redirect(folder_url)


@app.route(
    '/staff/folders/<int:user_id>/documents/<int:document_id>/file',
    methods=['GET'],
    endpoint='view_staff_document',
)
@login_required
def view_staff_document(user_id, document_id):
    """Open one filed staff document."""
    blocked = _staff_folder_guard()
    if blocked:
        return blocked
    document = db.session.get(StaffDocument, document_id)
    if not document or document.staff_id != user_id:
        abort(404)

    rel = (document.file_path or '').replace('\\', '/').lstrip('/')
    if rel.startswith('static/'):
        rel = rel[7:]
    directory = os.path.dirname(rel)
    filename = os.path.basename(rel)
    base_dir = os.path.realpath(os.path.join(BASE_DIR, 'static', directory.replace('/', os.sep)))
    file_path = os.path.realpath(os.path.join(base_dir, filename))
    if not filename or not file_path.startswith(base_dir) or not os.path.isfile(file_path):
        abort(404)
    return send_from_directory(
        base_dir, filename, as_attachment=False,
        download_name=document.original_filename or filename,
    )


@app.route(
    '/staff/folders/<int:user_id>/documents/<int:document_id>/delete',
    methods=['POST'],
    endpoint='delete_staff_document',
)
@login_required
def delete_staff_document(user_id, document_id):
    """Remove one document from a staff folder."""
    blocked = _staff_folder_guard()
    if blocked:
        return blocked
    document = db.session.get(StaffDocument, document_id)
    if not document or document.staff_id != user_id:
        abort(404)

    rel = (document.file_path or '').replace('\\', '/').lstrip('/')
    if rel.startswith('static/'):
        rel = rel[7:]
    try:
        os.remove(os.path.join(BASE_DIR, 'static', rel.replace('/', os.sep)))
    except OSError:
        pass
    db.session.delete(document)
    db.session.commit()
    flash('Document removed from this staff folder.', 'success')
    return redirect(url_for('staff_folder_detail', user_id=user_id))


@app.route('/id-cards/print/student/<int:student_id>', methods=['GET'], endpoint='print_student_id_card')
@login_required
def print_student_id_card(student_id):
    """Print one CR80 student ID card from the registrar folder."""
    if not _require_registrar_office():
        return redirect(url_for('login'))

    student = Student.query.get_or_404(student_id)
    display_year, *_rest = resolve_dashboard_academic_year(session_key=REGISTRAR_YEAR_SESSION_KEY)
    _sync_student_id_card(student, academic_year=display_year or student.academic_year)
    db.session.commit()

    if not student.id_card_ready:
        flash(
            f'ID card is not ready for {student.full_name}. Add a photo, class, and student ID first.',
            'warning',
        )
        return _registrar_student_folder_redirect(student.id)

    cards = [_id_card_print_payload(student, display_year)]
    dirty = _prepare_ready_card_photos_for_print(cards, flash_remaining=True)
    if dirty:
        db.session.commit()
    klass = student.assigned_class
    if str(request.args.get('download') or '').strip().lower() in {'1', 'true', 'yes', 'pdf'}:
        return _stream_id_cards_pdf(klass, display_year, cards, single=True)

    return render_template(
        'id_cards/print_batch.html',
        klass=klass,
        display_year=display_year,
        cards=cards,
        skipped=[],
        printed_at=datetime.now(timezone.utc),
        printed_by=current_user.full_name or current_user.email,
        liberia_seal_url=liberia_seal_static_url(),
        qr_localhost_warning=_id_cards_qr_localhost_warning(cards),
        download_url=request.path + '?download=1',
        download_filename=id_cards_pdf_filename(klass, display_year, single=True),
        refresh_photos_url=url_for('refresh_student_id_photo', student_id=student.id),
    )


@app.route('/edit-student/<int:student_id>', methods=['GET', 'POST'])
@login_required
def edit_student(student_id):
    if canonical_role(current_user) not in {"admin", "principal", "registrar"}:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    student = Student.query.get_or_404(student_id)
    ensure_student_secure_qr_token(student)
    persist_parent_report_token(student)
    form = RegisterStudentForm(obj=student)
    context = build_registrar_dashboard_context(form=form)
    form.klass.data = student.klass_id or 0
    form.academic_year.data = student.academic_year_id or 0
    return_to = request.args.get('return_to') or request.form.get('return_to')

    if request.method == 'GET':
        form.student_id.data = student.student_id
        form.level.data = academic_level_for_student(student) or student.level
        if student.registration_fees is not None and float(student.registration_fees) > 0:
            form.registration_fees.data = f"{float(student.registration_fees):,.2f}"
        else:
            form.registration_fees.data = "0.00"
        if student.user and student.user.email:
            form.email.data = student.user.email
        form.parent_phone.data = student.parent_phone
        form.guardian_name.data = student.guardian_name or resolve_parent_guardian_name(student)

    if form.validate_on_submit():
        existing_student = Student.query.filter_by(student_id=form.student_id.data.strip()).first()
        if existing_student and existing_student.id != student_id:
            flash("That student ID is already assigned to another student.", "danger")
            return redirect(url_for('edit_student', student_id=student_id))

        try:
            registration_fee_value, academic_year_id = apply_student_form_to_record(
                student,
                form,
                registrar_name=current_user.full_name,
            )
        except ValueError as exc:
            flash(str(exc), 'danger')
            return render_template(
                'edit_student.html',
                form=form,
                student=student,
                active_year=context.get('active_year'),
                class_division_labels=context.get('class_division_labels') or {},
                return_to=return_to,
                **build_student_qr_context(student),
                **build_parent_report_qr_context(student, student.academic_year_id),
            )

        if form.photo.data and hasattr(form.photo.data, 'filename') and form.photo.data.filename:
            photo_file = form.photo.data
            filename = secure_filename(photo_file.filename)
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
            filename = f"{timestamp}_{filename}"
            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'students')
            os.makedirs(upload_dir, exist_ok=True)
            file_path = os.path.join(upload_dir, filename)
            photo_file.save(file_path)
            student.photo = os.path.join('uploads', 'students', filename).replace('\\', '/')
            student.photo_filename = filename

        _sync_student_id_card(student, academic_year=student.academic_year)

        if form.email.data:
            portal_user = link_student_portal_from_form(
                student,
                form.email.data,
                password=form.password.data or None,
            )
            issued_password = getattr(portal_user, '_issued_initial_password', None) if portal_user else None
            if portal_user and issued_password:
                flash(
                    "Student portal password saved. Print the credential slip for the student.",
                    "success",
                )
            elif not portal_user:
                flash(
                    f"Could not link portal account for '{form.email.data}'. "
                    "That email may already belong to another student account.",
                    "warning",
                )
        else:
            issued_password = None

        persist_student_portal_contact_fields(student)

        registration_payment = None
        offer_receipt = False
        if registration_fee_value > 0 and academic_year_id:
            db.session.flush()
            registration_payment, offer_receipt = collect_registration_fee_payment(
                student,
                form,
                academic_year_id,
                registration_fee_value,
                update_existing=True,
            )

        db.session.commit()
        flash(f"Student {student.full_name} has been updated.", "success")
        if (form.parent_report_pin.data or '').strip():
            flash(
                "Parent report PIN saved. Share it with the guardian for QR report access.",
                "info",
            )
        if issued_password:
            stash_registrar_credential_password(student.id, issued_password)
            return redirect(url_for(
                'print_registrar_credential_slip',
                student_id=student.id,
            ))
        if offer_receipt and registration_payment:
            return redirect(url_for(
                'print_registrar_registration_receipt',
                payment_id=registration_payment.id,
            ))
        if return_to == 'class_roster' and student.klass_id:
            return redirect(url_for(
                'registrar_class_students',
                class_id=student.klass_id,
                **registrar_dashboard_redirect_kwargs(),
            ))
        return redirect(url_for('register_student', **registrar_dashboard_redirect_kwargs()))

    return render_template(
        'edit_student.html',
        form=form,
        student=student,
        active_year=context.get('active_year'),
        class_division_labels=context.get('class_division_labels') or {},
        return_to=return_to,
        **build_student_qr_context(student),
        **build_parent_report_qr_context(student, student.academic_year_id),
    )

# =========================================================================
# 1. CORE INSTITUTIONAL CLASS PROVISIONING MATRIX CONTROLLER
# =========================================================================
@app.route('/admin/classes/create', methods=['GET', 'POST'])
@login_required
def class_create():
    """
    Main structural controller to establish operational grade classrooms,
    load active entity ledgers, and manage systemic fee rates.
    """
    # Debugging / Auditing Node: Trace systemic credential clearance elevations
    print(f"--- [SECURITY AUDIT]: User ID {current_user.id} attempting layout access with role: '{current_user.role}' ---")

    # Access Authorization Protocol Layer
    if not current_user.role:
        flash("System Protection Fault: Your account lacks a defined systemic role configuration.", "danger")
        return redirect(url_for('login'))

    # Case-Insensitive Hardened Role Verification Check
    user_role_clean = str(current_user.role).strip().lower()
    if user_role_clean not in CLASS_STRUCTURE_ROLES:
        flash(
            "This page is split by office: VPA assigns teachers and subjects; "
            "VPI sets tuition and rooms. Other roles cannot change class structure.",
            "danger",
        )
        return redirect(url_for(role_home_endpoint()))

    if request.method == 'POST':
        if user_role_clean == 'vpi':
            flash("The VPI office sets tuition and rooms on existing classes. Creating classes and assigning teachers is the VPA office.", "warning")
            return redirect(url_for('class_create'))

        name = request.form.get('name', '').strip()
        grade_level = (request.form.get('grade_level') or '').strip()
        stream = request.form.get('stream', '').strip()
        yearly_fees = request.form.get('yearly_fees', '0.00').strip()
        ca_weight_raw = request.form.get('ca_weight', '').strip()
        exam_weight_raw = request.form.get('exam_weight', '').strip()
        room_id = request.form.get('room_id') or None

        # Validate Core System Variables
        if not name or not grade_level:
            flash("Data Integrity Warning: Class Name and Grade Level are mandatory fields.", "warning")
            return redirect(url_for('class_create'))
        if len(grade_level) > 50:
            flash("Data Integrity Warning: Grade Level must be 50 characters or fewer.", "warning")
            return redirect(url_for('class_create'))

        try:
            # Enforce Architectural Record Uniqueness
            existing_class = Class.query.filter(Class.name.ilike(name)).first()
            if existing_class:
                flash(f"Structural Collision: A classroom architecture named '{name}' already exists within the system matrix.", "danger")
                return redirect(url_for('class_create'))

            # Parse and Sanitize Financial Metric Arrays
            parsed_fees = parse_currency_amount_optional(yearly_fees) if yearly_fees else 0

            grading_scheme = None
            if ca_weight_raw or exam_weight_raw:
                try:
                    ca_weight = int(ca_weight_raw) if ca_weight_raw else 60
                    exam_weight = int(exam_weight_raw) if exam_weight_raw else 40
                except ValueError:
                    flash("Data Integrity Warning: Grading weights must be whole numbers.", "warning")
                    return redirect(url_for('class_create'))
                if ca_weight < 0 or exam_weight < 0:
                    flash("Data Integrity Warning: Grading weights must be zero or positive.", "warning")
                    return redirect(url_for('class_create'))
                if ca_weight + exam_weight > 0:
                    grading_scheme = {
                        'ca_weight': ca_weight,
                        'exam_weight': exam_weight,
                    }

            # Instantiate and Commit Core Class Node Structure
            new_class = Class(
                name=name,
                grade_level=grade_level,
                stream=stream if stream else None,
                yearly_fees=parsed_fees,
                grading_scheme=grading_scheme,
                room_id=int(room_id) if room_id else None
            )
            
            db.session.add(new_class)
            db.session.commit()
            ensure_class_official_subjects(new_class, commit=True)
            
            flash(f"Operational Node: Class '{name}' has been successfully provisioned and committed!", "success")
            return redirect(url_for('class_create'))  # Redirect back to keep working seamlessly
            
        except ValueError:
            flash("Data Mutation Exception: Invalid input provided for numerical or currency metrics.", "warning")
            return redirect(url_for('class_create'))
        except Exception as e:
            db.session.rollback()
            flash(f"System Matrix Fault: Failed to establish structural class. Details: {str(e)}", "danger")
            return redirect(url_for('class_create'))

    # GET Request Processing: Query and load cross-functional entity pipelines
    # Ordered cleanly by name so your drop-down and list matrices always display professionally
    rooms = Room.query.order_by(Room.name.asc()).all()
    classes, classes_by_division = list_classes_grouped()
    teachers = Teacher.query.filter(
        func.upper(Teacher.status) == 'ACTIVE'
    ).order_by(Teacher.first_name.asc(), Teacher.last_name.asc()).all()
    if not teachers:
        teachers = Teacher.query.order_by(Teacher.first_name.asc(), Teacher.last_name.asc()).all()
    return render_template(
        'class_create.html',
        rooms=rooms,
        classes=classes,
        classes_by_division=classes_by_division,
        teachers=teachers,
        sponsor_matrix=_build_class_sponsor_matrix(classes),
        grade_level_groups=GRADE_LEVEL_GROUPS_FOR_TEMPLATE,
        is_vpa_office=normalize_role(current_user) == 'vpa',
        is_vpi_office=normalize_role(current_user) == 'vpi',
    )


# =========================================================================
# 2. DYNAMIC PHYSICAL ASSET ROOM INVENTORY CO-CONTROLLER
# =========================================================================
@app.route('/admin/rooms/quick-create', methods=['POST'])
@login_required
def room_quick_create():
    """
    Sub-routing endpoint to dynamically expand the campus physical room inventory
    directly on-the-fly without exiting active workflows.
    """
    # Enforce Mirrored Administrative Access Controls
    user_role_clean = str(current_user.role).strip().lower() if hasattr(current_user, 'role') else ''
    if user_role_clean not in FACILITY_ROLES:
        flash(
            "Physical rooms are a VPI campus-operations function. "
            "The VPA office assigns teachers and subjects, not building inventory.",
            "danger",
        )
        return redirect(url_for(role_home_endpoint()))

    # Extract and Cleanse Asset Payload
    room_name = request.form.get('room_name', '').strip()
    room_number = request.form.get('room_number', '').strip()
    capacity_raw = request.form.get('capacity', '30').strip()

    if not room_name:
        flash("Data Integrity Violation: Physical room description/identifier is mandatory.", "warning")
        return redirect(url_for('class_create'))

    try:
        # Prevent input casting breakdowns with fallback metrics
        capacity = int(capacity_raw) if capacity_raw.isdigit() else 30

        # Run Verification Scans for Existing Asset Allocations
        if room_number and hasattr(Room, 'number'):
            existing_room = Room.query.filter(
                or_(Room.name.ilike(room_name), Room.number.ilike(room_number))
            ).first()
        else:
            existing_room = Room.query.filter(Room.name.ilike(room_name)).first()

        if existing_room:
            flash(f"Asset Namespace Collision: A room identifying as '{room_name}' is already indexed in infrastructure inventory.", "warning")
            return redirect(url_for('class_create'))

        # Append New Physical Space Architecture
        room_payload = {
            'name': room_name,
            'capacity': capacity,
            'current_occupancy': 0  # Defaults to clean state initialization
        }
        if room_number and hasattr(Room, 'number'):
            room_payload['number'] = room_number

        new_room = Room(**room_payload)
        
        db.session.add(new_room)
        db.session.commit()

        flash(f"Physical Asset Matrix: Space '{room_name}' successfully added to structural inventory data streams.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"System Matrix Fault: Failed to write room record mapping. Details: {str(e)}", "danger")

    # Refresh page layout state instantly to populate newly registered components
    return redirect(url_for('class_create'))

@app.route('/admin/classes/assign-teacher', methods=['POST'])
@login_required
def assign_teacher():
    """
    Handles form submission for allocating teachers to distinct class subjects
    via the ClassSubjectTeacher intermediate matrix mapping table.
    """
    # ✨ FIX 1: Grant permission to BOTH Admin and Principal roles (case-insensitive protection)
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked

    form = AssignTeacherForm()
    
    # Safely order fallback entries alphabetically by actual database string columns
    teachers = Teacher.query.order_by(Teacher.first_name.asc(), Teacher.last_name.asc()).all()
    classes = Class.query.order_by(Class.name.asc()).all()

    # Repopulate choices dynamically so form validation passes smoothly
    form.class_id.choices = [(c.id, c.name) for c in classes]
    form.teacher_id.choices = [
        (t.id, f"{(t.first_name or '').strip()} {(t.last_name or '').strip()}".strip() or (t.user.full_name if t.user else f"Teacher {t.id}"))
        for t in teachers
    ]

    if form.validate_on_submit():
        try:
            class_id = form.class_id.data
            teacher_id = form.teacher_id.data
            
            # Access the new subject field safely from your form string payload
            subject_name = form.subject_name.data.strip() if hasattr(form, 'subject_name') else request.form.get('subject_name', '').strip()

            if not subject_name:
                flash("Validation Error: Please provide a valid Subject Name.", "warning")
                return redirect(url_for('class_create'))

            # Verify entities exist using modern SQLAlchemy standards
            klass = db.session.get(Class, class_id)
            selected_teacher = db.session.get(Teacher, teacher_id)

            if not klass or not selected_teacher:
                flash("Invalid class or teacher selection.", "danger")
                return redirect(url_for('class_create'))

            # ✨ REVOLUTIONARY FIX: Check if this specific subject assignment is already registered
            existing_assignment = ClassSubjectTeacher.query.filter_by(
                class_id=class_id,
                subject_name=subject_name
            ).first()

            if existing_assignment:
                # Resolve relationship lookup cleanly
                assigned_t = existing_assignment.teacher_node if hasattr(existing_assignment, 'teacher_node') else existing_assignment.teacher
                t_name = f"{assigned_t.first_name or ''} {assigned_t.last_name or ''}".strip() if assigned_t else "Another teacher"
                flash(f"⚠️ Conflict: {t_name} is already assigned to teach '{subject_name}' to {klass.name}!", "warning")
                return redirect(url_for('class_create'))

            # ✨ CORE CHANGE: Instantiate a multi-assignment row instead of overwriting the Class table directly!
            new_assignment = ClassSubjectTeacher(
                class_id=klass.id,
                teacher_id=selected_teacher.id,
                subject_name=subject_name
            )
            
            db.session.add(new_assignment)
            db.session.commit()

            teacher_display = (
                f"{selected_teacher.first_name or ''} {selected_teacher.last_name or ''}".strip()
                or (selected_teacher.user.full_name if selected_teacher.user else f"Teacher {selected_teacher.id}")
            )

            flash(f"✨ Success! Assigned {teacher_display} to teach '{subject_name}' in room {klass.name}.", "success")
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"[-] Critical system assignment error: {str(e)}", exc_info=True)
            flash(f"Database write error during assignment configuration: {str(e)}", "danger")
    else:
        # Flash form parsing errors if any matching token fields fail validation checks (e.g., missing CSRF token)
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"Form Validation Error [{field}]: {err}", "danger")

    # Dynamic target check: falls back smoothly to class management page layouts
    return redirect(url_for('class_create') if 'class_create' in current_app.view_functions else url_for('dashboard'))


def _stream_preset_for_class(klass):
    """Official MoE subjects for a class (division catalog, then stream fallback)."""
    if not klass:
        return []
    catalog = list(division_subjects(resolve_from_class(klass)) or ())
    if catalog:
        return catalog
    stream = (klass.stream or 'general').strip().lower()
    aliases = {
        'sci': 'science', 'sciences': 'science', 'science stream': 'science',
        'art': 'arts', 'arts stream': 'arts', 'humanities': 'arts',
        'commerce': 'commercial', 'business': 'commercial', 'commercial stream': 'commercial',
    }
    stream = aliases.get(stream, stream)
    return STREAM_SUBJECT_PRESETS.get(stream, STREAM_SUBJECT_PRESETS['general'])


@app.route('/admin/subjects', defaults={'class_id': None}, methods=['GET', 'POST'])
@app.route('/admin/subjects/<int:class_id>', methods=['GET', 'POST'])
@login_required
def subject_setup(class_id=None):
    """Curriculum catalog — define subjects offered per class (VPA / Principal / Admin)."""
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked

    classes, classes_by_division = list_classes_grouped()
    selected_class = db.session.get(Class, class_id) if class_id else None
    if selected_class is None and class_id:
        flash('That class could not be found.', 'warning')
        return redirect(url_for('subject_setup'))

    seeded = 0
    for klass in classes:
        seeded += ensure_class_official_subjects(klass)
    if seeded:
        db.session.commit()

    if request.method == 'POST' and selected_class:
        action = (request.form.get('action') or '').strip()
        try:
            if action == 'add_subject':
                subject_name = (request.form.get('subject_name') or '').strip()
                if not subject_name:
                    flash('Enter a subject name.', 'warning')
                elif ClassSubject.query.filter_by(class_id=selected_class.id, subject_name=subject_name).first():
                    flash(f'"{subject_name}" is already in this class catalog.', 'warning')
                else:
                    db.session.add(ClassSubject(class_id=selected_class.id, subject_name=subject_name))
                    db.session.commit()
                    flash(f'Added "{subject_name}" to {selected_class.name}.', 'success')

            elif action == 'remove_subject':
                subject_row_id = request.form.get('subject_id', type=int)
                row = ClassSubject.query.filter_by(id=subject_row_id, class_id=selected_class.id).first()
                if row:
                    db.session.delete(row)
                    db.session.commit()
                    flash(f'Removed "{row.subject_name}" from {selected_class.name}.', 'success')

            elif action == 'apply_preset':
                preset = _stream_preset_for_class(selected_class)
                added = 0
                for name in preset:
                    if not ClassSubject.query.filter_by(class_id=selected_class.id, subject_name=name).first():
                        db.session.add(ClassSubject(class_id=selected_class.id, subject_name=name))
                        added += 1
                db.session.commit()
                flash(f'Loaded {added} preset subject(s) for {selected_class.name}.', 'success')

            elif action == 'sync_from_teachers':
                added = 0
                for alloc in ClassSubjectTeacher.query.filter_by(class_id=selected_class.id).all():
                    if not alloc.subject_name:
                        continue
                    if not ClassSubject.query.filter_by(class_id=selected_class.id, subject_name=alloc.subject_name).first():
                        db.session.add(ClassSubject(class_id=selected_class.id, subject_name=alloc.subject_name))
                        added += 1
                db.session.commit()
                flash(f'Synced {added} subject(s) from teacher assignments.', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Could not update subject catalog: {e}', 'danger')

        return redirect(url_for('subject_setup', class_id=selected_class.id))

    class_subjects = []
    teacher_map = {}
    preset_subjects = []
    if selected_class:
        class_subjects = (
            ClassSubject.query.filter_by(class_id=selected_class.id)
            .order_by(ClassSubject.subject_name.asc())
            .all()
        )
        preset_subjects = _stream_preset_for_class(selected_class)
        for alloc in ClassSubjectTeacher.query.filter_by(class_id=selected_class.id).all():
            teacher = alloc.teacher_node if hasattr(alloc, 'teacher_node') else alloc.teacher
            if not alloc.subject_name:
                continue
            label = (
                f"{(teacher.first_name or '').strip()} {(teacher.last_name or '').strip()}".strip()
                if teacher
                else 'Assigned teacher'
            )
            teacher_map.setdefault(alloc.subject_name, [])
            if label not in teacher_map[alloc.subject_name]:
                teacher_map[alloc.subject_name].append(label)

    return render_template(
        'subject_setup.html',
        classes=classes,
        classes_by_division=classes_by_division,
        selected_class=selected_class,
        class_subjects=class_subjects,
        teacher_map=teacher_map,
        preset_subjects=preset_subjects,
    )


@app.route('/announcements', methods=['GET', 'POST'])
@login_required
def announcements():
    # 1. Secure case-insensitive executive gatekeeping
    if current_user.role.lower() not in ["admin", "teacher", "principal", "vpa", "vpi", "dean"]:
        flash("Unauthorized access to communications management.", "danger")
        return redirect(url_for(role_home_endpoint()))

    # Explicit local import from your clean forms.py file
    from forms import AnnouncementForm
    form = AnnouncementForm()
    
    # Modernized query execution syntax
    items = Announcement.query.order_by(Announcement.id.desc()).all()

    if form.validate_on_submit():
        try:
            # ✨ Smart AI Scan: Automatically catch business classification from the title string
            title_text = form.title.data.lower()
            announcement_category = 'general'
            
            if "deadline" in title_text or "due" in title_text:
                announcement_category = 'deadline'
                flash("⏰ Academic submission deadline posted successfully.", "info")
            elif "warning" in title_text or "alert" in title_text:
                announcement_category = 'warning'
                flash("⚠️ Administrative compliance warning broadcasted.", "warning")
            elif any(word in title_text for word in ["fee", "payment", "sponsor", "business", "tuition"]):
                announcement_category = 'business_finance'
                flash("💼 Business/Financial notification published to the ledger.", "success")
            else:
                flash("General school announcement posted successfully.", "success")

            model_args = {
                "title": (form.title.data or "").strip(),
                "content": (form.content.data or "").strip(),
                "target_role": form.target_audience.data,
                "author": (current_user.full_name or current_user.email or "System").strip(),
                "category": announcement_category,
            }

            announcement = Announcement(**model_args)
            
            db.session.add(announcement)
            db.session.commit()
            
            return redirect(url_for('announcements'))

        except Exception as e:
            db.session.rollback()
            flash(f"System failure processing broadcast parameters: {str(e)}", "danger")
            return redirect(url_for('announcements'))

    # ✨ FIX: Catch any WTForms validation errors (like missing inputs) and display them
    elif request.method == 'POST':
        for field, errors in form.errors.items():
            for err in errors:
                field_label = getattr(form, field).label.text if hasattr(form, field) else field
                flash(f"{field_label}: {err}", "danger")

    return render_template('announcements.html', form=form, items=items)

# ---------------------- BUSINESS MANAGEMENT -----------------------
@app.route('/business-management', methods=['GET', 'POST'])
@role_required('VPI', 'business', 'admin', 'principal')  # Enforce administrative access permissions
def business_management():
    from forms import TransactionForm, EnrollmentForm, PaymentForm
    from models import Student, AcademicYear, Class, BusinessTransaction, StudentPayment, SchoolFee
    
    # 1. Initialize Forms
    form = TransactionForm()
    enroll_form = EnrollmentForm()
    payment_form = PaymentForm()

    all_years = all_academic_years()
    active_year = get_active_academic_year()
    payment_form.academic_year.choices = [(y.id, y.name) for y in all_years]

    # Pre-fill data if provided via search query parameters
    prefill_student_id = request.args.get('student_id', type=int)
    prefill_year_id = request.args.get('year_id', type=int)

    if request.method == 'GET':
        if prefill_year_id:
            payment_form.academic_year.data = prefill_year_id
        elif active_year:
            payment_form.academic_year.data = active_year.id

    default_year_name = active_year.name if active_year else (all_years[0].name if all_years else '')
    selected_year = request.args.get('year', default_year_name)
    selected_year_obj = next((y for y in all_years if y.name == selected_year), None)
    if selected_year_obj is None and active_year:
        selected_year_obj = active_year
        selected_year = active_year.name

    payment_year = None
    if payment_form.academic_year.data:
        payment_year = db.session.get(AcademicYear, payment_form.academic_year.data)
    if payment_year is None:
        payment_year = selected_year_obj
    payment_form.student.choices = [
        (s.id, f"{s.first_name} {s.last_name} ({s.student_id})")
        for s in list_payment_students_for_year(payment_year)
    ]
    if request.method == 'GET' and prefill_student_id:
        payment_form.student.data = prefill_student_id
    
    # 2. Handle Daily Expense/Income Transaction Posting
    if 'submit_transaction' in request.form:
        if form.validate_on_submit():
            try:
                # Fetch last balance metric to compute the balance_after runner delta
                last_tx = BusinessTransaction.query.filter_by(is_deleted=False).order_by(BusinessTransaction.id.desc()).first()
                prev_balance = last_tx.balance_after if last_tx and last_tx.balance_after else 0.0
                
                amount = parse_currency_amount(form.amount.data)
                prev_balance_decimal = parse_currency_amount_optional(prev_balance)
                new_balance = (
                    prev_balance_decimal + amount
                    if form.type.data == 'income'
                    else prev_balance_decimal - amount
                )

                new_tx = BusinessTransaction(
                    date=form.date.data,
                    type=form.type.data,
                    amount=amount,
                    category=form.category.data,
                    description=form.description.data,
                    balance_after=new_balance,  # ✨ Aligned column setup
                    academic_year=selected_year
                )
                db.session.add(new_tx)
                db.session.commit()
                flash('Transaction recorded successfully!', 'success')
                return redirect(url_for('business_management', year=selected_year))
            except Exception as e:
                db.session.rollback()
                flash(f"System failure processing ledger transaction: {str(e)}", "danger")
        else:
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"Transaction Field ({field}): {err}", "danger")

    # 3. Handle Student Payment Posting Pipeline
    if 'submit_payment' in request.form:
        if payment_form.validate_on_submit():
            try:
                payment_description = (payment_form.description.data or "Tuition").strip()
                student = db.session.get(Student, payment_form.student.data)

                if not student:
                    flash("Student extraction entity record not found.", "danger")
                    return redirect(url_for('business_management', year=selected_year))

                record_student_payment_with_income(
                    student,
                    payment_form.academic_year.data,
                    payment_form.term.data,
                    parse_currency_amount(payment_form.amount_paid.data),
                    payment_description,
                    installment=payment_form.installment.data,
                )
                db.session.commit()
                flash('Student payment recorded and posted to business income.', 'success')
                return redirect(url_for('business_management', year=selected_year))
            except Exception as e:
                db.session.rollback()
                flash(f"System failure recording transaction payment configuration: {str(e)}", "danger")
        else:
            for field, errors in payment_form.errors.items():
                for err in errors:
                    flash(f"Payment Field ({field}): {err}", "danger")

    # 4. Calculate Global Financial KPIs
    income_total = db.session.query(func.sum(BusinessTransaction.amount)).filter(
        BusinessTransaction.type == 'income', BusinessTransaction.academic_year == selected_year, BusinessTransaction.is_deleted == False
    ).scalar() or 0
    
    expense_total = db.session.query(func.sum(BusinessTransaction.amount)).filter(
        BusinessTransaction.type == 'expense', BusinessTransaction.academic_year == selected_year, BusinessTransaction.is_deleted == False
    ).scalar() or 0

    # 5. Institutional Analytics (Class-by-Class Financial Health)
    classes = Class.query.all()
    class_analytics = []
    
    fee_obj = SchoolFee.query.filter_by(
        academic_year_id=selected_year_obj.id,
        fee_type='tuition',
        class_id=None,
    ).first() if selected_year_obj else None
    yearly_fee_default = fee_obj.amount if fee_obj else 0

    for k in classes:
        current_fee = k.yearly_fees if k.yearly_fees and k.yearly_fees > 0 else yearly_fee_default
        
        students_query = Student.query.filter(
            Student.klass_id == k.id,
            Student.status.in_(list(ACTIVE_ENROLLMENT_STATUSES)),
        )
        if selected_year_obj:
            students_query = students_query.filter(Student.academic_year_id == selected_year_obj.id)
        students_in_class = students_query.all()
        student_count = len(students_in_class)
        total_expected = student_count * current_fee
        total_collected = sum(
            build_student_financials_business_summary(student, selected_year_obj)["total_collected"]
            for student in students_in_class
        )
        
        class_analytics.append({
            'name': k.name,
            'students_count': student_count,
            'yearly_fee': money(current_fee),
            'total_collected': money(total_collected),
            'balance': money(total_expected - total_collected)
        })

    # 6. Search Logic for Student Payments
    student_search = request.args.get('student_search', '')
    search_results = []
    if student_search:
        search_query = Student.query.filter(
            (Student.first_name.contains(student_search))
            | (Student.last_name.contains(student_search))
            | (Student.student_id == student_search)
        )
        active_year = get_active_academic_year()
        if active_year:
            search_query = search_query.filter(
                Student.academic_year_id == active_year.id,
                Student.is_registered.is_(True),
            )
        search_results = search_query.all()

    transactions = BusinessTransaction.query.filter_by(
        academic_year=selected_year, 
        is_deleted=False
    ).order_by(BusinessTransaction.date.desc()).all()
    
    return render_template(
        'business_management.html',
        form=form,
        enroll_form=enroll_form,
        payment_form=payment_form,
        income_total=income_total,
        expense_total=expense_total,
        class_search_results=class_analytics,
        search_results=search_results,
        transactions=transactions,
        selected_year=selected_year,
        years=all_years
    )

@app.route('/delete-transaction/<int:id>', methods=['POST'])
@role_required('VPI', 'business', 'admin')
def soft_delete_transaction(id):
    tx = BusinessTransaction.query.get_or_404(id)
    # Logic: Mark as deleted instead of removing from DB
    tx.is_deleted = True
    tx.deleted_at = datetime.now(timezone.utc)
    tx.deleted_by_id = current_user.id
    # Log this for your Cybersecurity Audit
    log_security_event(f"Transaction ID {id} was soft-deleted by {current_user.username or current_user.full_name}")
    db.session.commit()
    flash('Transaction removed from view. Audit log updated.', 'info')
    return redirect(url_for('business_management'))

@app.route('/business/daily-expenses')
@role_required('VPI', 'business', 'admin')
def daily_expense_report():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    expenses = BusinessTransaction.query.filter_by(
        date=today,
        type='expense',
        is_deleted=False
    ).all()
    total = sum(e.amount for e in expenses)
    return render_template('daily_expense_report.html', expenses=expenses, total=total, date=today)

@app.route('/business-overview')
@login_required
def business_overview():
    blocked = deny_unless_roles(FISCAL_COMMAND_ROLES, academic_office=False)
    if blocked:
        return blocked

    income_total = db.session.query(func.sum(BusinessTransaction.amount)).filter(BusinessTransaction.type == "income", BusinessTransaction.is_deleted == False).scalar() or 0
    expense_total = db.session.query(func.sum(BusinessTransaction.amount)).filter(BusinessTransaction.type == "expense", BusinessTransaction.is_deleted == False).scalar() or 0
    net_total = income_total - expense_total

    recent_transactions = BusinessTransaction.query.filter_by(is_deleted=False).order_by(BusinessTransaction.date.desc()).limit(5).all()

    return render_template(
        'business_overview.html',
        income_total=income_total,
        expense_total=expense_total,
        net_total=net_total,
        recent_transactions=recent_transactions
    )

@app.route('/payroll-summary')
@login_required
def payroll_summary():
    if normalize_role(current_user) not in {'admin', 'business'}:
        flash("Unauthorized access to payroll summary.", "danger")
        return redirect(url_for('login'))

    payroll_records = Payroll.query.order_by(Payroll.created_on.desc()).all()
    total_paid = sum(record.salary_amount for record in payroll_records if record.paid)
    total_pending = sum(record.salary_amount for record in payroll_records if not record.paid)

    return render_template(
        'payroll_summary.html',
        payroll_records=payroll_records,
        total_paid=total_paid,
        total_pending=total_pending
    )

@app.route('/financial-reports')
@login_required
def financial_reports():
    blocked = deny_unless_roles(FISCAL_COMMAND_ROLES, academic_office=False)
    if blocked:
        return blocked

    years = all_academic_years()

    return render_template(
        'financial_reports.html',
        years=years
    )

def _principal_student_average(student, active_year=None):
    grade_query = Grade.query.filter_by(student_id=student.id)
    if active_year:
        grade_query = grade_query.filter_by(academic_year_id=active_year.id)
    grades = grade_query.all()
    scored = [g.score for g in grades if g.score]
    if not scored:
        return 0
    return round(sum(scored) / len(scored), 1)


def _principal_students_for_display_year(students, display_year=None):
    """Strict year filter — excludes NULL academic_year_id bleed."""
    if not display_year:
        return []
    year_id = display_year.id
    return [student for student in students if student.academic_year_id == year_id]


def _principal_summarize_students(students, display_year=None):
    scoped_students = _principal_students_for_display_year(students, display_year)
    optimal_count = 0
    at_risk_count = 0
    suspended_count = 0
    for student in scoped_students:
        average = _principal_student_average(student, display_year)
        status = (student.status or 'ACTIVE').upper()
        if status == 'SUSPENDED':
            suspended_count += 1
        elif average < 70:
            at_risk_count += 1
        else:
            optimal_count += 1
    total = len(scoped_students)
    health_pct = round((optimal_count / total) * 100) if total else 100
    return {
        'student_count': total,
        'optimal_count': optimal_count,
        'at_risk_count': at_risk_count,
        'suspended_count': suspended_count,
        'health_pct': health_pct,
    }


def _principal_students_for_class(klass, display_year=None, *, viewing_archived=False):
    """Year-scoped class roster — uses historical class resolution for archived years."""
    if not display_year or not klass:
        return []
    year_id = display_year.id
    if viewing_archived:
        grade_ids = {
            row[0] for row in db.session.query(Grade.student_id).filter(
                Grade.academic_year_id == year_id,
                Grade.class_id == klass.id,
                Grade.student_id.isnot(None),
            ).distinct()
        }
        enroll_ids = {
            row[0] for row in db.session.query(Enrollment.student_id).filter(
                Enrollment.academic_year_id == year_id,
                Enrollment.class_id == klass.id,
                Enrollment.student_id.isnot(None),
            ).distinct()
        }
        live_ids = {
            row[0] for row in db.session.query(Student.id).filter(
                Student.academic_year_id == year_id,
                Student.klass_id == klass.id,
            )
        }
        ids = grade_ids | enroll_ids | live_ids
        if not ids:
            return []
        return (
            Student.query.filter(Student.id.in_(ids))
            .order_by(Student.last_name.asc(), Student.first_name.asc())
            .all()
        )

    roster = (
        students_for_academic_year(year_id, registered_only=True)
        .filter(Student.klass_id == klass.id)
        .filter(~Student.status.in_(list(ALUMNI_STATUSES)))
        .order_by(Student.last_name.asc(), Student.first_name.asc())
        .all()
    )
    if klass.grade_level is not None:
        roster = [
            student for student in roster
            if _student_grade_level(student) is None
            or _grades_match(_student_grade_level(student), klass.grade_level)
        ]
    return roster


def _principal_unallocated_students(display_year=None, *, viewing_archived=False):
    """Students tagged to the display year with no class assignment for that year."""
    if not display_year:
        return []
    year_id = display_year.id
    if viewing_archived:
        mapping = _student_class_map_for_display_year(display_year, viewing_archived=True)
        year_ids = set(_student_ids_with_year_history(year_id))
        unassigned_ids = [sid for sid in year_ids if not mapping.get(sid)]
        if not unassigned_ids:
            return []
        roster = (
            Student.query.filter(Student.id.in_(unassigned_ids))
            .order_by(Student.last_name.asc(), Student.first_name.asc())
            .all()
        )
        return roster
    return (
        _students_for_display_year(display_year, history_mode=False)
        .filter(Student.klass_id.is_(None))
        .order_by(Student.last_name.asc(), Student.first_name.asc())
        .all()
    )


def _principal_build_class_portfolios(display_year=None, search_class='', *, viewing_archived=False):
    portfolios = []
    search_class = (search_class or '').strip().lower()
    for klass in Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all():
        if search_class:
            haystack = ' '.join(filter(None, [
                klass.name,
                klass.stream,
                str(klass.grade_level),
            ])).lower()
            if search_class not in haystack:
                continue
        roster = _principal_students_for_class(
            klass, display_year, viewing_archived=viewing_archived,
        )
        summary = _principal_summarize_students(roster, display_year)
        portfolios.append({
            'klass': klass,
            **summary,
        })
    return portfolios


def _principal_build_unallocated_portfolio(display_year=None, *, viewing_archived=False):
    students = _principal_unallocated_students(
        display_year, viewing_archived=viewing_archived,
    )
    if not students:
        return None
    return _principal_summarize_students(students, display_year)


def _principal_filter_students(students, search_query='', status_filter='', display_year=None):
    filtered = []
    search_query = (search_query or '').strip().lower()
    for student in students:
        average = _principal_student_average(student, display_year)
        student.average = average
        status = (student.status or 'ACTIVE').upper()
        if search_query:
            haystack = ' '.join(filter(None, [
                student.first_name,
                student.last_name,
                student.student_id,
                student.full_name,
            ])).lower()
            if search_query not in haystack:
                continue
        if status_filter == 'failing' and average >= 70:
            continue
        if status_filter == 'suspended' and status != 'SUSPENDED':
            continue
        filtered.append(student)
    return filtered


# -------------------------- PAYROLL -------------------------------
@app.route('/principal/dashboard')
@role_required('Principal') # Ensure only the Principal can see this
def principal_dashboard():
    from datetime import timedelta
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=PRINCIPAL_YEAR_SESSION_KEY,
    )
    year_name = display_year.name if display_year else None

    # 1. Financial Stats (scoped to selected year when available)
    revenue_q = db.session.query(db.func.sum(BusinessTransaction.amount)).filter_by(
        type='income', is_deleted=False
    )
    expense_q = db.session.query(db.func.sum(BusinessTransaction.amount)).filter_by(
        type='expense', is_deleted=False
    )
    tx_count_q = BusinessTransaction.query.filter_by(is_deleted=False)
    if year_name:
        revenue_q = revenue_q.filter(BusinessTransaction.academic_year == year_name)
        expense_q = expense_q.filter(BusinessTransaction.academic_year == year_name)
        tx_count_q = tx_count_q.filter(BusinessTransaction.academic_year == year_name)
    total_revenue = revenue_q.scalar() or 0
    total_expenses = expense_q.scalar() or 0
    financial_stats = {
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_profit": total_revenue - total_expenses,
        "total_transactions": tx_count_q.count(),
    }

    # 2. Academic Stats (VPA Data - Liberian 70% Standard, year-scoped)
    year_students = (
        _students_for_display_year(display_year, history_mode=viewing_archived).all()
        if display_year else []
    )
    total_student_count = len(year_students)
    # Same enrollment counters as registrar roster (registered, non-alumni, year-scoped).
    counts = _registrar_counts_for_year(display_year, viewing_archived=viewing_archived)
    failing_students = [
        student for student in year_students
        if _principal_student_average(student, display_year) < 70
    ]
    academic_stats = {
        "passing_rate": round(((total_student_count - len(failing_students)) / total_student_count * 100), 1) if total_student_count > 0 else 0,
        "failing_count": len(failing_students),
    }

    # 3. Disciplinary Stats (Dean Data)
    active_suspensions = Suspension.query.filter(Suspension.return_date > datetime.now(timezone.utc)).count()
    disciplinary_stats = {
        "active_suspensions": active_suspensions
    }
    # 4. Security Stats (Admin Data)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    blocked_ips = SecurityLog.query.filter(SecurityLog.timestamp > yesterday, SecurityLog.event.contains('BLOCKED_IP')).count()
    security_stats = {
        "blocked_ips": blocked_ips
    }
    # 5. Active Student Condition Ledger (class folders + drill-down)
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    search_class = request.args.get('search_class', '')
    class_id = request.args.get('class_id', type=int)
    selected_folder = (request.args.get('folder') or '').strip().lower()
    selected_class = db.session.get(Class, class_id) if class_id else None

    class_portfolios = _principal_build_class_portfolios(
        display_year, search_class, viewing_archived=viewing_archived,
    )
    unallocated_portfolio = _principal_build_unallocated_portfolio(
        display_year, viewing_archived=viewing_archived,
    )

    students_list = []
    selected_class_stats = None
    if selected_folder == 'unallocated':
        roster = _principal_unallocated_students(
            display_year, viewing_archived=viewing_archived,
        )
        students_list = _principal_filter_students(
            roster, search_query, status_filter, display_year
        )
        selected_class_stats = _principal_summarize_students(roster, display_year)
    elif selected_class:
        roster = _principal_students_for_class(
            selected_class, display_year, viewing_archived=viewing_archived,
        )
        students_list = _principal_filter_students(
            roster, search_query, status_filter, display_year
        )
        selected_class_stats = _principal_summarize_students(roster, display_year)

    # 6. Recent Activity Feeds
    recent_tx_q = BusinessTransaction.query.filter_by(is_deleted=False)
    if year_name:
        recent_tx_q = recent_tx_q.filter(BusinessTransaction.academic_year == year_name)
    recent_transactions = recent_tx_q.order_by(BusinessTransaction.id.desc()).limit(14).all()

    today_key = datetime.now(timezone.utc).date().isoformat()
    today_income = Decimal('0.00')
    today_expense = Decimal('0.00')
    last_activity_date = None
    last_activity_description = None
    ledger_health = {
        'entries': len(recent_transactions),
        'income_total': Decimal(str(total_revenue or 0)),
        'expense_total': Decimal(str(total_expenses or 0)),
        'net_total': Decimal(str((total_revenue or 0) - (total_expenses or 0))),
        'today_income': Decimal('0.00'),
        'today_expense': Decimal('0.00'),
        'today_net': Decimal('0.00'),
        'latest_balance': Decimal('0.00'),
        'latest_tx_type': None,
        'latest_tx_amount': Decimal('0.00'),
    }

    if recent_transactions:
        latest = recent_transactions[0]
        ledger_health['latest_balance'] = parse_currency_amount_optional(latest.balance_after)
        ledger_health['latest_tx_type'] = (latest.type or '').lower()
        ledger_health['latest_tx_amount'] = parse_currency_amount_optional(latest.amount)
        last_activity_date = latest.date
        last_activity_description = latest.description

    for tx in recent_transactions:
        tx_amount = parse_currency_amount_optional(tx.amount)
        tx_date = (tx.date or '').strip()
        if tx_date != today_key:
            continue
        if (tx.type or '').lower() == 'income':
            today_income += tx_amount
        elif (tx.type or '').lower() == 'expense':
            today_expense += tx_amount

    ledger_health['today_income'] = today_income
    ledger_health['today_expense'] = today_expense
    ledger_health['today_net'] = today_income - today_expense

    # 6.5 Transaction anomaly scan (professional oversight)
    anomaly_flags = []

    def _money2(value):
        return parse_currency_amount_optional(value).quantize(Decimal('0.01'))

    # Rule A: unusually large expenses compared to recent expense pattern
    expense_amounts = [
        _money2(tx.amount)
        for tx in recent_transactions
        if (tx.type or '').lower() == 'expense'
    ]
    avg_expense = (
        (sum(expense_amounts, Decimal('0.00')) / Decimal(len(expense_amounts)))
        if expense_amounts else Decimal('0.00')
    )
    large_expense_threshold = max(Decimal('500.00'), (avg_expense * Decimal('2.50')).quantize(Decimal('0.01')))
    for tx in recent_transactions:
        tx_type = (tx.type or '').lower()
        tx_amount = _money2(tx.amount)
        if tx_type == 'expense' and tx_amount >= large_expense_threshold:
            anomaly_flags.append({
                'level': 'high',
                'code': 'LARGE_EXPENSE',
                'title': 'Large expense detected',
                'detail': f"{tx.date}: ${tx_amount:,.2f} ({(tx.category or 'Uncategorized')})",
            })

    # Rule B: repeated same amount/type on same day
    repeat_map = {}
    for tx in recent_transactions:
        key = (
            (tx.date or '').strip(),
            (tx.type or '').strip().lower(),
            _money2(tx.amount),
        )
        repeat_map[key] = repeat_map.get(key, 0) + 1
    for (tx_date, tx_type, tx_amount), count in repeat_map.items():
        if count >= 3:
            anomaly_flags.append({
                'level': 'medium',
                'code': 'REPEAT_PATTERN',
                'title': 'Repeated amount pattern',
                'detail': f"{tx_date}: {count} x {tx_type} at ${tx_amount:,.2f}",
            })

    # Rule C: uncategorized transactions
    uncategorized_count = sum(
        1 for tx in recent_transactions
        if not (tx.category or '').strip()
    )
    if uncategorized_count:
        anomaly_flags.append({
            'level': 'low',
            'code': 'MISSING_CATEGORY',
            'title': 'Uncategorized transactions',
            'detail': f"{uncategorized_count} recent entries are missing category labels",
        })

    # Rule D: daily cash movement warning
    if ledger_health['today_net'] < 0:
        anomaly_flags.append({
            'level': 'medium',
            'code': 'NEGATIVE_DAILY_NET',
            'title': 'Negative daily movement',
            'detail': f"Today net is ${ledger_health['today_net']:,.2f}",
        })

    # Rule E: cent-level running balance drift across adjacent ledger entries
    chron_tx = list(reversed(recent_transactions))
    drift_count = 0
    for idx in range(1, len(chron_tx)):
        prev_tx = chron_tx[idx - 1]
        tx = chron_tx[idx]
        prev_balance = parse_currency_amount_optional(prev_tx.balance_after)
        curr_balance = parse_currency_amount_optional(tx.balance_after)
        tx_amount = parse_currency_amount_optional(tx.amount)
        tx_type = (tx.type or '').lower()
        if tx_type == 'income':
            expected_balance = prev_balance + tx_amount
        elif tx_type == 'expense':
            expected_balance = prev_balance - tx_amount
        else:
            continue
        if abs((curr_balance - expected_balance).quantize(Decimal('0.01'))) > Decimal('0.01'):
            drift_count += 1
    if drift_count:
        anomaly_flags.append({
            'level': 'high',
            'code': 'BALANCE_DRIFT',
            'title': 'Running balance drift detected',
            'detail': f"{drift_count} ledger transitions failed cent-level reconciliation",
        })

    anomaly_counts = {
        'high': sum(1 for a in anomaly_flags if a['level'] == 'high'),
        'medium': sum(1 for a in anomaly_flags if a['level'] == 'medium'),
        'low': sum(1 for a in anomaly_flags if a['level'] == 'low'),
        'total': len(anomaly_flags),
    }

    security_events = SecurityLog.query.order_by(SecurityLog.timestamp.desc()).limit(5).all()
    class_portfolios_by_division = group_items_by_class(
        class_portfolios, lambda portfolio: portfolio.get('klass'),
    )

    return render_template('principal_dashboard.html',
                            financial_stats=financial_stats,
                           academic_stats=academic_stats,
                           counts=counts,
                           disciplinary_stats=disciplinary_stats,
                           security_stats=security_stats,
                           students=students_list,
                           class_portfolios=class_portfolios,
                           class_portfolios_by_division=class_portfolios_by_division,
                           unallocated_portfolio=unallocated_portfolio,
                           selected_class=selected_class,
                           selected_folder=selected_folder if selected_folder == 'unallocated' else '',
                           selected_class_stats=selected_class_stats,
                           class_id=class_id,
                           search_class=search_class,
                           recent_transactions=recent_transactions,
                           ledger_health=ledger_health,
                           anomaly_flags=anomaly_flags,
                           anomaly_counts=anomaly_counts,
                           last_activity_date=last_activity_date,
                           last_activity_description=last_activity_description,
                           security_events=security_events,
                           current_user=current_user,
                           active_year=active_year,
                           display_year=display_year,
                           years=years,
                           all_years=years,
                           viewing_archived=viewing_archived)

# -------------------------- VPI DASHBOARD -------------------------------
def _vpi_year_tx_query(selected_year_name):
    return BusinessTransaction.query.filter(
        BusinessTransaction.is_deleted == False,
        BusinessTransaction.academic_year == selected_year_name,
    )


def _vpi_class_collection_snapshots(display_year, *, viewing_archived=False):
    snapshots = []
    fee_obj = SchoolFee.query.filter_by(
        academic_year_id=display_year.id,
        fee_type='tuition',
        class_id=None,
    ).first() if display_year else None
    yearly_fee_default = fee_obj.amount if fee_obj else 0
    paid_by_student = {}
    if display_year:
        paid_by_student = dict(
            db.session.query(
                StudentPayment.student_id,
                func.coalesce(func.sum(StudentPayment.amount_paid), 0),
            )
            .filter(StudentPayment.academic_year_id == display_year.id)
            .group_by(StudentPayment.student_id)
            .all()
        )

    for klass in Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all():
        current_fee = klass.yearly_fees if klass.yearly_fees and klass.yearly_fees > 0 else yearly_fee_default
        students = (
            _principal_students_for_class(
                klass, display_year, viewing_archived=viewing_archived,
            )
            if display_year else []
        )
        collected = sum(
            Decimal(str(paid_by_student.get(student.id, 0) or 0))
            for student in students
        )
        expected = Decimal(str(current_fee)) * len(students)
        balance = max(Decimal('0'), expected - collected)
        rate = round(float(collected / expected * 100), 1) if expected > 0 else 0.0
        snapshots.append({
            'klass': klass,
            'student_count': len(students),
            'expected': money(expected),
            'collected': money(collected),
            'balance': money(balance),
            'collection_rate': rate,
        })
    return snapshots


def _vpi_outstanding_students(display_year, limit=10, *, viewing_archived=False):
    rows = []
    if not display_year:
        return rows
    paid_by_student = dict(
        db.session.query(
            StudentPayment.student_id,
            func.coalesce(func.sum(StudentPayment.amount_paid), 0),
        )
        .filter(StudentPayment.academic_year_id == display_year.id)
        .group_by(StudentPayment.student_id)
        .all()
    )
    fee_by_class = {c.id: Decimal(str(c.yearly_fees or 0)) for c in Class.query.all()}
    students = _students_for_display_year(display_year, history_mode=viewing_archived).all()
    for student in students:
        fee = fee_by_class.get(student.klass_id) or Decimal('0')
        paid = Decimal(str(paid_by_student.get(student.id, 0) or 0))
        balance = fee - paid
        if balance > 0:
            rows.append({
                'student': student,
                'yearly_fee': money(fee),
                'total_paid': money(paid),
                'balance': money(balance),
            })
    rows.sort(key=lambda row: row['balance'], reverse=True)
    return rows[:limit]


@app.route('/vpi/dashboard')
@login_required
@role_required('VPI', 'principal', 'admin')
def vpi_dashboard():
    """VPI — tuition, ledger, collections, and campus fiscal operations (not academics)."""
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=VPI_YEAR_SESSION_KEY,
    )
    selected_year = display_year
    selected_year_name = display_year.name if display_year else (
        active_year.name if active_year else (years[0].name if years else '')
    )

    year_filter = _vpi_year_tx_query(selected_year_name) if selected_year_name else BusinessTransaction.query.filter_by(is_deleted=False)

    def _year_ledger_sum(tx_type):
        query = db.session.query(func.sum(BusinessTransaction.amount)).filter(
            BusinessTransaction.is_deleted == False,
            BusinessTransaction.type == tx_type,
        )
        if selected_year_name:
            query = query.filter(BusinessTransaction.academic_year == selected_year_name)
        return query.scalar() or 0

    total_revenue = _year_ledger_sum('income')
    total_expenses = _year_ledger_sum('expense')
    net_profit = float(total_revenue) - float(total_expenses)

    tuition_collected = Decimal('0')
    total_expected = Decimal('0')
    students_with_balance = 0
    if selected_year:
        tuition_collected = Decimal(str(
            db.session.query(func.coalesce(func.sum(StudentPayment.amount_paid), 0))
            .filter(StudentPayment.academic_year_id == selected_year.id)
            .scalar() or 0
        ))
        year_students = _students_for_display_year(
            selected_year, history_mode=viewing_archived,
        ).with_entities(Student.id, Student.klass_id)
        paid_by_student = dict(
            db.session.query(
                StudentPayment.student_id,
                func.coalesce(func.sum(StudentPayment.amount_paid), 0),
            )
            .filter(StudentPayment.academic_year_id == selected_year.id)
            .group_by(StudentPayment.student_id)
            .all()
        )
        fee_by_class = {c.id: Decimal(str(c.yearly_fees or 0)) for c in Class.query.all()}
        for student_id, klass_id in year_students:
            fee = fee_by_class.get(klass_id) or Decimal('0')
            total_expected += fee
            paid = Decimal(str(paid_by_student.get(student_id, 0) or 0))
            if fee > paid:
                students_with_balance += 1

    collection_rate = round(float(tuition_collected / total_expected * 100), 1) if total_expected > 0 else 0.0
    outstanding_total = money(max(Decimal('0'), total_expected - tuition_collected))

    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    today_income = (
        db.session.query(func.sum(BusinessTransaction.amount))
        .filter(
            BusinessTransaction.is_deleted == False,
            BusinessTransaction.type == 'income',
            BusinessTransaction.date == today_str,
        )
        .scalar()
        or 0
    )
    today_expenses = (
        db.session.query(func.sum(BusinessTransaction.amount))
        .filter(
            BusinessTransaction.is_deleted == False,
            BusinessTransaction.type == 'expense',
            BusinessTransaction.date == today_str,
        )
        .scalar()
        or 0
    )

    recent_transactions = (
        year_filter.order_by(BusinessTransaction.date.desc()).limit(10).all()
        if selected_year_name else
        BusinessTransaction.query.filter_by(is_deleted=False).order_by(BusinessTransaction.date.desc()).limit(10).all()
    )
    recent_payments = StudentPayment.query.order_by(StudentPayment.paid_on.desc()).limit(8).all()
    if selected_year:
        recent_payments = (
            StudentPayment.query.filter_by(academic_year_id=selected_year.id)
            .order_by(StudentPayment.paid_on.desc())
            .limit(8)
            .all()
        )

    income_q = db.session.query(
        BusinessTransaction.category, func.sum(BusinessTransaction.amount)
    ).filter(BusinessTransaction.is_deleted == False, BusinessTransaction.type == 'income')
    expense_q = db.session.query(
        BusinessTransaction.category, func.sum(BusinessTransaction.amount)
    ).filter(BusinessTransaction.is_deleted == False, BusinessTransaction.type == 'expense')
    if selected_year_name:
        income_q = income_q.filter(BusinessTransaction.academic_year == selected_year_name)
        expense_q = expense_q.filter(BusinessTransaction.academic_year == selected_year_name)
    income_categories = income_q.group_by(BusinessTransaction.category).all()
    expense_categories = expense_q.group_by(BusinessTransaction.category).all()

    stats = {
        'total_revenue': money(total_revenue),
        'total_expenses': money(total_expenses),
        'net_profit': money(net_profit),
        'tuition_collected': money(tuition_collected),
        'outstanding_total': outstanding_total,
        'collection_rate': collection_rate,
        'students_with_balance': students_with_balance,
        'transaction_count': year_filter.count() if selected_year_name else BusinessTransaction.query.filter_by(is_deleted=False).count(),
        'today_income': money(today_income),
        'today_expenses': money(today_expenses),
        'ledger_balance': money(get_running_business_balance()),
        'active_students': (
            _students_for_display_year(display_year, history_mode=viewing_archived).count()
            if display_year else 0
        ),
    }

    return render_template(
        'vpi_dashboard.html',
        current_user=current_user,
        active_year=active_year,
        display_year=display_year,
        viewing_archived=viewing_archived,
        selected_year=selected_year,
        selected_year_name=selected_year_name,
        years=years,
        stats=stats,
        class_snapshots=_vpi_class_collection_snapshots(
            display_year, viewing_archived=viewing_archived,
        ),
        outstanding_students=_vpi_outstanding_students(
            display_year, viewing_archived=viewing_archived,
        ),
        recent_transactions=recent_transactions,
        recent_payments=recent_payments,
        income_categories=income_categories,
        expense_categories=expense_categories,
        total_revenue=stats['total_revenue'],
        total_expenses=stats['total_expenses'],
        net_profit=stats['net_profit'],
    )

# -------------------------- DEAN DASHBOARD -------------------------------
def _dean_student_has_active_suspension(student, current_time=None):
    current_time = current_time or datetime.now(timezone.utc)
    if (student.status or '').upper() == 'SUSPENDED':
        return True
    return Suspension.query.filter(
        Suspension.student_id == student.id,
        Suspension.return_date > current_time,
    ).count() > 0


def _dean_build_class_snapshots(display_year=None, *, viewing_archived=False):
    snapshots = []
    for klass in Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all():
        students = (
            _principal_students_for_class(
                klass, display_year, viewing_archived=viewing_archived,
            )
            if display_year else []
        )
        incident_count = 0
        if students:
            student_ids = [s.id for s in students]
            incident_count = (
                db.session.query(db.func.count(Discipline.id))
                .filter(Discipline.student_id.in_(student_ids))
                .scalar()
                or 0
            )
        snapshots.append({
            'klass': klass,
            'student_count': len(students),
            'suspended_count': sum(1 for s in students if (s.status or '').upper() == 'SUSPENDED'),
            'incident_count': incident_count,
        })
    return snapshots


@app.route('/dean/dashboard', methods=['GET'])
@login_required
@role_required('Dean')
def dean_dashboard():
    """Dean of Students — conduct, welfare, attendance, and campus oversight."""
    current_time = datetime.now(timezone.utc)
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=DEAN_YEAR_SESSION_KEY,
    )
    class_id = request.args.get('class_id', type=int)
    search_q = (request.args.get('q') or '').strip()

    rooms_list = Room.query.order_by(Room.name.asc()).all()
    classes = Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all()
    selected_class = db.session.get(Class, class_id) if class_id else None

    if class_id and selected_class and display_year:
        students = _principal_students_for_class(
            selected_class, display_year, viewing_archived=viewing_archived,
        )
    elif display_year:
        students = (
            _students_for_display_year(display_year, history_mode=viewing_archived)
            .order_by(Student.last_name.asc(), Student.first_name.asc())
            .all()
        )
    else:
        students = []
    if search_q:
        needle = search_q.lower()
        students = [
            student for student in students
            if needle in ' '.join(filter(None, [
                student.first_name,
                student.last_name,
                student.student_id,
                student.full_name,
            ])).lower()
        ]
    _attach_display_class(students, display_year, viewing_archived=viewing_archived)

    incident_counts = dict(
        db.session.query(Discipline.student_id, db.func.count(Discipline.id))
        .group_by(Discipline.student_id)
        .all()
    )
    for student in students:
        student.incident_count = incident_counts.get(student.id, 0)
        student.has_active_suspension = _dean_student_has_active_suspension(student, current_time)

    month_start = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today_str = current_time.strftime('%Y-%m-%d')
    active_suspensions = Suspension.query.filter(Suspension.return_date > current_time).count()
    total_suspensions = Suspension.query.count()
    incidents_this_month = Discipline.query.filter(Discipline.created_at >= month_start).count()
    suspended_students = Student.query.filter(func.upper(Student.status) == 'SUSPENDED').count()
    today_absences = Attendance.query.filter_by(date=today_str, status='absent').count()
    today_late = Attendance.query.filter_by(date=today_str, status='late').count()
    rooms_at_capacity = sum(1 for room in rooms_list if room.capacity and room.current_occupancy >= room.capacity)

    repeat_offenders = (
        db.session.query(Student, db.func.count(Discipline.id).label('incident_count'))
        .join(Discipline, Student.id == Discipline.student_id)
        .group_by(Student.id)
        .having(db.func.count(Discipline.id) >= 2)
        .order_by(db.func.count(Discipline.id).desc())
        .limit(8)
        .all()
    )
    at_risk_count = len(repeat_offenders)

    recent_suspensions = (
        Suspension.query.order_by(Suspension.id.desc()).limit(8).all()
    )
    discipline_incidents = (
        Discipline.query.order_by(Discipline.created_at.desc()).limit(8).all()
    )

    stats = {
        'active_suspensions': active_suspensions,
        'total_suspensions': total_suspensions,
        'incidents_this_month': incidents_this_month,
        'total_incidents': Discipline.query.count(),
        'suspended_students': suspended_students,
        'at_risk_students': at_risk_count,
        'today_absences': today_absences,
        'today_late': today_late,
        'total_students_enrolled': (
            _students_for_display_year(display_year, history_mode=viewing_archived).count()
            if display_year else 0
        ),
        'total_monitored_rooms': len(rooms_list),
        'rooms_at_capacity': rooms_at_capacity,
    }

    return render_template(
        'dean_dashboard.html',
        current_user=current_user,
        current_time=current_time,
        active_year=active_year,
        rooms_list=rooms_list,
        classes=classes,
        selected_class=selected_class,
        class_id=class_id,
        search_q=search_q,
        students=students,
        class_snapshots=_dean_build_class_snapshots(
            display_year, viewing_archived=viewing_archived,
        ),
        active_suspensions=active_suspensions,
        total_suspensions=total_suspensions,
        recent_suspensions=recent_suspensions,
        discipline_incidents=discipline_incidents,
        repeat_offenders=repeat_offenders,
        stats=stats,
        display_year=display_year,
        years=years,
        viewing_archived=viewing_archived,
        form=FlaskForm(),
        discipline_form=DisciplineForm(),
    )


@app.route('/dean/incident/process', methods=['POST'])
@login_required
@role_required('Dean')
def process_discipline_incident():
    student_id = request.form.get('student_id', type=int)
    offense = (request.form.get('offense') or '').strip()
    action_taken = (request.form.get('action_taken') or '').strip() or 'Logged for dean review'
    notes = (request.form.get('notes') or '').strip()
    class_id = request.form.get('return_class_id', type=int)
    search_q = (request.form.get('return_q') or '').strip()

    if not student_id or not offense:
        flash('Student and offense description are required.', 'danger')
        return redirect(url_for('dean_dashboard', class_id=class_id, q=search_q or None))

    student = db.session.get(Student, student_id)
    if not student:
        flash('Student record not found.', 'danger')
        return redirect(url_for('dean_dashboard'))

    incident = Discipline(
        student_id=student_id,
        offense=offense,
        action_taken=action_taken,
        notes=notes or None,
        logged_by_id=current_user.id,
    )
    db.session.add(incident)
    db.session.commit()
    flash(f'Conduct incident logged for {student.full_name}.', 'success')
    return redirect(url_for('dean_dashboard', class_id=class_id, q=search_q or None))


@app.route('/dean/suspension/process', methods=['POST'])
@login_required
@role_required('Dean')
def process_suspension():
    student_id = request.form.get('student_id', type=int)
    reason = (request.form.get('reason') or '').strip()
    start_date_str = request.form.get('start_date')
    return_date_str = request.form.get('return_date')
    class_id = request.form.get('return_class_id', type=int)
    search_q = (request.form.get('return_q') or '').strip()

    if not all([student_id, reason, start_date_str, return_date_str]):
        flash('All suspension fields are required.', 'danger')
        return redirect(url_for('dean_dashboard', class_id=class_id, q=search_q or None))

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        return_day = datetime.strptime(return_date_str, '%Y-%m-%d').date()
        return_dt = datetime.combine(return_day, datetime.max.time(), tzinfo=timezone.utc)

        student = db.session.get(Student, student_id)
        if not student:
            flash('Student record not found.', 'danger')
            return redirect(url_for('dean_dashboard'))

        new_sanction = Suspension(
            student_id=student_id,
            reason=reason,
            start_date=start_date,
            return_date=return_dt,
        )
        student.status = 'SUSPENDED'
        db.session.add(new_sanction)
        db.session.add(Discipline(
            student_id=student_id,
            offense=f'Suspension: {reason}',
            action_taken=f'Suspended until {return_date_str}',
            logged_by_id=current_user.id,
        ))
        db.session.commit()
        flash('Suspension recorded and parent notification letter is ready to print.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to record suspension: {e}")
        flash(f'Could not save suspension: {e}', 'danger')

    return redirect(url_for('dean_dashboard', class_id=class_id, q=search_q or None))


@app.route('/dean/suspension/reinstate', methods=['POST'])
@login_required
@role_required('Dean', 'admin')
def dean_reinstate_student():
    """Clear suspension and restore student to active status."""
    student_id = request.form.get('student_id', type=int)
    notes = (request.form.get('notes') or '').strip()
    class_id = request.form.get('return_class_id', type=int)
    search_q = (request.form.get('return_q') or '').strip()

    if not student_id:
        flash('Student is required.', 'danger')
        return redirect(url_for('dean_dashboard'))

    student = db.session.get(Student, student_id)
    if not student:
        flash('Student record not found.', 'danger')
        return redirect(url_for('dean_dashboard'))

    current_time = datetime.now(timezone.utc)
    active_suspensions = Suspension.query.filter(
        Suspension.student_id == student_id,
        Suspension.return_date > current_time,
    ).all()
    for suspension in active_suspensions:
        suspension.return_date = current_time

    student.status = 'ACTIVE'
    db.session.add(Discipline(
        student_id=student_id,
        offense='Suspension lifted / readmitted',
        action_taken='Reinstated to active status',
        notes=notes or None,
        logged_by_id=current_user.id,
    ))
    db.session.commit()
    flash(f'{student.full_name} has been reinstated and marked active.', 'success')
    return redirect(url_for('dean_dashboard', class_id=class_id, q=search_q or None))


# -------------------------- VPA DASHBOARD -------------------------------
def _vpa_student_average(student, academic_year=None, averages_map=None):
    """MoE student standing — mean of entered scores for the year (uses SQL map when provided)."""
    if averages_map is not None:
        return averages_map.get(student.id)
    query = db.session.query(func.avg(Grade.score)).filter(
        Grade.student_id == student.id,
        Grade.score.isnot(None),
    )
    if academic_year:
        query = query.filter(Grade.academic_year_id == academic_year.id)
    avg = query.scalar()
    return round(float(avg), 1) if avg is not None else None


def _vpa_averages_map(academic_year):
    """One GROUP BY query for all student averages in a year — never N queries."""
    if not academic_year:
        return {}
    cache_key = academic_year.id
    if has_request_context():
        maps = getattr(g, '_flpa_vpa_avg_maps', None)
        if maps is None:
            maps = {}
            g._flpa_vpa_avg_maps = maps
        if cache_key in maps:
            return maps[cache_key]
    rows = db.session.query(
        Grade.student_id,
        func.avg(Grade.score),
    ).filter(
        Grade.academic_year_id == academic_year.id,
        Grade.score.isnot(None),
    ).group_by(Grade.student_id).all()
    result = {sid: round(float(avg), 1) for sid, avg in rows if avg is not None}
    if has_request_context():
        g._flpa_vpa_avg_maps[cache_key] = result
    return result


def _vpa_year_grade_query(academic_year):
    query = Grade.query
    if academic_year:
        query = query.filter_by(academic_year_id=academic_year.id)
    return query


def _vpa_year_assessment_query(academic_year):
    query = Assessment.query
    if academic_year:
        query = query.filter_by(academic_year_id=academic_year.id)
    return query


def _vpa_build_class_snapshots(academic_year, *, viewing_archived=False, averages_map=None):
    snapshots = []
    if averages_map is None:
        averages_map = _vpa_averages_map(academic_year)
    year_id = academic_year.id if academic_year else None
    grade_counts = dict(
        db.session.query(Grade.class_id, func.count(Grade.id))
        .filter(Grade.academic_year_id == year_id)
        .group_by(Grade.class_id)
        .all()
    ) if year_id else {}
    assessment_counts = dict(
        db.session.query(Assessment.klass_id, func.count(Assessment.id))
        .filter(Assessment.academic_year_id == year_id)
        .group_by(Assessment.klass_id)
        .all()
    ) if year_id else {}

    subject_counts = dict(
        db.session.query(ClassSubject.class_id, func.count(ClassSubject.id))
        .group_by(ClassSubject.class_id)
        .all()
    )
    student_class_pairs = []
    if year_id:
        if viewing_archived:
            student_class_pairs = list(_student_class_map_for_display_year(
                academic_year, viewing_archived=True,
            ).items())
        else:
            student_class_pairs = (
                _students_for_display_year(academic_year, history_mode=False)
                .with_entities(Student.id, Student.klass_id)
                .all()
            )

    by_class = {}
    for sid, cid in student_class_pairs:
        if not cid:
            continue
        by_class.setdefault(cid, []).append(sid)

    for klass in Class.query.order_by(Class.grade_level.asc(), Class.name.asc()).all():
        student_ids = by_class.get(klass.id, [])
        valid_avgs = [averages_map[sid] for sid in student_ids if sid in averages_map]
        passing = sum(1 for avg in valid_avgs if avg >= MOE_PASSING_SCORE)
        failing = sum(1 for avg in valid_avgs if avg < MOE_PASSING_SCORE)
        class_avg = round(sum(valid_avgs) / len(valid_avgs), 1) if valid_avgs else None
        passing_rate = round(passing / len(valid_avgs) * 100, 1) if valid_avgs else 0.0
        snapshots.append({
            'klass': klass,
            'student_count': len(student_ids),
            'subject_count': subject_counts.get(klass.id, 0),
            'grade_count': grade_counts.get(klass.id, 0),
            'assessment_count': assessment_counts.get(klass.id, 0),
            'class_avg': class_avg,
            'passing_rate': passing_rate,
            'failing_count': failing,
        })
    return snapshots


def _vpa_performance_bands(academic_year, *, viewing_archived=False, averages_map=None, enrolled_count=0):
    if averages_map is None:
        averages_map = _vpa_averages_map(academic_year)
    bands = {'excellent': 0, 'good': 0, 'average': 0, 'needs_improvement': 0, 'no_grades': 0}
    graded = 0
    for avg in averages_map.values():
        graded += 1
        if avg >= 90:
            bands['excellent'] += 1
        elif avg >= 80:
            bands['good'] += 1
        elif avg >= MOE_PASSING_SCORE:
            bands['average'] += 1
        else:
            bands['needs_improvement'] += 1
    bands['no_grades'] = max(0, int(enrolled_count or 0) - graded)
    return bands


def _vpa_grade_letter_distribution(academic_year):
    buckets = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
    if not academic_year:
        return buckets
    letter = case(
        (Grade.score >= 90, 'A'),
        (Grade.score >= 80, 'B'),
        (Grade.score >= 70, 'C'),
        (Grade.score >= 60, 'D'),
        else_='F',
    )
    rows = db.session.query(letter, func.count(Grade.id)).filter(
        Grade.academic_year_id == academic_year.id,
        Grade.score.isnot(None),
    ).group_by(letter).all()
    for key, count in rows:
        if key in buckets:
            buckets[key] = count
    return buckets


def _vpa_ranked_students_by_average(academic_year, class_id=None, limit=10, *, below_moe=False, viewing_archived=False):
    if not academic_year:
        return []
    avg_sub = (
        db.session.query(
            Grade.student_id.label('student_id'),
            func.avg(Grade.score).label('avg_score'),
        )
        .filter(Grade.academic_year_id == academic_year.id, Grade.score.isnot(None))
        .group_by(Grade.student_id)
        .subquery()
    )
    query = db.session.query(Student, avg_sub.c.avg_score).join(
        avg_sub, Student.id == avg_sub.c.student_id
    )
    if below_moe:
        query = query.filter(avg_sub.c.avg_score < MOE_PASSING_SCORE).order_by(avg_sub.c.avg_score.asc())
    else:
        query = query.order_by(avg_sub.c.avg_score.desc())
    if class_id:
        student_ids = [
            s.id for s in _principal_students_for_class(
                db.session.get(Class, class_id), academic_year, viewing_archived=viewing_archived,
            )
        ]
        if not student_ids:
            return []
        query = query.filter(Student.id.in_(student_ids))
    rows = []
    for student, avg in query.limit(limit).all():
        rows.append({'student': student, 'average': round(float(avg), 1)})
    return rows


def _vpa_at_risk_students(academic_year, class_id=None, limit=10, *, viewing_archived=False):
    return _vpa_ranked_students_by_average(
        academic_year, class_id=class_id, limit=limit, below_moe=True, viewing_archived=viewing_archived,
    )


def _vpa_top_students(academic_year, class_id=None, limit=8, *, viewing_archived=False):
    return _vpa_ranked_students_by_average(
        academic_year, class_id=class_id, limit=limit, below_moe=False, viewing_archived=viewing_archived,
    )


#--------------------vpa/dashboard----------------------#
@app.route('/vpa/dashboard', methods=['GET'])
@login_required
@role_required('VPA')
def vpa_dashboard():
    """VPA — curriculum oversight, grade monitoring, and MoE academic standards."""
    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=VPA_YEAR_SESSION_KEY,
    )
    selected_year = display_year
    selected_year_name = display_year.name if display_year else (
        active_year.name if active_year else (years[0].name if years else '')
    )

    class_id = request.args.get('class_id', type=int)
    search_q = (request.args.get('q') or '').strip()
    selected_class = db.session.get(Class, class_id) if class_id else None
    page, per_page = clamp_page(request.args.get('page'), DASHBOARD_PAGE_SIZE)
    averages_map = _vpa_averages_map(display_year)

    if class_id and selected_class and display_year:
        roster = _principal_students_for_class(
            selected_class, display_year, viewing_archived=viewing_archived,
        )
        if search_q:
            needle = search_q.lower()
            roster = [
                student for student in roster
                if needle in ' '.join(filter(None, [
                    student.first_name, student.last_name, student.student_id, student.full_name,
                ])).lower()
            ]
        registry_total = len(roster)
        students = roster[(page - 1) * per_page: page * per_page]
    elif display_year:
        students_query = _students_for_display_year(
            display_year, history_mode=viewing_archived,
        )
        if search_q:
            like = f"%{search_q}%"
            students_query = students_query.filter(or_(
                Student.first_name.ilike(like),
                Student.last_name.ilike(like),
                Student.student_id.ilike(like),
            ))
        students_query = students_query.order_by(Student.last_name.asc(), Student.first_name.asc())
        registry_total = students_query.count()
        students = students_query.offset((page - 1) * per_page).limit(per_page).all()
    else:
        students = []
        registry_total = 0
    registry_pages = max(1, (registry_total + per_page - 1) // per_page) if registry_total else 1
    if page > registry_pages:
        page = registry_pages
    _attach_display_class(students, display_year, viewing_archived=viewing_archived)

    for student in students:
        student.academic_average = averages_map.get(student.id)
        student.grade_letter = (
            SchoolEngine.get_grade_letter(student.academic_average)
            if student.academic_average is not None
            else '-'
        )
        student.moe_status = (
            'Passing' if student.academic_average >= MOE_PASSING_SCORE
            else 'Below MoE Standard'
        ) if student.academic_average is not None else 'No grades'

    enrolled_count = (
        _students_for_display_year(display_year, history_mode=viewing_archived).count()
        if display_year
        else 0
    )
    performance_bands = _vpa_performance_bands(
        display_year,
        viewing_archived=viewing_archived,
        averages_map=averages_map,
        enrolled_count=enrolled_count,
    )
    graded_students = enrolled_count - performance_bands['no_grades']
    passing_count = (
        performance_bands['excellent']
        + performance_bands['good']
        + performance_bands['average']
    )
    passing_rate = round(passing_count / graded_students * 100, 1) if graded_students > 0 else 0.0

    catalog_subjects = ClassSubject.query.count()
    teacher_subjects = db.session.query(ClassSubjectTeacher.subject_name).distinct().count()
    subjects_allocated = max(catalog_subjects, teacher_subjects)

    grade_query = _vpa_year_grade_query(display_year)
    assessment_query = _vpa_year_assessment_query(display_year)

    recent_grades = grade_query.order_by(Grade.id.desc()).limit(10).all()
    recent_assessments = assessment_query.order_by(Assessment.id.desc()).limit(10).all()

    stats = {
        'total_students': enrolled_count,
        'total_classes': Class.query.count(),
        'total_teachers': Teacher.query.filter_by(status='ACTIVE').count(),
        'subjects_allocated': subjects_allocated,
        'total_assessments': assessment_query.count(),
        'grades_entered': grade_query.count(),
        'grades_published': grade_query.filter_by(submitted=True).count(),
        'pending_vpa_releases': (
            GradeRelease.query.filter_by(
                academic_year_id=display_year.id,
                status=GradeRelease.STATUS_PENDING_VPA,
            ).count()
            if display_year else 0
        ),
        'pending_transcript_releases': count_pending_transcript_releases(display_year),
        'passing_rate': passing_rate,
        'failing_count': performance_bands['needs_improvement'],
        'no_grade_data': performance_bands['no_grades'],
        'excellent_students': performance_bands['excellent'],
        'good_students': performance_bands['good'],
        'average_students': performance_bands['average'],
        'needs_improvement': performance_bands['needs_improvement'],
        'moe_standard': MOE_PASSING_SCORE,
    }

    at_risk_students = _vpa_at_risk_students(
        selected_year, class_id=class_id, viewing_archived=viewing_archived,
    )
    top_students = _vpa_top_students(
        selected_year, class_id=class_id, viewing_archived=viewing_archived,
    )
    _attach_display_class(
        [row['student'] for row in at_risk_students],
        display_year,
        viewing_archived=viewing_archived,
    )
    _attach_display_class(
        [row['student'] for row in top_students],
        display_year,
        viewing_archived=viewing_archived,
    )

    class_snapshots = _vpa_build_class_snapshots(
        display_year, viewing_archived=viewing_archived, averages_map=averages_map,
    )
    class_snapshots_by_division = group_items_by_class(
        class_snapshots,
        lambda snap: snap.get('klass') if isinstance(snap, dict) else None,
    )
    if not class_snapshots_by_division:
        _all_classes, class_snapshots_by_division = list_classes_grouped()
        class_snapshots_by_division = [
            {
                'key': group['key'],
                'label': group['label'],
                'classes': [{'klass': klass} for klass in group['classes']],
            }
            for group in class_snapshots_by_division
        ]

    return render_template(
        'vpa_dashboard.html',
        current_user=current_user,
        active_year=active_year,
        display_year=display_year,
        years=years,
        viewing_archived=viewing_archived,
        selected_year=selected_year,
        selected_year_name=selected_year_name,
        selected_class=selected_class,
        class_id=class_id,
        search_q=search_q,
        students=students,
        registry_page=page,
        registry_pages=registry_pages,
        registry_total=registry_total,
        stats=stats,
        class_snapshots=class_snapshots,
        class_snapshots_by_division=class_snapshots_by_division,
        grade_letter_distribution=_vpa_grade_letter_distribution(display_year),
        performance_bands=performance_bands,
        at_risk_students=at_risk_students,
        top_students=top_students,
        recent_grades=recent_grades,
        recent_assessments=recent_assessments,
        grading_periods=MOE_GRADING_PERIODS,
        pending_vpa_releases=stats.get('pending_vpa_releases', 0),
        pending_transcript_releases=stats.get('pending_transcript_releases', 0),
    )


def _grade_release_queue_rows(display_year=None, status=None):
    """Class/period packages waiting on or recently reviewed by VPA."""
    query = GradeRelease.query
    if display_year:
        query = query.filter_by(academic_year_id=display_year.id)
    if status:
        query = query.filter_by(status=status)
    else:
        query = query.filter(GradeRelease.status.in_((
            GradeRelease.STATUS_PENDING_VPA,
            GradeRelease.STATUS_RETURNED,
            GradeRelease.STATUS_APPROVED,
        )))
    releases = query.order_by(GradeRelease.id.desc()).all()
    rows = []
    for release in releases:
        klass = release.klass or db.session.get(Class, release.class_id)
        year = release.academic_year or db.session.get(AcademicYear, release.academic_year_id)
        submitted_count = 0
        for grade in Grade.query.filter_by(
            class_id=release.class_id,
            academic_year_id=release.academic_year_id,
            submitted=True,
        ).all():
            if _grade_release_period(grade) == release.period:
                submitted_count += 1
        sample_student = None
        if year:
            roster = get_class_students_for_year(release.class_id, year)
            sample_student = roster[0] if roster else None
        period_label = grading_period_label(release.period)
        class_name = klass.name if klass else 'Class'
        rows.append({
            'release': release,
            'klass': klass,
            'year': year,
            'period_label': period_label,
            'class_period_label': f'{class_name} — {period_label}',
            'submitted_count': submitted_count,
            'publisher': release.published_by,
            'approver': release.approved_by,
            'sample_student': sample_student,
        })
    return rows


def _load_reviewable_grade_release(release_id):
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked, None
    release = db.session.get(GradeRelease, release_id)
    if not release:
        flash('That grade package was not found.', 'danger')
        return redirect(url_for('vpa_grade_releases')), None
    return None, release


@app.route('/vpa/grade-releases', methods=['GET'])
@login_required
def vpa_grade_releases():
    """VPA queue: approve or return teacher-published class/period packages."""
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked

    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=VPA_YEAR_SESSION_KEY,
    )
    rows = _grade_release_queue_rows(display_year)
    pending_rows = [row for row in rows if row['release'].status == GradeRelease.STATUS_PENDING_VPA]
    returned_rows = [row for row in rows if row['release'].status == GradeRelease.STATUS_RETURNED]
    approved_rows = [row for row in rows if row['release'].status == GradeRelease.STATUS_APPROVED][:12]
    return render_template(
        'vpa_grade_releases.html',
        display_year=display_year,
        active_year=active_year,
        years=years,
        viewing_archived=viewing_archived,
        pending_rows=pending_rows,
        returned_rows=returned_rows,
        approved_rows=approved_rows,
    )


@app.route('/vpa/grade-releases/<int:release_id>/approve', methods=['POST'])
@login_required
def vpa_approve_grade_release(release_id):
    blocked, release = _load_reviewable_grade_release(release_id)
    if blocked:
        return blocked
    comment = (request.form.get('review_comment') or '').strip() or None
    release.status = GradeRelease.STATUS_APPROVED
    release.approved_by_id = current_user.id
    release.approved_at = datetime.now(timezone.utc)
    release.returned_by_id = None
    release.returned_at = None
    if comment:
        release.review_comment = comment
    db.session.commit()
    report_card_open = report_card_is_released(release.academic_year_id, release.class_id)
    flash(
        f'{grading_period_label(release.period)} for '
        f'{(release.klass.name if release.klass else "this class")} is approved. '
        "Students may now view, download, and print this period's grade sheet. "
        + (
            'The full-year Report Card is now released for this class.'
            if report_card_open
            else 'The Report Card stays sealed until the final marking period is approved.'
        ),
        'success',
    )
    return redirect(url_for('vpa_grade_releases'))


@app.route('/vpa/grade-releases/<int:release_id>/return', methods=['POST'])
@login_required
def vpa_return_grade_release(release_id):
    blocked, release = _load_reviewable_grade_release(release_id)
    if blocked:
        return blocked
    comment = (request.form.get('review_comment') or '').strip()
    if not comment:
        flash('Please add a short comment so the teacher knows what to correct.', 'warning')
        return redirect(url_for('vpa_grade_releases'))
    release.status = GradeRelease.STATUS_RETURNED
    release.returned_by_id = current_user.id
    release.returned_at = datetime.now(timezone.utc)
    release.approved_by_id = None
    release.approved_at = None
    release.review_comment = comment
    db.session.commit()
    flash(
        f'{grading_period_label(release.period)} was returned to the teacher. '
        'Students cannot view this period until it is published and approved again. '
        'Previously approved periods remain available.',
        'warning',
    )
    return redirect(url_for('vpa_grade_releases'))


def _transcript_release_queue_context(display_year):
    """Students waiting on Official Transcript approval, plus recent approvals."""
    year_wide = None
    approved_student_ids = set()
    approved_rows = []
    if display_year:
        year_wide = TranscriptRelease.query.filter(
            TranscriptRelease.academic_year_id == display_year.id,
            TranscriptRelease.student_id.is_(None),
            TranscriptRelease.status == TranscriptRelease.STATUS_APPROVED,
        ).first()
        student_releases = TranscriptRelease.query.filter(
            TranscriptRelease.academic_year_id == display_year.id,
            TranscriptRelease.student_id.isnot(None),
            TranscriptRelease.status == TranscriptRelease.STATUS_APPROVED,
        ).order_by(TranscriptRelease.approved_at.desc()).all()
        for release in student_releases:
            approved_student_ids.add(release.student_id)
            student = release.student or db.session.get(Student, release.student_id)
            if not student:
                continue
            klass = get_student_class_for_year(student, display_year.id)
            approved_rows.append({
                'release': release,
                'student': student,
                'klass': klass,
                'approver': release.approved_by,
            })

    pending_rows = []
    if display_year and not year_wide:
        students = _students_for_display_year(
            display_year, history_mode=True,
        ).order_by(Student.last_name.asc(), Student.first_name.asc()).all()
        for student in students:
            if student.id in approved_student_ids:
                continue
            pending_rows.append({
                'student': student,
                'klass': get_student_class_for_year(student, display_year.id),
            })
    return year_wide, pending_rows, approved_rows[:20]


@app.route('/vpa/transcript-releases', methods=['GET'])
@login_required
def vpa_transcript_releases():
    """VPA / Principal queue: release Official Transcripts to students and parents."""
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked

    display_year, active_year, years, viewing_archived = resolve_dashboard_academic_year(
        session_key=VPA_YEAR_SESSION_KEY,
    )
    year_wide, pending_rows, approved_rows = _transcript_release_queue_context(display_year)
    return render_template(
        'vpa_transcript_releases.html',
        display_year=display_year,
        active_year=active_year,
        years=years,
        viewing_archived=viewing_archived,
        year_wide=year_wide,
        pending_rows=pending_rows,
        approved_rows=approved_rows,
    )


@app.route('/vpa/transcript-releases/approve-year', methods=['POST'])
@login_required
def vpa_approve_year_transcripts():
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked
    year_id = request.form.get('academic_year_id', type=int)
    display_year = db.session.get(AcademicYear, year_id) if year_id else get_active_academic_year()
    if not display_year:
        flash('Select an academic year before releasing transcripts.', 'warning')
        return redirect(url_for('vpa_transcript_releases'))
    approve_official_transcript(display_year.id, student_id=None, user=current_user)
    flash(
        f'Official Transcripts for {display_year.name} are released. '
        'Students and parents may now view the portrait document in the portal.',
        'success',
    )
    return redirect(url_for('vpa_transcript_releases', academic_year_id=display_year.id))


@app.route('/vpa/transcript-releases/<int:student_id>/approve', methods=['POST'])
@login_required
def vpa_approve_student_transcript(student_id):
    blocked = deny_unless_roles(ACADEMIC_COMMAND_ROLES, academic_office=True)
    if blocked:
        return blocked
    student = Student.query.get_or_404(student_id)
    year_id = request.form.get('academic_year_id', type=int)
    display_year = db.session.get(AcademicYear, year_id) if year_id else get_active_academic_year()
    if not display_year:
        flash('Select an academic year before releasing a transcript.', 'warning')
        return redirect(url_for('vpa_transcript_releases'))
    approve_official_transcript(display_year.id, student_id=student.id, user=current_user)
    flash(
        f'Official Transcript for {student.full_name} is released for {display_year.name}.',
        'success',
    )
    return redirect(url_for('vpa_transcript_releases', academic_year_id=display_year.id))


@app.route('/payroll', methods=['GET', 'POST'])
@login_required
def payroll():
    if current_user.role not in ["admin", "business"]:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    form = PayrollForm()
    if form.validate_on_submit():
        # create a Payroll record (uses Payroll model)
        record = Payroll(
            staff_id=form.staff_id.data,
            occupation=form.occupation.data,
            month=form.month.data,
            salary_amount=parse_currency_amount(form.salary_amount.data),
            paid=bool(form.paid.data),
            created_on=datetime.now(timezone.utc)
        )
        db.session.add(record)
        db.session.commit()
        flash("Payroll record added successfully.", "success")
        return redirect(url_for('payroll'))

    payrolls = Payroll.query.order_by(Payroll.created_on.desc()).all()
    return render_template('payroll.html', form=form, payrolls=payrolls)

# -------------------------- PDF EXPORT ----------------------------
@app.route('/report-card/<int:student_id>/pdf')
@login_required
def report_card_pdf(student_id):
    student = Student.query.get_or_404(student_id)
    active_year = get_active_academic_year()
    year_id = request.args.get('academic_year_id', type=int) or (active_year.id if active_year else None)

    user_role = (current_user.role or '').lower()
    if user_role == 'student':
        linked_student = get_student_for_user(current_user)
        if not linked_student or linked_student.id != student.id:
            abort(403)
    elif user_role == 'parent':
        if student.parent_email != current_user.email:
            abort(403)
    elif user_role not in STAFF_INTERNAL_GRADE_ROLES:
        abort(403)
    elif user_role == 'teacher':
        teacher_profile = Teacher.query.filter_by(user_id=current_user.id).first()
        if not teacher_profile or not teacher_can_access_student(teacher_profile, current_user, student):
            abort(403)

    is_staff_preview = viewer_can_see_unreleased_official_grades()
    if not is_staff_preview:
        doc_state = student_official_documents_state(student, year_id)
        if not doc_state.get('report_card_unlocked'):
            display_year = db.session.get(AcademicYear, year_id) if year_id else None
            return render_official_grade_hold(
                student, display_year,
                hold_title='Report Card not yet issued',
                hold_message=STUDENT_REPORT_CARD_HOLD_MESSAGE,
                hold_meta=doc_state.get('report_card_blocker_note'),
            )
    return build_official_grade_sheet_pdf(
        student, year_id, kind='report', approved_only=not is_staff_preview,
    )

# ------------------------ ANALYTICS ENDPOINTS ------------------------
from flask import jsonify

@app.route('/analytics/gender')
@login_required
def analytics_gender():
    _require_analytics_access()
    male_count = Student.query.filter(
        func.upper(Student.gender).in_(('M', 'MALE'))
    ).count()
    female_count = Student.query.filter(
        func.upper(Student.gender).in_(('F', 'FEMALE'))
    ).count()
    other_count = Student.query.filter(
        ~func.upper(Student.gender).in_(('M', 'MALE', 'F', 'FEMALE'))
    ).count()
    return jsonify({
        'male': male_count,
        'female': female_count,
        'other': other_count
    })

#--------------analystic/enrollment-------------------#

@app.route('/analytics/enrollment')
@login_required
def analytics_enrollment():
    _require_analytics_access()
    from collections import defaultdict
    class_counts = defaultdict(int)
    active_year = get_active_academic_year()
    students_q = Student.query.filter(Student.klass_id.isnot(None))
    if active_year:
        students_q = students_q.filter_by(academic_year_id=active_year.id)
    for student in students_q.all():
        class_counts[str(student.klass_id)] += 1
    return jsonify({
        'total': sum(class_counts.values()),
        'by_class': dict(class_counts),
    })

#----------------Delete Users--------------------------#

@app.route('/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if normalize_role(current_user) != "admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))
    if user_id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('admin_users'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully.", "success")
    return redirect(url_for('admin_users'))

#-----------------analytics/payments-----------------#

@app.route('/analytics/payments')
@login_required
def analytics_payments():
    _require_analytics_access()
    from collections import defaultdict
    year_counts = defaultdict(float)
    payments = StudentPayment.query.all()
    for p in payments:
        year_counts[str(p.academic_year_id)] += p.amount_paid
    return jsonify({
        'total': sum(year_counts.values()),
        'by_year': year_counts
    })

#----------------User profile---------------------#

@app.route('/account/settings', methods=['GET', 'POST'])
@login_required
def account_settings():
    """Logged-in user: change password and upload a square profile photo."""
    password_form = AccountPasswordForm()
    photo_form = AccountPhotoForm()

    if request.method == 'POST' and photo_form.submit_photo.data:
        if photo_form.validate():
            photo_file = photo_form.photo.data
            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'photos')
            os.makedirs(upload_dir, exist_ok=True)
            ext = (secure_filename(photo_file.filename).rsplit('.', 1)[-1] or 'jpg').lower()
            if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
                ext = 'jpg'
            filename = f"{current_user.id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}.{ext}"
            file_path = os.path.join(upload_dir, filename)
            try:
                if Image is not None:
                    img = Image.open(photo_file.stream)
                    if ImageOps is not None:
                        img = ImageOps.exif_transpose(img)
                    if img.mode not in ('RGB', 'RGBA'):
                        img = img.convert('RGB')
                    width, height = img.size
                    side = min(width, height)
                    left = (width - side) // 2
                    top = (height - side) // 2
                    img = img.crop((left, top, left + side, top + side))
                    resample = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', Image.LANCZOS)
                    img = img.resize((400, 400), resample)
                    save_kwargs = {}
                    if ext in ('jpg', 'jpeg'):
                        img = img.convert('RGB')
                        save_kwargs['quality'] = 88
                    img.save(file_path, **save_kwargs)
                else:
                    photo_file.save(file_path)
                current_user.photo = os.path.join('uploads', 'photos', filename).replace('\\', '/')
                db.session.commit()
                flash("Profile photo updated.", "success")
                return redirect(url_for('account_settings'))
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error(f"Account photo upload failed: {exc}")
                flash("Could not save that photo. Try a JPG or PNG.", "danger")
        else:
            flash("Choose a valid image (JPG, PNG, GIF, or WebP).", "danger")

    elif request.method == 'POST' and password_form.submit_password.data:
        if password_form.validate():
            if password_form.new_password.data != password_form.confirm_password.data:
                flash("New password and confirmation do not match.", "danger")
            elif not check_password_hash(current_user.password_hash, password_form.current_password.data):
                flash("Current password is incorrect.", "danger")
            else:
                current_user.set_password(password_form.new_password.data)
                current_user.must_change_password = False
                db.session.commit()
                flash("Password updated.", "success")
                return redirect(url_for(home_endpoint_for_role(current_user)))
        else:
            flash("Please correct the password fields and try again.", "danger")

    home_endpoint = home_endpoint_for_role(current_user)
    return render_template(
        'account_settings.html',
        password_form=password_form,
        photo_form=photo_form,
        dashboard_url=url_for(home_endpoint),
        role_label=dashboard_role_label(current_user),
        preview_url=current_user.photo_url,
        default_avatar_url=default_static_photo_url(),
    )


@app.route('/api/profile', methods=['GET'])
@login_required
def api_profile():
    """
    Secure Profile Extraction API Payload Endpoint
    Serializes relational database records for async DOM parsing.
    """
    try:
        # Fallback dictionary structures if properties return empty string variables
        payload = {
            "id": current_user.id,
            "full_name": (current_user.full_name or '').strip(),
            "role": (current_user.role or '').strip(),
            "email": current_user.email or '',
            "telephone": getattr(current_user, 'telephone_number', '') or '',
            "home_address": getattr(current_user, 'home_address', '') or '',
            "dob": getattr(current_user, 'date_of_birth', '') or '',
        }
        
        return jsonify(payload), 200
        
    except Exception as e:
        current_app.logger.error(f"API Profiler Exception: {str(e)}")
        return jsonify({"error": "Failed to compile background structural credentials"}), 500
#---------------------analytics grades-------------------------------#

@app.route('/analytics/grades')
@login_required
def analytics_grades():
    _require_analytics_access()
    from collections import defaultdict
    subject_counts = defaultdict(float)
    grades = Grade.query.all()
    for g in grades:
        subject_counts[str(g.subject)] += g.score
    return jsonify({
        'total': sum(subject_counts.values()),
        'by_subject': subject_counts
    })

# ---------------------------- ERROR -------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

# -------------------------------------------------------------------
# Run
# -------------------------------------------------------------------
app = init_export_routes(app)

#--------------Admin edit User-------------------------------------#

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if normalize_role(current_user) not in ('admin', 'principal'):
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    from forms import EditUserForm
    user = db.first_or_404(db.select(User).filter_by(id=user_id))
    current_role = normalize_role(current_user)

    if current_role == 'principal' and normalize_role(user) == 'admin':
        flash("This admin account cannot be managed here.", "danger")
        return redirect(url_for('admin_users'))

    form = EditUserForm(obj=user)

    if form.validate_on_submit():
        username = (form.username.data or '').strip() or None
        if User.query.filter(User.email == form.email.data, User.id != user_id).first():
            flash("That email is already assigned to another user.", "danger")
            return render_template('admin_edit_user.html', form=form, user=user)
        if username and User.query.filter(User.username == username, User.id != user_id).first():
            flash("That username is already assigned to another user.", "danger")
            return render_template('admin_edit_user.html', form=form, user=user)

        requested_role = (form.role.data or '').strip().lower()
        if current_role == 'principal' and requested_role == 'admin' and user_id != current_user.id:
            flash("Only an admin can assign the admin role.", "danger")
            return render_template('admin_edit_user.html', form=form, user=user)

        if user_id == current_user.id:
            new_role = (form.role.data or '').strip().lower()
            if normalize_role(current_user) in ('admin', 'principal') and new_role not in ('admin', 'principal'):
                flash("You cannot change your own role away from admin/principal access.", "danger")
                return render_template('admin_edit_user.html', form=form, user=user)

        user.email = form.email.data
        user.username = username
        user.full_name = form.full_name.data
        user.role = form.role.data
        user.home_address = form.home_address.data
        user.telephone_number = form.telephone_number.data

        if form.password.data:
            user.set_password(form.password.data)
            user.must_change_password = True

        photo_file = form.photo.data
        if photo_file and getattr(photo_file, 'filename', None):
            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            filename = secure_filename(photo_file.filename)
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
            filename = f"{timestamp}_{filename}"
            file_path = os.path.join(upload_dir, filename)
            photo_file.save(file_path)
            user.photo = os.path.join('uploads', filename).replace('\\', '/')

        if user.role.lower() == 'teacher':
            name_parts = (user.full_name or '').strip().split(None, 1)
            first_name = name_parts[0].strip() if name_parts else user.full_name
            last_name = name_parts[1].strip() if len(name_parts) > 1 else ''
            existing_teacher = Teacher.query.filter_by(user_id=user.id).first()
            if not existing_teacher:
                teacher_profile = Teacher(
                    user_id=user.id,
                    first_name=first_name or 'Unknown',
                    last_name=last_name or user.full_name,
                    status='ACTIVE'
                )
                db.session.add(teacher_profile)

        try:
            db.session.commit()
            flash(f"User {user.full_name} updated successfully.", "success")
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback()
            flash(f"Could not update user: {str(e)}", "danger")

    return render_template('admin_edit_user.html', form=form, user=user)

#--------------Admin transfer User ---------------------------#

@app.route('/admin/users/transfer-role', methods=['POST'])
@login_required
def transfer_role():
    if normalize_role(current_user) not in ('admin', 'principal'):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    role = (request.form.get('role') or '').strip().lower()
    to_user_id = request.form.get('to_user_id', type=int)
    if not role or not to_user_id:
        flash('Role and target user are required.', 'danger')
        return redirect(url_for('admin_users'))

    to_user = db.session.get(User, to_user_id)
    if not to_user:
        flash('Target user not found.', 'danger')
        return redirect(url_for('admin_users'))
    try:
        previous = transfer_staff_role(role, to_user, actor_id=current_user.id)
        db.session.commit()
        if previous:
            names = ', '.join(u.full_name for u in previous)
            flash(
                f"{role.title()} role transferred to {to_user.full_name}. "
                f"Previous holder(s) deactivated: {names}.",
                'success',
            )
        else:
            flash(f"{role.title()} role assigned to {to_user.full_name}.", 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Role transfer failed: {exc}', 'danger')

    return redirect(url_for('admin_users'))

#-------- Admin ASctivate and Deactivate User--------------------#

@app.route('/admin/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
def deactivate_staff_user(user_id):
    if normalize_role(current_user) not in ('admin', 'principal'):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))

    if user_id == current_user.id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin_users'))

    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))

    reason = (request.form.get('reason') or '').strip() or None
    try:
        summary = deactivate_user_account(user, reason=reason, actor_id=current_user.id)
        db.session.commit()
        msg = f'{user.full_name} has been deactivated.'
        if summary.get('teacher_released'):
            msg += ' Class-teacher assignments were released.'
        flash(msg, 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Deactivation failed: {exc}', 'danger')

    return redirect(url_for('admin_users'))

#--------Admin Add Users-------------------#

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    # ✨ FIX 1: Grant permission to BOTH Admin and Principal roles (case-insensitive protection)
    if current_user.role.lower() not in ['admin', 'principal']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    from forms import CreateUserForm
    form = CreateUserForm()
    
    # Modernized explicit query order execution
    users = db.session.execute(db.select(User).order_by(User.id.desc())).scalars().all()
    classes = db.session.execute(db.select(Class).order_by(Class.name)).scalars().all()

    if form.validate_on_submit():
        submitted_email = (form.email.data or '').strip()
        existing_email_user = User.query.filter(
            func.lower(User.email) == submitted_email.lower()
        ).first()
        if existing_email_user:
            flash(
                f"A user with the email '{submitted_email}' already exists "
                f"({existing_email_user.full_name}). Please use a different email address.",
                "danger",
            )
            return render_template('admin_users.html', form=form, users=users, classes=classes)

        try:
            # Create user entity schema array
            user = User(
                email=submitted_email,
                full_name=form.full_name.data,
                role=form.role.data,
                home_address=form.home_address.data,
                telephone_number=form.telephone_number.data
            )
            user.set_password(form.password.data)

            # Photo processing system pipeline
            photo_file = form.photo.data
            if photo_file:
                upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                
                # Clean and isolate filename parameters safely
                filename = secure_filename(photo_file.filename)
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
                filename = f"{timestamp}_{filename}"
                
                file_path = os.path.join(upload_dir, filename)
                photo_file.save(file_path)
                user.photo = os.path.join('uploads', filename).replace('\\', '/')

            db.session.add(user)
            db.session.flush()  # Generates the user.id node for matching teacher profiles

            # Profile creation tier for teacher tracking logs
            if user.role.lower() == 'teacher':
                name_parts = (user.full_name or '').strip().split(None, 1)  # Split on first whitespace only
                first_name = name_parts[0].strip() if name_parts else user.full_name
                last_name = name_parts[1].strip() if len(name_parts) > 1 else ''
                
                # Ensure teacher profile doesn't already exist
                existing_teacher = Teacher.query.filter_by(user_id=user.id).first()
                if not existing_teacher:
                    teacher_profile = Teacher(
                        user_id=user.id,
                        first_name=first_name or 'Unknown',
                        last_name=last_name or user.full_name,
                        status='ACTIVE'
                    )
                    db.session.add(teacher_profile)
                    logger.info(f"✅ Created Teacher profile for user {user.id}: {first_name} {last_name}")
                else:
                    logger.warning(f"⚠️ Teacher profile already exists for user {user.id}")

            db.session.commit()
            flash(f"User {user.full_name} ({user.role}) created successfully.", "success")
            return redirect(url_for('admin_users'))

        except IntegrityError as e:
            db.session.rollback()
            if 'users.email' in str(e.orig):
                flash(f"A user with the email '{submitted_email}' already exists. Please use a different email address.", "danger")
            elif 'users.username' in str(e.orig):
                flash("That username is already taken. Please choose a different one.", "danger")
            else:
                flash("Could not create user because it conflicts with an existing record.", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"Database write fault occurred during enrollment processing: {str(e)}", "danger")

    return render_template('admin_users.html', form=form, users=users, classes=classes)


@app.route('/admin/users/<int:user_id>/unlock', methods=['POST'])
@login_required
def unlock_user(user_id):
    if normalize_role(current_user) not in ('admin', 'principal'):
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    # ✨ Modern Flask-SQLAlchemy lookup format
    user = db.first_or_404(db.select(User).filter_by(id=user_id))

    try:
        # ✨ FIX 2: Reset the User's core model security state fields if they exist
        if hasattr(user, 'login_attempts'):
            user.login_attempts = 0
        if hasattr(user, 'is_locked'):
            user.is_locked = False
        if hasattr(user, 'status'):
            user.status = 'Active'
        if hasattr(user, 'is_active'):
            user.is_active = True
        user.deactivated_at = None
        user.deactivation_reason = None

        # Clear recent failed login attempts (last 15 minutes to clear brute-force threshold logs)
        fifteen_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
        
        deleted_count = db.session.execute(
            db.delete(SecurityLog).where(
                SecurityLog.event == 'FAILED_LOGIN',
                SecurityLog.timestamp >= fifteen_minutes_ago
            )
        ).rowcount

        # Log this administrative override execution
        unlock_log = SecurityLog(
            ip_address=request.remote_addr,
            event=f"ACCOUNT_UNLOCKED: User ID {user.id} manually unlocked by {current_user.full_name} ({normalize_role(current_user)}).",
        )
        db.session.add(unlock_log)
        
        db.session.commit()
        flash(f"Account successfully unlocked for {user.username if hasattr(user, 'username') else 'the user'}. Security tracking variables reset.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"System directory lock failure: {str(e)}", "danger")

    # Dynamic fallback check to make sure the redirect endpoint doesn't break
    target = 'admin_users' if 'admin_users' in current_app.view_functions else 'dashboard'
    return redirect(url_for(target))

with app.app_context():
    try:
        db.create_all()
        ensure_legacy_sqlite_schema()
        ensure_grade_releases_table()
        ensure_transcript_releases_table()
        ensure_scale_indexes(db)
        sealed = seal_academic_year_folders(db)
        if sealed:
            print(f"Year folders: tagged {sealed} unassigned record(s) into their academic year.")
        run_repairs = os.environ.get('RUN_BOOT_REPAIRS', '').lower() in ('1', 'true', 'yes')
        if run_repairs:
            repair_submission_legacy_links()
            relocated_media = normalize_misplaced_school_media()
            if relocated_media:
                print(f"School media repair: moved {relocated_media} photo/video item(s) out of entrance/info sections.")
            repaired_links = repair_student_portal_links()
            if repaired_links:
                print(f"Student portal repair: linked {repaired_links} student profile(s) to login account(s).")
            repaired_classes = repair_stale_student_class_assignments()
            if repaired_classes:
                print(f"Student class repair: synced {repaired_classes} stale class assignment(s) after rollover.")
            repaired_qr = repair_student_qr_tokens()
            if repaired_qr:
                print(f"Student QR repair: issued secure verification tokens for {repaired_qr} student profile(s).")
            repaired_parent_qr = repair_parent_report_tokens()
            if repaired_parent_qr:
                print(f"Parent report QR repair: issued tokens for {repaired_parent_qr} student profile(s).")
            synced = backfill_student_payments_to_income_ledger()
            if synced:
                print(f"Business ledger sync: posted {synced} historical student fee payment(s) as income.")
        print("Database ready. Year indexes on. Set RUN_BOOT_REPAIRS=1 only to run a full data-repair pass.")
    except Exception as db_err:
        print(f"Warning: table auto-generation bypass encountered: {db_err}")

if __name__ == '__main__':
    _start_rembg_session_preload()
    host = os.environ.get('BIND_HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '3000'))
    threads = recommended_waitress_threads()
    connection_limit = env_int('WAITRESS_CONNECTION_LIMIT', 200, minimum=20, maximum=2000)
    channel_timeout = env_int('WAITRESS_CHANNEL_TIMEOUT', 480, minimum=30, maximum=600)
    backlog = env_int('WAITRESS_BACKLOG', 256, minimum=16, maximum=2048)
    
    print("\n" + "=" * 50)
    print(f"  Server active on port {port} ({threads} Waitress threads)")
    print(f"  > Local Access:   http://localhost:{port}")
    print(f"  > Loopback IP:    http://127.0.0.1:{port}")
    print(f"  > Network Bind:   http://0.0.0.0:{port}")
    print("=" * 50 + "\n")
    
    try:
        from waitress import serve
        serve(
            app,
            host=host,
            port=port,
            threads=threads,
            connection_limit=connection_limit,
            channel_timeout=channel_timeout,
            backlog=backlog,
        )
    except Exception as e:
        print(f"Waitress production engine failed: {e}")
        print("Falling back to local development server...")
        # Bound to host ('0.0.0.0') to allow port forwarding tools to connect
        app.run(debug=False, host=host, port=port)