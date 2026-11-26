"""Principal office authority is shared with VPI and the School Proprietor."""
import unittest
import uuid

from app import app, PRINCIPAL_COMMAND_ROLES, PRINCIPAL_OFFICE_ROLES
from models import User, db


class PrincipalOfficeShareTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        self.client = self.app.test_client()
        self.token = uuid.uuid4().hex[:8]
        self.created = []
        with self.app.app_context():
            self.vpi_id = self._make_user('vpi', 'VPI Officer')
            self.prop_id = self._make_user('proprietor', 'School Proprietor')
            self.teacher_id = self._make_user('teacher', 'Classroom Teacher')
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            for user_id in self.created:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def _make_user(self, role, name):
        user = User(
            email=f'{role}-{self.token}@test.com',
            full_name=name,
            role=role,
        )
        user.set_password('password')
        db.session.add(user)
        db.session.flush()
        self.created.append(user.id)
        return user.id

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_role_sets_include_vpi_and_proprietor(self):
        self.assertEqual(PRINCIPAL_OFFICE_ROLES, frozenset({'principal', 'vpi', 'proprietor'}))
        self.assertTrue({'admin', 'principal', 'vpi', 'proprietor'} <= PRINCIPAL_COMMAND_ROLES)

    def test_vpi_and_proprietor_open_principal_pages(self):
        pages = (
            '/principal/dashboard',
            '/admin/users',
            '/principal/attendance',
            '/principal/grade-entry',
        )
        for actor in (self.vpi_id, self.prop_id):
            self._login(actor)
            for path in pages:
                response = self.client.get(path, follow_redirects=False)
                self.assertIn(
                    response.status_code,
                    (200, 302),
                    msg=f'{actor} {path} -> {response.status_code}',
                )
                if response.status_code == 302:
                    location = response.headers.get('Location', '')
                    self.assertFalse(
                        location.endswith('/login'),
                        msg=f'{path} sent {actor} to login: {location}',
                    )

    def test_proprietor_cannot_open_admin_dashboard(self):
        self._login(self.prop_id)
        for path in ('/dashboard', '/dashboard?view=admin', '/business/dashboard'):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 302, msg=path)
            self.assertIn('/proprietor/dashboard', response.headers.get('Location', ''), msg=path)

    def test_teacher_still_blocked_from_principal_users(self):
        self._login(self.teacher_id)
        response = self.client.get('/admin/users', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Unauthorized access', response.data)


if __name__ == '__main__':
    unittest.main()
