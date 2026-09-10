"""Public homepage, about, and contact copy."""
import unittest

from app import app
from school_divisions import SCHOOL_PRINT_EMAIL_ADDRESS, SCHOOL_PRINT_NAME


class PublicPagesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()

    def test_home_uses_school_language(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(SCHOOL_PRINT_NAME, body)
        self.assertIn('Learn About the Academy', body)
        self.assertIn('Upcoming School Calendar', body)
        self.assertNotIn('Analyze Product Matrix', body)
        self.assertNotIn('See Event Parameters', body)
        self.assertNotIn('Feature Leaders', body)

    def test_about_page_introduces_the_school(self):
        response = self.client.get('/about')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('Who We Are', body)
        self.assertIn('Our Leadership', body)
        self.assertNotIn('Executive Administrative Matrix', body)
        self.assertNotIn('Secure Routing Email', body)

    def test_contact_shows_official_school_email(self):
        response = self.client.get('/contact')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(SCHOOL_PRINT_EMAIL_ADDRESS, body)
        self.assertIn('Send a Message', body)
        self.assertNotIn('xhangocharm@gmail.com', body)
        self.assertNotIn('Send Support Ticket', body)

    def test_contact_form_requires_all_fields(self):
        response = self.client.post('/contact', data={
            'name': 'Parent',
            'email': 'parent@example.com',
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Please complete every field', response.get_data(as_text=True))

    def test_contact_form_accepts_a_complete_message(self):
        response = self.client.post('/contact', data={
            'name': 'Parent Example',
            'email': 'parent@example.com',
            'subject': 'Admissions',
            'message': 'When does the next entrance exam take place?',
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('Thank you. The academy has your message.', body)
        self.assertIn(SCHOOL_PRINT_EMAIL_ADDRESS, body)

    def test_login_page_title(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Sign In', response.get_data(as_text=True))

    def test_footer_uses_leaders_tagline(self):
        response = self.client.get('/')
        body = response.get_data(as_text=True)
        self.assertIn('Empowering the next generation of leaders.', body)
        self.assertNotIn('Next Generation of Systems', body)
