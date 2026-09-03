import unittest
import uuid
from datetime import date

from app import app
from constants import ROLE_REGISTRAR, ROLE_TEACHER
from models import AcademicYear, Class, Student, User, db


class RegistrarCredentialSlipTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.unique = uuid.uuid4().hex[:8]
        self.created = {
            'users': [],
            'students': [],
            'classes': [],
            'years': [],
        }

        with self.app.app_context():
            registrar = User(
                email=f'registrar-slip-{self.unique}@test.com',
                full_name='Slip Test Registrar',
                role=ROLE_REGISTRAR,
            )
            registrar.set_password('password')
            teacher = User(
                email=f'teacher-slip-{self.unique}@test.com',
                full_name='Slip Test Teacher',
                role=ROLE_TEACHER,
            )
            teacher.set_password('password')
            db.session.add_all([registrar, teacher])
            db.session.flush()
            self.registrar_id = registrar.id
            self.teacher_id = teacher.id
            self.created['users'].extend([registrar.id, teacher.id])

            klass = Class(
                name=f'Slip Class {self.unique}',
                grade_level='6th',
            )
            db.session.add(klass)
            db.session.flush()
            self.class_id = klass.id
            self.created['classes'].append(klass.id)

            year = AcademicYear(
                name=f'20{self.unique[:2]}-20{self.unique[2:4]}',
                start_date=date(2098, 9, 1),
                end_date=date(2099, 6, 30),
                is_active=False,
                created_by=registrar.id,
            )
            db.session.add(year)
            db.session.flush()
            self.year_id = year.id
            self.created['years'].append(year.id)

            self.student_code = f'99{self.unique[:2]}-{self.unique[2:]}'
            self.portal_email = f'slip-student-{self.unique}@test.com'
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.rollback()
            leftover = Student.query.filter(
                (Student.student_id == self.student_code)
                | (Student.id.in_(self.created['students'] or [0]))
            ).all()
            portal_ids = [row.user_id for row in leftover if row.user_id]
            for row in leftover:
                db.session.delete(row)
            db.session.flush()
            portal = User.query.filter_by(email=self.portal_email).first()
            if portal:
                portal_ids.append(portal.id)
            for user_id in dict.fromkeys(portal_ids):
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            for year_id in self.created['years']:
                AcademicYear.query.filter_by(id=year_id).delete(synchronize_session=False)
            for class_id in self.created['classes']:
                Class.query.filter_by(id=class_id).delete(synchronize_session=False)
            db.session.flush()
            for user_id in dict.fromkeys(self.created['users']):
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def _registration_payload(self, password=''):
        return {
            'first_name': 'Slip',
            'last_name': 'Student',
            'email': self.portal_email,
            'password': password,
            'confirm_password': password,
            'dob': '2012-05-01',
            'gender': 'Male',
            'level': 'Elementary',
            'student_id': self.student_code,
            'klass': str(self.class_id),
            'academic_year': str(self.year_id),
            'registration_fees': '0.00',
            'registration_payment_status': 'unpaid',
            'is_returning': '',
        }

    def test_register_creates_portal_user_and_slip_is_registrar_only(self):
        self._login(self.registrar_id)
        response = self.client.post(
            '/register-student',
            data=self._registration_payload(),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:800])
        location = response.headers.get('Location', '')
        self.assertIn('/credential-slip', location)
        self.assertNotIn('pwd=', location.lower())
        self.assertNotIn('password=', location.lower())

        with self.app.app_context():
            student = Student.query.filter_by(student_id=self.student_code).first()
            self.assertIsNotNone(student)
            self.created['students'].append(student.id)
            self.assertIsNotNone(student.user_id)
            portal = db.session.get(User, student.user_id)
            self.assertIsNotNone(portal)
            self.assertEqual((portal.role or '').lower(), 'student')
            self.assertTrue(portal.must_change_password)
            self.assertEqual(portal.username, self.student_code)
            self.assertEqual(portal.email, self.portal_email)
            self.assertFalse(portal.check_password('student123'))
            student_pk = student.id

        slip = self.client.get(f'/registrar/students/{student_pk}/credential-slip')
        self.assertEqual(slip.status_code, 200)
        body = slip.get_data(as_text=True)
        self.assertIn('Student Portal Credential Slip', body)
        self.assertIn(self.student_code, body)
        self.assertIn(self.portal_email, body)
        self.assertNotIn('student123', body)
        self.assertIn('You must change this password on first login', body)

        reprint = self.client.get(f'/registrar/students/{student_pk}/credential-slip')
        self.assertEqual(reprint.status_code, 200)
        reprint_body = reprint.get_data(as_text=True)
        self.assertIn('Issued at registration', reprint_body)
        self.assertIn('Reset from Admin', reprint_body)

        self._login(self.teacher_id)
        denied = self.client.get(
            f'/registrar/students/{student_pk}/credential-slip',
            follow_redirects=True,
        )
        self.assertEqual(denied.status_code, 200)
        self.assertIn(b'Unauthorized access', denied.data)

    def test_custom_initial_password_shown_once_from_session(self):
        custom = 'SafePass9'
        self._login(self.registrar_id)
        response = self.client.post(
            '/register-student',
            data=self._registration_payload(password=custom),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:800])
        location = response.headers.get('Location', '')
        self.assertIn('/credential-slip', location)
        self.assertNotIn(custom, location)

        with self.app.app_context():
            student = Student.query.filter_by(student_id=self.student_code).first()
            self.assertIsNotNone(student)
            self.created['students'].append(student.id)
            portal = db.session.get(User, student.user_id)
            self.assertTrue(portal.must_change_password)
            self.assertTrue(portal.check_password(custom))
            student_pk = student.id

        slip = self.client.get(f'/registrar/students/{student_pk}/credential-slip')
        self.assertEqual(slip.status_code, 200)
        self.assertIn(custom.encode(), slip.data)

        reprint = self.client.get(f'/registrar/students/{student_pk}/credential-slip')
        self.assertNotIn(custom.encode(), reprint.data)
        self.assertIn(b'Issued at registration', reprint.data)


if __name__ == '__main__':
    unittest.main()
