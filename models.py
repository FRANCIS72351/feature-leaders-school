from datetime import datetime, timezone
from flask_login import UserMixin
from decimal import Decimal
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import validates, synonym
import os
import struct
import zlib
db = SQLAlchemy()

DEFAULT_STUDENT_PHOTO = "uploads/photos/default_student.png"
DEFAULT_USER_PHOTO = "uploads/photos/default_student.png"
DEFAULT_AVATAR_ALIASES = (
    "uploads/photos/default_student.png",
    "images/default-avatar.png",
    "img/default-avatar.png",
)
SCHOOL_LOGO_FILENAME = "images/LOGO.png"
_PHOTO_SEARCH_DIRS = (
    "uploads/photos",
    "uploads/students",
    "uploads/id_photos",
    "uploads/signatures",
    "uploads",
    "images",
    "img",
)
_DEFAULT_AVATAR_READY = False


def _static_photo_filename(photo_path):
    """Normalize a stored photo path to a static-relative filename."""
    if not photo_path:
        return None
    clean_path = str(photo_path).strip().replace("\\", "/")
    if not clean_path:
        return None
    if clean_path.startswith(("http://", "https://", "data:")):
        return clean_path
    marker = "/static/"
    idx = clean_path.lower().find(marker)
    if idx != -1:
        return clean_path[idx + len(marker):].lstrip("/")
    if clean_path.lower().startswith("static/"):
        return clean_path[7:]
    # Windows absolute paths (C:/...) are not static URLs; keep the basename.
    if len(clean_path) >= 2 and clean_path[1] == ":":
        return clean_path.rsplit("/", 1)[-1] or None
    return clean_path.lstrip("/")


def _photo_candidate_filenames(photo_path):
    """Possible static-relative paths for a stored photo value."""
    clean = _static_photo_filename(photo_path)
    if not clean:
        return []
    if clean.startswith(("http://", "https://", "data:")):
        return [clean]
    seen = []
    def _add(item):
        if item and item not in seen:
            seen.append(item)
    _add(clean)
    basename = clean.rsplit("/", 1)[-1]
    if basename:
        for folder in _PHOTO_SEARCH_DIRS:
            _add(f"{folder}/{basename}")
        _add(basename)
    return seen


def _png_chunk(tag, data):
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _build_default_avatar_png_bytes(size=128):
    """Circular red badge with a white person silhouette (real RGBA PNG)."""
    cx = cy = (size - 1) / 2.0
    r_badge = size / 2.0 - 1.5
    head_cy = cy - size * 0.16
    head_r = size * 0.16
    body_cy = cy + size * 0.28
    body_rx = size * 0.24
    body_ry = size * 0.28
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy > r_badge * r_badge:
                row.extend((0, 0, 0, 0))
                continue
            hx = x - cx
            hy = y - head_cy
            in_head = hx * hx + hy * hy <= head_r * head_r
            bx = (x - cx) / body_rx
            by = (y - body_cy) / body_ry
            in_body = (bx * bx + by * by <= 1.0) and (y > cy - size * 0.02)
            if in_head or in_body:
                row.extend((255, 255, 255, 255))
            else:
                row.extend((200, 40, 40, 255))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + _png_chunk(b"IEND", b"")
    )


_IMAGE_UPLOAD_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _is_placeholder_photo_name(photo_path):
    name = os.path.basename(str(photo_path or "").replace("\\", "/")).strip().lower()
    return name in ("default_student.png", "default-avatar.png", "default_avatar.png")


def _looks_like_raster_image(full_path):
    """True when path is an actual PNG/JPEG/GIF/WebP/BMP, not a text placeholder."""
    try:
        if not os.path.isfile(full_path) or os.path.getsize(full_path) < 24:
            return False
        with open(full_path, "rb") as fh:
            head = fh.read(16)
        ext = os.path.splitext(full_path)[1].lower()
    except OSError:
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head.startswith(b"\xff\xd8\xff"):
        return True
    if head.startswith((b"GIF87a", b"GIF89a")):
        return True
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return True
    if head.startswith(b"BM"):
        return True
    # Uploaded ID files that browsers still render (CMYK JPEG, odd headers).
    return ext in _IMAGE_UPLOAD_EXT and os.path.getsize(full_path) >= 24


def _ensure_default_avatar_files(static_root):
    """Replace text .png placeholders with a real circular default avatar."""
    global _DEFAULT_AVATAR_READY
    if _DEFAULT_AVATAR_READY or not static_root:
        return
    targets = (
        os.path.join(static_root, "uploads", "photos", "default_student.png"),
        os.path.join(static_root, "images", "default-avatar.png"),
        os.path.join(static_root, "img", "default-avatar.png"),
    )
    payload = None
    for path in targets:
        if _looks_like_raster_image(path):
            continue
        if payload is None:
            payload = _build_default_avatar_png_bytes()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(payload)
        except OSError:
            continue
    _DEFAULT_AVATAR_READY = any(_looks_like_raster_image(path) for path in targets)


def _static_file_on_disk(relative_path):
    """True when relative_path is a real image file under Flask's static folder."""
    from flask import current_app, has_app_context

    if not relative_path or relative_path.startswith(("http://", "https://", "data:")):
        return False
    if not has_app_context():
        return False

    roots = []
    static_root = getattr(current_app, "static_folder", None)
    if static_root:
        roots.append(static_root)
    root_path = getattr(current_app, "root_path", None)
    if root_path:
        roots.append(os.path.join(root_path, "static"))

    seen = set()
    rel = relative_path.replace("/", os.sep)
    for root in roots:
        norm = os.path.normpath(root)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        full = os.path.join(root, rel)
        try:
            if _looks_like_raster_image(full):
                return True
        except (OSError, ValueError):
            continue
    return False


def _static_url(filename):
    """Build a /static/... URL that never raises outside a request."""
    from flask import url_for, has_app_context, has_request_context

    filename = (filename or DEFAULT_STUDENT_PHOTO).replace("\\", "/").lstrip("/")
    if len(filename) >= 2 and filename[1] == ":":
        filename = DEFAULT_STUDENT_PHOTO
    if has_request_context() or has_app_context():
        try:
            return url_for("static", filename=filename)
        except Exception:
            pass
    return f"/static/{filename}"


def static_photo_file_exists(photo_path):
    """True when the stored photo maps to a real image file under static/."""
    if not photo_path or not str(photo_path).strip():
        return False
    raw = str(photo_path).strip()
    if raw.startswith(("http://", "https://", "data:")):
        return True
    try:
        if os.path.isabs(raw) and _looks_like_raster_image(raw):
            return True
    except (OSError, ValueError):
        pass
    for candidate in _photo_candidate_filenames(raw):
        if candidate.startswith(("http://", "https://", "data:")):
            return True
        if _static_file_on_disk(candidate):
            return True
    return False


