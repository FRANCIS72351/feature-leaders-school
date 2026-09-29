"""Proprietor audit trail: proprietor-only desk, login history, and activity records."""
import unittest
import uuid

from app import app, log_activity, ensure_audit_logs_table
from models import AuditLog, User, db


class ProprietorAuditTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        self.token = uuid.uuid4().hex[:8]
        self.created_users = []
        self.created_logs = []
        self.client = self.app.test_client()
        with self.app.app_context():
            ensure_audit_logs_table()
            self.proprietor_id = self._make_user('proprietor', 'School Proprietor')
            self.owner_id = self._make_user('owner', 'Campus Owner')
            self.admin_id = self._make_user('admin', 'System Admin')
            self.vpa_id = self._make_user('vpa', 'Vice Principal Academics')
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
        self.created_users.append(user.id)
        return user.id

    def tearDown(self):
        with self.app.app_context():
            if self.created_users:
                AuditLog.query.filter(AuditLog.user_id.in_(self.created_users)).delete(
                    synchronize_session=False
                )
            if self.created_logs:
                AuditLog.query.filter(AuditLog.id.in_(self.created_logs)).delete(
                    synchronize_session=False
                )
            for user_id in self.created_users:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_proprietor_and_owner_can_open_audit_desk(self):
        for actor in (self.proprietor_id, self.owner_id):
            self._login(actor)
            page = self.client.get('/proprietor/audit-logs')
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Proprietor only', page.data)
            self.assertIn(b'Live activity audit trail', page.data)
            pulse = self.client.get('/proprietor/audit-logs.json')
            self.assertEqual(pulse.status_code, 200)
            payload = pulse.get_json()
            self.assertIn('logs', payload)

    def test_admin_and_vpa_cannot_open_audit_desk(self):
        for actor in (self.admin_id, self.vpa_id):
            self._login(actor)
            page = self.client.get('/proprietor/audit-logs', follow_redirects=False)
            self.assertIn(page.status_code, (302, 303))
            pulse = self.client.get('/proprietor/audit-logs.json', follow_redirects=False)
            self.assertIn(pulse.status_code, (302, 303))

    def test_successful_login_writes_user_login(self):
        with self.app.app_context():
            user = db.session.get(User, self.proprietor_id)
            email = user.email
        response = self.client.post(
            '/login',
            data={'email': email, 'password': 'password'},
            follow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        with self.app.app_context():
            row = (
                AuditLog.query
                .filter_by(user_id=self.proprietor_id, action='USER_LOGIN')
                .order_by(AuditLog.id.desc())
                .first()
            )
            self.assertIsNotNone(row)
            self.assertEqual(row.user_role, 'proprietor')
            self.created_logs.append(row.id)

    def test_log_activity_records_actor_and_details(self):
        with self.app.app_context():
            user = db.session.get(User, self.proprietor_id)
            entry = log_activity(
                'UPDATE_GRADE',
                'Updated Grade 3 Math from 70 to 88',
                user=user,
                commit=True,
            )
            self.assertIsNotNone(entry)
            self.created_logs.append(entry.id)
            saved = db.session.get(AuditLog, entry.id)
            self.assertEqual(saved.action, 'UPDATE_GRADE')
            self.assertIn('70 to 88', saved.details)
            self.assertEqual(saved.user_name, 'School Proprietor')
            self.assertEqual(saved.user_role, 'proprietor')


if __name__ == '__main__':
    unittest.main()
