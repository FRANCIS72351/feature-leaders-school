"""Registry may print class and student period sheets only after academic release."""
import uuid
import unittest
from datetime import date

from app import app
from constants import ROLE_REGISTRAR, ROLE_TEACHER
from models import (
    AcademicYear,
    Class,
    Grade,
    GradeRelease,
    Student,
    StudentPeriodRelease,
    User,
    db,
)


class RegistryPeriodSheetsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()
        self.token = uuid.uuid4().hex[:8]
        self.ids = {'users': [], 'students': [], 'classes': [], 'years': [], 'grades': [], 'releases': [], 'student_releases': []}
        with self.app.app_context():
            registrar = User(
                email=f'reg-pps-{self.token}@test.com',
                full_name='Print Registrar',
                role=ROLE_REGISTRAR,
            )
            registrar.set_password('password')
            teacher = User(
                email=f'teach-pps-{self.token}@test.com',
                full_name='Print Teacher',
                role=ROLE_TEACHER,
            )
            teacher.set_password('password')
            db.session.add_all([registrar, teacher])
            db.session.flush()
            self.registrar_id = registrar.id
            self.teacher_id = teacher.id
            self.ids['users'].extend([registrar.id, teacher.id])

            klass = Class(name=f'PPS {self.token}', grade_level='6th')
            db.session.add(klass)
            db.session.flush()
            self.class_id = klass.id
            self.ids['classes'].append(klass.id)

            year = AcademicYear(
                name=f'20{self.token[:2]}/20{self.token[2:4]}',
                start_date=date(2098, 9, 1),
                end_date=date(2099, 6, 30),
                is_active=True,
                created_by=registrar.id,
            )
            db.session.add(year)
            db.session.flush()
            self.year_id = year.id
            self.ids['years'].append(year.id)

            student = Student(
                student_id=f'77{self.token[:2]}-{int(self.token[:4], 16) % 90000 + 10000:05d}',
                first_name='Ama',
                last_name='Sheet',
                dob=date(2014, 3, 4),
                gender='Female',
                klass_id=klass.id,
                academic_year_id=year.id,
                is_registered=True,
            )
            db.session.add(student)
            db.session.flush()
            self.student_id = student.id
            self.ids['students'].append(student.id)

            grade = Grade(
                student_id=student.id,
                academic_year_id=year.id,
                class_id=klass.id,
                subject='Mathematics',
                subject_name='Mathematics',
                score=91,
                marking_period=1,
                period=1,
                submitted=True,
            )
            db.session.add(grade)
            db.session.commit()
            self.ids['grades'].append(grade.id)

    def tearDown(self):
        with self.app.app_context():
            StudentPeriodRelease.query.filter(
                StudentPeriodRelease.student_id.in_(self.ids['students'] or [0])
            ).delete(synchronize_session=False)
            GradeRelease.query.filter(
                GradeRelease.class_id.in_(self.ids['classes'] or [0])
            ).delete(synchronize_session=False)
            Grade.query.filter(Grade.student_id.in_(self.ids['students'] or [0])).delete(synchronize_session=False)
            Student.query.filter(Student.id.in_(self.ids['students'] or [0])).delete(synchronize_session=False)
            Class.query.filter(Class.id.in_(self.ids['classes'] or [0])).delete(synchronize_session=False)
            AcademicYear.query.filter(AcademicYear.id.in_(self.ids['years'] or [0])).delete(synchronize_session=False)
            User.query.filter(User.id.in_(self.ids['users'] or [0])).delete(synchronize_session=False)
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def _class_url(self, period=1):
        return f'/registrar/period-sheets/class/{self.class_id}/{period}?academic_year_id={self.year_id}'

    def _student_url(self, period=1):
        return (
            f'/registrar/period-sheets/student/{self.student_id}'
            f'?academic_year_id={self.year_id}&period={period}'
        )

    def test_teacher_cannot_open_print_desk(self):
        self._login(self.teacher_id)
        response = self.client.get('/registrar/period-sheets', follow_redirects=False)
        self.assertIn(response.status_code, (302, 401, 403))

    def test_registrar_desk_shows_locked_until_release(self):
        self._login(self.registrar_id)
        response = self.client.get(f'/registrar/period-sheets?academic_year_id={self.year_id}')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('Period Grade Sheets', body)
        self.assertIn('Period 1 locked', body)

    def test_unreleased_class_sheet_is_blocked(self):
        self._login(self.registrar_id)
        response = self.client.get(self._class_url(), follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/registrar/period-sheets', response.headers.get('Location', ''))

    def test_released_class_sheet_prints(self):
        with self.app.app_context():
            release = GradeRelease(
                academic_year_id=self.year_id,
                class_id=self.class_id,
                period=1,
                status=GradeRelease.STATUS_APPROVED,
            )
            db.session.add(release)
            db.session.commit()
            self.ids['releases'].append(release.id)
        self._login(self.registrar_id)
        desk = self.client.get(f'/registrar/period-sheets?academic_year_id={self.year_id}&open_class_id={self.class_id}')
        self.assertEqual(desk.status_code, 200)
        self.assertIn('Print Period 1', desk.get_data(as_text=True))
        sheet = self.client.get(self._class_url())
        self.assertEqual(sheet.status_code, 200)
        body = sheet.get_data(as_text=True)
        self.assertIn('Ama', body)
        self.assertIn('Back', body)

    def test_student_sheet_needs_release(self):
        self._login(self.registrar_id)
        blocked = self.client.get(self._student_url(), follow_redirects=False)
        self.assertEqual(blocked.status_code, 302)
        with self.app.app_context():
            row = StudentPeriodRelease(
                academic_year_id=self.year_id,
                student_id=self.student_id,
                class_id=self.class_id,
                period=1,
                status=StudentPeriodRelease.STATUS_APPROVED,
            )
            db.session.add(row)
            db.session.commit()
            self.ids['student_releases'].append(row.id)
        opened = self.client.get(self._student_url())
        self.assertEqual(opened.status_code, 200)
        self.assertIn('Ama', opened.get_data(as_text=True))
        self.assertIn('Back to period print desk', opened.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