def resolve_static_photo_url(photo_path, default_filename=DEFAULT_STUDENT_PHOTO):
    """Turn a stored photo path into a working static URL (uploaded file or default)."""
    from flask import current_app, has_app_context

    if has_app_context() and getattr(current_app, "static_folder", None):
        _ensure_default_avatar_files(current_app.static_folder)

    for candidate in _photo_candidate_filenames(photo_path):
        if candidate.startswith(("http://", "https://", "data:")):
            return candidate
        if _static_file_on_disk(candidate):
            return _static_url(candidate)

    fallbacks = []
    for name in (default_filename, DEFAULT_STUDENT_PHOTO, DEFAULT_USER_PHOTO) + DEFAULT_AVATAR_ALIASES:
        if name and name not in fallbacks:
            fallbacks.append(name)
    for fallback in fallbacks:
        if _static_file_on_disk(fallback):
            return _static_url(fallback)
    return _static_url(fallbacks[0] if fallbacks else DEFAULT_STUDENT_PHOTO)


def default_static_photo_url():
    """Always-valid default avatar URL for templates and onerror fallbacks."""
    return resolve_static_photo_url(None, default_filename=DEFAULT_USER_PHOTO)


def school_logo_static_url():
    """Always-valid school logo URL (LOGO.png, with lowercase fallback)."""
    for name in (SCHOOL_LOGO_FILENAME, "images/logo.png", "images/logo1.png"):
        if _static_file_on_disk(name):
            return _static_url(name)
    return _static_url(SCHOOL_LOGO_FILENAME)


LIBERIA_SEAL_FILENAMES = (
    "images/liberia_seal.png",
    "images/liberia-seal.png",
    "images/liberia_coat_of_arms.png",
    "images/coat_of_arms.png",
    "images/liberia.png",
    "images/seal.png",
)


def liberia_seal_static_url():
    """Liberia coat-of-arms URL when a seal image is present under static/images/."""
    for name in LIBERIA_SEAL_FILENAMES:
        if _static_file_on_disk(name):
            return _static_url(name)
    return None


PRINCIPAL_SIGNATURE_FILENAMES = (
    "images/principal_signature.png",
    "images/principal-signature.png",
)


def principal_signature_static_url():
    """School principal's authorizing signature for the back of every ID card."""
    for name in PRINCIPAL_SIGNATURE_FILENAMES:
        if _static_file_on_disk(name):
            return _static_url(name)
    return None


# Algerian is a licensed Monotype face bundled with Windows/Office, so it cannot
# be vendored here. Browsers use a locally installed copy when the machine has
# one; drop a copy under static/fonts/ to serve it to everyone else.
DISPLAY_FONT_FILENAMES = (
    "fonts/algerian.woff2",
    "fonts/algerian.ttf",
)


def display_font_static_url():
    """Self-hosted Algerian URL when a copy is present under static/fonts/."""
    for name in DISPLAY_FONT_FILENAMES:
        if _static_file_on_disk(name):
            return _static_url(name)
    return None

