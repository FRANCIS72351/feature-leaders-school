# System User Roles Configurations
ROLE_ADMIN = 'admin'
ROLE_REGISTRAR = 'registrar'
ROLE_TEACHER = 'teacher'
ROLE_BUSINESS = 'business'
ROLE_SPONSOR = 'sponsor'
ROLE_STUDENT = 'student'

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
# ATT 10 + PART 10 + QUIZ 15 + ASSG 20 + CW 15 + HW 10 + TEST 20 = 100
# Form field names stay stable (homework uses `other`).
PERIOD_COMPONENT_SPECS = (
    ('attendance', 'ATT', 'Attendance', 10.0),
    ('participation', 'PART', 'Participation', 10.0),
    ('quiz', 'QUIZ', 'Quiz', 15.0),
    ('assignment', 'ASSG', 'Assignment', 20.0),
    ('classwork', 'CW', 'Class Work', 15.0),
    ('other', 'HW', 'Homework', 10.0),
    ('test', 'TEST', 'Test', 20.0),
)
PERIOD_COMPONENT_MAXIMA = {
    key: max_score for key, _code, _label, max_score in PERIOD_COMPONENT_SPECS
}
PERIOD_COMPONENT_SCHEME_NOTE = (
    'ATT 10 + PART 10 + QUIZ 15 + ASSG 20 + CW 15 + HW 10 + TEST 20 = 100'
)
PERIOD_COMPONENT_ACTIVITY_TYPES = {
    'attendance': 'Class Work',
    'participation': 'Class Work',
    'quiz': 'Quiz',
    'assignment': 'Assignment',
    'classwork': 'Class Work',
    'other': 'Assignment',
    'test': 'Test',
}
