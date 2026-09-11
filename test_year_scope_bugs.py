"""Year isolation and registrar contact persistence bug fixes."""
import unittest
import uuid
from datetime import date

from app import (
    TEACHER_YEAR_SESSION_KEY,
    app,
    get_teacher_class_cards,
    list_payment_students_for_year,
    persist_student_portal_contact_fields,
)
from constants import ROLE_REGISTRAR
from models import (
    AcademicYear,
    Class,
    ClassSubjectTeacher,
    Grade,
    Student,
    Teacher,
    User,
    db,
)


class YearScopeBugFixTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.token = uuid.uuid4().hex[:8]
        self.created = {
            'users': [],
            'teachers': [],
            'classes': [],
            'years': [],
            'students': [],
            'allocs': [],
            'grades': [],
        }
        self.prior_active_year_ids = []

        with self.app.app_context():
            self.prior_active_year_ids = [
                year.id for year in AcademicYear.query.filter_by(is_active=True).all()
            ]
            AcademicYear.query.filter_by(is_active=True).update(
                {AcademicYear.is_active: False},
                synchronize_session=False,
            )

            teacher_user = User(
                email=f'teach-scope-{self.token}@test.com',
                full_name='Scope Teacher',
                role='teacher',
            )
            teacher_user.set_password('password')
            registrar = User(
                email=f'reg-scope-{self.token}@test.com',
                full_name='Scope Registrar',
                role=ROLE_REGISTRAR,
            )
            registrar.set_password('password')
            db.session.add_all([teacher_user, registrar])
            db.session.flush()
            self.teacher_user_id = teacher_user.id
            self.registrar_id = registrar.id
            self.created['users'].extend([teacher_user.id, registrar.id])

            teacher = Teacher(
                user_id=teacher_user.id,
                first_name='Scope',
                last_name='Teacher',
                status='ACTIVE',
            )
            db.session.add(teacher)
            db.session.flush()
            self.teacher_id = teacher.id
            self.created['teachers'].append(teacher.id)

            klass = Class(
                name=f'Scope Class {self.token}',
                grade_level='10',
            )
            db.session.add(klass)
            db.session.flush()
            self.class_id = klass.id
            self.created['classes'].append(klass.id)

            alloc = ClassSubjectTeacher(
                class_id=klass.id,
                teacher_id=teacher.id,
                subject_name='Mathematics',
            )
            db.session.add(alloc)
            db.session.flush()
            self.created['allocs'].append(alloc.id)

            archived = AcademicYear(
                name=f'SC{self.token}-25-26',
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=False,
                created_by=registrar.id,
            )
            active = AcademicYear(
                name=f'SC{self.token}-26-27',
                start_date=date(2026, 9, 1),
                end_date=date(2027, 6, 30),
                is_active=True,
                created_by=registrar.id,
            )
            db.session.add_all([archived, active])
            db.session.flush()
            self.archived_year_id = archived.id
            self.active_year_id = active.id
            self.created['years'].extend([archived.id, active.id])

            current_student = Student(
                student_id=f'SC{self.token}A',
                first_name='Current',
                last_name='Enrollee',
                dob=date(2009, 1, 1),
                gender='F',
                klass_id=klass.id,
                grade_level='10',
                academic_year_id=active.id,
                status='ACTIVE',
                is_registered=True,
            )
            prior_student = Student(
                student_id=f'SC{self.token}B',
                first_name='Prior',
                last_name='Enrollee',
                dob=date(2008, 1, 1),
                gender='M',
                klass_id=klass.id,
                grade_level='10',
                academic_year_id=archived.id,
                status='ACTIVE',
                is_registered=True,
            )
            portal_user = User(
                email=f'student-scope-{self.token}@test.com',
                full_name='Portal Scope',
                role='student',
            )
            portal_user.set_password('password')
            db.session.add_all([current_student, prior_student, portal_user])
            db.session.flush()
            prior_student.user_id = portal_user.id
            self.current_student_id = current_student.id
            self.prior_student_id = prior_student.id
            self.portal_user_id = portal_user.id
            self.created['users'].append(portal_user.id)
            self.created['students'].extend([current_student.id, prior_student.id])

            prior_grade = Grade(
                student_id=prior_student.id,
                academic_year_id=archived.id,
                class_id=klass.id,
                subject='Mathematics',
                subject_name='Mathematics',
                score=81,
                marking_period=1,
                period=1,
                submitted=True,
            )
            db.session.add(prior_grade)
            db.session.flush()
            self.created['grades'].append(prior_grade.id)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.rollback()
            Grade.query.filter(Grade.id.in_(self.created['grades'] or [0])).delete(
                synchronize_session=False,
            )
            Grade.query.filter(Grade.student_id.in_(self.created['students'] or [0])).delete(
                synchronize_session=False,
            )
            ClassSubjectTeacher.query.filter(
                ClassSubjectTeacher.id.in_(self.created['allocs'] or [0])
            ).delete(synchronize_session=False)
            for student_id in self.created['students']:
                Student.query.filter_by(id=student_id).delete(synchronize_session=False)
            for teacher_id in self.created['teachers']:
                Teacher.query.filter_by(id=teacher_id).delete(synchronize_session=False)
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

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_teacher_class_cards_count_archived_year_roster(self):
        with self.app.app_context():
            teacher = db.session.get(Teacher, self.teacher_id)
            user = db.session.get(User, self.teacher_user_id)

            live_cards = get_teacher_class_cards(
                teacher, user, self.archived_year_id, viewing_archived=False,
            )
            live_counts = {card['id']: card['student_count'] for card in live_cards}
            self.assertEqual(live_counts.get(self.class_id, 0), 1)

            archived_cards = get_teacher_class_cards(
                teacher, user, self.archived_year_id, viewing_archived=True,
            )
            archived_counts = {card['id']: card['student_count'] for card in archived_cards}
            self.assertGreaterEqual(archived_counts.get(self.class_id, 0), 1)

            # After rollover the prior student still has a grade in the archived class.
            prior = db.session.get(Student, self.prior_student_id)
            prior.academic_year_id = self.active_year_id
            db.session.commit()

            stale_live = get_teacher_class_cards(
                teacher, user, self.archived_year_id, viewing_archived=False,
            )
            stale_live_counts = {card['id']: card['student_count'] for card in stale_live}
            history_cards = get_teacher_class_cards(
                teacher, user, self.archived_year_id, viewing_archived=True,
            )
            history_counts = {card['id']: card['student_count'] for card in history_cards}
            self.assertEqual(stale_live_counts.get(self.class_id, 0), 0)
            self.assertGreaterEqual(history_counts.get(self.class_id, 0), 1)

    def test_save_grades_refuses_archived_year_write(self):
        self._login(self.teacher_user_id)
        with self.client.session_transaction() as sess:
            sess[TEACHER_YEAR_SESSION_KEY] = self.archived_year_id

        response = self.client.post(
            f'/save-grades/{self.class_id}',
            data={
                'subject': 'Mathematics',
                'period': '7',
                'exam_%s' % self.current_student_id: '88',
                'return_to': 'teacher_grade_sheet',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:800])
        html = response.get_data(as_text=True)
        self.assertIn('read-only for archived academic years', html)

        with self.app.app_context():
            written = Grade.query.filter_by(
                student_id=self.current_student_id,
                academic_year_id=self.active_year_id,
                subject='Mathematics',
                marking_period=7,
            ).count()
            self.assertEqual(written, 0)

    def test_payment_students_stay_in_selected_year(self):
        with self.app.app_context():
            archived = db.session.get(AcademicYear, self.archived_year_id)
            active = db.session.get(AcademicYear, self.active_year_id)
            archived_ids = {s.id for s in list_payment_students_for_year(archived)}
            active_ids = {s.id for s in list_payment_students_for_year(active)}
            self.assertIn(self.prior_student_id, archived_ids)
            self.assertNotIn(self.current_student_id, archived_ids)
            self.assertIn(self.current_student_id, active_ids)
            self.assertNotIn(self.prior_student_id, active_ids)

    def test_registrar_phone_and_address_persist_to_portal_user(self):
        with self.app.test_request_context(
            '/',
            method='POST',
            data={
                'telephone_number': '0770001111',
                'home_address': '12 Campus Road',
            },
        ):
            with self.app.app_context():
                student = db.session.get(Student, self.prior_student_id)
                persist_student_portal_contact_fields(student)
                db.session.commit()
                user = db.session.get(User, self.portal_user_id)
                self.assertEqual(user.telephone_number, '0770001111')
                self.assertEqual(user.home_address, '12 Campus Road')

    def test_teacher_dashboard_archived_year_is_read_only(self):
        self._login(self.teacher_user_id)
        response = self.client.get(
            f'/teacher/dashboard?academic_year_id={self.archived_year_id}'
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:800])
        html = response.get_data(as_text=True)
        self.assertIn('Grade entry is read-only', html)
        self.assertIn('archived', html.lower())


if __name__ == '__main__':
    unittest.main()