# =====================================================================
# 1. AUTHENTICATION & CORE USER MODEL
# =====================================================================
class User(db.Model, UserMixin):
    """
    Central Security and Authentication Core.
    Houses global baseline profile variables, hashed access credentials, 
    and multi-factor parameters across all functional operational roles.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # admin, teacher, student, parent, sponsor
    full_name = db.Column(db.String(120), nullable=False)
    photo = db.Column(db.String(200))
    totp_secret = db.Column(db.String(32))  # 2FA Secret Key
    home_address = db.Column(db.String(255))
    telephone_number = db.Column(db.String(20))
    status = db.Column(db.String(20), default='Active', server_default='Active', nullable=False)
    is_active = db.Column(db.Boolean, default=True, server_default='1', nullable=False)
    must_change_password = db.Column(
        db.Boolean, default=False, server_default='0', nullable=False,
    )
    deactivated_at = db.Column(db.DateTime, nullable=True)
    deactivation_reason = db.Column(db.String(255), nullable=True)
    id_card_photo_path = db.Column(db.String(200), nullable=True)
    id_card_signature_path = db.Column(db.String(200), nullable=True)
    id_expiration_date = db.Column(db.Date, nullable=True)
    staff_id_card_ready = db.Column(db.Boolean, default=False, server_default='0', nullable=False)

    # Employment record shown in the staff folder (VPA / Principal office).
    job_title = db.Column(db.String(120), nullable=True)
    department = db.Column(db.String(120), nullable=True)
    employment_type = db.Column(db.String(40), nullable=True)  # Full-time, Part-time, Contract, Volunteer
    hire_date = db.Column(db.Date, nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    national_id_number = db.Column(db.String(60), nullable=True)
    highest_qualification = db.Column(db.String(160), nullable=True)
    emergency_contact_name = db.Column(db.String(120), nullable=True)
    emergency_contact_phone = db.Column(db.String(40), nullable=True)
    staff_notes = db.Column(db.Text, nullable=True)

    def is_account_active(self):
        """Return True when the account may authenticate."""
        if self.is_active is False:
            return False
        normalized = (self.status or 'Active').strip().lower()
        return normalized not in ('inactive', 'terminated', 'disabled', 'suspended')

    def set_password(self, password):
        """Hash and store the provided plaintext password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify the provided password against the stored hash."""
        if not self.is_account_active():
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def has_photo(self):
        """True when this account has an uploaded photo file on disk."""
        return static_photo_file_exists(self.photo)

    @property
    def photo_url(self):
        """Always return a working avatar URL (uploaded file, student photo, or default)."""
        sources = []
        if self.photo:
            sources.append(self.photo)
        profile = getattr(self, "student_profile", None)
        if profile is not None:
            if getattr(profile, "photo", None):
                sources.append(profile.photo)
            filename = (getattr(profile, "photo_filename", None) or "").strip()
            if filename and filename.lower() not in ("default_student.png", "default-avatar.png"):
                sources.append(f"uploads/photos/{filename}")
                sources.append(f"uploads/students/{filename}")
        for source in sources:
            if source and static_photo_file_exists(source):
                return resolve_static_photo_url(source, default_filename=DEFAULT_USER_PHOTO)
        return resolve_static_photo_url(self.photo, default_filename=DEFAULT_USER_PHOTO)

    def __repr__(self):
        return f"<User {self.full_name} ({self.role})>"


class SecurityLog(db.Model):
    __tablename__ = "security_logs"

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45))  # Supports both IPv4 and IPv6
    event = db.Column(db.String(100))      # e.g., "FAILED_LOGIN", "SUSPENDED_ENTRY"
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<SecurityLog {self.event} from {self.ip_address} at {self.timestamp}>"


# =====================================================================
# 2. ACADEMIC ENVIRONMENT INFRASTRUCTURE
# =====================================================================
class Room(db.Model):
    """
    Physical space allocation mapping tracking structural infrastructure layouts,
    maximum design capacity, and real-time occupancy loads within the institution.
    """
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)  # Core Identifier (e.g., 'Room 101', 'Lab A')
    number = db.Column(db.String(20), nullable=True, unique=True)  # Secondary identifier for room number/code
    capacity = db.Column(db.Integer, nullable=False, default=40)
    current_occupancy = db.Column(db.Integer, nullable=False, default=0)

    # Relationship backref tracking classes operating inside this space
    assigned_classes = db.relationship("Class", backref="physical_room", lazy=True)

    def __repr__(self):
        return f"<Room {self.name} ({self.current_occupancy}/{self.capacity})>"
    
class AcademicYear(db.Model):
    __tablename__ = "academic_years"

    id = db.Column(db.Integer, primary_key=True)
    
    # Using String(32) to comfortably fit formats like "2025–2026" or "2025/2026"
    name = db.Column(db.String(32), unique=True, nullable=False)  
    
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    
    # default=False ensures a new year isn't active until explicitly set 
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    
    # Audit and tracking fields from your first model
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_on = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    current_year = db.Column(db.String(20), nullable=True)
    klass_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=True)

    # Relationships to enable cascading historical tracking
    grades = db.relationship(
        'Grade',
        backref='academic_year',
        lazy=True,
        passive_deletes=True,
    )
    
    # REMOVED the broken payments line! 
    # Your StudentPayment class automatically handles this link via 'payment_records'

    def __repr__(self):
        return f"<AcademicYear {self.name} (Active: {self.is_active})>"


class Class(db.Model):
    """
    Academic Infrastructure Node:
    Manages structural grade sections, physical facility mappings, 
    and foundational tuition rate metrics.
    """
    __tablename__ = 'classes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    grade_level = db.Column(db.String(50), nullable=False)                   # e.g., Grade 7, JSS 1
    stream = db.Column(db.String(50), nullable=True)                         # e.g., 'Science', 'Arts'
    yearly_fees = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Optional links to an assigned teacher and a sponsoring user (e.g., form/class sponsor)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    sponsor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id', ondelete='SET NULL'), nullable=True)

    # FIXED RELATIONSHIPS: Uses explicit back_populates to map allocations cleanly without collisions
    allocations = db.relationship('ClassSubjectTeacher', back_populates='klass_node', cascade="all, delete-orphan", lazy='dynamic')
    subject_catalog = db.relationship('ClassSubject', back_populates='klass', cascade="all, delete-orphan", lazy='dynamic')
    students = db.relationship('Student', back_populates='assigned_class', lazy='dynamic')

    # Optional per-class grading scheme, stored as JSON. Example:
    # {"method": "category", "categories": {"assignments": 40, "tests": 20, "exam": 40}, "drop_lowest": {"assignments": 1}}
    grading_scheme = db.Column(db.JSON, nullable=True)

    @validates('yearly_fees')
    def validate_fees(self, key, value):
        if value is None:
            return 0.00
        float_val = float(value)
        if float_val < 0:
            raise ValueError("Financial Constraint Violation: Baseline fees cannot be below 0.00")
        return float_val

    @validates('grade_level')
    def validate_grade_level(self, key, value):
        if value is None:
            raise ValueError("Structural Constraint Violation: Grade level is required.")
        text = str(value).strip()
        if not text:
            raise ValueError("Structural Constraint Violation: Grade level cannot be empty.")
        if len(text) > 50:
            raise ValueError("Structural Constraint Violation: Grade level must be 50 characters or fewer.")
        return text

    @property
    def school_division(self):
        from school_divisions import resolve_from_class
        return resolve_from_class(self)

    @property
    def school_division_label(self):
        from school_divisions import division_label_for_class
        return division_label_for_class(self)

    @property
    def student_count(self):
        return self.students.count()

    @property
    def yearly_fee(self):
        """Alias for templates and legacy code that use yearly_fee."""
        return self.yearly_fees

    @yearly_fee.setter
    def yearly_fee(self, value):
        self.yearly_fees = value

    @property
    def allocation_summary(self):
        return self.allocations.count()

    def __repr__(self):
        return f"<ClassNode ID: {self.id} | Label: {self.name} | Tier: {self.grade_level}>"


# =====================================================================
# 3. FACULTY & TERNARY ALLOCATION SYSTEM
# =====================================================================
class Teacher(db.Model):
    """
    Personnel profile mapping for active teaching faculty members,
    tied back structurally to user authentication accounts.
    """
    __tablename__ = "teachers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(80), nullable=True)  # Primary specialized domain
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("teacher_profile", uselist=False))
    status = db.Column(db.String(20), default='ACTIVE', server_default='ACTIVE', nullable=False)
    # FIXED RELATIONSHIP: Uses back_populates to safely connect with allocation matrices
    allocations = db.relationship('ClassSubjectTeacher', back_populates='teacher_node', cascade="all, delete-orphan")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def photo_url(self):
        """Faculty photos live on the linked User.photo column."""
        user_photo = getattr(self.user, "photo", None) if self.user else None
        return resolve_static_photo_url(user_photo, default_filename=DEFAULT_USER_PHOTO)

    def __repr__(self):
        return f"<Teacher {self.full_name}>"


class ClassSubjectTeacher(db.Model):
    """
    Relational Bridge Matrix Model:
    Explicitly maps the ternary relationship between a Class, a Teacher, 
    and a Subject, preventing duplicates via DB constraints.
    """
    __tablename__ = 'class_subject_teachers'

    __table_args__ = (
        db.UniqueConstraint(
            'class_id', 'teacher_id', 'subject_name', 
            name='uix_class_teacher_subject_allocation'
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id', ondelete='CASCADE'), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id', ondelete='CASCADE'), nullable=False, index=True)
    subject_name = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # FIXED INTERCONNECTS: Replaced duplicate overlapping backrefs with unified populating references
    klass_node = db.relationship('Class', back_populates='allocations')
    teacher_node = db.relationship('Teacher', back_populates='allocations')

    @property
    def teacher(self):
        return self.teacher_node

    @property
    def allocation_signature(self):
        return f"CLS-{self.class_id}::TCH-{self.teacher_id}::SUB-{str(self.subject_name).upper().strip()}"

    def __repr__(self):
        return f"<ClassSubjectTeacher Assignment ID: {self.id} | Class: {self.class_id} -> Subject: {self.subject_name}>"


class ClassSubject(db.Model):
    """Subjects offered in a class before or without a teacher assignment."""
    __tablename__ = 'class_subjects'

    __table_args__ = (
        db.UniqueConstraint('class_id', 'subject_name', name='uix_class_subject_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id', ondelete='CASCADE'), nullable=False, index=True)
    subject_name = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    klass = db.relationship('Class', back_populates='subject_catalog')

    def __repr__(self):
        return f"<ClassSubject {self.class_id}: {self.subject_name}>"


def resolve_parent_guardian_name(student):
    """Parent / Guardian display name from registrar field or linked parent account."""
    if not student:
        return None
    for candidate in (
        getattr(student, 'guardian_name', None),
        getattr(student, 'parent_name', None),
        getattr(getattr(student, 'parent_user', None), 'full_name', None),
    ):
        text = str(candidate).strip() if candidate else ''
        if text:
            return text
    return None


# =====================================================================
# 4. STUDENT RECORD LEDGER NODES
# =====================================================================
class Student(db.Model):
    """
    Comprehensive demographic, operational, and financial control records
    for registered institutional students.
    """
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    student_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    student_id_code = db.Column(db.String(50), unique=True, index=True, nullable=True)

    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    parent_email = db.Column(db.String(120), nullable=True)
    parent_phone = db.Column(db.String(20), nullable=True)
    guardian_name = db.Column(db.String(120), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    secure_qr_token = db.Column(db.String(128), unique=True, nullable=True, index=True)
    parent_report_token = db.Column(db.String(128), unique=True, nullable=True, index=True)
    parent_report_pin_hash = db.Column(db.String(200), nullable=True)

    photo = db.Column(db.String(200), nullable=True)
    photo_filename = db.Column(db.String(200), default='default_student.png')
    signature_filename = db.Column(db.String(200), nullable=True)
    id_card_ready = db.Column(db.Boolean, default=False, server_default='0', nullable=False)
    id_expiration_date = db.Column(db.Date, nullable=True)

    status = db.Column(db.String(20), default='ACTIVE', nullable=False)  # ACTIVE, REPEAT, SUMMER_SCHOOL, FAILED, SUSPENDED, ALUMNI, GRADUATED
    grade_level = db.Column(db.String(50), nullable=True)
    level = db.Column(db.String(50), nullable=True)                      # Elementary, Junior High, Senior High
    registration_type = db.Column(db.String(20), default='New', nullable=False)
    registrar = db.Column(db.String(100), nullable=True)

    # Core relationship foreign keys
    klass_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True)

    __table_args__ = (
        db.Index("ix_students_year_class", "academic_year_id", "klass_id"),
        db.Index("ix_students_year_status", "academic_year_id", "status"),
    )

    tuition_cleared = db.Column(db.Boolean, default=False, nullable=False)
    registration_fees = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    is_promoted = db.Column(db.Boolean, default=False, server_default='0', nullable=False)
    is_registered = db.Column(db.Boolean, default=True, server_default='1', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        backref=db.backref("student_profile", uselist=False),
    )
    parent_user = db.relationship(
        "User",
        foreign_keys=[parent_id],
        backref=db.backref("linked_students", lazy="dynamic"),
    )
    assigned_class = db.relationship("Class", back_populates="students")
    academic_year = db.relationship("AcademicYear", backref=db.backref("students_ledger", lazy="dynamic"))
    
    # =========================================================================
    # BACKWARD COMPATIBILITY PROPERTIES (CRASH PREVENTERS)
    # =========================================================================
    @property
    def klass(self):
        """Maps student.klass directly to assigned_class to fix template lookups."""
        return self.assigned_class

    @property
    def class_(self):
        """Maps student.class_ directly to assigned_class as an alternative safety hook."""
        return self.assigned_class

    @property
    def current_class(self):
        """Dean/legacy dashboard alias for assigned class."""
        return self.assigned_class

    @property
    def current_class_id(self):
        """Alias for klass_id used by roster and finance gatekeeping queries."""
        return self.klass_id

    @property
    def current_grade(self):
        """Grade tier for the student (maps to grade_level / assigned class)."""
        if self.grade_level is not None:
            return self.grade_level
        if self.assigned_class and self.assigned_class.grade_level is not None:
            return self.assigned_class.grade_level
        return None

    @property
    def academic_division_label(self):
        """Elementary / Junior High / Senior High from assigned class."""
        from school_divisions import academic_level_for_student
        return academic_level_for_student(self)

    @current_grade.setter
    def current_grade(self, value):
        self.grade_level = value

    @validates('registration_fees')
    def validate_fees(self, key, value):
        if value is None:
            return Decimal('0.00')
        # Ensure handling as Decimal for structural precision
        decimal_val = Decimal(str(value))
        if decimal_val < 0.00:
            raise ValueError("Accounting Exception: Registration values cannot be negative.")
        return decimal_val

    @property
    def full_name(self):
        if self.user and getattr(self.user, 'full_name', None):
            return str(self.user.full_name).strip()
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def parent_guardian_name(self):
        """Name printed on ID cards and registrar files (typed guardian or linked parent)."""
        return resolve_parent_guardian_name(self)

    def _id_photo_sources(self):
        """Candidate paths for a real (non-placeholder) student photograph.

        Processed ID JPEGs (uploads/id_photos/) come first so print never serves
        an uncropped uploads/students/ original when both exist.
        """
        sources = []
        if self.photo and not _is_placeholder_photo_name(self.photo):
            sources.append(self.photo)
        filename = (self.photo_filename or "").strip()
        if filename and not _is_placeholder_photo_name(filename):
            if "/" in filename.replace("\\", "/"):
                sources.append(filename.replace("\\", "/"))
            else:
                sources.append(f"uploads/id_photos/{filename}")
                sources.append(f"uploads/photos/{filename}")
                sources.append(f"uploads/students/{filename}")
                sources.append(filename)
        if self.user and getattr(self.user, "photo", None) and not _is_placeholder_photo_name(self.user.photo):
            sources.append(self.user.photo)
        preferred = []
        rest = []
        seen = set()
        for source in sources:
            key = source.replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            basename = source.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if "/id_photos/" in source.replace("\\", "/") and not basename.startswith("original_"):
                preferred.append(source)
            else:
                rest.append(source)
        return preferred + rest

    @property
    def photo_url(self):
        """Always return a working avatar URL (student, user, or default)."""
        for source in self._id_photo_sources():
            if static_photo_file_exists(source):
                return resolve_static_photo_url(source, default_filename=DEFAULT_STUDENT_PHOTO)
        return resolve_static_photo_url(None, default_filename=DEFAULT_STUDENT_PHOTO)

    @property
    def has_id_photo(self):
        """True when a real student photograph exists (not the default avatar)."""
        return any(static_photo_file_exists(source) for source in self._id_photo_sources())

    @property
    def official_signature_mark(self):
        """Professional ID signature: last name plus first-name initial (e.g. Reawes P.)."""
        last = " ".join((self.last_name or "").split()).title()
        first = " ".join((self.first_name or "").split())
        if not last and not first:
            parts = (self.full_name or "").split()
            first = parts[0] if parts else ""
            last = " ".join(parts[1:]).title() if len(parts) > 1 else ""
        initial = f"{first[0].upper()}." if first else ""
        if last and initial:
            return f"{last} {initial}"
        return last or (first.title() if first else "")

    @property
    def signature_url(self):
        """Static URL for an uploaded handwritten signature, or None if missing."""
        filename = (self.signature_filename or "").strip().replace("\\", "/")
        if not filename:
            return None
        sources = [filename] if "/" in filename else [f"uploads/signatures/{filename}", filename]
        for source in sources:
            if static_photo_file_exists(source):
                return resolve_static_photo_url(source, default_filename=DEFAULT_STUDENT_PHOTO)
        return None

    @property
    def has_signature(self):
        return bool(self.signature_url or self.official_signature_mark)

    def __repr__(self):
        return f"<StudentNode ID: {self.student_id} | Name: {self.full_name}>"

    @property
    def student_code(self):
        """Permanent public student code (alias for student_id)."""
        return self.student_id


class StudentRegistryDocument(db.Model):
    """Scanned or uploaded papers kept in a student's registrar folder."""
    __tablename__ = "student_registry_documents"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    doc_type = db.Column(db.String(40), nullable=False, default="other")
    original_filename = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    ocr_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    student = db.relationship(
        "Student",
        backref=db.backref(
            "registry_documents",
            lazy="select",
            cascade="all, delete-orphan",
            order_by="StudentRegistryDocument.created_at.desc()",
        ),
    )
    uploaded_by = db.relationship("User")
    academic_year = db.relationship("AcademicYear")

    DOC_TYPE_LABELS = {
        "birth_certificate": "Birth certificate",
        "national_id": "National ID / passport",
        "report_card": "Report card",
        "medical": "Medical record",
        "transfer": "Transfer letter",
        "photo_id": "Student photo ID",
        "other": "Other document",
    }

    @property
    def type_label(self):
        return self.DOC_TYPE_LABELS.get(self.doc_type, "Document")

    @property
    def is_image(self):
        name = (self.original_filename or self.file_path or "").lower()
        mime = (self.mime_type or "").lower()
        return mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))

    @property
    def is_pdf(self):
        name = (self.original_filename or self.file_path or "").lower()
        mime = (self.mime_type or "").lower()
        return mime == "application/pdf" or name.endswith(".pdf")

    def __repr__(self):
        return f"<StudentRegistryDocument {self.id} student={self.student_id}>"


