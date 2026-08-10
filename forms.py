from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, SelectField,
    FloatField, TextAreaField, DateField, IntegerField,
    BooleanField, FileField
)
from wtforms.validators import DataRequired, Email, Optional, ValidationError, Length
from flask_wtf.file import FileAllowed
from constants import GRADING_PERIODS
from utils import parse_currency_amount


class CurrencyField(StringField):
    """Accept formatted currency input such as 60,000 or 1200.50."""

    def _value(self):
        return self.data if self.data is not None else ""


def validate_currency(form, field):
    if field.data is None or not str(field.data).strip():
        return
    try:
        parse_currency_amount(field.data)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def optional_int_coerce(value):
    """Coerce select values to int; treat blank/placeholder as None."""
    if value is None or value == '' or value == 0 or value == '0':
        return None
    return int(value)


# --------------------------------------------------------------
# AUTHENTICATION FORMS
# --------------------------------------------------------------

class LeaderForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired()])
    role = StringField('Position/Role', validators=[DataRequired()])
    bio = TextAreaField('Short Bio', validators=[DataRequired()])
    contact = StringField('Contact Email or Link', validators=[Optional()])
    category = StringField('Category', validators=[DataRequired(), Length(max=100)])
    photo = FileField('Photo', validators=[FileAllowed(['jpg', 'png', 'jpeg'], 'Images only!')])
    submit = SubmitField('Save Leader')

def validate_login_identifier(form, field):
    """Accept portal email or permanent student ID (e.g. 2526-00001)."""
    value = (field.data or '').strip()
    field.data = value
    if not value:
        raise ValidationError('Email or Student ID is required.')
    if '@' in value:
        if len(value) > 120 or value.count('@') != 1 or not value.split('@')[1]:
            raise ValidationError('Enter a valid email address or student ID.')
        return
    if value.replace('-', '').isdigit() and len(value.replace('-', '')) >= 4:
        return
    if len(value) >= 3 and '-' in value:
        return
    raise ValidationError('Enter a valid email address or student ID (e.g. 2526-00001).')


class LoginForm(FlaskForm):
    email = StringField("Email or Student ID", validators=[DataRequired(), validate_login_identifier])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class ChangeDetailsForm(FlaskForm):
    email = StringField("New Email", validators=[DataRequired(), Email()])
    password = PasswordField("New Password", validators=[Optional()])
    submit = SubmitField("Update")


# --------------------------------------------------------------
# STUDENT & CLASS FORMS
# --------------------------------------------------------------
class EnrollmentForm(FlaskForm):
    student = SelectField("Student", coerce=int, validators=[DataRequired()])
    klass = SelectField("Class", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Enroll Student")


class SelfRegistrationForm(FlaskForm):
    """Public self-service enrollment with email lookup for returning students."""
    email = StringField("Student Email", validators=[DataRequired(), Email()])
    first_name = StringField("First Name", validators=[DataRequired()])
    last_name = StringField("Last Name", validators=[DataRequired()])
    dob = DateField("Date of Birth", validators=[DataRequired()])
    gender = SelectField(
        "Gender",
        choices=[("Male", "Male"), ("Female", "Female"), ("Other", "Other")],
        validators=[DataRequired()],
    )
    level = SelectField(
        "Academic Level",
        choices=[("Senior High", "Senior High"), ("Junior High", "Junior High"), ("Elementary", "Elementary")],
        validators=[DataRequired()],
    )
    parent_email = StringField("Parent/Guardian Email", validators=[Optional(), Email()])
    klass = SelectField("Class", coerce=optional_int_coerce, validators=[Optional()])
    password = PasswordField("Portal Password (Optional)", validators=[Optional()])
    is_returning = BooleanField("Returning Student", default=False)
    submit = SubmitField("Submit Registration")


class ParentReportGateForm(FlaskForm):
    verify_method = SelectField(
        'Verification method',
        choices=[('pin', 'Parent PIN'), ('phone', 'Phone last 4 digits')],
        validators=[DataRequired()],
        default='pin',
    )
    parent_pin = StringField('Parent PIN', validators=[Optional()])
    phone_last4 = StringField('Last 4 digits of parent phone', validators=[Optional()])
    submit = SubmitField('View Report Card')


class RegisterStudentForm(FlaskForm):
    first_name = StringField("First Name", validators=[DataRequired()])
    last_name = StringField("Last Name", validators=[DataRequired()])
    email = StringField("Email", validators=[Optional(), Email()])
    password = PasswordField("Password (Optional)", validators=[Optional()])
    dob = DateField("Date of Birth", validators=[DataRequired()])
    gender = SelectField(
        "Gender",
        choices=[("Male", "Male"), ("Female", "Female"), ("Other", "Other")],
        validators=[DataRequired()]
    )
    level = SelectField(
        "Academic Level",
        choices=[("Senior High", "Senior High"), ("Junior High", "Junior High"), ("Elementary", "Elementary")],
        validators=[DataRequired()]
    )
    student_id = StringField(
        "Student ID",
        validators=[Optional()],
        description="Leave blank to auto-generate for new students.",
    )
    parent_email = StringField("Parent Email", validators=[Optional(), Email()])
    parent_phone = StringField(
        "Parent/Guardian Phone",
        validators=[Optional(), Length(max=20)],
        description="Used for parent report QR verification (last 4 digits).",
    )
    parent_report_pin = StringField(
        "Parent Report PIN",
        validators=[Optional(), Length(min=4, max=6)],
        description="4–6 digit PIN for scanning report QR without login. Leave blank to keep current.",
    )
    photo = FileField("Photo", validators=[FileAllowed(["jpg", "png", "jpeg"], "Images only!")])
    klass = SelectField("Assign Class", coerce=optional_int_coerce, validators=[Optional()])
    academic_year = SelectField("Academic Year", coerce=optional_int_coerce, validators=[DataRequired()])
    registration_fees = CurrencyField(
        "Registration Fees",
        validators=[Optional(), validate_currency],
        default="0.00",
    )
    is_returning = BooleanField("Returning Student", default=False)
    submit = SubmitField("Register")


class ClassForm(FlaskForm):
    name = StringField("Class Name", validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])
    yearly_fee = CurrencyField("Yearly Fee", validators=[Optional(), validate_currency])
    teacher_id = IntegerField("Teacher Internal ID", validators=[Optional()])
    submit = SubmitField("Save Class")


