# System User Roles Configurations
ROLE_ADMIN = 'admin'
ROLE_REGISTRAR = 'registrar'
ROLE_TEACHER = 'teacher'
ROLE_BUSINESS = 'business'
ROLE_SPONSOR = 'sponsor'
ROLE_STUDENT = 'student'

# Liberia dual currency — defined first so every importer can see US$ / L$.
CURRENCY_USD = 'USD'
CURRENCY_LRD = 'LRD'
CURRENCY_CHOICES = (
    ('USD', 'US$ — United States Dollar'),
    ('LRD', 'L$ — Liberian Dollar'),
)
CURRENCY_SYMBOLS = {
    CURRENCY_USD: 'US$',
    CURRENCY_LRD: 'L$',
}

# MoE marking periods: 1, 2, 3, EXAM, 4, 5, 6, FINAL EXAM (IDs 7 and 8 = semester exams)
GRADING_PERIODS = [
    (1, 'Period 1'),
    (2, 'Period 2'),
    (3, 'Period 3'),
    (7, 'Exam (Sem 1)'),
    (4, 'Period 4'),
    (5, 'Period 5'),
    (6, 'Period 6'),
    (8, 'Exam (Sem 2)'),
]

_GRADING_PERIOD_LABELS = dict(GRADING_PERIODS)


def grading_period_label(period_num):
    """Human-readable label for a marking period number."""
    try:
        period_num = int(period_num)
    except (TypeError, ValueError):
        return str(period_num) if period_num else '1'
    return _GRADING_PERIOD_LABELS.get(period_num, str(period_num))


# Period continuous assessment totaling 100 (no period exam).
# C/PART 5 + QUIZ 30 + ASSG 5 + CW 15 + ATT 5 + TEST 40 = 100
# Form field names stay stable; homework (`other`) and direct total are retired.
PERIOD_COMPONENT_SPECS = (
    ('participation', 'C/PART', 'C/Participation', 5.0),
    ('quiz', 'QUIZ', 'Quiz', 30.0),
    ('assignment', 'ASSG', 'Assignment', 5.0),
    ('classwork', 'CW', 'Classwork', 15.0),
    ('attendance', 'ATT', 'Attendance', 5.0),
    ('test', 'TEST', 'Test', 40.0),
)
PERIOD_COMPONENT_MAXIMA = {
    key: max_score for key, _code, _label, max_score in PERIOD_COMPONENT_SPECS
}
PERIOD_COMPONENT_SCHEME_NOTE = (
    'C/Participation 5 + Quiz 30 + Assignment 5 + Classwork 15 + Attendance 5 + Test 40 = 100'
)
# Each activity input is capped at its listed points. No extra-credit over-weight.
PERIOD_COMPONENT_EXTRA_CREDIT_FACTOR = 1.0
PERIOD_COMPONENT_FIELD_MAX = 100.0
PERIOD_TOTAL_LISTED_MAX = 100.0
PERIOD_TOTAL_EXTRA_CREDIT_MAX = 100.0


def period_component_ceiling(listed_max):
    """Highest score accepted for a component (equals the listed points)."""
    try:
        listed_max = float(listed_max)
    except (TypeError, ValueError):
        listed_max = 0.0
    return round(listed_max * PERIOD_COMPONENT_EXTRA_CREDIT_FACTOR, 1)


PERIOD_COMPONENT_CEILINGS = {
    key: period_component_ceiling(max_score)
    for key, max_score in PERIOD_COMPONENT_MAXIMA.items()
}
PERIOD_COMPONENT_ACTIVITY_TYPES = {
    'attendance': 'Class Work',
    'participation': 'Class Work',
    'quiz': 'Quiz',
    'assignment': 'Assignment',
    'classwork': 'Class Work',
    'test': 'Test',
}


def normalize_currency(code):
    raw = (code or CURRENCY_USD).strip().upper().replace(' ', '')
    if raw in {CURRENCY_LRD, 'LD', 'L$', 'LD$', 'LR'}:
        return CURRENCY_LRD
    return CURRENCY_USD


def currency_symbol(code):
    return CURRENCY_SYMBOLS.get(normalize_currency(code), 'US$')


def format_school_money(amount, currency='USD'):
    """Professional Liberian till notation: US$ 1,000.00 or L$ 185,000.00."""
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    return f"{currency_symbol(currency)} {value:,.2f}"


# Liberia private-school billing: two semesters in the year; school fees in three yearly installments.
SEMESTER_CHOICES = (
    (1, 'First Semester'),
    (2, 'Second Semester'),
)
INSTALLMENT_FULL = 0
INSTALLMENT_CHOICES = (
    (1, '1st Installment'),
    (2, '2nd Installment'),
    (3, '3rd Installment'),
)
INSTALLMENT_FORM_CHOICES = INSTALLMENT_CHOICES + (
    (INSTALLMENT_FULL, 'Full year settlement'),
)
SCHOOL_FEE_KIND_CHOICES = (
    ('tuition', 'School fees'),
    ('registration', 'Registration fee'),
    ('re_admission', 'Re-admission fee'),
    ('id_card', 'ID card replacement'),
    ('documents', 'Documents / certificates'),
    ('other', 'Other school charge'),
)
_SEMESTER_LABELS = dict(SEMESTER_CHOICES)
_INSTALLMENT_LABELS = dict(INSTALLMENT_FORM_CHOICES)


def semester_label(term):
    try:
        term = int(term)
    except (TypeError, ValueError):
        return 'First Semester'
    return _SEMESTER_LABELS.get(term, 'First Semester')


def installment_label(number):
    try:
        number = int(number)
    except (TypeError, ValueError):
        return ''
    return _INSTALLMENT_LABELS.get(number, '')


def billing_period_label(term, installment=None):
    """Official receipt line: First Semester · 2nd Installment (of three for the year)."""
    heading = semester_label(term)
    inst = installment_label(installment)
    return f'{heading} · {inst}' if inst else heading


def format_dual_money(totals):
    """Join USD and LRD buckets for a till or report heading."""
    parts = []
    usd = float((totals or {}).get(CURRENCY_USD) or 0)
    lrd = float((totals or {}).get(CURRENCY_LRD) or 0)
    if usd or not lrd:
        parts.append(format_school_money(usd, CURRENCY_USD))
    if lrd:
        parts.append(format_school_money(lrd, CURRENCY_LRD))
    return '  ·  '.join(parts)
