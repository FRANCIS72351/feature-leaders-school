import unittest
import uuid
from datetime import date
from types import SimpleNamespace

from app import (
    app,
    apply_returning_retention_class,
    returning_student_retention_info,
)
from constants import ROLE_REGISTRAR
from models import AcademicYear, Class, Student, User, db


class RegistrarRepeatLookupTestCase(unittest.TestCase):
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
                email=f'registrar-repeat-{self.unique}@test.com',
                full_name='Repeat Test Registrar',
                role=ROLE_REGISTRAR,
            )
            registrar.set_password('password')
            db.session.add(registrar)
            db.session.flush()
            self.registrar_id = registrar.id
            self.created['users'].append(registrar.id)

            klass = Class(
                name=f'Grade 7 Repeat {self.unique}',
                grade_level='7th',
            )
            other = Class(
                name=f'Grade 8 Promo {self.unique}',
                grade_level='8th',
            )
            db.session.add_all([klass, other])
            db.session.flush()
            self.class_id = klass.id
            self.other_class_id = other.id
            self.class_name = klass.name
            self.created['classes'].extend([klass.id, other.id])

            year = AcademicYear(
                name=f'20{self.unique[:2]}-20{self.unique[2:4]}',
                start_date=date(2097, 9, 1),
                end_date=date(2098, 6, 30),
                is_active=False,
                created_by=registrar.id,
            )
            db.session.add(year)
            db.session.flush()
            self.year_id = year.id
            self.created['years'].append(year.id)

            self.repeat_code = f'7701-{int(self.unique[:4], 16) % 90000 + 10000:05d}'
            self.summer_code = f'7702-{int(self.unique[:4], 16) % 90000 + 10000:05d}'
            self.active_code = f'7703-{int(self.unique[:4], 16) % 90000 + 10000:05d}'

            repeater = Student(
                student_id=self.repeat_code,
                first_name='Amina',
                last_name='Repeater',
                dob=date(2012, 3, 4),
                gender='Female',
                klass_id=klass.id,
                grade_level='7th',
                level='Junior High',
                academic_year_id=year.id,
                status='REPEAT',
                registration_type='Returning',
                is_registered=True,
            )
            summer = Student(
                student_id=self.summer_code,
                first_name='Samuel',
                last_name='Summer',
                dob=date(2012, 5, 6),
                gender='Male',
                klass_id=klass.id,
                grade_level='7th',
                level='Junior High',
                academic_year_id=year.id,
                status='SUMMER_SCHOOL',
                registration_type='Returning',
                is_registered=True,
            )
            active = Student(
                student_id=self.active_code,
                first_name='Nora',
                last_name='Promoted',
                dob=date(2012, 7, 8),
                gender='Female',
                klass_id=klass.id,
                grade_level='7th',
                level='Junior High',
                academic_year_id=year.id,
                status='ACTIVE',
                registration_type='Returning',
                is_registered=True,
            )
            db.session.add_all([repeater, summer, active])
            db.session.flush()
            self.repeat_id = repeater.id
            self.summer_id = summer.id
            self.active_id = active.id
            self.created['students'].extend([repeater.id, summer.id, active.id])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.rollback()
            for student_id in self.created['students']:
                Student.query.filter_by(id=student_id).delete(synchronize_session=False)
            db.session.flush()
            for year_id in self.created['years']:
                AcademicYear.query.filter_by(id=year_id).delete(synchronize_session=False)
            for class_id in self.created['classes']:
                Class.query.filter_by(id=class_id).delete(synchronize_session=False)
            db.session.flush()
            for user_id in self.created['users']:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.registrar_id)
            sess['_fresh'] = True

    def test_retention_info_uses_repeat_and_summer_status(self):
        with self.app.app_context():
            repeater = db.session.get(Student, self.repeat_id)
            summer = db.session.get(Student, self.summer_id)
            active = db.session.get(Student, self.active_id)

            repeat_info = returning_student_retention_info(repeater)
            self.assertIsNotNone(repeat_info)
            self.assertEqual(repeat_info['code'], 'REPEAT')
            self.assertEqual(repeat_info['label'], 'Repeat class')
            self.assertTrue(repeat_info['lock_class'])
            self.assertEqual(repeat_info['klass_id'], self.class_id)
            self.assertIn('same grade', repeat_info['message'])
            self.assertNotIn('reparting', repeat_info['message'].lower())

            summer_info = returning_student_retention_info(summer)
            self.assertIsNotNone(summer_info)
            self.assertEqual(summer_info['code'], 'SUMMER_SCHOOL')
            self.assertEqual(summer_info['label'], 'Summer School')

            self.assertIsNone(returning_student_retention_info(active))

    def test_apply_retention_locks_assigned_class(self):
        with self.app.app_context():
            repeater = db.session.get(Student, self.repeat_id)
            form = SimpleNamespace(klass=SimpleNamespace(data=self.other_class_id))
            info = apply_returning_retention_class(repeater, form)
            self.assertEqual(info['code'], 'REPEAT')
            self.assertEqual(form.klass.data, self.class_id)

    def test_lookup_payload_flags_repeat_and_summer(self):
        self._login()
        repeat_resp = self.client.post(
            '/api/registrar/lookup-student',
            json={'student_id': self.repeat_code},
        )
        self.assertEqual(repeat_resp.status_code, 200, repeat_resp.get_data(as_text=True)[:500])
        repeat_data = repeat_resp.get_json()
        self.assertTrue(repeat_data['found'])
        self.assertEqual(repeat_data['promotion_status'], 'REPEAT')
        self.assertEqual(repeat_data['retention']['label'], 'Repeat class')
        self.assertEqual(repeat_data['retention']['klass_id'], self.class_id)
        self.assertTrue(repeat_data['retention']['lock_class'])
        self.assertIn('Repeat class', repeat_data['welcome_message'])
        self.assertIn('not promoted', repeat_data['welcome_message'])

        summer_resp = self.client.post(
            '/api/registrar/lookup-student',
            json={'student_id': self.summer_code},
        )
        self.assertEqual(summer_resp.status_code, 200)
        summer_data = summer_resp.get_json()
        self.assertEqual(summer_data['promotion_status'], 'SUMMER_SCHOOL')
        self.assertEqual(summer_data['retention']['label'], 'Summer School')

        active_resp = self.client.post(
            '/api/registrar/lookup-student',
            json={'student_id': self.active_code},
        )
        self.assertEqual(active_resp.status_code, 200)
        active_data = active_resp.get_json()
        self.assertTrue(active_data['found'])
        self.assertIsNone(active_data.get('retention'))
        self.assertIsNone(active_data.get('promotion_status'))

    def test_student_folder_shows_repeat_class_banner(self):
        self._login()
        response = self.client.get(
            f'/registrar/dashboard?academic_year_id={self.year_id}&search_student=Amina'
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Repeat class', html)
        self.assertIn('They stay in the same grade, not promoted.', html)
        self.assertIn('retention-placement-banner is-repeat', html)
        self.assertIn(self.class_name, html)
        self.assertNotIn('reparting', html.lower())

    def test_student_folder_shows_summer_school_banner(self):
        self._login()
        response = self.client.get(
            f'/registrar/dashboard?academic_year_id={self.year_id}&search_student=Samuel'
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Summer School', html)
        self.assertIn('They stay in the same grade, not promoted.', html)
        self.assertIn('retention-placement-banner is-summer', html)