class CreateClassForm(FlaskForm):
    name = StringField('Class Name', validators=[DataRequired()])
    grade_level = StringField('Grade Level', validators=[DataRequired(), Length(max=50)])
    stream = StringField('Stream / Track', validators=[Optional(), Length(max=50)])
    description = TextAreaField('Description', validators=[Optional()])
    yearly_fee = CurrencyField('Yearly Fee', validators=[Optional(), validate_currency])
    ca_weight = IntegerField('Continuous Assessment Weight (%)', validators=[Optional()])
    exam_weight = IntegerField('Exam Weight (%)', validators=[Optional()])
    teacher_id = SelectField('Teacher', coerce=int, validators=[Optional()])
    sponsor_id = SelectField('Sponsor', coerce=int, validators=[Optional()])
    submit = SubmitField('Save Class')

class AssignTeacherForm(FlaskForm):
    class_id = SelectField('Class', coerce=int, validators=[DataRequired()])
    teacher_id = SelectField('Teacher', coerce=int, validators=[DataRequired()])
    subject_name = StringField('Subject Name', validators=[DataRequired()])  # <-- Make sure this is present
    submit = SubmitField('Assign Teacher')


# --------------------------------------------------------------
# FINANCE & PAYROLL FORMS
# --------------------------------------------------------------
class SetFeeForm(FlaskForm):
    academic_year = SelectField("Academic Year", coerce=int, validators=[DataRequired()])
    amount = CurrencyField(
        "School Fee Amount",
        validators=[DataRequired(), validate_currency],
    )
    submit = SubmitField("Set Fees")


class PaymentForm(FlaskForm):
    student = SelectField("Student", coerce=int, validators=[DataRequired()])
    academic_year = SelectField("Academic Year", coerce=int, validators=[DataRequired()])
    term = SelectField(
        "Term",
        choices=[(1, "Semester 1"), (2, "Semester 2")],
        coerce=int,
        validators=[DataRequired()]
    )
    installment = SelectField(
        "Installment",
        choices=[(0, "None / Full Payment"), (1, "1st Installment"), (2, "2nd Installment"), (3, "3rd Installment")],
        coerce=int,
        validators=[Optional()]
    )
    description = StringField("Fee Description (e.g. Tuition, Uniform, Graduation)", validators=[Optional()])
    amount_paid = CurrencyField(
        "Amount Paid",
        validators=[DataRequired(), validate_currency],
    )
    submit = SubmitField("Record Payment")


class PayrollForm(FlaskForm):
    staff_id = SelectField("Select Staff", coerce=int, validators=[DataRequired()])
    occupation = StringField("Occupation", validators=[DataRequired()])
    month = StringField("Month (e.g. January 2025)", validators=[DataRequired()])
    salary_amount = CurrencyField(
        "Salary Amount",
        validators=[DataRequired(), validate_currency],
    )
    paid = BooleanField("Paid")
    submit = SubmitField("Save Payroll Record")


