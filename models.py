from datetime import datetime, timezone
from flask_login import UserMixin
from decimal import Decimal
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import validates, synonym
db = SQLAlchemy()

DEFAULT_STUDENT_PHOTO = "uploads/photos/default_student.png"
DEFAULT_USER_PHOTO = "images/MAN.jpg"


def resolve_static_photo_url(photo_path, default_filename=DEFAULT_STUDENT_PHOTO):
    """Turn a stored relative photo path into a Flask static file URL."""
    from flask import url_for

    if photo_path:
        clean_path = str(photo_path).strip().replace("\\", "/")
        if clean_path.startswith(("http://", "https://")):
            return clean_path
        if clean_path.startswith("static/"):
            return url_for("static", filename=clean_path[7:])
        if clean_path.startswith("/static/"):
            return url_for("static", filename=clean_path[8:])
        if clean_path.startswith("/"):
            clean_path = clean_path.lstrip("/")
        return url_for("static", filename=clean_path)

    return url_for("static", filename=default_filename)

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
    deactivated_at = db.Column(db.DateTime, nullable=True)
    deactivation_reason = db.Column(db.String(255), nullable=True)

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
    def photo_url(self):
        """Generate a proper photo URL from the photo column safely."""
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
        return f"{self.first_name} {self.last_name}"

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
    parent_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    secure_qr_token = db.Column(db.String(128), unique=True, nullable=True, index=True)
    parent_report_token = db.Column(db.String(128), unique=True, nullable=True, index=True)
    parent_report_pin_hash = db.Column(db.String(200), nullable=True)

    photo = db.Column(db.String(200), nullable=True)
    photo_filename = db.Column(db.String(200), default='default_student.png')

    status = db.Column(db.String(20), default='ACTIVE', nullable=False)  # ACTIVE, REPEAT, FAILED, SUSPENDED, ALUMNI, GRADUATED
    grade_level = db.Column(db.String(50), nullable=True)
    level = db.Column(db.String(50), nullable=True)                      # Elementary, Junior High, Senior High
    registration_type = db.Column(db.String(20), default='New', nullable=False)
    registrar = db.Column(db.String(100), nullable=True)

    # Core relationship foreign keys
    klass_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True)

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
    def photo_url(self):
        photo_path = self.photo
        if not photo_path and self.photo_filename and self.photo_filename != "default_student.png":
            photo_path = f"uploads/students/{self.photo_filename}"
        if not photo_path and self.user and getattr(self.user, "photo", None):
            photo_path = self.user.photo
        return resolve_static_photo_url(photo_path, default_filename=DEFAULT_STUDENT_PHOTO)

    def __repr__(self):
        return f"<StudentNode ID: {self.student_id} | Name: {self.full_name}>"

    @property
    def student_code(self):
        """Permanent public student code (alias for student_id)."""
        return self.student_id


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
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=True)

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
    activity_id = db.Column(db.Integer, db.ForeignKey('assessments.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False)

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
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    due_date = db.Column(db.String(20), nullable=True)
    scan_keywords = db.Column(db.String(500), nullable=True)
    external_url = db.Column(db.String(500), nullable=True)
    classroom_notes = db.Column(db.Text, nullable=True)

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
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True)
    date = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # present, absent, late, excused
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)

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
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False)
    
    # Breakdown filters for tracking payment intervals
    term = db.Column(db.Integer, nullable=False)           # e.g., Term 1, Term 2
    installment = db.Column(db.Integer, nullable=True)     # e.g., 1st installment, 2nd installment
    
    # Payment detail metrics
    amount_paid = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(255), nullable=True) 
    
    # Modernized timezone-aware payment timestamp
    paid_on = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

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
        if not self.photo:
            return None
        path = self.photo.replace('\\', '/')
        if path.startswith('static/'):
            path = path[7:]
        return path

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
            "This school's Keep Track system is temporarily on hold for the next academic year. "
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