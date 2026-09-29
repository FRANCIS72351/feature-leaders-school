"""Senior High grade and transcript release is reserved for the School Proprietor."""
import unittest
import uuid
from datetime import date

from app import app, SENIOR_GRADE_RELEASE_HOLD_MESSAGE, official_transcript_is_released
from models import (
    AcademicYear, Class, Grade, GradeRelease, Student, TranscriptRelease, User, db,
)


class SeniorGradeReleaseProprietorTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        self.token = uuid.uuid4().hex[:8]
        self.created = {
            'users': [], 'classes': [], 'years': [], 'students': [],
            'grades': [], 'releases': [],
        }
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

            proprietor = User(
                email=f'proprietor-{self.token}@test.com',
                full_name='School Proprietor',
                role='proprietor',
            )
            proprietor.set_password('password')
            vpa = User(
                email=f'vpa-senior-{self.token}@test.com',
                full_name='VPA Officer',
                role='vpa',
            )
            vpa.set_password('password')
            admin = User(
                email=f'admin-senior-{self.token}@test.com',
                full_name='System Admin',
                role='admin',
            )
            admin.set_password('password')
            db.session.add_all([proprietor, vpa, admin])
            db.session.flush()
            self.created['users'].extend([proprietor.id, vpa.id, admin.id])
            self.proprietor_id = proprietor.id
            self.vpa_id = vpa.id
            self.admin_id = admin.id

            senior = Class(name=f'SHS 11 {self.token}', grade_level=11)
            junior = Class(name=f'JHS 8 {self.token}', grade_level=8)
            db.session.add_all([senior, junior])
            db.session.flush()
            self.created['classes'].extend([senior.id, junior.id])
            self.senior_class_id = senior.id
            self.junior_class_id = junior.id

            year = AcademicYear(
                name=f'20{self.token[:2]}-20{self.token[2:4]}',
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=True,
                created_by=proprietor.id,
            )
            db.session.add(year)
            db.session.flush()
            self.created['years'].append(year.id)
            self.year_id = year.id

            student = Student(
                student_id=f'SH{self.token.upper()}',
                first_name='Senior',
                last_name='Scholar',
                dob=date(2008, 4, 4),
                gender='F',
                klass_id=senior.id,
                grade_level=11,
                academic_year_id=year.id,
                status='ACTIVE',
                is_registered=True,
            )
            junior_student = Student(
                student_id=f'JH{self.token.upper()}',
                first_name='Junior',
                last_name='Scholar',
                dob=date(2010, 5, 5),
                gender='M',
                klass_id=junior.id,
                grade_level=8,
                academic_year_id=year.id,
                status='ACTIVE',
                is_registered=True,
            )
            db.session.add_all([student, junior_student])
            db.session.flush()
            self.created['students'].extend([student.id, junior_student.id])
            self.student_id = student.id
            self.junior_student_id = junior_student.id

            grade = Grade(
                student_id=student.id,
                academic_year_id=year.id,
                class_id=senior.id,
                subject='Mathematics',
                subject_name='Mathematics',
                score=91,
                marking_period=1,
                period=1,
                submitted=True,
            )
            db.session.add(grade)
            db.session.flush()
            self.created['grades'].append(grade.id)

            release = GradeRelease(
                academic_year_id=year.id,
                class_id=senior.id,
                period=1,
                status=GradeRelease.STATUS_PENDING_VPA,
            )
            db.session.add(release)
            db.session.flush()
            self.created['releases'].append(release.id)
            self.release_id = release.id
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            TranscriptRelease.query.filter(
                TranscriptRelease.academic_year_id.in_(self.created['years'] or [0])
            ).delete(synchronize_session=False)
            for key, model in (
                ('releases', GradeRelease),
                ('grades', Grade),
                ('students', Student),
                ('classes', Class),
                ('years', AcademicYear),
                ('users', User),
            ):
                for row_id in self.created[key]:
                    model.query.filter_by(id=row_id).delete(synchronize_session=False)
            for year_id in self.prior_active_year_ids:
                year = db.session.get(AcademicYear, year_id)
                if year:
                    year.is_active = True
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_vpa_cabinet_hides_senior_high_folders(self):
        self._login(self.vpa_id)
        page = self.client.get(f'/vpa/grade-releases?academic_year_id={self.year_id}')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertNotIn(f'id="folder-{self.senior_class_id}"', html)
        self.assertIn('Senior High sealed from this desk', html)
        self.assertIn(f'id="folder-{self.junior_class_id}"', html)

    def test_vpa_cannot_approve_senior_high_release(self):
        self._login(self.vpa_id)
        response = self.client.post(
            f'/vpa/grade-releases/{self.release_id}/approve',
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(SENIOR_GRADE_RELEASE_HOLD_MESSAGE.encode(), response.data)
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            self.assertEqual(release.status, GradeRelease.STATUS_PENDING_VPA)

    def test_admin_cannot_open_senior_seal_desk(self):
        self._login(self.admin_id)
        page = self.client.get('/proprietor/senior-grade-releases', follow_redirects=False)
        self.assertIn(page.status_code, (302, 303))
        transcripts = self.client.get(
            '/proprietor/senior-transcript-releases', follow_redirects=False,
        )
        self.assertIn(transcripts.status_code, (302, 303))

    def test_proprietor_can_release_senior_high(self):
        self._login(self.proprietor_id)
        desk = self.client.get(
            f'/proprietor/senior-grade-releases?academic_year_id={self.year_id}'
        )
        self.assertEqual(desk.status_code, 200)
        html = desk.get_data(as_text=True)
        self.assertIn('Senior High Seal Desk', html)
        self.assertIn('Grades per student', html)
        self.assertIn(f'id="folder-{self.senior_class_id}"', html)
        self.assertNotIn(f'id="folder-{self.junior_class_id}"', html)

        approve = self.client.post(
            f'/vpa/grade-releases/{self.release_id}/approve',
            follow_redirects=True,
        )
        self.assertEqual(approve.status_code, 200)
        self.assertIn(b'approved', approve.data.lower())
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            self.assertEqual(release.status, GradeRelease.STATUS_APPROVED)

    def test_proprietor_can_release_grade_per_student(self):
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_DRAFT
            db.session.commit()

        self._login(self.proprietor_id)
        folder = self.client.get(
            f'/proprietor/senior-grade-releases/class/{self.senior_class_id}'
            f'?academic_year_id={self.year_id}'
        )
        self.assertEqual(folder.status_code, 200)
        self.assertIn(b'Senior Scholar', folder.data)
        self.assertIn(b'Release', folder.data)

        approve = self.client.post(
            f'/vpa/grade-releases/student/{self.student_id}/period/1/approve',
            data={'academic_year_id': self.year_id, 'class_id': self.senior_class_id},
            follow_redirects=True,
        )
        self.assertEqual(approve.status_code, 200)
        self.assertIn(b'released', approve.data.lower())

    def test_vpa_cannot_release_senior_transcript(self):
        self._login(self.vpa_id)
        page = self.client.get(
            f'/vpa/transcript-releases?academic_year_id={self.year_id}'
        )
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertNotIn(f'id="folder-{self.senior_class_id}"', html)
        self.assertIn('Senior High sealed from this desk', html)

        blocked = self.client.post(
            f'/vpa/transcript-releases/{self.student_id}/approve',
            data={'academic_year_id': self.year_id},
            follow_redirects=True,
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertIn(SENIOR_GRADE_RELEASE_HOLD_MESSAGE.encode(), blocked.data)
        with self.app.app_context():
            self.assertFalse(
                official_transcript_is_released(self.student_id, self.year_id)
            )

    def test_year_wide_vpa_release_skips_senior(self):
        self._login(self.vpa_id)
        posted = self.client.post(
            '/vpa/transcript-releases/approve-year',
            data={'academic_year_id': self.year_id},
            follow_redirects=True,
        )
        self.assertEqual(posted.status_code, 200)
        with self.app.app_context():
            self.assertTrue(
                official_transcript_is_released(self.junior_student_id, self.year_id)
            )
            self.assertFalse(
                official_transcript_is_released(self.student_id, self.year_id)
            )

    def test_proprietor_can_release_transcript_per_student(self):
        self._login(self.proprietor_id)
        desk = self.client.get(
            f'/proprietor/senior-transcript-releases?academic_year_id={self.year_id}'
        )
        self.assertEqual(desk.status_code, 200)
        html = desk.get_data(as_text=True)
        self.assertIn('Transcripts per student', html)
        self.assertIn(f'id="folder-{self.senior_class_id}"', html)

        folder = self.client.get(
            f'/proprietor/senior-transcript-releases/class/{self.senior_class_id}'
            f'?academic_year_id={self.year_id}'
        )
        self.assertEqual(folder.status_code, 200)
        self.assertIn(b'Senior Scholar', folder.data)

        approve = self.client.post(
            f'/vpa/transcript-releases/{self.student_id}/approve',
            data={'academic_year_id': self.year_id},
            follow_redirects=True,
        )
        self.assertEqual(approve.status_code, 200)
        self.assertIn(b'released', approve.data.lower())
        with self.app.app_context():
            self.assertTrue(
                official_transcript_is_released(self.student_id, self.year_id)
            )


if __name__ == '__main__':
    unittest.main()