class BusinessTransactionForm(FlaskForm):
    date = StringField("Date (YYYY-MM-DD)", validators=[DataRequired()])
    type = SelectField(
        "Type",
        choices=[("income", "Income"), ("expense", "Expense")],
        validators=[DataRequired()]
    )
    amount = CurrencyField("Amount", validators=[DataRequired(), validate_currency])
    description = TextAreaField("Description", validators=[Optional()])
    category = StringField("Category", validators=[Optional()])
    submit = SubmitField("Save Transaction")

# --------------------------------------------------------------
# ACADEMIC YEAR & SPONSORSHIP
# --------------------------------------------------------------
class AcademicYearForm(FlaskForm):
    name = StringField("Academic Year (e.g. 2025–2026)", validators=[DataRequired()])
    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[Optional()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class RolloverWizardForm(FlaskForm):
    """Multi-step academic year rollover wizard (single POST on final step)."""
    end_current_year = BooleanField("End the current active academic year", default=True)
    target_mode = SelectField(
        "Target Year",
        choices=[("new", "Create & activate a new year"), ("existing", "Activate an existing year")],
        default="new",
    )
    target_year_id = SelectField("Existing Year", coerce=optional_int_coerce, validators=[Optional()])
    new_year_name = StringField("New Year Name", validators=[Optional()])
    new_year_start = DateField("New Year Start", validators=[Optional()])
    new_year_end = DateField("New Year End", validators=[Optional()])
    apply_promotions = BooleanField("Promote students to next grade level", default=True)
    reset_tuition_cleared = BooleanField("Reset tuition clearance for re-enrolled students", default=True)
    charge_registration_fee = BooleanField(
        "Post registration fees to business income during rollover",
        default=False,
    )
    exclude_graduated = BooleanField("Skip students already marked Graduated", default=True)
    exclude_withdrawn = BooleanField("Skip students marked Withdrawn", default=True)
    exclude_suspended = BooleanField("Skip suspended students", default=False)
    confirm_rollover = BooleanField(
        "I confirm this rollover will update student records and optional fee ledgers",
        validators=[DataRequired()],
    )
    submit = SubmitField("Execute Rollover")


class SponsorForm(FlaskForm):
    user_id = IntegerField("User ID (if admin creating)", validators=[Optional()])
    student_id = IntegerField("Student ID", validators=[DataRequired()])
    amount = CurrencyField("Amount", validators=[DataRequired(), validate_currency])
    submit = SubmitField("Sponsor")


# --------------------------------------------------------------
# COMMUNICATION & DISCIPLINE
# --------------------------------------------------------------
class AnnouncementForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired()])
    content = TextAreaField("Message Content", validators=[DataRequired()])
    target_audience = SelectField(
        "Target Audience",
        choices=[
            ("all", "All"),
            ("parents", "Parents"),
            ("students", "Students"),
            ("teachers", "Teachers"),
            ("sponsors", "Sponsors"),
        ],
        validators=[DataRequired()],
    )
    submit = SubmitField("Post")


class EventForm(FlaskForm):
    title = StringField("Event Title", validators=[DataRequired()])
    description = TextAreaField("Description", validators=[DataRequired()])
    location = StringField("Location", validators=[Optional()])
    date = DateField("Date", validators=[DataRequired()])
    event_type = SelectField(
        "Event Type",
        choices=[
            ("general", "General"),
            ("entrance", "Entrance Exam"),
            ("academic", "Academic"),
            ("sports", "Sports"),
            ("pta", "PTA / Community"),
        ],
        validators=[DataRequired()],
    )
    submit = SubmitField("Save Event")


class SchoolMediaForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])
    media_type = SelectField(
        "Media Type",
        choices=[
            ("photo", "Photo"),
            ("video", "Video"),
            ("document", "Information Sheet / Document"),
        ],
        validators=[DataRequired()],
    )
    category = SelectField(
        "Category",
        choices=[
            ("general", "General Update"),
            ("advertisement", "Advertisement / Promo Video"),
            ("gallery", "School Gallery"),
            ("entrance", "Entrance Exam Notice (documents only)"),
            ("info_sheet", "Academic Year Info Sheet (documents only)"),
        ],
        validators=[DataRequired()],
    )
    academic_year = SelectField("Academic Year", coerce=optional_int_coerce, validators=[Optional()])
    external_url = StringField("Video Link (YouTube/Vimeo URL)", validators=[Optional()])
    media_file = FileField("Upload File", validators=[Optional()])
    is_published = BooleanField("Publish to school portal", default=True)
    submit = SubmitField("Save")