class StaffDocument(db.Model):
    """Papers filed in an employee's staff folder (VPA / Principal office)."""
    __tablename__ = "staff_documents"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    doc_type = db.Column(db.String(40), nullable=False, default="other")
    original_filename = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    staff = db.relationship(
        "User",
        foreign_keys=[staff_id],
        backref=db.backref(
            "staff_documents",
            lazy="select",
            cascade="all, delete-orphan",
            order_by="StaffDocument.created_at.desc()",
        ),
    )
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_id])

    DOC_TYPE_LABELS = {
        "appointment_letter": "Appointment letter",
        "contract": "Employment contract",
        "cv": "CV / résumé",
        "certificate": "Academic certificate",
        "national_id": "National ID / passport",
        "police_clearance": "Police clearance",
        "medical": "Medical record",
        "reference": "Reference letter",
        "appraisal": "Performance appraisal",
        "warning": "Warning / disciplinary letter",
        "other": "Other document",
    }

    @property
    def type_label(self):
        return self.DOC_TYPE_LABELS.get(self.doc_type, "Document")

    @property
    def is_image(self):
        name = (self.original_filename or self.file_path or "").lower()
        mime = (self.mime_type or "").lower()
        return mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))

    @property
    def is_pdf(self):
        name = (self.original_filename or self.file_path or "").lower()
        mime = (self.mime_type or "").lower()
        return mime == "application/pdf" or name.endswith(".pdf")

    def __repr__(self):
        return f"<StaffDocument {self.id} staff={self.staff_id}>"


