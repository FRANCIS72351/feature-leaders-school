# System User Roles Configurations
ROLE_ADMIN = 'admin'
ROLE_REGISTRAR = 'registrar'
ROLE_TEACHER = 'teacher'
ROLE_BUSINESS = 'business'
ROLE_SPONSOR = 'sponsor'
ROLE_STUDENT = 'student'

# MoE marking periods: 1, 2, 3, EXAM, 4, 5, 6, FINAL EXAM (IDs 7 and 8 = semester exams)
GRADING_PERIODS = [
    (1, '1'),
    (2, '2'),
    (3, '3'),
    (7, 'EXAM'),
    (4, '4'),
    (5, '5'),
    (6, '6'),
    (8, 'FINAL EXAM'),
]

_GRADING_PERIOD_LABELS = dict(GRADING_PERIODS)


def grading_period_label(period_num):
    """Human-readable label for a marking period number."""
    try:
        period_num = int(period_num)
    except (TypeError, ValueError):
        return str(period_num) if period_num else '1'
    return _GRADING_PERIOD_LABELS.get(period_num, str(period_num))