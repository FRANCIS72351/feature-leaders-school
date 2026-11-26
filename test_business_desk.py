"""Business Manager desk is isolated from academic grading."""
import unittest
import uuid

from app import app
from models import User, db


class BusinessDeskIsolationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        self.token = uuid.uuid4().hex[:8]
        self.client = self.app.test_client()
        self.user_ids = []
        with self.app.app_context():
            business = User(
                email=f'bursar-{self.token}@test.com',
                full_name='School Bursar',
                role='business',
            )
            business.set_password('password')
            db.session.add(business)
            db.session.flush()
            self.user_ids.append(business.id)
            self.business_id = business.id
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            for user_id in self.user_ids:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.business_id)
            sess['_fresh'] = True

    def test_business_opens_command_desk(self):
        self._login()
        page = self.client.get('/business/dashboard')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('Command desk', html)
        self.assertIn('Procurement', html)
        self.assertIn('Support staff', html)

    def test_business_cannot_open_grade_releases(self):
        self._login()
        page = self.client.get('/vpa/grade-releases', follow_redirects=False)
        self.assertIn(page.status_code, (302, 303))
        self.assertIn('/business/dashboard', page.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