class Suspension(db.Model):
    __tablename__ = "suspensions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    return_date = db.Column(db.DateTime, nullable=False)

    student = db.relationship("Student", backref=db.backref("suspensions_history", lazy="dynamic"))

    def __repr__(self):
        return f"<Suspension Student ID {self.student_id} until {self.return_date}>"
class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=True, index=True)

    __table_args__ = (
        db.Index("ix_enrollments_year_student", "academic_year_id", "student_id"),
        db.Index("ix_enrollments_year_class", "academic_year_id", "class_id"),
    )

    student = db.relationship("Student", backref=db.backref("class_enrollments", cascade="all, delete-orphan"))
    klass = db.relationship("Class", backref=db.backref("class_enrollments", cascade="all, delete-orphan"))
    academic_year = db.relationship("AcademicYear", backref=db.backref("class_enrollments", lazy="dynamic"))

    def __repr__(self):
        return f"<Enrollment ID {self.id}: Student {self.student_id} -> Class {self.class_id}>"

# =====================================================================
# 8. DISCIPLINARY & BEHAVIORAL CONTROL LAYER
# =====================================================================
class Discipline(db.Model):
    """
    Schema maintaining behavioral records, structural infractions,
    and formal disciplinary actions logged for registered students.
    """
    __tablename__ = "discipline_records"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    offense = db.Column(db.String(200), nullable=False)  # e.g., "Chronic Tardiness", "Dress Code Violation"
    infraction = synonym('offense')
    incident = synonym('offense')
    action_taken = db.Column(db.String(200), nullable=False) # e.g., "Parent Conference", "Detention"
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    date_logged = synonym('created_at')
    date = synonym('created_at')
    logged_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Core Relationships
    student = db.relationship("Student", backref=db.backref("discipline_logs", lazy="dynamic", cascade="all, delete-orphan"))
    staff_reporter = db.relationship("User", foreign_keys=[logged_by_id], backref="reported_infractions")

    def __repr__(self):
        return f"<Discipline Record ID {self.id} | Student ID {self.student_id} - {self.offense}>"
    
# =====================================================================
# 9. INSTITUTIONAL ASSET & INVENTORY LOGISTICS MODEL
# =====================================================================
class Asset(db.Model):
    """
    Schema maintaining structural asset protection records, inventory metrics,
    and institutional property valuations.
    """
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)          # e.g., "HP ProBook Laptop", "Generator", "Desk"
    serial_number = db.Column(db.String(100), unique=True)    # Serial lookup identifier
    category = db.Column(db.String(100))                       # e.g., "Electronics", "Furniture", "Vehicles"
    status = db.Column(db.String(50), default="Functional")   # Functional, Under Repair, Decommissioned
    purchase_date = db.Column(db.Date, nullable=True)
    cost = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f"<Asset {self.name} | Status: {self.status}>"
    
