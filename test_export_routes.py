import unittest
import uuid
from datetime import date

from app import app
from constants import ROLE_ADMIN
from models import AcademicYear, Class, Student, User, db


class ExportRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.test_email = f'export-test-{uuid.uuid4().hex}@test.com'
        self.created_ids = {'users': [], 'classes': [], 'years': [], 'students': []}
        self.client = self.app.test_client()
        with self.app.app_context():
            AcademicYear.query.filter_by(is_active=True).update(
                {AcademicYear.is_active: False},
                synchronize_session=False,
            )
            db.session.commit()

            admin = User(email=self.test_email, full_name='Admin User', role=ROLE_ADMIN)
            admin.set_password('password')
            db.session.add(admin)
            db.session.flush()
            self.created_ids['users'].append(admin.id)
            self.admin_id = admin.id

            test_class = Class(name=f'Export Test {uuid.uuid4().hex[:8]}', grade_level=10)
            db.session.add(test_class)
            db.session.flush()
            self.created_ids['classes'].append(test_class.id)

            test_year = AcademicYear(
                name=f'20{uuid.uuid4().hex[:2]}-20{uuid.uuid4().hex[:2]}',
                start_date=date(2025, 1, 1),
                end_date=date(2026, 1, 1),
                is_active=True,
                created_by=admin.id,
            )
            db.session.add(test_year)
            db.session.flush()
            self.created_ids['years'].append(test_year.id)

            student = Student(
                student_id=f'EXP{uuid.uuid4().hex[:6].upper()}',
                first_name='Test',
                last_name='Student',
                dob=date(2005, 1, 1),
                gender='M',
                klass_id=test_class.id,
                academic_year_id=test_year.id,
            )
            db.session.add(student)
            db.session.flush()
            self.created_ids['students'].append(student.id)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            for student_id in self.created_ids['students']:
                Student.query.filter_by(id=student_id).delete(synchronize_session=False)
            for year_id in self.created_ids['years']:
                AcademicYear.query.filter_by(id=year_id).delete(synchronize_session=False)
            for class_id in self.created_ids['classes']:
                Class.query.filter_by(id=class_id).delete(synchronize_session=False)
            for user_id in self.created_ids['users']:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['_fresh'] = True

    def test_export_students_csv(self):
        self.login()
        response = self.client.get('/export/students')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Student ID,First Name,Last Name', response.data)
        self.assertIn(b'Test', response.data)
        self.assertIn(b'Student', response.data)


if __name__ == '__main__':
    unittest.main()
