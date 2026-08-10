import unittest
import uuid

from app import app
from constants import ROLE_ADMIN
from models import User, db


class AdminUserEditTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.created_user_ids = []
        self.unique = uuid.uuid4().hex[:8]

        with self.app.app_context():
            admin = User(
                email=f'admin-edit-{self.unique}@test.com',
                full_name='Edit Test Admin',
                role=ROLE_ADMIN,
            )
            admin.set_password('password')
            db.session.add(admin)
            db.session.flush()
            self.admin_id = admin.id
            self.created_user_ids.append(admin.id)

            principal = User(
                email=f'principal-edit-{self.unique}@test.com',
                full_name='Edit Test Principal',
                role='principal',
            )
            principal.set_password('password')
            db.session.add(principal)
            db.session.flush()
            self.principal_id = principal.id
            self.created_user_ids.append(principal.id)

            target = User(
                email=f'target-edit-{self.unique}@test.com',
                full_name='Target User',
                role='teacher',
                username=f'target_{self.unique}',
            )
            target.set_password('oldpassword')
            db.session.add(target)
            db.session.flush()
            self.target_id = target.id
            self.created_user_ids.append(target.id)

            teacher = User(
                email=f'teacher-edit-{self.unique}@test.com',
                full_name='Edit Test Teacher',
                role='teacher',
            )
            teacher.set_password('password')
            db.session.add(teacher)
            db.session.flush()
            self.teacher_id = teacher.id
            self.created_user_ids.append(teacher.id)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            for user_id in self.created_user_ids:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_admin_can_view_edit_page(self):
        self._login(self.admin_id)
        response = self.client.get(f'/admin/users/{self.target_id}/edit')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Target User', response.data)

    def test_business_dashboard_renders_for_admin(self):
        self._login(self.admin_id)
        response = self.client.get('/business/dashboard')
        self.assertEqual(response.status_code, 200)

    def test_principal_can_edit_user(self):
        self._login(self.principal_id)
        response = self.client.post(
            f'/admin/users/{self.target_id}/edit',
            data={
                'email': f'updated-{self.unique}@test.com',
                'username': f'updated_{self.unique}',
                'full_name': 'Updated Target',
                'role': 'registrar',
                'home_address': '',
                'telephone_number': '',
                'password': '',
                'submit': 'Save Changes',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'updated successfully', response.data)

        with self.app.app_context():
            user = db.session.get(User, self.target_id)
            self.assertEqual(user.full_name, 'Updated Target')
            self.assertEqual(user.role, 'registrar')
            self.assertTrue(user.check_password('oldpassword'))

    def test_admin_can_change_password(self):
        self._login(self.admin_id)
        response = self.client.post(
            f'/admin/users/{self.target_id}/edit',
            data={
                'email': f'target-edit-{self.unique}@test.com',
                'username': f'target_{self.unique}',
                'full_name': 'Target User',
                'role': 'teacher',
                'home_address': '',
                'telephone_number': '',
                'password': 'newpassword123',
                'submit': 'Save Changes',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            user = db.session.get(User, self.target_id)
            self.assertTrue(user.check_password('newpassword123'))

    def test_teacher_cannot_edit_user(self):
        self._login(self.teacher_id)
        response = self.client.get(f'/admin/users/{self.target_id}/edit', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Unauthorized access', response.data)

    def test_duplicate_email_rejected(self):
        self._login(self.admin_id)
        response = self.client.post(
            f'/admin/users/{self.target_id}/edit',
            data={
                'email': f'principal-edit-{self.unique}@test.com',
                'username': f'target_{self.unique}',
                'full_name': 'Target User',
                'role': 'teacher',
                'home_address': '',
                'telephone_number': '',
                'password': '',
                'submit': 'Save Changes',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'email is already assigned', response.data)

    def test_admin_cannot_demote_own_role(self):
        self._login(self.admin_id)
        response = self.client.post(
            f'/admin/users/{self.admin_id}/edit',
            data={
                'email': f'admin-edit-{self.unique}@test.com',
                'username': '',
                'full_name': 'Edit Test Admin',
                'role': 'teacher',
                'home_address': '',
                'telephone_number': '',
                'password': '',
                'submit': 'Save Changes',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'cannot change your own role', response.data)


if __name__ == '__main__':
    unittest.main()
