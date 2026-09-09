"""Canonical Kindergarten / Elementary / Junior High / Senior High mapping.

Future Leaders (Liberia) class folders in keeptrack_full.db:

    ABC, K-1, K-2                         → Kindergarten
    1st … 6th  (Grade 1st … Grade 6)      → Elementary
    7th … 9th  (Grade 7 … Grade 9)        → Junior High
    10th, 11th, 12 (Grade 10 … Grade 12)  → Senior High

String sort on grade_level put Grade 10 next to Grade 1st and ABC/K-1/K-2
after Grade 9. Substring checks ('grade 1' in 'grade 10', 'k-i' vs 'k-1')
put the same classes on the wrong grade-sheet heading. All grouping and
document titles should go through this module.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re

DIVISION_KINDERGARTEN = 'kindergarten'
DIVISION_ELEMENTARY = 'elementary'
DIVISION_JUNIOR_HIGH = 'junior_high'
DIVISION_SENIOR_HIGH = 'senior_high'
DIVISION_UNASSIGNED = 'unassigned'

DIVISION_ORDER = (
    DIVISION_KINDERGARTEN,
    DIVISION_ELEMENTARY,
    DIVISION_JUNIOR_HIGH,
    DIVISION_SENIOR_HIGH,
)

DIVISION_LABELS = {
    DIVISION_KINDERGARTEN: 'Kindergarten',
    DIVISION_ELEMENTARY: 'Elementary',
    DIVISION_JUNIOR_HIGH: 'Junior High',
    DIVISION_SENIOR_HIGH: 'Senior High',
    DIVISION_UNASSIGNED: 'Other',
}

# Printed documents (report cards and periodic grade sheets)
SCHOOL_PRINT_NAME = 'Future Leaders Preparatory Academy'
SCHOOL_PRINT_ADDRESS_LINE = 'Center Street, South Beach'
SCHOOL_PRINT_CITY_LINE = 'Monrovia, Liberia'
SCHOOL_PRINT_FULL_ADDRESS = 'Center Street, South Beach, Monrovia, Liberia'
SCHOOL_PRINT_PHONES = '0886-612-070 / 0775-313-359 / 0881-164-147'
SCHOOL_PRINT_PHONE = f'Telephone: {SCHOOL_PRINT_PHONES}'
SCHOOL_PRINT_EMAIL_ADDRESS = 'flpacardinals@gmail.com'
SCHOOL_PRINT_EMAIL = f'Email: {SCHOOL_PRINT_EMAIL_ADDRESS}'
SCHOOL_PRINT_MOTTO = 'Honor, Excellence, Academics, Discipline, Success'
SCHOOL_PRINT_BRAND_RED = '#c82828'
SCHOOL_PRINT_VPI_TITLE = 'VPI'
SCHOOL_PRINT_VPI_NAME = 'Othello B. Gbarjuewaye'
SCHOOL_PRINT_SPONSOR_TITLE = 'Class Sponsor'
SCHOOL_PRINT_PRINCIPAL_TITLE = 'Principal'
SCHOOL_PRINT_GRADING_METHOD = (
    'EXCELLENT 90-100 A, GOOD 80-89 B, FAIR 70-79 C, FAILURE BELOW 70 D'
)

AVERAGE_ROW_NAME = 'AVERAGE'
CONDUCT_ROW_NAME = 'CONDUCT'
REPORT_SUMMARY_ROWS = (AVERAGE_ROW_NAME, CONDUCT_ROW_NAME)

# Official Word-template subjects, in print order. Display names are exact.
REPORT_CARD_SUBJECTS = {
    'kindergarten': (
        'Mathematics',
        'English',
        'Spelling',
        'Reading',
        'Bible',
        'Social Studies',
        'Health Science',
        'Phonics',
        'Science',
        'Alph. Writing',
        'Num. Writing',
        'Shapes/Colors',
        'Drawing',
        'P. Education',
    ),
    'elementary': (
        'Mathematics',
        'English',
        'Reading',
        'Spelling',
        'Gen. Science',
        'Bible',
        'Social Studies',
        'French',
        'Phonics',
        'Hand Writing',
        'Comp. Science',
        'Num. Writing',
        'Shapes/Colors',
        'P. Education',
    ),
    'junior': (
        'Mathematics',
        'English',
        'Literature',
        'Vocabulary',
        'Gen. Science',
        'RE/ Education',
        'History',
        'Geography',
        'Civics',
        'French',
        'Comp. Science',
        'Phon. /O. Eng',
        'P. Education',
    ),
    'senior': (
        'Mathematics',
        'English',
        'Literature',
        'Chemistry',
        'Economics',
        'Physics',
        'Government',
        'History',
        'Geography',
        'Biology',
        'R/Education',
        'French',
        'O.Eng/Vocab',
        'R.O.T.C',
    ),
}

DIVISION_SUBJECT_CATALOGS = {
    DIVISION_KINDERGARTEN: REPORT_CARD_SUBJECTS['kindergarten'],
    DIVISION_ELEMENTARY: REPORT_CARD_SUBJECTS['elementary'],
    DIVISION_JUNIOR_HIGH: REPORT_CARD_SUBJECTS['junior'],
    DIVISION_SENIOR_HIGH: REPORT_CARD_SUBJECTS['senior'],
}

PERIOD_COLUMNS = (
    'p1', 'p2', 'p3', 'exam1', 'sem1',
    'p4', 'p5', 'p6', 'exam2', 'sem2',
    'yearly', 'remarks',
)
REPORT_CARD_PERIOD_COLUMNS = PERIOD_COLUMNS


def numeric_report_score(value):
    """Coerce a stored period/exam score to float; blank / dash / None stay empty."""
    if value in (None, '', '-', '—'):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().rstrip('%').strip()
        if value in ('', '-', '—'):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(str(value).strip().rstrip('%').strip())
        except (TypeError, ValueError):
            return None


def display_report_score(value):
    """Show whole numbers without a trailing .0 on official tables."""
    num = numeric_report_score(value)
    if num is None:
        return ''
    if num == int(num):
        return int(num)
    return round(num, 1)


def mean_available_scores(values):
    """Mean of present numeric scores (official SEM.AVE / yearly formula)."""
    scores = [numeric_report_score(value) for value in values]
    scores = [score for score in scores if score is not None]
    if not scores:
        return ''
    return round(sum(scores) / len(scores), 1)


def official_subject_score_row(name, scores_by_period, division_key=None, *, aggregates=True):
    """One official report-card / grade-sheet subject row from period scores.

    Period keys: 1–6 = P1–P6, 7 = semester 1 exam, 8 = semester 2 exam.
    SEM.AVE is the mean of whichever of that semester's period/exam scores exist.

    aggregates=False is the single-period sheet: SEM.AVE and YEARLY stay blank
    because they cannot be computed honestly from one marking period.
    """
    scores_by_period = scores_by_period or {}

    def cell(period_num):
        return display_report_score(scores_by_period.get(period_num))

    p1, p2, p3 = cell(1), cell(2), cell(3)
    p4, p5, p6 = cell(4), cell(5), cell(6)
    exam1, exam2 = cell(7), cell(8)
    if aggregates:
        sem1 = display_report_score(mean_available_scores([p1, p2, p3, exam1]))
        sem2 = display_report_score(mean_available_scores([p4, p5, p6, exam2]))
        yearly = display_report_score(
            mean_available_scores([p1, p2, p3, exam1, p4, p5, p6, exam2])
        )
        remark_source = yearly if yearly != '' else (sem2 if sem2 != '' else sem1)
    else:
        sem1 = sem2 = yearly = ''
        shown = [c for c in (p1, p2, p3, exam1, p4, p5, p6, exam2) if c != '']
        remark_source = shown[0] if len(shown) == 1 else display_report_score(
            mean_available_scores(shown)
        )
    remark = division_score_remark(remark_source, division_key)
    return {
        'name': name,
        'p1': p1, 'p2': p2, 'p3': p3,
        'exam': exam1, 'exam1': exam1,
        'avg': sem1, 'sem1': sem1,
        'p4': p4, 'p5': p5, 'p6': p6,
        'final_exam': exam2, 'exam2': exam2,
        'sem2_avg': sem2, 'sem2': sem2,
        'final_avg': yearly, 'yearly': yearly,
        'remark': remark, 'remarks': remark,
    }


# Score columns on the official grid (aliases share one printed cell).
_AVERAGE_COLUMN_SPECS = (
    ('p1', ('p1',)),
    ('p2', ('p2',)),
    ('p3', ('p3',)),
    ('exam', ('exam', 'exam1')),
    ('avg', ('avg', 'sem1')),
    ('p4', ('p4',)),
    ('p5', ('p5',)),
    ('p6', ('p6',)),
    ('final_exam', ('final_exam', 'exam2')),
    ('sem2_avg', ('sem2_avg', 'sem2')),
    ('final_avg', ('final_avg', 'yearly')),
)


def _blank_score_row(name, *, is_summary=True, blank_empty=True):
    return {
        'name': name,
        'is_summary': is_summary,
        'blank_empty': blank_empty,
        'p1': '', 'p2': '', 'p3': '',
        'exam': '', 'exam1': '',
        'avg': '', 'sem1': '',
        'p4': '', 'p5': '', 'p6': '',
        'final_exam': '', 'exam2': '',
        'sem2_avg': '', 'sem2': '',
        'final_avg': '', 'yearly': '',
        'remark': '', 'remarks': '',
    }


def _subject_column_values(subjects, keys):
    """Numeric scores in one printed column, skipping AVERAGE / CONDUCT rows."""
    values = []
    for subject in subjects or []:
        if not isinstance(subject, dict):
            continue
        if subject.get('is_summary') or is_report_summary_subject(subject.get('name')):
            continue
        raw = None
        for key in keys:
            candidate = subject.get(key)
            if candidate not in (None, ''):
                raw = candidate
                break
        num = numeric_report_score(raw)
        if num is not None:
            values.append(num)
    return values


def column_average_from_subjects(subjects, keys, *, yearly=False):
    """Mean of subject scores in one column. Yearly prints as 76.71%."""
    values = _subject_column_values(subjects, keys)
    if not values:
        return ''
    mean = sum(values) / len(values)
    if yearly:
        return f'{mean:.2f}%'
    return display_report_score(mean)


def official_average_row(subjects, division_key=None):
    """Footer AVERAGE row: mean of each score column across academic subjects."""
    _ = division_key  # Remarks stay blank on the printed AVERAGE row.
    cells = {}
    for dest, keys in _AVERAGE_COLUMN_SPECS:
        cells[dest] = column_average_from_subjects(
            subjects, keys, yearly=(dest == 'final_avg'),
        )
    yearly = cells['final_avg']
    return {
        'name': AVERAGE_ROW_NAME,
        'is_summary': True,
        'blank_empty': True,
        'p1': cells['p1'], 'p2': cells['p2'], 'p3': cells['p3'],
        'exam': cells['exam'], 'exam1': cells['exam'],
        'avg': cells['avg'], 'sem1': cells['avg'],
        'p4': cells['p4'], 'p5': cells['p5'], 'p6': cells['p6'],
        'final_exam': cells['final_exam'], 'exam2': cells['final_exam'],
        'sem2_avg': cells['sem2_avg'], 'sem2': cells['sem2_avg'],
        'final_avg': yearly, 'yearly': yearly,
        'remark': '', 'remarks': '',
    }


def official_conduct_row(scores_by_period=None, division_key=None, *, aggregates=True):
    """Footer CONDUCT row. Period cells stay blank when no conduct grades exist."""
    scores_by_period = scores_by_period or {}
    has_scores = any(
        numeric_report_score(value) is not None
        for value in scores_by_period.values()
    )
    if not has_scores:
        return _blank_score_row(CONDUCT_ROW_NAME)
    row = official_subject_score_row(
        CONDUCT_ROW_NAME, scores_by_period, division_key, aggregates=aggregates,
    )
    row['is_summary'] = True
    row['blank_empty'] = True
    row['remark'] = ''
    row['remarks'] = ''
    return row


def report_card_footer_rows(
    academic_subjects,
    conduct_scores_by_period=None,
    division_key=None,
    *,
    aggregates=True,
):
    """AVERAGE then CONDUCT — always the last two rows of the grades table."""
    return [
        official_average_row(academic_subjects, division_key),
        official_conduct_row(conduct_scores_by_period, division_key, aggregates=aggregates),
    ]

_DIVISION_SUBJECT_ALIASES = {
    'kindergarten': DIVISION_KINDERGARTEN,
    'elementary': DIVISION_ELEMENTARY,
    'junior': DIVISION_JUNIOR_HIGH,
    'junior_high': DIVISION_JUNIOR_HIGH,
    'senior': DIVISION_SENIOR_HIGH,
    'senior_high': DIVISION_SENIOR_HIGH,
}

# Stored / informal names that should land on an official catalog row.
_SUBJECT_ALIAS_GROUPS = (
    ('MATHEMATICS', 'MATH', 'MATHS', 'MATHEMATIC'),
    ('ENGLISH', 'ENG', 'ENGLISH LANGUAGE', 'LANG ARTS', 'LANGUAGE ARTS'),
    ('GEN SCIENCE', 'GENERAL SCIENCE', 'INT SCIENCE', 'INTEGRATED SCIENCE'),
    ('COMP SCIENCE', 'COMPUTER SCIENCE', 'ICT', 'COMPUTER', 'COMPUTER STUDIES'),
    ('P EDUCATION', 'PHYSICAL EDUCATION', 'PE', 'P E', 'PHY EDUCATION'),
    (
        'RE EDUCATION',
        'RELIGIOUS EDUCATION',
        'R EDUCATION',
        'R E EDUCATION',
        'REL EDUCATION',
        'REL ED',
        'RE',
        'R E',
        'RELIGION',
    ),
    ('PHON O ENG', 'PHONICS ORAL ENGLISH', 'ORAL ENGLISH', 'PHONICS O ENG'),
    ('O ENG VOCAB', 'ORAL ENGLISH VOCABULARY', 'O ENG VOCABULARY'),
    ('ALPH WRITING', 'ALPHABET WRITING', 'ALPHA WRITING'),
    ('NUM WRITING', 'NUMBER WRITING', 'NUMERAL WRITING', 'NUMERICAL WRITING'),
    ('SHAPES COLORS', 'SHAPES AND COLORS', 'SHAPES COLOURS', 'SHAPES AND COLOURS'),
    ('HAND WRITING', 'HANDWRITING'),
    ('R O T C', 'ROTC'),
    ('HEALTH SCIENCE', 'HEALTH', 'HEALTH EDUCATION'),
    ('SOCIAL STUDIES', 'SOCIAL SCIENCE', 'SST'),
    ('LITERATURE', 'LIT', 'ENGLISH LITERATURE'),
    ('VOCABULARY', 'VOCAB'),
    ('CONDUCT', 'BEHAVIOUR', 'BEHAVIOR', 'DEPORTMENT'),
)

GRADE_PRINT_LABELS = {
    'ABC': 'ABC',
    'K-1': 'K-I',
    'K-2': 'K-II',
    '1st': 'GRADE 1',
    '2nd': 'GRADE 2',
    '3rd': 'GRADE 3',
    '4th': 'GRADE 4',
    '5th': 'GRADE 5',
    '6th': 'GRADE 6',
    '7th': 'GRADE 7',
    '8th': 'GRADE 8',
    '9th': 'GRADE 9',
    '10th': 'GRADE 10',
    '11th': 'GRADE 11',
    '12': 'GRADE 12',
    'Graduation': 'GRADUATION',
}

ACADEMIC_LEVEL_CHOICES = [
    (DIVISION_LABELS[DIVISION_KINDERGARTEN], DIVISION_LABELS[DIVISION_KINDERGARTEN]),
    (DIVISION_LABELS[DIVISION_ELEMENTARY], DIVISION_LABELS[DIVISION_ELEMENTARY]),
    (DIVISION_LABELS[DIVISION_JUNIOR_HIGH], DIVISION_LABELS[DIVISION_JUNIOR_HIGH]),
    (DIVISION_LABELS[DIVISION_SENIOR_HIGH], DIVISION_LABELS[DIVISION_SENIOR_HIGH]),
]

# Stored values match this school's Class.name labels (and map existing
# "Grade 10" / "Grade 1st" strings back onto the same choices).
GRADE_LEVEL_GROUPS = (
    (
        DIVISION_KINDERGARTEN,
        (
            ('ABC', 'ABC'),
            ('K-1', 'K-1'),
            ('K-2', 'K-2'),
        ),
    ),
    (
        DIVISION_ELEMENTARY,
        (
            ('1st', '1st (Grade 1)'),
            ('2nd', '2nd (Grade 2)'),
            ('3rd', '3rd (Grade 3)'),
            ('4th', '4th (Grade 4)'),
            ('5th', '5th (Grade 5)'),
            ('6th', '6th (Grade 6)'),
        ),
    ),
    (
        DIVISION_JUNIOR_HIGH,
        (
            ('7th', '7th (Grade 7)'),
            ('8th', '8th (Grade 8)'),
            ('9th', '9th (Grade 9)'),
        ),
    ),
    (
        DIVISION_SENIOR_HIGH,
        (
            ('10th', '10th (Grade 10)'),
            ('11th', '11th (Grade 11)'),
            ('12', '12 (Grade 12)'),
        ),
    ),
)

GRADE_LEVEL_SELECT_CHOICES = [
    (value, f'{DIVISION_LABELS[division]} — {label}')
    for division, options in GRADE_LEVEL_GROUPS
    for value, label in options
]

# [{'label': 'Kindergarten', 'options': (('ABC', 'ABC'), ...)}, ...] for
# templates that render an <optgroup> per division (e.g. class_create.html).
GRADE_LEVEL_GROUPS_FOR_TEMPLATE = [
    {'label': DIVISION_LABELS[division], 'options': options}
    for division, options in GRADE_LEVEL_GROUPS
]

_GRADE_CHOICE_VALUES = {value for value, _label in GRADE_LEVEL_SELECT_CHOICES}

_ORDINAL_TO_CANONICAL = {
    1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: '5th', 6: '6th',
    7: '7th', 8: '8th', 9: '9th', 10: '10th', 11: '11th', 12: '12',
}

_KG_RE = re.compile(
    r'\b(?:'
    r'abc|beginner|nursery|kindergarten|kinder|'
    r'pre[- ]?k(?:g)?|'
    r'kg(?:\s*[- ]?\s*(?:ii|2|i|1))?|'
    r'k\s*[- ]\s*(?:ii|2|i|1)|'
    r'k[12]'
    r')\b',
    re.IGNORECASE,
)
_KG_ABC_RE = re.compile(r'\b(?:abc|beginner|nursery|pre[- ]?k(?:g)?)\b', re.IGNORECASE)
_KG_TWO_RE = re.compile(
    r'\b(?:k\s*[- ]\s*(?:ii|2)|k2|kg\s*[- ]?\s*(?:ii|2))\b',
    re.IGNORECASE,
)
_KG_ONE_RE = re.compile(
    r'\b(?:k\s*[- ]\s*(?:i|1)|k1|kg\s*[- ]?\s*(?:i|1))\b',
    re.IGNORECASE,
)

_JSS_RE = re.compile(r'\bjss\s*[- ]?\s*([123])\b', re.IGNORECASE)
_SSS_RE = re.compile(r'\bsss\s*[- ]?\s*([123])\b', re.IGNORECASE)
_ORDINAL_RE = re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)\b', re.IGNORECASE)
_GRADE_N_RE = re.compile(r'\bgrade\s+(\d{1,2})\b', re.IGNORECASE)
_BARE_GRADE_RE = re.compile(r'^(\d{1,2})$')

_KEYWORD_DIVISION = (
    (re.compile(r'\b(?:kindergarten|kinder|\bkg\b|nursery|beginner|pre[- ]?k)\b', re.I), DIVISION_KINDERGARTEN),
    (re.compile(r'\b(?:junior\s*high|\bjhs\b|\bjss\b)\b', re.I), DIVISION_JUNIOR_HIGH),
    (re.compile(r'\b(?:senior\s*high|\bshs\b|\bsss\b)\b', re.I), DIVISION_SENIOR_HIGH),
    (re.compile(r'\b(?:elementary|primary)\b', re.I), DIVISION_ELEMENTARY),
)


def _joined_text(*parts):
    chunks = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            chunks.append(text)
    return ' '.join(chunks)


def _is_kindergarten(haystack):
    if not haystack:
        return False
    return bool(_KG_RE.search(haystack))


def _kg_rank(haystack):
    if not haystack:
        return 1
    if _KG_ABC_RE.search(haystack):
        return 0
    if _KG_TWO_RE.search(haystack):
        return 2
    if _KG_ONE_RE.search(haystack):
        return 1
    return 1


def parse_grade_number(*parts):
    """Return 1–12 when the labels name an elementary/JHS/SHS grade.

    Kindergarten tokens (ABC, K-1, K-2, KG) return None so they are not
    treated as Grade 1.
    """
    haystack = _joined_text(*parts)
    if not haystack:
        return None
    if _is_kindergarten(haystack):
        return None

    jss = _JSS_RE.search(haystack)
    if jss:
        return 6 + int(jss.group(1))
    sss = _SSS_RE.search(haystack)
    if sss:
        return 9 + int(sss.group(1))

    found = []
    for match in _ORDINAL_RE.finditer(haystack):
        number = int(match.group(1))
        if 1 <= number <= 12:
            found.append(number)
    for match in _GRADE_N_RE.finditer(haystack):
        number = int(match.group(1))
        if 1 <= number <= 12:
            found.append(number)
    if found:
        for number in (12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1):
            if number in found:
                return number

    for part in parts:
        if part is None:
            continue
        match = _BARE_GRADE_RE.match(str(part).strip())
        if match:
            number = int(match.group(1))
            if 1 <= number <= 12:
                return number
    return None


def division_for_grade_number(number):
    if number is None:
        return None
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None
    if 1 <= number <= 6:
        return DIVISION_ELEMENTARY
    if 7 <= number <= 9:
        return DIVISION_JUNIOR_HIGH
    if 10 <= number <= 12:
        return DIVISION_SENIOR_HIGH
    return None


def resolve_school_division(*parts, default=DIVISION_UNASSIGNED):
    """Map class name / grade_level / stream / student.level to a division key."""
    haystack = _joined_text(*parts)
    if not haystack:
        return default

    if _is_kindergarten(haystack):
        return DIVISION_KINDERGARTEN

    mapped = division_for_grade_number(parse_grade_number(*parts))
    if mapped:
        return mapped

    for pattern, key in _KEYWORD_DIVISION:
        if pattern.search(haystack):
            return key
    return default


def resolve_from_class(klass, *extra_parts):
    if klass is None:
        return resolve_school_division(*extra_parts)
    return resolve_school_division(
        getattr(klass, 'name', None),
        getattr(klass, 'grade_level', None),
        getattr(klass, 'stream', None),
        *extra_parts,
    )


def division_for_class(klass, *extra_parts):
    """Kindergarten / Elementary / Junior High / Senior High for a class."""
    return resolve_from_class(klass, *extra_parts)


def division_label(division_key):
    return DIVISION_LABELS.get(division_key, DIVISION_LABELS[DIVISION_UNASSIGNED])


def division_label_for_class(klass, *extra_parts):
    return division_label(resolve_from_class(klass, *extra_parts))


def academic_level_for_student(student):
    """Kindergarten / Elementary / Junior High / Senior High for enrollment forms.

    Assigned class is the source of truth so a blank or stale student.level
    does not leave Academic Level empty on returning-student screens.
    """
    if student is None:
        return ''

    klass = getattr(student, 'assigned_class', None) or getattr(student, 'klass', None)
    stored_level = (getattr(student, 'level', None) or '').strip()
    grade_level = getattr(student, 'grade_level', None)
    key = resolve_from_class(klass, grade_level, stored_level)
    if key and key != DIVISION_UNASSIGNED:
        return division_label(key)
    if stored_level in DIVISION_LABELS.values():
        return stored_level
    from_stored = resolve_school_division(stored_level)
    if from_stored != DIVISION_UNASSIGNED:
        return division_label(from_stored)
    return ''


def class_sort_key(name=None, grade_level=None, stream=None):
    division = resolve_school_division(name, grade_level, stream)
    if division in DIVISION_ORDER:
        div_index = DIVISION_ORDER.index(division)
    else:
        div_index = len(DIVISION_ORDER)
    haystack = _joined_text(name, grade_level, stream)
    if division == DIVISION_KINDERGARTEN:
        subrank = _kg_rank(haystack)
    else:
        subrank = parse_grade_number(name, grade_level, stream)
        if subrank is None:
            subrank = 50
    return (div_index, subrank, (name or '').lower())


def class_sort_key_from_klass(klass):
    if klass is None:
        return (len(DIVISION_ORDER), 99, '')
    return class_sort_key(
        getattr(klass, 'name', None),
        getattr(klass, 'grade_level', None),
        getattr(klass, 'stream', None),
    )


def sort_classes(classes):
    return sorted(classes or [], key=class_sort_key_from_klass)


def group_classes(classes):
    """Return [{key, label, classes}, ...] in school order, skipping empty groups."""
    buckets = {key: [] for key in DIVISION_ORDER}
    other = []
    for klass in sort_classes(classes):
        key = resolve_from_class(klass)
        if key in buckets:
            buckets[key].append(klass)
        else:
            other.append(klass)
    groups = [
        {'key': key, 'label': DIVISION_LABELS[key], 'classes': buckets[key]}
        for key in DIVISION_ORDER
        if buckets[key]
    ]
    if other:
        groups.append({
            'key': DIVISION_UNASSIGNED,
            'label': DIVISION_LABELS[DIVISION_UNASSIGNED],
            'classes': other,
        })
    return groups


def group_items_by_class(items, get_klass):
    """Group class-linked records into [{key, label, classes}, ...] in school order.

    Uses the key 'classes' (not 'items') so Jinja `group.classes` never
    resolves to dict.items.
    """
    decorated = []
    for item in items or []:
        klass = get_klass(item)
        decorated.append((class_sort_key_from_klass(klass), item, klass))
    decorated.sort(key=lambda row: row[0])

    buckets = {key: [] for key in DIVISION_ORDER}
    other = []
    for _sort_key, item, klass in decorated:
        key = resolve_from_class(klass)
        if key in buckets:
            buckets[key].append(item)
        else:
            other.append(item)
    groups = [
        {'key': key, 'label': DIVISION_LABELS[key], 'classes': buckets[key]}
        for key in DIVISION_ORDER
        if buckets[key]
    ]
    if other:
        groups.append({
            'key': DIVISION_UNASSIGNED,
            'label': DIVISION_LABELS[DIVISION_UNASSIGNED],
            'classes': other,
        })
    return groups


def canonical_grade_value(*parts):
    """Map 'Grade 10' / 'Grade K-1' onto the class_create dropdown values."""
    haystack = _joined_text(*parts)
    if not haystack:
        return ''
    if haystack in _GRADE_CHOICE_VALUES:
        return haystack
    if _is_kindergarten(haystack):
        rank = _kg_rank(haystack)
        return {0: 'ABC', 1: 'K-1', 2: 'K-2'}.get(rank, 'K-1')
    number = parse_grade_number(*parts)
    if number in _ORDINAL_TO_CANONICAL:
        return _ORDINAL_TO_CANONICAL[number]
    return haystack


def coerce_grade_level_choice(stored):
    if stored is None:
        return ''
    text = str(stored).strip()
    if text in _GRADE_CHOICE_VALUES:
        return text
    canonical = canonical_grade_value(text)
    if canonical in _GRADE_CHOICE_VALUES:
        return canonical
    return text


def normalize_subject_key(name):
    """Uppercase alphanumerics only, so GEN. SCIENCE matches Gen Science."""
    text = re.sub(r'[^A-Z0-9]+', ' ', (name or '').upper())
    return ' '.join(text.split())


def subject_match_key(name):
    """Stable key for comparing stored names to official catalog names."""
    norm = normalize_subject_key(name)
    if not norm:
        return ''
    for group in _SUBJECT_ALIAS_GROUPS:
        if norm in group:
            return group[0]
    return norm


def subject_slug(name):
    """Unique slug for a subject; aliases such as PE and P. Education share one."""
    key = subject_match_key(name)
    if not key:
        return ''
    return key.lower().replace(' ', '-')


def is_report_summary_subject(name):
    key = subject_match_key(name)
    return key in (
        subject_match_key(AVERAGE_ROW_NAME),
        subject_match_key(CONDUCT_ROW_NAME),
    )


def is_conduct_subject(name):
    return subject_match_key(name) == subject_match_key(CONDUCT_ROW_NAME)


def division_subjects(division_key):
    """Official academic subjects for a school section, in card order."""
    if not division_key:
        return ()
    if division_key in DIVISION_SUBJECT_CATALOGS:
        return DIVISION_SUBJECT_CATALOGS[division_key]
    if division_key in REPORT_CARD_SUBJECTS:
        return REPORT_CARD_SUBJECTS[division_key]
    mapped = _DIVISION_SUBJECT_ALIASES.get(str(division_key).lower())
    return DIVISION_SUBJECT_CATALOGS.get(mapped, ())


def subjects_for_class(klass, *extra_parts):
    """Official report-card subjects for a class object or class name."""
    if isinstance(klass, str):
        return division_subjects(resolve_school_division(klass, *extra_parts))
    return division_subjects(resolve_from_class(klass, *extra_parts))


def canonical_subject_name(name, division_key=None):
    """Map a stored subject onto the official catalog name for a division."""
    if not name:
        return None
    if is_conduct_subject(name):
        return CONDUCT_ROW_NAME
    if subject_match_key(name) == subject_match_key(AVERAGE_ROW_NAME):
        return AVERAGE_ROW_NAME
    catalog = division_subjects(division_key) if division_key else ()
    needle = subject_match_key(name)
    if not needle:
        return None
    for official in catalog:
        if subject_match_key(official) == needle:
            return official
    # Legacy imports sometimes contain a small typo that is not a known alias.
    # Accept only a strong, unambiguous catalog match so unrelated subjects do
    # not get merged merely because they share a word such as "Science".
    fuzzy_matches = sorted(
        (
            SequenceMatcher(None, needle, subject_match_key(official)).ratio(),
            official,
        )
        for official in catalog
        if subject_match_key(official)
    )
    if fuzzy_matches:
        best_ratio, best_name = fuzzy_matches[-1]
        runner_up = fuzzy_matches[-2][0] if len(fuzzy_matches) > 1 else 0.0
        if best_ratio >= 0.88 and best_ratio - runner_up >= 0.08:
            return best_name
    if not catalog:
        for subjects in DIVISION_SUBJECT_CATALOGS.values():
            for official in subjects:
                if subject_match_key(official) == needle:
                    return official
    return None


def order_subjects_by_catalog(names, division_key, keep_unknown=True):
    """Return names in official card order; unknown extras stay at the end."""
    catalog = list(division_subjects(division_key))
    used = set()
    ordered = []
    incoming = [name for name in (names or []) if name]

    for official in catalog:
        official_key = subject_match_key(official)
        for name in incoming:
            if is_report_summary_subject(name):
                continue
            if subject_match_key(name) == official_key:
                if official_key not in used:
                    ordered.append(official)
                    used.add(official_key)
                break

    if keep_unknown:
        for name in incoming:
            if is_report_summary_subject(name):
                continue
            key = subject_match_key(name)
            if not key or key in used:
                continue
            canon = canonical_subject_name(name, division_key)
            if canon:
                if subject_match_key(canon) not in used:
                    ordered.append(canon)
                    used.add(subject_match_key(canon))
                continue
            ordered.append(name)
            used.add(key)
    return ordered


def report_card_subject_names(division_key):
    """Academic catalog plus AVERAGE and CONDUCT rows."""
    return list(division_subjects(division_key)) + list(REPORT_SUMMARY_ROWS)


def grade_print_label(canonical_value):
    if not canonical_value:
        return None
    return GRADE_PRINT_LABELS.get(canonical_value, str(canonical_value).upper())


def current_class_display_label(*parts):
    return grade_print_label(canonical_grade_value(*parts))


def next_class_display_label(*parts):
    nxt = next_canonical_grade(*parts)
    if nxt is None:
        return None
    return grade_print_label(nxt)


# 4-digit start (optional 2-digit end) or compact 2+2, any dash/slash, extra words OK.
_YEAR_SPAN_RE = re.compile(
    r'(?<!\d)(\d{4})\s*[-–—/]\s*(\d{2,4})(?!\d)'
    r'|(?<!\d)(\d{2})\s*[-–—/]\s*(\d{2})(?!\d)'
)


def _expand_span_end_year(start, end_raw):
    """Resolve a 2-digit end year without assuming the current century prefix."""
    if end_raw >= 100:
        return end_raw
    end = (start // 100) * 100 + end_raw
    if end < start:
        end += 100
    return end


def parse_academic_year_span(name):
    """Return (start_year, end_year) for labels like 2035-2036, 2035–36, 35-36.

    Century wrap uses the start year, not today's date: 2099-00 → (2099, 2100).
    Two-digit starts are read as 20xx (35-36 → 2035-2036).
    """
    text = (name or '').strip()
    if not text:
        return None
    match = _YEAR_SPAN_RE.search(text)
    if not match:
        return None
    if match.group(1) is not None:
        start = int(match.group(1))
        end = _expand_span_end_year(start, int(match.group(2)))
        return (start, end)
    start = 2000 + int(match.group(3))
    end = 2000 + int(match.group(4))
    if end < start:
        end += 100
    return (start, end)


def academic_year_span_key(name):
    """Canonical YYYY-YYYY key, or None when the label is not a year span."""
    span = parse_academic_year_span(name)
    if not span:
        return None
    return f'{span[0]}-{span[1]}'


def normalize_academic_year_name(name):
    """Store parseable spans as hyphenated YYYY-YYYY; leave other labels as typed."""
    key = academic_year_span_key(name)
    if key:
        return key
    return (name or '').strip()


def next_academic_year_label(name):
    """Advance 2035-2036 / 2035–36 / 2035/2036 to 2036-2037."""
    span = parse_academic_year_span(name)
    if not span:
        return None
    return f'{span[0] + 1}-{span[1] + 1}'


def format_academic_year_label(name):
    """Print as 2035/2036 when the stored year looks like a span."""
    span = parse_academic_year_span(name)
    if not span:
        return (name or '').strip()
    return f'{span[0]}/{span[1]}'


def division_document_titles(division_key, kind='sheet'):
    """Titles used on printed grade sheets and report cards."""
    if kind == 'report':
        return {
            DIVISION_KINDERGARTEN: 'Kindergarten Division Report Card',
            DIVISION_ELEMENTARY: 'Elementary Division Report Card',
            DIVISION_JUNIOR_HIGH: 'Junior High Report Card',
            DIVISION_SENIOR_HIGH: 'Senior High Report Card',
        }.get(division_key, 'Elementary Division Report Card')
    if kind == 'record':
        return {
            DIVISION_KINDERGARTEN: 'Kindergarten Division Academic Performance Record',
            DIVISION_ELEMENTARY: 'Elementary Division Academic Performance Record',
            DIVISION_JUNIOR_HIGH: 'Junior High Academic Performance Record',
            DIVISION_SENIOR_HIGH: 'Senior High Academic Performance Record',
        }.get(division_key, 'Elementary Division Academic Performance Record')
    return {
        DIVISION_KINDERGARTEN: 'Kindergarten Division Grade Sheet',
        DIVISION_ELEMENTARY: 'Elementary Division Grade Sheet',
        DIVISION_JUNIOR_HIGH: 'Junior High Grade Sheet',
        DIVISION_SENIOR_HIGH: 'Senior High Grade Sheet',
    }.get(division_key, 'Elementary Division Grade Sheet')


def division_subject_heading(division_key):
    """Column heading for the subject list on official documents."""
    return 'SUBJECTS'


def division_left_signatory(division_key):
    return SCHOOL_PRINT_SPONSOR_TITLE


def division_score_remark(score, division_key=None):
    """Remark language for a numeric year average. Kindergarten stays gentler."""
    if score in (None, '', '-', '—'):
        return '—'
    try:
        score = float(score)
    except (TypeError, ValueError):
        return '—'
    if division_key == DIVISION_KINDERGARTEN:
        if score >= 90:
            return 'Excellent'
        if score >= 80:
            return 'Good'
        if score >= 70:
            return 'Satisfactory'
        return 'Needs Support'
    if score >= 90:
        return 'Excellent'
    if score >= 80:
        return 'Good'
    if score >= 70:
        return 'Fair'
    return 'Failure'


def division_legend_rows(division_key):
    """Grading-key rows printed under the score table."""
    if division_key == DIVISION_KINDERGARTEN:
        return (
            ('Excellent', '90 – 100', 'A'),
            ('Good', '80 – 89', 'B'),
            ('Satisfactory', '70 – 79', 'C'),
            ('Needs Support', 'Below 70', 'D'),
        )
    return (
        ('Excellent', '90 – 100', 'A'),
        ('Good', '80 – 89', 'B'),
        ('Fair', '70 – 79', 'C'),
        ('Failure', 'Below 70', 'D'),
    )


def next_canonical_grade(*parts):
    """Next class in school order (ABC → K-1 → … → 12 → Graduation)."""
    current = canonical_grade_value(*parts)
    sequence = [value for _div, options in GRADE_LEVEL_GROUPS for value, _label in options]
    if current not in sequence:
        return None
    idx = sequence.index(current)
    if idx + 1 >= len(sequence):
        return 'Graduation'
    return sequence[idx + 1]


# Official Transcript letterhead (paper form). The transcript used to carry its
# own phone list; it now tracks the school line so retired numbers cannot linger
# on one document after being changed on the others.
TRANSCRIPT_PRINT_ADDRESS = 'CENTER STREET-SOUTH BEACH, MONROVIA, LIBERIA'
TRANSCRIPT_PRINT_PHONES = SCHOOL_PRINT_PHONES
TRANSCRIPT_PRINT_EMAIL = 'flpacardinals@gmail.com'

_GRADE_NUMBER_WORDS = {
    1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six',
    7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten', 11: 'Eleven', 12: 'Twelve',
}

# Paper slots: (print name, alias names that map onto that row).
_TRANSCRIPT_CATEGORY_SLOTS = (
    (
        'LANGUAGE ARTS',
        (
            ('English', ('English', 'ENG', 'English Language')),
            ('Literature/Reading', ('Literature', 'Reading', 'Literature/Reading', 'English Literature')),
            ('French', ('French',)),
            (
                'Oral English/Vocabulary',
                (
                    'O.Eng/Vocab', 'Oral English/Vocabulary', 'Phon. /O. Eng',
                    'Vocabulary', 'Oral English',
                ),
            ),
            (
                'Religious Moral Edu. / Bible',
                (
                    'R/Education', 'RE/ Education', 'Religious Moral Edu. / Bible',
                    'Bible', 'Religious Education',
                ),
            ),
        ),
    ),
    (
        'SOCIAL STUDIES',
        (
            ('History', ('History',)),
            ('Economics/Civics', ('Economics', 'Civics', 'Economics/Civics')),
            ('Geography', ('Geography',)),
            ('Government', ('Government',)),
        ),
    ),
    (
        'MATHEMATICS',
        (
            ('Algebra/Geometry', ('Mathematics', 'Algebra/Geometry', 'Algebra', 'Geometry')),
        ),
    ),
    (
        'GENERAL SCIENCE',
        (
            ('Biology', ('Biology',)),
            ('Chemistry', ('Chemistry',)),
            ('Physics', ('Physics',)),
            ('Health Science', ('Health Science', 'Health')),
            (
                'Agri. Science',
                ('Agri. Science', 'Agriculture', 'Agricultural Science', 'Agric. Science'),
            ),
        ),
    ),
)

_TRANSCRIPT_STANDALONE_SLOT = (
    'R.O.T.C. / Physical Edu.',
    ('R.O.T.C', 'R.O.T.C.', 'P. Education', 'Physical Education', 'PE'),
)

_TRANSCRIPT_EXTRA_CATEGORY_KEYS = {
    'LANGUAGE ARTS': {
        'ENGLISH', 'LITERATURE', 'READING', 'FRENCH', 'O ENG VOCAB', 'PHON O ENG',
        'VOCABULARY', 'RE EDUCATION', 'BIBLE', 'SPELLING', 'PHONICS', 'HAND WRITING',
        'ALPH WRITING',
    },
    'SOCIAL STUDIES': {
        'HISTORY', 'ECONOMICS', 'CIVICS', 'GEOGRAPHY', 'GOVERNMENT', 'SOCIAL STUDIES',
    },
    'MATHEMATICS': {
        'MATHEMATICS', 'ALGEBRA', 'GEOMETRY', 'NUM WRITING', 'SHAPES COLORS',
    },
    'GENERAL SCIENCE': {
        'BIOLOGY', 'CHEMISTRY', 'PHYSICS', 'HEALTH SCIENCE', 'AGRI SCIENCE',
        'AGRICULTURE', 'AGRICULTURAL SCIENCE', 'GEN SCIENCE', 'SCIENCE',
        'COMP SCIENCE',
    },
}

_TRANSCRIPT_STANDALONE_KEYS = {'R O T C', 'P EDUCATION'}


def transcript_letterhead():
    """Paper Official Transcript header (phones/address as on the FLPA form)."""
    brand = dict(school_print_brand())
    brand['transcript_address'] = TRANSCRIPT_PRINT_ADDRESS
    brand['transcript_phones'] = TRANSCRIPT_PRINT_PHONES
    brand['transcript_email'] = TRANSCRIPT_PRINT_EMAIL
    return brand


def _transcript_ordinal(number):
    try:
        number = int(number)
    except (TypeError, ValueError):
        return 'N/A'
    if number <= 0:
        return 'N/A'
    if 10 <= (number % 100) <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
    return f'{number}{suffix}'


def transcript_grade_heading(*parts):
    """GRADE: (10) Ten — kindergarten and unlabeled values stay as printed."""
    number = parse_grade_number(*parts)
    if number in _GRADE_NUMBER_WORDS:
        return f'({number}) {_GRADE_NUMBER_WORDS[number]}'
    canon = canonical_grade_value(*parts)
    if canon:
        return grade_print_label(canon) or str(canon)
    for part in parts:
        text = str(part).strip() if part is not None else ''
        if text:
            return text
    return 'N/A'


def transcript_grade_ordinal(*parts):
    """11th / Graduation / K-I for the certified-paragraph blanks."""
    number = parse_grade_number(*parts)
    if number:
        return _transcript_ordinal(number)
    canon = canonical_grade_value(*parts)
    if not canon:
        return 'N/A'
    if canon == 'Graduation':
        return 'Graduation'
    return grade_print_label(canon) or str(canon)


def transcript_promotion_fields(promotion, *current_grade_parts):
    """(promoted_to, conditioned_in, retained_in) from year-end MoE decision."""
    current_ord = transcript_grade_ordinal(*current_grade_parts)
    nxt = next_canonical_grade(*current_grade_parts)
    next_ord = transcript_grade_ordinal(nxt) if nxt else 'N/A'
    decision = (promotion or {}).get('decision')
    if decision == 'graduate':
        return 'Graduation', 'N/A', 'N/A'
    if decision == 'promote':
        if nxt == 'Graduation':
            return 'Graduation', 'N/A', 'N/A'
        return next_ord, 'N/A', 'N/A'
    if decision == 'summer_school':
        return 'N/A', current_ord, 'N/A'
    if decision == 'repeat':
        return 'N/A', 'N/A', current_ord
    return 'N/A', 'N/A', 'N/A'


def transcript_conduct_label(value):
    """Paper CONDUCT wording (VERY GOOD, not the 6-period remark scale)."""
    number = numeric_report_score(value)
    if number is None:
        return ''
    if number >= 90:
        return 'EXCELLENT'
    if number >= 80:
        return 'VERY GOOD'
    if number >= 70:
        return 'GOOD'
    if number >= 60:
        return 'FAIR'
    return 'POOR'


def _transcript_score_cells(subject):
    subject = subject or {}
    return {
        'sem1': subject.get('sem1') if subject.get('sem1') not in (None, '') else subject.get('avg', ''),
        'sem2': subject.get('sem2') if subject.get('sem2') not in (None, '') else subject.get('sem2_avg', ''),
        'yearly': (
            subject.get('yearly')
            if subject.get('yearly') not in (None, '')
            else subject.get('final_avg', '')
        ),
    }


def _transcript_row(subject, display_name):
    cells = _transcript_score_cells(subject)
    return {
        'name': display_name,
        'kind': 'subject',
        'sem1': cells['sem1'] or '',
        'sem2': cells['sem2'] or '',
        'yearly': cells['yearly'] or '',
    }


def _pop_matching_subject(remaining, alias_names):
    keys = {subject_match_key(name) for name in alias_names if subject_match_key(name)}
    for index, subject in enumerate(remaining):
        if subject_match_key(subject.get('name')) in keys:
            return remaining.pop(index)
    return None


def _transcript_category_for_name(name):
    key = subject_match_key(name)
    if not key or key in _TRANSCRIPT_STANDALONE_KEYS:
        return None
    for category, keys in _TRANSCRIPT_EXTRA_CATEGORY_KEYS.items():
        if key in keys:
            return category
    return None


def build_transcript_grade_groups(subjects, division_key=None):
    """Group report-card rows into the Official Transcript paper layout.

    Senior High keeps the FLPA paper list (blank Health Science / Agri. Science
    when those scores are missing). Other divisions print category headers and
    only the subjects the student actually has.
    """
    academic = []
    average_row = None
    conduct_row = None
    for subject in subjects or []:
        if not isinstance(subject, dict):
            continue
        name = subject.get('name') or ''
        if is_conduct_subject(name):
            conduct_row = subject
            continue
        if is_report_summary_subject(name):
            average_row = subject
            continue
        academic.append(dict(subject))

    remaining = list(academic)
    use_paper = division_key == DIVISION_SENIOR_HIGH
    groups = []

    for category, slots in _TRANSCRIPT_CATEGORY_SLOTS:
        rows = []
        for paper_name, aliases in slots:
            matched = _pop_matching_subject(remaining, aliases)
            if matched:
                display = paper_name if use_paper else (matched.get('name') or paper_name)
                rows.append(_transcript_row(matched, display))
            elif use_paper:
                rows.append(_transcript_row(_blank_score_row(paper_name, is_summary=False), paper_name))
        extras = [
            subject for subject in remaining
            if _transcript_category_for_name(subject.get('name')) == category
        ]
        for extra in extras:
            remaining.remove(extra)
            rows.append(_transcript_row(extra, extra.get('name') or 'Subject'))
        if rows:
            groups.append({'kind': 'category', 'label': category, 'rows': rows})

    standalone_name, standalone_aliases = _TRANSCRIPT_STANDALONE_SLOT
    matched_pe = _pop_matching_subject(remaining, standalone_aliases)
    pe_rows = []
    if matched_pe:
        display = standalone_name if use_paper else (matched_pe.get('name') or standalone_name)
        pe_rows.append(_transcript_row(matched_pe, display))
    elif use_paper:
        pe_rows.append(_transcript_row(
            _blank_score_row(standalone_name, is_summary=False),
            standalone_name,
        ))
    leftover_pe = [
        subject for subject in remaining
        if subject_match_key(subject.get('name')) in _TRANSCRIPT_STANDALONE_KEYS
    ]
    for extra in leftover_pe:
        remaining.remove(extra)
        pe_rows.append(_transcript_row(extra, extra.get('name') or standalone_name))
    if pe_rows:
        groups.append({'kind': 'standalone', 'label': None, 'rows': pe_rows})

    if remaining:
        groups.append({
            'kind': 'category',
            'label': 'ADDITIONAL SUBJECTS',
            'rows': [
                _transcript_row(subject, subject.get('name') or 'Subject')
                for subject in remaining
            ],
        })

    return groups, average_row, conduct_row


def transcript_conduct_cells(conduct_row):
    cells = _transcript_score_cells(conduct_row)
    return {
        'sem1': transcript_conduct_label(cells.get('sem1')),
        'sem2': transcript_conduct_label(cells.get('sem2')),
        'yearly': transcript_conduct_label(cells.get('yearly')),
    }


def school_print_brand():
    """Header block shared by on-screen and PDF report documents."""
    return {
        'name': SCHOOL_PRINT_NAME,
        'address': SCHOOL_PRINT_ADDRESS_LINE,
        'city': SCHOOL_PRINT_CITY_LINE,
        'full_address': SCHOOL_PRINT_FULL_ADDRESS,
        'phones': SCHOOL_PRINT_PHONES,
        'phone': SCHOOL_PRINT_PHONE,
        'email_address': SCHOOL_PRINT_EMAIL_ADDRESS,
        'email': SCHOOL_PRINT_EMAIL,
        'motto': SCHOOL_PRINT_MOTTO,
        'brand_red': SCHOOL_PRINT_BRAND_RED,
        'grading_method': SCHOOL_PRINT_GRADING_METHOD,
        'vpi_title': SCHOOL_PRINT_VPI_TITLE,
        'vpi_name': SCHOOL_PRINT_VPI_NAME,
        'sponsor_title': SCHOOL_PRINT_SPONSOR_TITLE,
        'principal_title': SCHOOL_PRINT_PRINCIPAL_TITLE,
    }


def class_document_context(klass):
    """Division titles and print header for a class grade sheet."""
    division_key = resolve_from_class(klass)
    brand = school_print_brand()
    return {
        'school_name': brand['name'],
        'school': brand,
        'division': division_key,
        'division_label': division_label(division_key),
        'division_sheet_title': division_document_titles(division_key, 'sheet'),
        'division_report_title': division_document_titles(division_key, 'report'),
        'subject_heading': division_subject_heading(division_key),
        'left_signatory': division_left_signatory(division_key),
        'is_kindergarten': division_key == DIVISION_KINDERGARTEN,
    }
