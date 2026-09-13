"""School division mapping — no student PII, no database required."""
import unittest

from school_divisions import (
    AVERAGE_ROW_NAME,
    CONDUCT_ROW_NAME,
    DIVISION_ELEMENTARY,
    DIVISION_JUNIOR_HIGH,
    DIVISION_KINDERGARTEN,
    DIVISION_SENIOR_HIGH,
    academic_level_for_student,
    REPORT_CARD_SUBJECTS,
    canonical_grade_value,
    canonical_subject_name,
    class_sort_key,
    coerce_grade_level_choice,
    division_document_titles,
    division_for_class,
    division_legend_rows,
    division_score_remark,
    division_subject_heading,
    format_academic_year_label,
    next_academic_year_label,
    next_canonical_grade,
    normalize_academic_year_name,
    parse_academic_year_span,
    parse_grade_number,
    official_subject_score_row,
    official_average_row,
    official_conduct_row,
    report_card_footer_rows,
    report_card_subject_names,
    numeric_report_score,
    resolve_from_class,
    resolve_school_division,
    sort_classes,
    subject_match_key,
    subject_slug,
    subjects_for_class,
    build_transcript_grade_groups,
    transcript_conduct_label,
    transcript_grade_heading,
    transcript_promotion_fields,
    grade_document_signatories,
    school_print_brand,
    SCHOOL_PRINT_VPI_NAME,
    SCHOOL_PRINT_VPA_TITLE,
    SCHOOL_PRINT_VPI_TITLE,
    SCHOOL_PRINT_SPONSOR_TITLE,
    SCHOOL_PRINT_PRINCIPAL_TITLE,
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

    def test_academic_level_comes_from_assigned_class(self):
        class _Student:
            assigned_class = _FakeClass('8th', 'Grade 8', 'Grade 8')
            klass = assigned_class
            level = ''
            grade_level = None

        self.assertEqual(academic_level_for_student(_Student()), 'Junior High')

        class _StaleLevel:
            assigned_class = _FakeClass('4th', 'Grade 4th', 'Grade 4th')
            klass = assigned_class
            level = 'Senior High'
            grade_level = 'Grade 4th'

        self.assertEqual(academic_level_for_student(_StaleLevel()), 'Elementary')

        class _NoClass:
            assigned_class = None
            klass = None
            level = 'Junior High'
            grade_level = None

        self.assertEqual(academic_level_for_student(_NoClass()), 'Junior High')

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
        self.assertEqual(next_canonical_grade('12th', 'Grade 12th'), 'Graduation')
        self.assertEqual(parse_grade_number('12th', 'Grade 12'), 12)
        self.assertEqual(parse_grade_number('10th Grade 2040'), 10)
        self.assertIsNone(parse_grade_number('13th'))
        self.assertIsNone(parse_grade_number('Class of 2036'))

    def test_academic_year_span_survives_decade_and_century_edges(self):
        self.assertEqual(parse_academic_year_span('2035-2036'), (2035, 2036))
        self.assertEqual(parse_academic_year_span('2035–36'), (2035, 2036))
        self.assertEqual(parse_academic_year_span('2040/2041 Academic Year'), (2040, 2041))
        self.assertEqual(parse_academic_year_span('35-36'), (2035, 2036))
        self.assertEqual(parse_academic_year_span('2099-00'), (2099, 2100))
        self.assertEqual(parse_academic_year_span('2099—2100'), (2099, 2100))
        self.assertEqual(next_academic_year_label('2035–2036'), '2036-2037')
        self.assertEqual(next_academic_year_label('2099/00'), '2100-2101')
        self.assertEqual(format_academic_year_label('2035–36'), '2035/2036')
        self.assertEqual(format_academic_year_label('2099-00'), '2099/2100')
        self.assertEqual(normalize_academic_year_name('2040 – 2041'), '2040-2041')
        self.assertIsNone(parse_academic_year_span('Fall Session'))

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
        self.assertEqual(subject_slug('RE/ Education'), subject_slug('RE/Education'))
        self.assertEqual(subject_slug('RE/ Education'), subject_slug('R.E. Education'))

    def test_subject_canonicalization_accepts_unambiguous_typo(self):
        self.assertEqual(
            canonical_subject_name('RE Educaton', DIVISION_JUNIOR_HIGH),
            'RE/ Education',
        )
        self.assertIsNone(
            canonical_subject_name('Science', DIVISION_JUNIOR_HIGH),
        )

    def test_comp_science_punctuation_variants_merge(self):
        self.assertEqual(
            subject_match_key('Comp. Science'),
            subject_match_key('Comp.Science'),
        )
        self.assertEqual(
            canonical_subject_name('Comp.Science', DIVISION_JUNIOR_HIGH),
            'Comp. Science',
        )
        self.assertEqual(division_score_remark(88, DIVISION_JUNIOR_HIGH), 'Good')
        self.assertEqual(division_score_remark(72, DIVISION_JUNIOR_HIGH), 'Fair')
        self.assertEqual(division_score_remark(69, DIVISION_JUNIOR_HIGH), 'Failure')

    def test_report_card_names_end_with_average_and_conduct(self):
        names = report_card_subject_names(DIVISION_SENIOR_HIGH)
        self.assertEqual(names[-2], AVERAGE_ROW_NAME)
        self.assertEqual(names[-1], CONDUCT_ROW_NAME)
        self.assertNotIn(AVERAGE_ROW_NAME, names[:-2])
        self.assertNotIn(CONDUCT_ROW_NAME, names[:-2])

    def test_average_row_means_each_column_and_yearly_percent(self):
        math = official_subject_score_row('Mathematics', {1: 80, 2: 90, 7: 70})
        english = official_subject_score_row('English', {1: 70, 2: 80, 7: 60})
        conduct = official_conduct_row({1: 100, 2: 100})
        average = official_average_row([math, english, conduct])
        self.assertEqual(average['name'], AVERAGE_ROW_NAME)
        self.assertTrue(average['is_summary'])
        self.assertEqual(average['p1'], 75)
        self.assertEqual(average['p2'], 85)
        self.assertEqual(average['exam'], 65)
        self.assertEqual(average['final_avg'], '75.00%')
        self.assertEqual(average['remark'], '')

    def test_conduct_row_exists_blank_without_scores(self):
        blank = official_conduct_row()
        self.assertEqual(blank['name'], CONDUCT_ROW_NAME)
        self.assertTrue(blank['is_summary'])
        self.assertEqual(blank['p1'], '')
        self.assertEqual(blank['final_avg'], '')
        filled = official_conduct_row({1: 88, 2: 92})
        self.assertEqual(filled['p1'], 88)
        self.assertEqual(filled['p2'], 92)
        self.assertEqual(filled['remark'], '')

    def test_footer_rows_are_always_average_then_conduct(self):
        footers = report_card_footer_rows([])
        self.assertEqual(len(footers), 2)
        self.assertEqual(footers[0]['name'], AVERAGE_ROW_NAME)
        self.assertEqual(footers[1]['name'], CONDUCT_ROW_NAME)
        self.assertEqual(numeric_report_score('76.71%'), 76.71)

    def test_transcript_groups_senior_paper_slots_and_blank_science(self):
        english = official_subject_score_row('English', {1: 80, 4: 90})
        biology = official_subject_score_row('Biology', {1: 70, 4: 72})
        groups, _average, _conduct = build_transcript_grade_groups(
            [english, biology],
            DIVISION_SENIOR_HIGH,
        )
        labels = [group.get('label') for group in groups]
        self.assertIn('LANGUAGE ARTS', labels)
        self.assertIn('GENERAL SCIENCE', labels)
        science = next(group for group in groups if group['label'] == 'GENERAL SCIENCE')
        names = [row['name'] for row in science['rows']]
        self.assertEqual(names[:3], ['Biology', 'Chemistry', 'Physics'])
        self.assertIn('Health Science', names)
        self.assertIn('Agri. Science', names)
        health = next(row for row in science['rows'] if row['name'] == 'Health Science')
        self.assertEqual(health['yearly'], '')

    def test_transcript_heading_and_summer_school_narrative(self):
        self.assertEqual(transcript_grade_heading('10th'), '(10) Ten')
        self.assertEqual(transcript_conduct_label(80), 'VERY GOOD')
        promoted, conditioned, retained = transcript_promotion_fields(
            {'decision': 'summer_school'},
            '10th',
        )
        self.assertEqual(promoted, 'N/A')
        self.assertEqual(conditioned, '10th')
        self.assertEqual(retained, 'N/A')

    def test_grade_signatories_prefer_named_vpa_over_vpi(self):
        block = grade_document_signatories(
            sponsor_name='Ada Mensah',
            principal_name='Rev. James Kollie',
            vpa_name='Miatta K. VPA',
            vpi_name='Othello B. Gbarjuewaye',
        )
        self.assertEqual(len(block['signatories']), 3)
        sponsor, academic, principal = block['signatories']
        self.assertEqual(sponsor['key'], 'sponsor')
        self.assertEqual(sponsor['name'], 'Ada Mensah')
        self.assertEqual(sponsor['title'], SCHOOL_PRINT_SPONSOR_TITLE)
        self.assertEqual(academic['key'], 'vpa')
        self.assertEqual(academic['name'], 'Miatta K. VPA')
        self.assertEqual(academic['title'], SCHOOL_PRINT_VPA_TITLE)
        self.assertEqual(academic['office'], 'Vice Principal for Academics')
        self.assertEqual(principal['key'], 'principal')
        self.assertEqual(principal['name'], 'Rev. James Kollie')
        self.assertEqual(principal['title'], SCHOOL_PRINT_PRINCIPAL_TITLE)
        self.assertEqual(block['academic_officer_key'], 'vpa')

    def test_grade_signatories_fall_back_to_printed_vpi(self):
        block = grade_document_signatories(
            sponsor_name='Form Teacher',
            principal_name='Head of School',
        )
        academic = block['signatories'][1]
        self.assertEqual(academic['key'], 'vpi')
        self.assertEqual(academic['name'], SCHOOL_PRINT_VPI_NAME)
        self.assertEqual(academic['title'], SCHOOL_PRINT_VPI_TITLE)
        self.assertEqual(block['sponsor_name'], 'Form Teacher')
        self.assertEqual(block['principal_name'], 'Head of School')

    def test_school_print_brand_never_omits_signature_structure(self):
        brand = school_print_brand(sponsor_name='Class Lead', principal_name='Principal Name')
        self.assertEqual(len(brand['signatories']), 3)
        self.assertEqual(brand['signatories'][0]['name'], 'Class Lead')
        self.assertEqual(brand['signatories'][2]['name'], 'Principal Name')
        self.assertEqual(brand['brand_navy'], '#002d62')
        self.assertEqual(brand['brand_gold'], '#c5a572')
        self.assertTrue(brand['academic_officer_name'])


if __name__ == '__main__':
    unittest.main()