class ConfirmDeleteForm(FlaskForm):
    submit = SubmitField("Delete")


class DisciplineForm(FlaskForm):
    student_id = IntegerField("Student Internal ID", validators=[DataRequired()])
    offense = StringField("Offense", validators=[DataRequired()])
    action_taken = StringField("Action Taken", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Report")


# --------------------------------------------------------------
# ATTENDANCE & GRADING
# --------------------------------------------------------------
class AttendanceForm(FlaskForm):
    student_id = IntegerField("Student ID", validators=[DataRequired()])
    date = DateField("Date", validators=[DataRequired()])
    status = SelectField(
        "Status",
        choices=[
            ("present", "Present"),
            ("absent", "Absent"),
            ("late", "Late"),
            ("excused", "Excused"),
        ],
        validators=[DataRequired()]
    )
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Record")


class RecordClassroomActivityForm(FlaskForm):
    """Log an in-class activity (blackboard work, verbal instructions, shared Drive link)."""
    title = StringField(
        "Activity Title",
        validators=[DataRequired()],
        render_kw={"placeholder": "e.g. Blackboard drill — Fractions", "maxlength": 120},
    )
    subject_name = SelectField("Subject", validators=[DataRequired()])
    marking_period = SelectField(
        "Marking Period",
        coerce=int,
        validators=[DataRequired()],
        choices=GRADING_PERIODS,
    )
    evaluation_type = SelectField(
        "Activity Type",
        choices=[
            ("Class Work", "Class Work"),
            ("Assignment", "Assignment"),
            ("Quiz", "Quiz"),
            ("Test", "Test"),
            ("Exam", "Exam"),
        ],
        validators=[DataRequired()],
    )
    max_score = FloatField(
        "Maximum Score",
        default=100.0,
        validators=[DataRequired()],
        render_kw={"min": 1, "max": 1000, "step": 0.5},
    )
    due_date = DateField("Due Date (optional)", validators=[Optional()])
    external_url = StringField(
        "Google Drive / Shared Link",
        validators=[Optional()],
        render_kw={"placeholder": "https://drive.google.com/..."},
    )
    classroom_notes = TextAreaField(
        "Classroom Notes",
        validators=[Optional()],
        render_kw={
            "placeholder": "What you wrote on the board, verbal instructions, or class procedure…",
            "rows": 5,
        },
    )
    submit = SubmitField("Create Activity")

    def validate_title(self, field):
        if not (field.data or "").strip():
            raise ValidationError("Activity title is required.")

    def validate_external_url(self, field):
        raw = (field.data or "").strip()
        if not raw:
            return
        if not raw.startswith(("http://", "https://")):
            raise ValidationError("Enter a full URL starting with http:// or https://")

    def validate_max_score(self, field):
        if field.data is None:
            return
        if field.data <= 0 or field.data > 1000:
            raise ValidationError("Maximum score must be between 1 and 1000.")


class CreateUserForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    full_name = StringField('Full Name', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    role = SelectField('Role', choices=[
        ('admin', 'Admin'),
        ('teacher', 'Teacher'),
        ('student', 'Student'),
        ('parent', 'Parent'),
        ('business', 'Business Manager'),
        ('registrar', 'Registrar'),
        ('principal', 'Principal'),
        ('vpi', 'VPI'),
        ('vpa', 'VPA'),
        ('dean', 'Dean'),
        ('sponsor', 'Sponsor'),
    ], validators=[DataRequired()])
    home_address = StringField('Home Address', validators=[Optional()])
    telephone_number = StringField('Telephone Number', validators=[Optional()])
    photo = FileField('Profile Photo', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    submit = SubmitField('Create User')


class EditUserForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    username = StringField('Username', validators=[Optional()])
    full_name = StringField('Full Name', validators=[DataRequired()])
    password = PasswordField('New Password (leave blank to keep current)', validators=[Optional()])
    role = SelectField('Role', choices=[
        ('admin', 'Admin'),
        ('teacher', 'Teacher'),
        ('student', 'Student'),
        ('parent', 'Parent'),
        ('business', 'Business Manager'),
        ('registrar', 'Registrar'),
        ('principal', 'Principal'),
        ('vpi', 'VPI'),
        ('vpa', 'VPA'),
        ('dean', 'Dean'),
        ('sponsor', 'Sponsor'),
    ], validators=[DataRequired()])
    home_address = StringField('Home Address', validators=[Optional()])
    telephone_number = StringField('Telephone Number', validators=[Optional()])
    photo = FileField('Profile Photo', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    submit = SubmitField('Save Changes')

TransactionForm = BusinessTransactionForm
