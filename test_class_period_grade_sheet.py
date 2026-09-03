import unittest
import uuid
from datetime import date

from app import app
from models import AcademicYear, Class, Grade, GradeRelease, Student, User, db


class ClassPeriodGradeSheetTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        self.token = uuid.uuid4().hex[:8]
        self.client = self.app.test_client()
        with self.app.app_context():
            AcademicYear.query.filter_by(is_active=True).update(
                {AcademicYear.is_active: False}, synchronize_session=False,
            )

            self.vpa = User(email=f'vpa-{self.token}@test.com', full_name='VPA Reviewer', role='vpa')
            self.vpa.set_password('password')
            self.teacher_user = User(email=f'teach-{self.token}@test.com', full_name='Class Teacher', role='teacher')
            self.teacher_user.set_password('password')
            db.session.add_all([self.vpa, self.teacher_user])
            db.session.flush()
            self.vpa_id, self.teacher_user_id = self.vpa.id, self.teacher_user.id

            klass = Class(name=f'Sheet Class {self.token}', grade_level=10)
            db.session.add(klass)
            db.session.flush()
            self.class_id = klass.id

            year = AcademicYear(
                name=f'20{self.token[:2]}-20{self.token[2:4]}',
                start_date=date(2025, 9, 1), end_date=date(2026, 6, 30),
                is_active=True, created_by=self.vpa_id,
            )
            db.session.add(year)
            db.session.flush()
            self.year_id = year.id

            student = Student(
                student_id=f'SH{self.token.upper()}', first_name='Sheet', last_name='Student',
                dob=date(2008, 1, 1), gender='F', klass_id=klass.id, grade_level=10,
                academic_year_id=year.id, status='ACTIVE', is_registered=True,
            )
            db.session.add(student)
            db.session.flush()
            self.student_id = student.id

            grade = Grade(
                student_id=student.id, academic_year_id=year.id, class_id=klass.id,
                subject='Mathematics', subject_name='Mathematics', score=88,
                marking_period=1, period=1, submitted=True,
            )
            db.session.add(grade)
            db.session.flush()

            release = GradeRelease(
                academic_year_id=year.id, class_id=klass.id, period=1,
                status=GradeRelease.STATUS_PENDING_VPA,
            )
            db.session.add(release)
            db.session.commit()
            self.release_id = release.id

    def tearDown(self):
        with self.app.app_context():
            GradeRelease.query.filter_by(class_id=self.class_id).delete(synchronize_session=False)
            Grade.query.filter_by(class_id=self.class_id).delete(synchronize_session=False)
            Student.query.filter_by(id=self.student_id).delete(synchronize_session=False)
            AcademicYear.query.filter_by(id=self.year_id).delete(synchronize_session=False)
            Class.query.filter_by(id=self.class_id).delete(synchronize_session=False)
            User.query.filter(User.id.in_([self.vpa_id, self.teacher_user_id])).delete(synchronize_session=False)
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_vpa_can_view_and_approve_from_sheet(self):
        self._login(self.vpa_id)
        resp = self.client.get(f'/grades/period-sheet/{self.class_id}/1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Period Grade Sheet', resp.data)
        self.assertIn(b'Sheet Student', resp.data)
        self.assertIn(b'88', resp.data)

    def test_unrelated_teacher_cannot_view(self):
        self._login(self.teacher_user_id)
        resp = self.client.get(f'/grades/period-sheet/{self.class_id}/1', follow_redirects=True)
        self.assertIn(b'assigned classes', resp.data)


if __name__ == '__main__':
    unittest.main()
