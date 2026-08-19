"""School division mapping — no student PII, no database required."""
import unittest

from school_divisions import (
    AVERAGE_ROW_NAME,
    CONDUCT_ROW_NAME,
    DIVISION_ELEMENTARY,
    DIVISION_JUNIOR_HIGH,
    DIVISION_KINDERGARTEN,
    DIVISION_SENIOR_HIGH,
    REPORT_CARD_SUBJECTS,
    canonical_grade_value,
    class_sort_key,
    coerce_grade_level_choice,
    division_document_titles,
    division_for_class,
    division_legend_rows,
    division_score_remark,
    division_subject_heading,
    next_canonical_grade,
    parse_grade_number,
    resolve_from_class,
    resolve_school_division,
    sort_classes,
    subject_slug,
    subjects_for_class,
)


class _FakeClass:
    def __init__(self, name, grade_level, stream=None):
        self.name = name
        self.grade_level = grade_level
        self.stream = stream


# Actual Class rows from instance/keeptrack_full.db (name, grade_level, stream)
LIVE_CLASSES = [
    _FakeClass('ABC', 'Grade ABC', 'Grade ABC'),
    _FakeClass('K-1', 'Grade K-1', 'Grade K-1'),
    _FakeClass('K-2', 'Grade K-2', 'Grade K-2'),
    _FakeClass('1st', 'Grade 1st', 'Grade 1st'),
    _FakeClass('2nd', 'Grade 2nd', 'Grade 2nd'),
    _FakeClass('3rd', 'Grade 3rd', 'Grade 3rd'),
    _FakeClass('4th', 'Grade 4th', 'Grade 4th'),
    _FakeClass('5th', 'Grade 5th', 'Grade 5th'),
    _FakeClass('6th', 'Grade 6', 'Grade 6'),
    _FakeClass('7th', 'Grade 7', 'Grade 7'),
    _FakeClass('8th', 'Grade 8', 'Grade 8'),
    _FakeClass('9th', 'Grade 9', 'Grade 9'),
    _FakeClass('10th', 'Grade 10', 'Grade 10'),
    _FakeClass('11th', 'Grade 11', 'Grade 11'),
    _FakeClass('12', 'Grade 12', 'GRade 12'),
]

EXPECTED_DIVISION = {
    'ABC': DIVISION_KINDERGARTEN,
    'K-1': DIVISION_KINDERGARTEN,
    'K-2': DIVISION_KINDERGARTEN,
    '1st': DIVISION_ELEMENTARY,
    '2nd': DIVISION_ELEMENTARY,
    '3rd': DIVISION_ELEMENTARY,
    '4th': DIVISION_ELEMENTARY,
    '5th': DIVISION_ELEMENTARY,
    '6th': DIVISION_ELEMENTARY,
    '7th': DIVISION_JUNIOR_HIGH,
    '8th': DIVISION_JUNIOR_HIGH,
    '9th': DIVISION_JUNIOR_HIGH,
    '10th': DIVISION_SENIOR_HIGH,
    '11th': DIVISION_SENIOR_HIGH,
    '12': DIVISION_SENIOR_HIGH,
}


