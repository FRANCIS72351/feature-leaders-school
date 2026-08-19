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
SCHOOL_PRINT_PHONES = '0777-287-456 / 0770-203-098 / 0881-164-147'
SCHOOL_PRINT_PHONE = f'Telephone: {SCHOOL_PRINT_PHONES}'
SCHOOL_PRINT_EMAIL_ADDRESS = 'flpacardinals@gmail.com'
SCHOOL_PRINT_EMAIL = f'Email: {SCHOOL_PRINT_EMAIL_ADDRESS}'
SCHOOL_PRINT_MOTTO = 'Honor, Excellence, Academic, Discipline and Success'
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
    ('RE EDUCATION', 'RELIGIOUS EDUCATION', 'R EDUCATION', 'R E', 'RELIGION'),
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


def format_academic_year_label(name):
    """Print as 2025/2026 when the stored year looks like a span."""
    text = (name or '').strip()
    match = re.search(r'(\d{4})\s*[-–/]\s*(\d{2,4})', text)
    if not match:
        return text
    start, end = match.group(1), match.group(2)
    if len(end) == 2:
        end = start[:2] + end
    return f'{start}/{end}'


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
