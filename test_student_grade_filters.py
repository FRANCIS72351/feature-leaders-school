import unittest

from app import resolve_listed_subject


class ResolveListedSubjectTests(unittest.TestCase):
    def test_matches_ignoring_case_and_spaces(self):
        names = ['Mathematics', 'English Language', 'Physical Education']
        self.assertEqual(resolve_listed_subject('mathematics', names), 'Mathematics')
        self.assertEqual(
            resolve_listed_subject('English  Language', names),
            'English Language',
        )

    def test_keeps_requested_name_when_not_listed_if_no_fallback(self):
        names = ['Mathematics']
        self.assertEqual(
            resolve_listed_subject('Science', names, fallback_first=False),
            'Science',
        )

    def test_empty_request_uses_first(self):
        names = ['Mathematics', 'English']
        self.assertEqual(resolve_listed_subject('', names), 'Mathematics')


if __name__ == '__main__':
    unittest.main()