# =====================================================================
# 10. FACILITY MAINTENANCE & LOGISTICS LOGS
# =====================================================================
class MaintenanceTicket(db.Model):
    """
    Schema maintaining infrastructure repair notes, asset service requests,
    and operational technical ticket tracking across the campus.
    """
    __tablename__ = "maintenance_tickets"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False)
    issue_description = db.Column(db.Text, nullable=False)    # e.g., "Screen cracked", "Oil leak"
    priority = db.Column(db.String(50), default="Medium")      # Low, Medium, High, Emergency
    status = db.Column(db.String(50), default="Pending")       # Pending, In Progress, Resolved, Cancelled
    logged_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)

    # Core Relationship mapping back into the master Asset system nodes
    asset = db.relationship("Asset", backref=db.backref("maintenance_history", lazy="dynamic", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<MaintenanceTicket ID {self.id} | Asset ID {self.asset_id} | Status: {self.status}>"

# =====================================================================
# 11. GENERAL ACTIVITY LOG / AUDIT TRAIL LAYER
# =====================================================================
class Activity(db.Model):
    """
    Schema maintaining general system activity tracking, audit trails,
    and administrative operational histories.
    """
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(255), nullable=False)       # e.g., "Updated Grade for Student ID 5"
    module = db.Column(db.String(100), nullable=True)       # e.g., "Grading", "Finance", "Inventory"
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)

    # Core Relationship mapping back to the User who performed the action
    user = db.relationship("User", backref=db.backref("activity_history", lazy="dynamic"))

    def __repr__(self):
        return f"<Activity ID {self.id} | User {self.user_id} | Action: {self.action}>"


class RolloverLog(db.Model):
    """Audit trail for academic year rollover operations."""
    __tablename__ = "rollover_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    from_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id', ondelete='SET NULL'), nullable=True)
    from_year_name = db.Column(db.String(32), nullable=True)
    to_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id', ondelete='SET NULL'), nullable=True)
    to_year_name = db.Column(db.String(32), nullable=True)
    promoted = db.Column(db.Integer, default=0, nullable=False)
    retained = db.Column(db.Integer, default=0, nullable=False)
    graduated = db.Column(db.Integer, default=0, nullable=False)
    re_registration = db.Column(db.Integer, default=0, nullable=False)
    rollover_mode = db.Column(db.String(20), default='quick', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", backref=db.backref("rollover_logs", lazy="dynamic"))
    from_year = db.relationship("AcademicYear", foreign_keys=[from_year_id])
    to_year = db.relationship("AcademicYear", foreign_keys=[to_year_id])

    def __repr__(self):
        return (
            f"<RolloverLog {self.from_year_name} → {self.to_year_name} "
            f"by user {self.user_id}>"
        )

# =====================================================================
# 12. ACADEMIC SUBMISSIONS & ASSIGNMENT GRADING PIPELINE
# =====================================================================
class Submission(db.Model):
    """
    Schema maintaining records for student assignment, test, or quiz submissions,
    tracking grading evaluations, feedback notes, and completion timelines.
    """
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('assessments.id', ondelete='CASCADE'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False, index=True)

    text_response = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    score = db.Column(db.Float, nullable=True)
    teacher_feedback = db.Column(db.Text, nullable=True)
    is_graded = db.Column(db.Boolean, default=False, nullable=False)
    scan_code = db.Column(db.String(36), unique=True, nullable=True, index=True)
    score_published = db.Column(db.Boolean, default=False, nullable=False)

    # Modern field aliases mapped to legacy SQLite columns
    assessment_id = synonym('activity_id')
    submission_text = synonym('text_response')

    assessment = db.relationship(
        "Assessment",
        foreign_keys=[activity_id],
        backref=db.backref("student_submissions", lazy="dynamic", cascade="all, delete-orphan"),
    )
    student = db.relationship("Student", backref=db.backref("academic_submissions", lazy="dynamic", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Submission ID {self.id} | Assessment ID {self.activity_id} | Student ID {self.student_id} | Graded: {self.is_graded}>"

class Announcement(db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(50), nullable=False, default="all")
    category = db.Column(db.String(50), nullable=True)
    author = db.Column(db.String(100), nullable=False, default="System")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Template-friendly aliases mapped to legacy DB columns
    content = synonym("body")
    target_role = synonym("audience")

    @property
    def formatted_date(self):
        if not self.created_at:
            return "Date unknown"
        if isinstance(self.created_at, datetime):
            return self.created_at.strftime("%b %d, %Y")
        return str(self.created_at)[:16]

    def __repr__(self):
        return f"<Announcement '{self.title}' for {self.audience}>"

# =====================================================================
# 5. LIBERIA MOE 6-PERIOD GRADING SYSTEM & ATTENDANCE
# =====================================================================
class Grade(db.Model):
    """
    Standard Liberia Ministry of Education (MoE) 6-Period System Grade Tracking Layout.
    Incorporates continuous assessment (60%) and examination weights (40%).
    Now fully isolated by Academic Year multi-tenancy.
    """
    __tablename__ = "grades"

    id = db.Column(db.Integer, primary_key=True)
    
    # Core foreign keys with explicit ondelete rules
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True)
    
    # The crucial multi-tenancy link for academic year switching
    academic_year_id = db.Column(
        db.Integer,
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Subject Details
    subject = db.Column(db.String(120), nullable=True)
    subject_name = db.Column(db.String(100), nullable=False)
    
    # Structural Context tracking 
    marking_period = db.Column(db.Integer)  # 1-6 regular, 7 Exam, 8 Final Exam
    period = db.Column(db.String(50), nullable=True)  # e.g., "Period 1", "First Semester"
    activity_type = db.Column(db.String(50))  # Test, Quiz, Assignment
    
    # Grade breakdown weights
    ca_score = db.Column(db.Float, default=0.0)    # 60% Continuous Assessment Weight
    exam_score = db.Column(db.Float, default=0.0)  # 40% Examination Weight
    score = db.Column(db.Float, default=0.0)       # Calculated individual total
    # JSON: {attendance, participation, quiz, assignment, classwork, other, test, direct_total}
    component_scores = db.Column(db.Text, nullable=True)
    
    # 6-Period System Columns for historical summary within the session
    p1 = db.Column(db.Integer, default=0)
    p2 = db.Column(db.Integer, default=0)
    p3 = db.Column(db.Integer, default=0)
    p4 = db.Column(db.Integer, default=0)
    p5 = db.Column(db.Integer, default=0)
    p6 = db.Column(db.Integer, default=0)
    
    # Workflow Status Flags
    submitted = db.Column(db.Boolean, default=False, nullable=False)
    is_finalized = db.Column(db.Boolean, default=False, nullable=False)  # Locked entry flag
    remarks = db.Column(db.String(200), nullable=True)

    # Attribution — who last entered or edited scores (teacher vs principal backup)
    entered_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entered_by_role = db.Column(db.String(30), nullable=True)

    __table_args__ = (
        db.Index("ix_grades_year_student", "academic_year_id", "student_id"),
        db.Index("ix_grades_year_class", "academic_year_id", "class_id"),
        db.Index("ix_grades_student", "student_id"),
    )

    # ORM Relationships mapping
    student = db.relationship("Student", backref=db.backref("grades_ledger", lazy="dynamic", cascade="all, delete-orphan"))
    teacher = db.relationship("Teacher", backref=db.backref("grades_ledger", lazy="dynamic"))
    klass = db.relationship("Class", backref=db.backref("grades_ledger", lazy="dynamic"))
    entered_by_user = db.relationship("User", foreign_keys=[entered_by_user_id])

    @property
    def final_average(self):
        """Calculates MoE rounded average across all periods with entered grades."""
        scores = [self.p1, self.p2, self.p3, self.p4, self.p5, self.p6]
        valid_scores = [s for s in scores if s > 0]
        return round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0.0

    def __repr__(self):
        return f"<Grade ID {self.id}: Student {self.student_id} - Year ID: {self.academic_year_id} - Subj: {self.subject_name}>"


class GradeRelease(db.Model):
    """VPA approval package for one class marking period (report card / grade sheet)."""
    __tablename__ = "grade_releases"

    STATUS_DRAFT = "draft"
    STATUS_PENDING_VPA = "pending_vpa"
    STATUS_APPROVED = "approved"
    STATUS_RETURNED = "returned"

    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False
    )
    class_id = db.Column(
        db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    period = db.Column(db.Integer, nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_DRAFT, server_default="draft")

    published_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at = db.Column(db.DateTime, nullable=True)

    approved_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at = db.Column(db.DateTime, nullable=True)

    returned_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    returned_at = db.Column(db.DateTime, nullable=True)
    review_comment = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "academic_year_id", "class_id", "period",
            name="uq_grade_release_year_class_period",
        ),
        db.Index("ix_grade_releases_status", "status"),
        db.Index("ix_grade_releases_year_class", "academic_year_id", "class_id"),
    )

    academic_year = db.relationship("AcademicYear")
    klass = db.relationship("Class")
    published_by = db.relationship("User", foreign_keys=[published_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    returned_by = db.relationship("User", foreign_keys=[returned_by_id])

    @property
    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING_VPA

    def __repr__(self):
        return (
            f"<GradeRelease year={self.academic_year_id} class={self.class_id} "
            f"period={self.period} status={self.status}>"
        )


class TranscriptRelease(db.Model):
    """VPA / Principal approval to release Official Transcript to students and parents."""
    __tablename__ = "transcript_releases"

    STATUS_APPROVED = "approved"

    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False
    )
    # NULL student_id = school-wide release for the academic year.
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=True
    )

    status = db.Column(
        db.String(20), nullable=False, default=STATUS_APPROVED, server_default="approved"
    )

    approved_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at = db.Column(db.DateTime, nullable=True)
    review_comment = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.Index("ix_transcript_releases_status", "status"),
        db.Index("ix_transcript_releases_year_student", "academic_year_id", "student_id"),
    )

    academic_year = db.relationship("AcademicYear")
    student = db.relationship("Student")
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])

    @property
    def is_year_wide(self):
        return self.student_id is None

    @property
    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    def __repr__(self):
        return (
            f"<TranscriptRelease year={self.academic_year_id} student={self.student_id} "
            f"status={self.status}>"
        )


