"""Registrar Target Class dropdown must list real class folders."""
import re
import unittest
import uuid
from datetime import date

from app import (
    app,
    list_assignable_registration_classes,
    registration_class_select_groups,
)
from constants import ROLE_REGISTRAR
from models import AcademicYear, Class, User, db


class RegisterStudentClassChoicesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.unique = uuid.uuid4().hex[:8]
        self.created = {'users': [], 'classes': [], 'years': []}
        self.prior_active_year_ids = []

        with self.app.app_context():
            self.prior_active_year_ids = [
                year.id for year in AcademicYear.query.filter_by(is_active=True).all()
            ]

            registrar = User(
                email=f'registrar-class-choices-{self.unique}@test.com',
                full_name='Class Choices Registrar',
                role=ROLE_REGISTRAR,
            )
            registrar.set_password('password')
            db.session.add(registrar)
            db.session.flush()
            self.registrar_id = registrar.id
            self.created['users'].append(registrar.id)

            kg = Class(
                name=f'ABC {self.unique}',
                grade_level='Grade ABC',
                stream='Grade ABC',
            )
            elementary = Class(
                name=f'3rd {self.unique}',
                grade_level='Grade 3rd',
                stream='Grade 3rd',
            )
            senior = Class(
                name=f'11th {self.unique}',
                grade_level='Grade 11',
                stream='Grade 11',
            )
            db.session.add_all([kg, elementary, senior])
            db.session.flush()
            self.kg_id = kg.id
            self.elementary_id = elementary.id
            self.senior_id = senior.id
            self.kg_name = kg.name
            self.elementary_name = elementary.name
            self.senior_name = senior.name
            self.created['classes'].extend([kg.id, elementary.id, senior.id])

            year = AcademicYear(
                name=f'CC{self.unique}-35-36',
                start_date=date(2035, 9, 1),
                end_date=date(2036, 6, 30),
                is_active=True,
                created_by=registrar.id,
            )
            db.session.add(year)
            db.session.flush()
            self.year_id = year.id
            self.created['years'].append(year.id)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.rollback()
            for year_id in self.created['years']:
                AcademicYear.query.filter_by(id=year_id).delete(synchronize_session=False)
            for class_id in self.created['classes']:
                Class.query.filter_by(id=class_id).delete(synchronize_session=False)
            for user_id in self.created['users']:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            if self.prior_active_year_ids:
                AcademicYear.query.filter(
                    AcademicYear.id.in_(self.prior_active_year_ids)
                ).update(
                    {AcademicYear.is_active: True},
                    synchronize_session=False,
                )
            db.session.commit()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.registrar_id)
            sess['_fresh'] = True

    def _assert_select_has_class(self, html, class_id, class_name):
        class_select = re.search(
            r'<select[^>]*id="class_id"[^>]*>.*?</select>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(class_select, 'Target Class select was not rendered')
        select_html = class_select.group(0)
        self.assertRegex(
            select_html,
            rf'value="{class_id}"',
            f'Class id {class_id} missing from Target Class dropdown',
        )
        self.assertIn(class_name, select_html)

    def test_helper_includes_existing_classes_grouped_by_division(self):
        with self.app.app_context():
            rows = list_assignable_registration_classes()
            ids = {klass.id for klass in rows}
            self.assertIn(self.kg_id, ids)
            self.assertIn(self.elementary_id, ids)
            self.assertIn(self.senior_id, ids)

            groups = registration_class_select_groups(rows)
            options = [opt for group in groups for opt in group['options']]
            option_ids = {opt['id'] for opt in options}
            self.assertIn(self.kg_id, option_ids)
            self.assertIn(self.elementary_id, option_ids)
            self.assertIn(self.senior_id, option_ids)

            labels = {group['label'] for group in groups if group['options']}
            self.assertIn('Kindergarten', labels)
            self.assertIn('Elementary', labels)
            self.assertIn('Senior High', labels)

    def test_helper_still_lists_classes_without_an_active_year(self):
        with self.app.app_context():
            AcademicYear.query.filter_by(is_active=True).update(
                {AcademicYear.is_active: False},
                synchronize_session=False,
            )
            db.session.commit()
            groups = registration_class_select_groups()
            option_ids = {opt['id'] for group in groups for opt in group['options']}
            self.assertIn(self.elementary_id, option_ids)

    def test_register_student_page_renders_class_options(self):
        self._login()
        response = self.client.get('/register-student')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:800])
        html = response.get_data(as_text=True)
        self.assertIn('Choose Class Folder...', html)
        self._assert_select_has_class(html, self.kg_id, self.kg_name)
        self._assert_select_has_class(html, self.elementary_id, self.elementary_name)
        self._assert_select_has_class(html, self.senior_id, self.senior_name)
        self.assertIn('Kindergarten', html)
        self.assertIn('Elementary', html)
        self.assertIn('Senior High', html)

    def test_roster_search_does_not_empty_class_picker(self):
        self._login()
        response = self.client.get('/register-student?search_class=zzzz-no-such-class')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:800])
        html = response.get_data(as_text=True)
        self._assert_select_has_class(html, self.elementary_id, self.elementary_name)


if __name__ == '__main__':
    unittest.main()
