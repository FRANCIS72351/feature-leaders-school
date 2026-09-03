import unittest
import uuid
from datetime import date

from app import (
    STUDENT_TRANSCRIPT_HOLD_MESSAGE,
    app,
)
from models import AcademicYear, Class, Grade, Student, TranscriptRelease, User, db


class OfficialTranscriptRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.token = uuid.uuid4().hex[:8]
        self.created = {
            'users': [], 'classes': [], 'years': [], 'students': [], 'grades': [],
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

            registrar = User(
                email=f'registrar-tx-{self.token}@test.com',
                full_name='Transcript Registrar',
                role='registrar',
            )
            registrar.set_password('password')
            vpa = User(
                email=f'vpa-tx-{self.token}@test.com',
                full_name='Transcript VPA',
                role='vpa',
            )
            vpa.set_password('password')
            teacher = User(
                email=f'teacher-tx-{self.token}@test.com',
                full_name='Transcript Teacher',
                role='teacher',
            )
            teacher.set_password('password')
            student_user = User(
                email=f'student-tx-{self.token}@test.com',
                full_name='Mohammed Kamara',
                role='student',
            )
            student_user.set_password('password')
            parent = User(
                email=f'parent-tx-{self.token}@test.com',
                full_name='Transcript Parent',
                role='parent',
            )
            parent.set_password('password')
            db.session.add_all([registrar, vpa, teacher, student_user, parent])
            db.session.flush()
            self.created['users'].extend([
                registrar.id, vpa.id, teacher.id, student_user.id, parent.id,
            ])
            self.registrar_id = registrar.id
            self.vpa_id = vpa.id
            self.teacher_id = teacher.id
            self.student_user_id = student_user.id
            self.parent_id = parent.id
            self.parent_email = parent.email

            klass = Class(
                name=f'Transcript Class {self.token}',
                grade_level='10th',
            )
            db.session.add(klass)
            db.session.flush()
            self.created['classes'].append(klass.id)
            self.class_id = klass.id

            year = AcademicYear(
                name=f'20{self.token[:2]}-20{self.token[2:4]}',
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=True,
                created_by=registrar.id,
            )
            db.session.add(year)
            db.session.flush()
            self.created['years'].append(year.id)
            self.year_id = year.id

            student = Student(
                student_id=f'TX{self.token.upper()}',
                first_name='Mohammed',
                last_name='Kamara',
                dob=date(2008, 1, 1),
                gender='M',
                klass_id=klass.id,
                grade_level='10th',
                academic_year_id=year.id,
                status='ACTIVE',
                is_registered=True,
                user_id=student_user.id,
                parent_email=parent.email,
            )
            db.session.add(student)
            db.session.flush()
            self.created['students'].append(student.id)
            self.student_id = student.id

            grade = Grade(
                student_id=student.id,
                academic_year_id=year.id,
                class_id=klass.id,
                subject='English',
                subject_name='English',
                score=88,
                marking_period=1,
                period=1,
                submitted=True,
            )
            db.session.add(grade)
            db.session.flush()
            self.created['grades'].append(grade.id)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            TranscriptRelease.query.filter(
                TranscriptRelease.academic_year_id.in_(self.created['years'] or [0])
            ).delete(synchronize_session=False)
            for grade_id in self.created['grades']:
                Grade.query.filter_by(id=grade_id).delete(synchronize_session=False)
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

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_registrar_transcript_is_official_portrait_document(self):
        self._login(self.registrar_id)
        response = self.client.get(f'/transcript/{self.student_id}?academic_year_id={self.year_id}')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('OFFICIAL TRANSCRIPT', body)
        self.assertIn('YEARLY AVERAGE', body)
        self.assertIn('1ST SEMESTER', body)
        self.assertIn('LANGUAGE ARTS', body)
        self.assertIn('size: A4 portrait', body)
        self.assertNotIn('size: A4 landscape', body)
        self.assertNotIn('PUBLISHED RECORDS', body)
        self.assertNotIn('SELECTED YEAR', body)

    def test_vpa_can_open_transcript_and_teacher_cannot(self):
        self._login(self.vpa_id)
        allowed = self.client.get(f'/transcript/{self.student_id}')
        self.assertEqual(allowed.status_code, 200)
        self.assertIn('OFFICIAL TRANSCRIPT', allowed.get_data(as_text=True))

        self._login(self.teacher_id)
        denied = self.client.get(f'/transcript/{self.student_id}')
        self.assertEqual(denied.status_code, 302)

    def test_student_blocked_without_transcript_approval(self):
        self._login(self.student_user_id)
        response = self.client.get(
            f'/transcript/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertIn(response.status_code, (302, 403))
        body = response.get_data(as_text=True)
        self.assertNotIn('YEARLY AVERAGE', body)
        self.assertNotIn('1ST SEMESTER', body)
        self.assertNotIn('size: A4 portrait', body)
        if response.status_code == 403:
            self.assertIn(STUDENT_TRANSCRIPT_HOLD_MESSAGE, body)

    def test_parent_blocked_without_transcript_approval(self):
        self._login(self.parent_id)
        response = self.client.get(
            f'/transcript/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertIn(response.status_code, (302, 403))
        self.assertNotIn('YEARLY AVERAGE', response.get_data(as_text=True))

    def test_student_records_redirect_respects_transcript_gate(self):
        self._login(self.student_user_id)
        response = self.client.get(f'/student/records/{self.year_id}')
        self.assertIn(response.status_code, (302, 403))
        body = response.get_data(as_text=True)
        self.assertNotIn('YEARLY AVERAGE', body)
        self.assertNotIn('1ST SEMESTER', body)
        if response.status_code == 302:
            self.assertNotIn('/transcript/', response.headers.get('Location', ''))

    def test_staff_can_print_before_student_release(self):
        self._login(self.registrar_id)
        response = self.client.get(
            f'/transcript/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('OFFICIAL TRANSCRIPT', response.get_data(as_text=True))

    def test_student_can_view_after_vpa_approves(self):
        self._login(self.vpa_id)
        approve = self.client.post(
            f'/vpa/transcript-releases/{self.student_id}/approve',
            data={'academic_year_id': self.year_id},
        )
        self.assertIn(approve.status_code, (302, 200))

        self._login(self.student_user_id)
        response = self.client.get(
            f'/transcript/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('OFFICIAL TRANSCRIPT', body)
        self.assertIn('YEARLY AVERAGE', body)
        self.assertIn('size: A4 portrait', body)

        records = self.client.get(f'/student/records/{self.year_id}')
        self.assertEqual(records.status_code, 302)
        self.assertIn(f'/transcript/{self.student_id}', records.headers.get('Location', ''))

    def test_year_wide_release_unlocks_student_portal(self):
        self._login(self.vpa_id)
        posted = self.client.post(
            '/vpa/transcript-releases/approve-year',
            data={'academic_year_id': self.year_id},
        )
        self.assertIn(posted.status_code, (302, 200))

        self._login(self.student_user_id)
        response = self.client.get(
            f'/transcript/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('OFFICIAL TRANSCRIPT', response.get_data(as_text=True))

    def test_vpa_dashboard_returns_200(self):
        self._login(self.vpa_id)
        response = self.client.get('/vpa/dashboard')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('VPA Academic Command Center', body)
        self.assertIn('Approve Transcripts', body)
        self.assertIn('/vpa/transcript-releases', body)

    def test_vpa_and_principal_can_open_approve_queue(self):
        self._login(self.vpa_id)
        queue = self.client.get('/vpa/transcript-releases')
        self.assertEqual(queue.status_code, 200)
        self.assertIn('Approve Transcripts', queue.get_data(as_text=True))

        with self.app.app_context():
            principal = User(
                email=f'principal-tx-{self.token}@test.com',
                full_name='Transcript Principal',
                role='principal',
            )
            principal.set_password('password')
            db.session.add(principal)
            db.session.commit()
            principal_id = principal.id
            self.created['users'].append(principal_id)
        self._login(principal_id)
        principal_queue = self.client.get('/vpa/transcript-releases')
        self.assertEqual(principal_queue.status_code, 200)
        self.assertIn('Approve Transcripts', principal_queue.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