class Assessment(db.Model):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(250))
    date = db.Column(db.String(20))
    max_score = db.Column(db.Float, default=100.0)
    klass_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_name = db.Column(db.String(100), nullable=True)
    activity_type = db.Column(db.String(50), default="Assignment")  # Assignment, Class Work, Quiz, Test, Exam
    submission_mode = db.Column(db.String(30), default="file_upload")  # file_upload, text_entry, in_class
    marking_period = db.Column(db.Integer, default=1)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=True, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    due_date = db.Column(db.String(20), nullable=True)
    scan_keywords = db.Column(db.String(500), nullable=True)
    external_url = db.Column(db.String(500), nullable=True)
    classroom_notes = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.Index("ix_assessments_year_class", "academic_year_id", "klass_id"),
    )

    klass = db.relationship("Class", backref=db.backref("assessments", lazy="dynamic", cascade="all, delete-orphan"))
    teacher = db.relationship("Teacher", backref=db.backref("assessments", lazy="dynamic"))
    academic_year = db.relationship("AcademicYear", backref=db.backref("assessments", lazy="dynamic"))

    @property
    def is_exam_component(self):
        return (self.activity_type or '').strip().lower() == 'exam'

    @property
    def is_classroom_activity(self):
        return (self.submission_mode or '').strip().lower() == 'in_class'

    @property
    def delivery_badge(self):
        return 'Classroom Activity' if self.is_classroom_activity else 'Digital Submission'

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        try:
            from datetime import date
            return date.fromisoformat(self.due_date) < date.today()
        except ValueError:
            return False

    def __repr__(self):
        return f"<Assessment ID {self.id}: {self.title} for Class {self.klass_id}>"


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True)
    date = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # present, absent, late, excused
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)

    __table_args__ = (
        db.Index("ix_attendance_year_date", "academic_year_id", "date"),
        db.Index("ix_attendance_student_date", "student_id", "date"),
        db.Index("ix_attendance_class_date", "class_id", "date"),
    )

    student = db.relationship("Student", backref=db.backref("attendance_ledger", lazy="dynamic", cascade="all, delete-orphan"))
    klass = db.relationship("Class", backref=db.backref("attendance_records", lazy="dynamic"))
    teacher = db.relationship("Teacher", backref=db.backref("attendance_taken", lazy="dynamic"))
    academic_year = db.relationship("AcademicYear", backref=db.backref("attendance_records", lazy="dynamic"))

    def __repr__(self):
        return f"<Attendance ID {self.id}: Student {self.student_id} - {self.status} on {self.date}>"


class SponsorWelfareNote(db.Model):
    """Pastoral / welfare notes logged by a class sponsor or form teacher."""
    __tablename__ = "sponsor_welfare_notes"

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    note_type = db.Column(db.String(40), default="welfare")  # welfare, parent_contact, academic, health
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    klass = db.relationship("Class", backref=db.backref("welfare_notes", lazy="dynamic"))
    student = db.relationship("Student", backref=db.backref("welfare_notes", lazy="dynamic"))
    teacher = db.relationship("Teacher", backref=db.backref("welfare_notes", lazy="dynamic"))

    def __repr__(self):
        return f"<SponsorWelfareNote {self.id} class={self.class_id}>"


class ClassAnnouncement(db.Model):
    """Class-scoped notices posted by the sponsor / form teacher."""
    __tablename__ = "class_announcements"

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(30), default="students")  # students, parents, both
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    klass = db.relationship("Class", backref=db.backref("class_announcements", lazy="dynamic"))
    author = db.relationship("User", backref=db.backref("class_announcements", lazy="dynamic"))

    def __repr__(self):
        return f"<ClassAnnouncement '{self.title}' class={self.class_id}>"