class SchoolDivisionTests(unittest.TestCase):
    def test_live_class_rows_land_in_the_right_division(self):
        for klass in LIVE_CLASSES:
            self.assertEqual(
                resolve_school_division(klass.name, klass.grade_level, klass.stream),
                EXPECTED_DIVISION[klass.name],
                msg=f'{klass.name} / {klass.grade_level}',
            )

    def test_grade_10_is_not_elementary(self):
        self.assertEqual(
            resolve_school_division('10th', 'Grade 10', 'Grade 10'),
            DIVISION_SENIOR_HIGH,
        )
        self.assertNotEqual(
            resolve_school_division('Grade 10'),
            DIVISION_ELEMENTARY,
        )

    def test_kindergarten_is_not_senior_or_grade_one(self):
        for name, grade in (('ABC', 'Grade ABC'), ('K-1', 'Grade K-1'), ('K-2', 'Grade K-2')):
            self.assertEqual(resolve_school_division(name, grade), DIVISION_KINDERGARTEN)
            self.assertIsNone(parse_grade_number(name, grade))

    def test_wrong_student_level_does_not_override_class(self):
        self.assertEqual(
            resolve_school_division('K-1', 'Grade K-1', 'Senior High'),
            DIVISION_KINDERGARTEN,
        )
        self.assertEqual(
            resolve_school_division('10th', 'Grade 10', 'Elementary'),
            DIVISION_SENIOR_HIGH,
        )

    def test_keyword_only_labels(self):
        self.assertEqual(resolve_school_division('Senior High'), DIVISION_SENIOR_HIGH)
        self.assertEqual(resolve_school_division('Junior High'), DIVISION_JUNIOR_HIGH)
        self.assertEqual(resolve_school_division('Elementary'), DIVISION_ELEMENTARY)
        self.assertEqual(resolve_school_division('Kindergarten'), DIVISION_KINDERGARTEN)

    def test_roman_and_jss_aliases(self):
        self.assertEqual(resolve_school_division('K-I'), DIVISION_KINDERGARTEN)
        self.assertEqual(resolve_school_division('K-II'), DIVISION_KINDERGARTEN)
        self.assertEqual(resolve_school_division('JSS 1'), DIVISION_JUNIOR_HIGH)
        self.assertEqual(resolve_school_division('SSS 3'), DIVISION_SENIOR_HIGH)
        self.assertEqual(parse_grade_number('JSS 1'), 7)
        self.assertEqual(parse_grade_number('SSS 1'), 10)

    def test_sort_puts_kingdoms_in_school_order(self):
        scrambled = list(reversed(LIVE_CLASSES))
        ordered = sort_classes(scrambled)
        self.assertEqual(
            [klass.name for klass in ordered],
            ['ABC', 'K-1', 'K-2', '1st', '2nd', '3rd', '4th', '5th', '6th',
             '7th', '8th', '9th', '10th', '11th', '12'],
        )
        # String sort of grade_level is exactly the bug: Grade 10 before Grade 1st,
        # ABC/K-1/K-2 after Grade 9.
        string_sorted = sorted(LIVE_CLASSES, key=lambda k: (k.grade_level, k.name))
        self.assertEqual(string_sorted[0].name, '10th')
        self.assertEqual(string_sorted[-1].name, 'K-2')

    def test_class_sort_key_stable_for_grade_ten_vs_first(self):
        tenth = class_sort_key('10th', 'Grade 10')
        first = class_sort_key('1st', 'Grade 1st')
        self.assertLess(first, tenth)

    def test_canonical_dropdown_values(self):
        self.assertEqual(canonical_grade_value('Grade 10'), '10th')
        self.assertEqual(canonical_grade_value('Grade 1st'), '1st')
        self.assertEqual(canonical_grade_value('Grade K-1'), 'K-1')
        self.assertEqual(canonical_grade_value('Grade ABC'), 'ABC')
        self.assertEqual(canonical_grade_value('GRade 12'), '12')
        self.assertEqual(coerce_grade_level_choice('Grade 6'), '6th')

    def test_document_titles(self):
        self.assertEqual(
            division_document_titles(DIVISION_SENIOR_HIGH, 'sheet'),
            'Senior High Grade Sheet',
        )
        self.assertEqual(
            division_document_titles(DIVISION_KINDERGARTEN, 'report'),
            'Kindergarten Division Report Card',
        )
        self.assertEqual(
            division_document_titles(DIVISION_ELEMENTARY, 'record'),
            'Elementary Division Academic Performance Record',
        )
        self.assertEqual(
            division_document_titles(DIVISION_JUNIOR_HIGH, 'report'),
            'Junior High Report Card',
        )

    def test_document_copy_matches_division(self):
        self.assertEqual(division_subject_heading(DIVISION_KINDERGARTEN), 'SUBJECTS')
        self.assertEqual(division_subject_heading(DIVISION_SENIOR_HIGH), 'SUBJECTS')
        self.assertEqual(division_score_remark(65, DIVISION_KINDERGARTEN), 'Needs Support')
        self.assertEqual(division_score_remark(65, DIVISION_SENIOR_HIGH), 'Failure')
        self.assertEqual(division_legend_rows(DIVISION_KINDERGARTEN)[-1][0], 'Needs Support')
        self.assertEqual(next_canonical_grade('K-1', 'Grade K-1'), 'K-2')
        self.assertEqual(next_canonical_grade('K-2', 'Grade K-2'), '1st')
        self.assertEqual(next_canonical_grade('6th', 'Grade 6'), '7th')
        self.assertEqual(next_canonical_grade('9th', 'Grade 9'), '10th')
        self.assertEqual(next_canonical_grade('12', 'Grade 12'), 'Graduation')

    def test_live_classes_get_their_division_subject_catalog(self):
        expected_catalog = {
            DIVISION_KINDERGARTEN: REPORT_CARD_SUBJECTS['kindergarten'],
            DIVISION_ELEMENTARY: REPORT_CARD_SUBJECTS['elementary'],
            DIVISION_JUNIOR_HIGH: REPORT_CARD_SUBJECTS['junior'],
            DIVISION_SENIOR_HIGH: REPORT_CARD_SUBJECTS['senior'],
        }
        for klass in LIVE_CLASSES:
            division = division_for_class(klass)
            self.assertEqual(division, resolve_from_class(klass))
            catalog = subjects_for_class(klass)
            self.assertEqual(catalog, expected_catalog[division], msg=klass.name)
            self.assertNotIn(AVERAGE_ROW_NAME, catalog)
            self.assertNotIn(CONDUCT_ROW_NAME, catalog)

    def test_division_catalogs_are_not_mixed(self):
        self.assertNotIn('Chemistry', REPORT_CARD_SUBJECTS['kindergarten'])
        self.assertNotIn('Drawing', REPORT_CARD_SUBJECTS['elementary'])
        self.assertNotIn('Bible', REPORT_CARD_SUBJECTS['junior'])
        self.assertNotIn('Spelling', REPORT_CARD_SUBJECTS['senior'])
        self.assertIn('Alph. Writing', REPORT_CARD_SUBJECTS['kindergarten'])
        self.assertIn('Hand Writing', REPORT_CARD_SUBJECTS['elementary'])
        self.assertIn('Phon. /O. Eng', REPORT_CARD_SUBJECTS['junior'])
        self.assertIn('R.O.T.C', REPORT_CARD_SUBJECTS['senior'])

    def test_subject_slug_collapses_aliases(self):
        self.assertEqual(subject_slug('P. Education'), subject_slug('PE'))
        self.assertEqual(subject_slug('Comp. Science'), subject_slug('ICT'))
        self.assertEqual(subject_slug('Gen. Science'), subject_slug('General Science'))
        self.assertEqual(subject_slug('RE/ Education'), subject_slug('Religious Education'))


if __name__ == '__main__':
    unittest.main()
