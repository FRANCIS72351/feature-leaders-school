"""Attendance roll HTML shows student photos and full names with readable markup."""
import os
import unittest
import uuid
from datetime import date

from app import app
from models import (
    AcademicYear,
    Attendance,
    Class,
    ClassSubjectTeacher,
    Student,
    Teacher,
    User,
    _build_default_avatar_png_bytes,
    db,
)


class AttendanceRollPhotoTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        self.client = self.app.test_client()
        self.token = uuid.uuid4().hex[:8]
        self.created = {
            'users': [],
            'teachers': [],
            'classes': [],
            'years': [],
            'students': [],
            'allocs': [],
        }
        self.prior_active_year_ids = []
        self.photo_rel = f'uploads/photos/att_roll_{self.token}.png'
        self.photo_path = None
        self.student_name = 'Amina Rolltest'
        self.student_code = f'AR{self.token}-00001'

        with self.app.app_context():
            self.prior_active_year_ids = [
                year.id for year in AcademicYear.query.filter_by(is_active=True).all()
            ]
            AcademicYear.query.filter_by(is_active=True).update(
                {AcademicYear.is_active: False},
                synchronize_session=False,
            )

            teacher_user = User(
                email=f'teach-roll-{self.token}@test.com',
                full_name='Roll Teacher',
                role='teacher',
            )
            teacher_user.set_password('password')
            admin = User(
                email=f'admin-roll-{self.token}@test.com',
                full_name='Roll Admin',
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
                first_name='Roll',
                last_name='Teacher',
                status='ACTIVE',
            )
            db.session.add(teacher)
            db.session.flush()
            self.teacher_id = teacher.id
            self.created['teachers'].append(teacher.id)

            klass = Class(
                name=f'Roll Class {self.token}',
                grade_level='10',
                teacher_id=teacher.id,
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

            year = AcademicYear(
                name=f'AR{self.token}-26-27',
                start_date=date(2026, 9, 1),
                end_date=date(2027, 6, 30),
                is_active=True,
                created_by=admin.id,
            )
            db.session.add(year)
            db.session.flush()
            self.year_id = year.id
            self.created['years'].append(year.id)

            static_root = self.app.static_folder
            self.photo_path = os.path.join(static_root, self.photo_rel.replace('/', os.sep))
            os.makedirs(os.path.dirname(self.photo_path), exist_ok=True)
            with open(self.photo_path, 'wb') as fh:
                fh.write(_build_default_avatar_png_bytes())

            student = Student(
                student_id=self.student_code,
                first_name='Amina',
                last_name='Rolltest',
                dob=date(2009, 3, 14),
                gender='F',
                klass_id=klass.id,
                grade_level='10',
                academic_year_id=year.id,
                status='ACTIVE',
                is_registered=True,
                photo=self.photo_rel,
            )
            db.session.add(student)
            db.session.flush()
            self.student_id = student.id
            self.created['students'].append(student.id)
            self.photo_url = student.photo_url
            db.session.commit()

    def tearDown(self):
        if self.photo_path and os.path.isfile(self.photo_path):
            try:
                os.remove(self.photo_path)
            except OSError:
                pass
        with self.app.app_context():
            db.session.rollback()
            Attendance.query.filter(
                Attendance.student_id.in_(self.created['students'] or [0])
            ).delete(synchronize_session=False)
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

    def _assert_roll_identity(self, html):
        self.assertIn(self.student_name.encode(), html)
        self.assertIn(self.student_code.encode(), html)
        self.assertIn(b'att-student-photo', html)
        self.assertIn(b'alt="Amina Rolltest"', html)
        self.assertIn(self.photo_rel.encode(), html)
        self.assertIn(b'attendance_roll.css', html)
        self.assertIn(b'att-student-name', html)

    def test_teacher_attendance_roll_includes_photo_and_full_name(self):
        self._login(self.teacher_user_id)
        response = self.client.get(
            f'/teacher/class/{self.class_id}/attendance?date=2026-09-13'
        )
        self.assertEqual(response.status_code, 200)
        self._assert_roll_identity(response.data)
        self.assertIn(b'All Present', response.data)
        self.assertIn(b'All Late', response.data)
        self.assertIn(b'All Absent', response.data)
        self.assertIn(b'Not saved', response.data)
        self.assertIn(b'att-note-input', response.data)

    def test_class_day_roster_includes_photo_and_full_name(self):
        self._login(self.admin_id)
        response = self.client.get(
            f'/attendance/class/{self.class_id}/day/2026-09-13'
        )
        self.assertEqual(response.status_code, 200)
        self._assert_roll_identity(response.data)
        self.assertIn(b'Class Roster', response.data)


if __name__ == '__main__':
    unittest.main()