# =====================================================================
# 6. ACCOUNTING, TUITION & FINANCES
# =====================================================================
class Payroll(db.Model):
    __tablename__ = "payrolls"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    occupation = db.Column(db.String(100), nullable=False)
    month = db.Column(db.String(20), nullable=False)
    salary_amount = db.Column(db.Numeric(10, 2), nullable=False)
    paid = db.Column(db.Boolean, default=False, nullable=False)
    created_on = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    staff = db.relationship("User", backref=db.backref("payroll_records", lazy="dynamic", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Payroll ID {self.id}: Staff {self.staff_id} - {self.month}>"


class SchoolFee(db.Model):
    """
    Configuration Model: Tuition and per-class registration fees for an academic year.
    When class_id is null, amount applies as the year-wide tuition default.
    When fee_type is 'registration', amount is the registration fee for that class/year.
    """
    __tablename__ = "school_fees"

    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=True)
    fee_type = db.Column(db.String(30), default="tuition", nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    academic_year = db.relationship("AcademicYear", backref=db.backref("fees_records", lazy="dynamic", cascade="all, delete-orphan"))
    klass = db.relationship("Class", backref=db.backref("fee_schedules", lazy="dynamic"))

    def __repr__(self):
        label = f"Class {self.class_id}" if self.class_id else "Year-wide"
        return f"<SchoolFee {self.fee_type} | Year {self.academic_year_id} | {label} | ${self.amount}>"


class StudentPayment(db.Model):
    """
    Transaction Model: Tracks actual fee payments made by individual students.
    Merges old StudentPayment & new FeePayment logic, fully sandboxed by Academic Year.
    """
    __tablename__ = "student_payments"

    id = db.Column(db.Integer, primary_key=True)
    
    # Core multi-tenancy foreign keys with explicit ondelete behavior
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Breakdown filters for tracking payment intervals
    term = db.Column(db.Integer, nullable=False)           # e.g., Term 1, Term 2
    installment = db.Column(db.Integer, nullable=True)     # e.g., 1st installment, 2nd installment
    
    # Payment detail metrics
    amount_paid = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(255), nullable=True) 
    
    # Modernized timezone-aware payment timestamp
    paid_on = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.Index("ix_payments_year_student", "academic_year_id", "student_id"),
    )

    # =========================================================================
    # PLACE THE RELATIONSHIPS HERE (AT THE BOTTOM OF THE MODEL FIELDS)
    # =========================================================================
    student = db.relationship("Student", backref=db.backref("payment_records", lazy="dynamic", cascade="all, delete-orphan"))
    academic_year = db.relationship("AcademicYear", backref=db.backref("payment_records", lazy="dynamic"))
  
    def __repr__(self):
        return f"<StudentPayment ID {self.id}: Student ID {self.student_id} | Year ID {self.academic_year_id} | Paid: ${self.amount_paid}>"

class BusinessTransaction(db.Model):
    __tablename__ = "business_transactions"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'income' or 'expense'
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(250))
    category = db.Column(db.String(120))             # e.g., "Tuition", "Stationery", "Fuel"
    balance_after = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    academic_year = db.Column(db.String(32))
    
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    __table_args__ = (
        db.Index("ix_biz_year_type_deleted", "academic_year", "type", "is_deleted"),
    )

    deleted_by = db.relationship("User", foreign_keys=[deleted_by_id], backref="deleted_transactions")

    def __repr__(self):
        return f"<BusinessTransaction ID {self.id}: {self.type} - ${self.amount}>"


class Sponsor(db.Model):
    __tablename__ = "sponsors"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)

    user = db.relationship("User", backref=db.backref("sponsorship_ledger", lazy="dynamic"))
    student = db.relationship("Student", backref=db.backref("sponsorship_ledger", lazy="dynamic"))

    def __repr__(self):
        return f"<Sponsor ID {self.id}: User {self.user_id} sponsoring Student {self.student_id}>"


# =====================================================================
# 7. PUBLIC MARKETING & ORGANIZATIONAL LEADERSHIP
# =====================================================================
class LeaderCategory(db.Model):
    __tablename__ = "leader_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    # Relationship cascade tracks the child nodes natively
    leaders = db.relationship("Leader", back_populates="category_node", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<LeaderCategory {self.name}>"


class Leader(db.Model):
    __tablename__ = "leaders"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(120))
    bio = db.Column(db.Text)
    contact = db.Column(db.String(120))
    photo = db.Column(db.String(200))
    category_id = db.Column(db.Integer, db.ForeignKey("leader_categories.id", ondelete="CASCADE"), nullable=False)

    # Maps cleanly using back_populates
    category_node = db.relationship("LeaderCategory", back_populates="leaders")

    @property
    def category(self):
        """Template alias for category_node."""
        return self.category_node

    @property
    def photo_static_path(self):
        """Normalized path for url_for('static', filename=...)."""
        return _static_photo_filename(self.photo)

    @property
    def photo_url(self):
        """Always return a working leader photo URL (uploaded file or default)."""
        return resolve_static_photo_url(self.photo, default_filename=DEFAULT_USER_PHOTO)

    def __repr__(self):
        return f"<Leader {self.name} - {self.role}>"


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200))
    date = db.Column(db.Date, nullable=False)
    event_type = db.Column(db.String(50), default="general", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"<Event {self.title} on {self.date}>"


class SchoolMedia(db.Model):
    """Photos, videos, and downloadable info sheets for the school community."""
    __tablename__ = "school_media"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    media_type = db.Column(db.String(20), nullable=False)  # photo, video, document
    category = db.Column(db.String(30), default="general", nullable=False)
    file_path = db.Column(db.String(500), nullable=True)
    external_url = db.Column(db.String(500), nullable=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    duration_seconds = db.Column(db.Integer, nullable=True)

    academic_year = db.relationship("AcademicYear", backref=db.backref("school_media_items", lazy="dynamic"))
    author = db.relationship("User", backref=db.backref("school_media_posts", lazy="dynamic"))

    @property
    def static_file_path(self):
        if not self.file_path:
            return None
        path = str(self.file_path).replace("\\", "/")
        if path.startswith("static/"):
            path = path[7:]
        return path

    def __repr__(self):
        return f"<SchoolMedia {self.title} ({self.media_type})>"


class SystemSetting(db.Model):
    """Singleton row controlling global system availability (license / hold)."""
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    system_active = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    hold_message = db.Column(
        db.Text,
        default=(
            "This school's Future Leaders system is temporarily on hold for the next academic year. "
            "Please contact the system architect, Francis Brownell, to renew your subscription."
        ),
        nullable=False,
    )
    admin_contact_email = db.Column(db.String(120), default="xhangocharm@gmail.com", nullable=False)
    admin_contact_phone = db.Column(db.String(30), default="0889358194", nullable=True)
    deactivated_at = db.Column(db.DateTime, nullable=True)
    deactivated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    deactivated_by = db.relationship("User", foreign_keys=[deactivated_by_id])

    def __repr__(self):
        state = "ACTIVE" if self.system_active else "ON HOLD"
        return f"<SystemSetting {state}>"
