"""Teacher dashboard shows classes the faculty member sponsors."""
import unittest
import uuid
from datetime import date

from app import (
    TEACHER_YEAR_SESSION_KEY,
    app,
    get_sponsored_class_cards,
    get_teacher_class_cards,
)
from models import (
    AcademicYear,
    Class,
    ClassSubjectTeacher,
    Student,
    Teacher,
    User,
    db,
)


class TeacherSponsorDashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.token = uuid.uuid4().hex[:8]
        self.class_name = f'Grade 7A {self.token}'
        self.created = {
            'users': [],
            'teachers': [],
            'classes': [],
            'years': [],
            'students': [],
            'allocs': [],
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

            # Shift users.id ahead of teachers.id so a FK mix-up cannot pass by coincidence.
            padding_users = []
            for index in range(3):
                pad = User(
                    email=f'pad-sponsor-{index}-{self.token}@test.com',
                    full_name=f'Padding {index}',
                    role='teacher',
                )
                pad.set_password('password')
                padding_users.append(pad)
            db.session.add_all(padding_users)
            db.session.flush()
            self.created['users'].extend(user.id for user in padding_users)

            teacher_user = User(
                email=f'sponsor-dash-{self.token}@test.com',
                full_name='Sponsor Dashboard Teacher',
                role='teacher',
            )
            teacher_user.set_password('password')
            admin = User(
                email=f'admin-sponsor-dash-{self.token}@test.com',
                full_name='Sponsor Dashboard Admin',
                role='admin',
            )
            admin.set_password('password')
            db.session.add_all([teacher_user, admin])
            db.session.flush()
            self.teacher_user_id = teacher_user.id
            self.admin_id = admin.id
            self.created['users'].extend([teacher_user.id, admin.id])

            teacher = Teacher(
                user_id=teacher_user.id,
                first_name='Sponsor',
                last_name='Dashboard',
                status='ACTIVE',
            )
            db.session.add(teacher)
            db.session.flush()
            self.teacher_id = teacher.id
            self.created['teachers'].append(teacher.id)
            self.assertNotEqual(
                self.teacher_id,
                self.teacher_user_id,
                'Test needs Teacher.id != User.id to catch the sponsor FK mix-up',
            )

            klass = Class(
                name=self.class_name,
                grade_level='7',
                stream='A',
                sponsor_id=teacher_user.id,
            )
            db.session.add(klass)
            db.session.flush()
            self.class_id = klass.id
            self.created['classes'].append(klass.id)

            archived = AcademicYear(
                name=f'SD{self.token}-25-26',
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=False,
                created_by=admin.id,
            )
            active = AcademicYear(
                name=f'SD{self.token}-26-27',
                start_date=date(2026, 9, 1),
                end_date=date(2027, 6, 30),
                is_active=True,
                created_by=admin.id,
            )
            db.session.add_all([archived, active])
            db.session.flush()
            self.archived_year_id = archived.id
            self.active_year_id = active.id
            self.created['years'].extend([archived.id, active.id])

            student = Student(
                student_id=f'SD{self.token}A',
                first_name='Sponsored',
                last_name='Learner',
                dob=date(2013, 2, 2),
                gender='F',
                klass_id=klass.id,
                grade_level='7',
                academic_year_id=active.id,
                status='ACTIVE',
                is_registered=True,
            )
            db.session.add(student)
            db.session.flush()
            self.student_id = student.id
            self.created['students'].append(student.id)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.rollback()
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

    def test_dashboard_shows_sponsored_class_after_login(self):
        self._login(self.teacher_user_id)
        response = self.client.get('/teacher/dashboard')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:800])
        html = response.get_data(as_text=True)
        self.assertIn(self.class_name, html)
        self.assertIn(f'You are the class sponsor for {self.class_name}', html)
        self.assertIn('Sponsored classes', html)
        self.assertIn(f'/teacher/sponsor/{self.class_id}', html)
        self.assertIn('1 student', html)

    def test_dashboard_keeps_sponsor_wording_when_also_teaching(self):
        with self.app.app_context():
            alloc = ClassSubjectTeacher(
                class_id=self.class_id,
                teacher_id=self.teacher_id,
                subject_name='English',
            )
            db.session.add(alloc)
            db.session.flush()
            self.created['allocs'].append(alloc.id)
            db.session.commit()

        self._login(self.teacher_user_id)
        response = self.client.get('/teacher/dashboard')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:800])
        html = response.get_data(as_text=True)
        self.assertIn(f'You are the class sponsor for {self.class_name}', html)
        self.assertIn('You also teach this class', html)
        self.assertIn('Class Sponsor', html)

    def test_dashboard_still_lists_sponsored_class_for_archived_year(self):
        self._login(self.teacher_user_id)
        with self.client.session_transaction() as sess:
            sess[TEACHER_YEAR_SESSION_KEY] = self.archived_year_id
        response = self.client.get(
            f'/teacher/dashboard?academic_year_id={self.archived_year_id}'
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:800])
        html = response.get_data(as_text=True)
        self.assertIn(self.class_name, html)
        self.assertIn(f'You are the class sponsor for {self.class_name}', html)
        self.assertIn('Sponsored classes', html)

    def test_sponsored_cards_match_user_id_not_teacher_id(self):
        with self.app.app_context():
            teacher = db.session.get(Teacher, self.teacher_id)
            user = db.session.get(User, self.teacher_user_id)

            cards = get_sponsored_class_cards(user, self.active_year_id)
            names = [card['name'] for card in cards]
            self.assertIn(self.class_name, names)

            teaching_cards = get_teacher_class_cards(teacher, user, self.active_year_id)
            teaching_names = [card['name'] for card in teaching_cards]
            self.assertIn(self.class_name, teaching_names)
            sponsor_card = next(
                card for card in teaching_cards if card['id'] == self.class_id
            )
            self.assertTrue(sponsor_card['is_sponsor'])
            self.assertIn('Class Sponsor', sponsor_card['role_labels'])

            klass = db.session.get(Class, self.class_id)
            klass.sponsor_id = teacher.id
            db.session.commit()

            wrong_id_cards = get_sponsored_class_cards(user, self.active_year_id)
            self.assertNotIn(self.class_name, [card['name'] for card in wrong_id_cards])

            klass.sponsor_id = user.id
            db.session.commit()


if __name__ == '__main__':
    unittest.main()
