"""Staff folders: only the academic office may open them, and each folder holds one employee."""
import io
import os
import unittest
import uuid
from datetime import date

from app import app, STAFF_FOLDER_ROLES
from models import db, StaffDocument, Teacher, User


class StaffFolderTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        self.token = uuid.uuid4().hex[:8]
        self.created_users = []
        self.created_teachers = []
        self.created_docs = []
        self.client = self.app.test_client()

        with self.app.app_context():
            self.vpa_id = self._make_user('vpa', 'VPA Reviewer')
            self.principal_id = self._make_user('principal', 'School Principal')
            self.business_id = self._make_user('business', 'Bursar Officer')
            self.teacher_user_id = self._make_user('teacher', 'Grace Teacher')

            teacher = Teacher(
                user_id=self.teacher_user_id,
                first_name='Grace',
                last_name='Teacher',
                subject='Mathematics',
            )
            db.session.add(teacher)
            db.session.flush()
            self.created_teachers.append(teacher.id)
            db.session.commit()

    def _make_user(self, role, name):
        user = User(
            email=f'{role}-{self.token}@test.com',
            full_name=name,
            role=role,
        )
        user.set_password('password')
        db.session.add(user)
        db.session.flush()
        self.created_users.append(user.id)
        return user.id

    def tearDown(self):
        with self.app.app_context():
            for doc in StaffDocument.query.filter(
                StaffDocument.staff_id.in_(self.created_users or [0])
            ).all():
                rel = (doc.file_path or '').replace('/', os.sep)
                try:
                    os.remove(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', rel))
                except OSError:
                    pass
            StaffDocument.query.filter(
                StaffDocument.staff_id.in_(self.created_users or [0])
            ).delete(synchronize_session=False)
            for teacher_id in self.created_teachers:
                Teacher.query.filter_by(id=teacher_id).delete(synchronize_session=False)
            for user_id in self.created_users:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_vpa_and_principal_can_open_folders(self):
        for actor in (self.vpa_id, self.principal_id):
            self._login(actor)
            listing = self.client.get('/staff/folders')
            self.assertEqual(listing.status_code, 200)
            self.assertIn(b'Staff Folders', listing.data)

            folder = self.client.get(f'/staff/folders/{self.teacher_user_id}')
            self.assertEqual(folder.status_code, 200)
            self.assertIn(b'Grace Teacher', folder.data)
            self.assertIn(b'Employment Record', folder.data)

    def test_other_offices_are_turned_away(self):
        self._login(self.business_id)
        listing = self.client.get('/staff/folders', follow_redirects=False)
        self.assertEqual(listing.status_code, 302)

        folder = self.client.get(f'/staff/folders/{self.teacher_user_id}', follow_redirects=False)
        self.assertEqual(folder.status_code, 302)

    def test_staff_cannot_open_their_own_or_others_folders(self):
        self._login(self.teacher_user_id)
        own = self.client.get(f'/staff/folders/{self.teacher_user_id}', follow_redirects=False)
        self.assertEqual(own.status_code, 302)

    def test_employment_record_saves(self):
        self._login(self.vpa_id)
        response = self.client.post(
            f'/staff/folders/{self.teacher_user_id}/employment',
            data={
                'job_title': 'Senior Mathematics Teacher',
                'department': 'Mathematics',
                'employment_type': 'Full-time',
                'hire_date': '2019-09-02',
                'telephone_number': '0770000000',
                'emergency_contact_name': 'Next Of Kin',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            saved = db.session.get(User, self.teacher_user_id)
            self.assertEqual(saved.job_title, 'Senior Mathematics Teacher')
            self.assertEqual(saved.department, 'Mathematics')
            self.assertEqual(saved.employment_type, 'Full-time')
            self.assertEqual(saved.hire_date, date(2019, 9, 2))
            self.assertEqual(saved.emergency_contact_name, 'Next Of Kin')

    def test_invalid_employment_type_is_rejected(self):
        self._login(self.vpa_id)
        self.client.post(
            f'/staff/folders/{self.teacher_user_id}/employment',
            data={'employment_type': 'Whatever'},
            follow_redirects=True,
        )
        with self.app.app_context():
            self.assertIsNone(db.session.get(User, self.teacher_user_id).employment_type)

    def test_document_upload_and_delete(self):
        self._login(self.vpa_id)
        upload = self.client.post(
            f'/staff/folders/{self.teacher_user_id}/documents',
            data={
                'doc_type': 'contract',
                'title': 'Employment contract 2025',
                'upload_file': (io.BytesIO(b'%PDF-1.4 test contract'), 'contract.pdf'),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        self.assertEqual(upload.status_code, 200)

        with self.app.app_context():
            document = StaffDocument.query.filter_by(staff_id=self.teacher_user_id).first()
            self.assertIsNotNone(document)
            self.assertEqual(document.doc_type, 'contract')
            self.assertEqual(document.title, 'Employment contract 2025')
            self.assertTrue(document.is_pdf)
            document_id = document.id

        opened = self.client.get(
            f'/staff/folders/{self.teacher_user_id}/documents/{document_id}/file'
        )
        self.assertEqual(opened.status_code, 200)

        removed = self.client.post(
            f'/staff/folders/{self.teacher_user_id}/documents/{document_id}/delete',
            follow_redirects=True,
        )
        self.assertEqual(removed.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(db.session.get(StaffDocument, document_id))

    def test_executable_upload_is_refused(self):
        self._login(self.vpa_id)
        self.client.post(
            f'/staff/folders/{self.teacher_user_id}/documents',
            data={'upload_file': (io.BytesIO(b'MZ payload'), 'payroll.exe')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        with self.app.app_context():
            self.assertEqual(
                StaffDocument.query.filter_by(staff_id=self.teacher_user_id).count(), 0
            )

    def test_document_of_another_staff_member_is_not_reachable(self):
        """The URL carries both ids; they must agree or the document stays hidden."""
        self._login(self.vpa_id)
        self.client.post(
            f'/staff/folders/{self.teacher_user_id}/documents',
            data={
                'doc_type': 'medical',
                'upload_file': (io.BytesIO(b'%PDF-1.4 private'), 'medical.pdf'),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        with self.app.app_context():
            document_id = StaffDocument.query.filter_by(
                staff_id=self.teacher_user_id
            ).first().id

        mismatched = self.client.get(
            f'/staff/folders/{self.business_id}/documents/{document_id}/file'
        )
        self.assertEqual(mismatched.status_code, 404)

    def test_students_never_get_a_staff_folder(self):
        with self.app.app_context():
            student_user_id = self._make_user('student', 'Portal Student')
            db.session.commit()
        self._login(self.vpa_id)
        response = self.client.get(
            f'/staff/folders/{student_user_id}', follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('student', STAFF_FOLDER_ROLES)

    def test_search_filters_the_directory(self):
        self._login(self.vpa_id)
        hit = self.client.get('/staff/folders?q=Grace')
        self.assertIn(b'Grace Teacher', hit.data)
        miss = self.client.get('/staff/folders?q=zzzznotfound')
        self.assertNotIn(b'Grace Teacher', miss.data)


if __name__ == '__main__':
    unittest.main()
