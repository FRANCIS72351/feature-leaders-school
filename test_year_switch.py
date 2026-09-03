import unittest
import uuid
from datetime import date

from app import (
    REGISTRAR_YEAR_SESSION_KEY,
    adjacent_academic_years,
    app,
    resolve_dashboard_academic_year,
)
from constants import ROLE_REGISTRAR
from models import AcademicYear, Class, Student, User, db


class RegistrarYearSwitchTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.token = uuid.uuid4().hex[:8]
        self.created = {'users': [], 'classes': [], 'years': [], 'students': []}
        self.prior_active_year_ids = []
        self.client = self.app.test_client()
        with self.app.app_context():
            self.prior_active_year_ids = [
                y.id for y in AcademicYear.query.filter_by(is_active=True).all()
            ]
            AcademicYear.query.filter_by(is_active=True).update(
                {AcademicYear.is_active: False},
                synchronize_session=False,
            )

            registrar = User(
                email=f'registrar-{self.token}@test.com',
                full_name='Year Switch Registrar',
                role=ROLE_REGISTRAR,
            )
            registrar.set_password('password')
            db.session.add(registrar)
            db.session.flush()
            self.created['users'].append(registrar.id)
            self.registrar_id = registrar.id

            klass = Class(name=f'Switch Class {self.token}', grade_level=10)
            db.session.add(klass)
            db.session.flush()
            self.created['classes'].append(klass.id)
            self.class_id = klass.id

            self.prior_year_name = f'YS{self.token}-25-26'
            self.current_year_name = f'YS{self.token}-26-27'
            prior_year = AcademicYear(
                name=self.prior_year_name,
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=False,
                created_by=registrar.id,
            )
            current_year = AcademicYear(
                name=self.current_year_name,
                start_date=date(2026, 9, 1),
                end_date=date(2027, 6, 30),
                is_active=True,
                created_by=registrar.id,
            )
            db.session.add_all([prior_year, current_year])
            db.session.flush()
            self.created['years'].extend([prior_year.id, current_year.id])
            self.prior_year_id = prior_year.id
            self.current_year_id = current_year.id

            prior_student = Student(
                student_id=f'YS{self.token}A',
                first_name='Prior',
                last_name='Enrollee',
                dob=date(2008, 1, 1),
                gender='F',
                klass_id=klass.id,
                grade_level=10,
                academic_year_id=prior_year.id,
                status='ACTIVE',
                is_registered=True,
            )
            current_student = Student(
                student_id=f'YS{self.token}B',
                first_name='Current',
                last_name='Enrollee',
                dob=date(2009, 1, 1),
                gender='M',
                klass_id=klass.id,
                grade_level=10,
                academic_year_id=current_year.id,
                status='ACTIVE',
                is_registered=True,
            )
            db.session.add_all([prior_student, current_student])
            db.session.flush()
            self.created['students'].extend([prior_student.id, current_student.id])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            for student_id in self.created['students']:
                Student.query.filter_by(id=student_id).delete(synchronize_session=False)
            for year_id in self.created['years']:
                AcademicYear.query.filter_by(id=year_id).delete(synchronize_session=False)
            for class_id in self.created['classes']:
                Class.query.filter_by(id=class_id).delete(synchronize_session=False)
            for user_id in self.created['users']:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            if self.prior_active_year_ids:
                AcademicYear.query.filter(AcademicYear.id.in_(self.prior_active_year_ids)).update(
                    {AcademicYear.is_active: True},
                    synchronize_session=False,
                )
            db.session.commit()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.registrar_id)
            sess['_fresh'] = True

    def test_session_keeps_archived_year_without_query_param(self):
        with self.app.test_request_context('/registrar/dashboard'):
            from flask import session
            session.clear()
            session[REGISTRAR_YEAR_SESSION_KEY] = self.prior_year_id
            display, active, years, viewing_archived = resolve_dashboard_academic_year(
                session_key=REGISTRAR_YEAR_SESSION_KEY,
            )
            self.assertIsNotNone(display)
            self.assertEqual(display.id, self.prior_year_id)
            self.assertTrue(viewing_archived)
            self.assertEqual(active.id, self.current_year_id)
            self.assertGreaterEqual(len(years), 2)
            scoped = [year for year in years if year.id in (self.prior_year_id, self.current_year_id)]
            older, newer = adjacent_academic_years(display, scoped)
            self.assertIsNone(older)
            self.assertIsNotNone(newer)
            self.assertEqual(newer.id, self.current_year_id)

    def test_registrar_can_switch_years_and_persist(self):
        self.login()
        first = self.client.get(
            f'/registrar/dashboard?academic_year_id={self.prior_year_id}',
            follow_redirects=True,
        )
        self.assertEqual(first.status_code, 200)
        html = first.get_data(as_text=True)
        self.assertIn('name="academic_year_id"', html)
        self.assertIn(self.prior_year_name, html)
        self.assertIn(self.current_year_name, html)
        self.assertIn('Prior Enrollee', html)
        self.assertNotIn('Current Enrollee', html)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get(REGISTRAR_YEAR_SESSION_KEY), self.prior_year_id)

        persisted = self.client.get('/registrar/dashboard', follow_redirects=True)
        self.assertEqual(persisted.status_code, 200)
        persisted_html = persisted.get_data(as_text=True)
        self.assertIn(f'Viewing: {self.prior_year_name}', persisted_html)
        self.assertIn('Prior Enrollee', persisted_html)
        self.assertNotIn('Current Enrollee', persisted_html)

        back = self.client.get(
            f'/registrar/dashboard?academic_year_id={self.current_year_id}',
            follow_redirects=True,
        )
        self.assertEqual(back.status_code, 200)
        back_html = back.get_data(as_text=True)
        self.assertIn(f'Viewing: {self.current_year_name}', back_html)
        self.assertIn('Current Enrollee', back_html)
        self.assertNotIn('Prior Enrollee', back_html)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get(REGISTRAR_YEAR_SESSION_KEY), self.current_year_id)


if __name__ == '__main__':
    unittest.main()
