import unittest
import uuid
from datetime import date

from app import (
    app,
    get_or_create_grade_release,
    mark_grade_package_pending_vpa,
    student_official_documents_state,
    STUDENT_GRADE_HOLD_MESSAGE,
    STUDENT_REPORT_CARD_HOLD_MESSAGE,
    STUDENT_PERIOD_HOLD_MESSAGE,
    awaiting_vpa_periods_note,
    build_report_card_structured_data,
    evaluate_class_rank,
    _competition_ranks,
    _ordinal_rank,
)
from models import AcademicYear, Class, Grade, GradeRelease, Student, User, db


class GradeReleaseAccessTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
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

            vpa = User(
                email=f'vpa-{self.token}@test.com',
                full_name='VPA Reviewer',
                role='vpa',
            )
            vpa.set_password('password')
            student_user = User(
                email=f'student-{self.token}@test.com',
                full_name='Portal Student',
                role='student',
            )
            student_user.set_password('password')
            db.session.add_all([vpa, student_user])
            db.session.flush()
            self.created['users'].extend([vpa.id, student_user.id])
            self.vpa_id = vpa.id
            self.student_user_id = student_user.id

            klass = Class(name=f'Release Class {self.token}', grade_level=10)
            db.session.add(klass)
            db.session.flush()
            self.created['classes'].append(klass.id)
            self.class_id = klass.id

            year = AcademicYear(
                name=f'20{self.token[:2]}-20{self.token[2:4]}',
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=True,
                created_by=vpa.id,
            )
            db.session.add(year)
            db.session.flush()
            self.created['years'].append(year.id)
            self.year_id = year.id

            student = Student(
                student_id=f'GR{self.token.upper()}',
                first_name='Portal',
                last_name='Student',
                dob=date(2008, 1, 1),
                gender='F',
                klass_id=klass.id,
                grade_level=10,
                academic_year_id=year.id,
                user_id=student_user.id,
                status='ACTIVE',
                is_registered=True,
            )
            db.session.add(student)
            db.session.flush()
            self.created['students'].append(student.id)
            self.student_id = student.id

            grade = Grade(
                student_id=student.id,
                academic_year_id=year.id,
                class_id=klass.id,
                subject='Mathematics',
                subject_name='Mathematics',
                score=88,
                marking_period=1,
                period=1,
                submitted=True,
            )
            db.session.add(grade)
            db.session.flush()
            self.created['grades'].append(grade.id)

            release = GradeRelease(
                academic_year_id=year.id,
                class_id=klass.id,
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
            if self.created['years'] or self.created['classes']:
                GradeRelease.query.filter(
                    db.or_(
                        GradeRelease.academic_year_id.in_(self.created['years'] or [0]),
                        GradeRelease.class_id.in_(self.created['classes'] or [0]),
                    )
                ).delete(synchronize_session=False)
            for release_id in self.created['releases']:
                GradeRelease.query.filter_by(id=release_id).delete(synchronize_session=False)
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
            AcademicYear.query.filter(AcademicYear.id.in_(self.prior_active_year_ids)).update(
                {AcademicYear.is_active: True},
                synchronize_session=False,
            )
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_pending_blocks_student_html_and_pdf(self):
        self._login(self.student_user_id)
        sheet = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertEqual(sheet.status_code, 200)
        self.assertIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), sheet.data)
        self.assertNotIn(b'Published Grade Sheet', sheet.data)

        pdf = self.client.get(f'/student/grade-sheet/pdf?academic_year_id={self.year_id}')
        self.assertEqual(pdf.status_code, 200)
        self.assertIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), pdf.data)
        self.assertNotIn(b'application/pdf', (pdf.mimetype or '').encode())

        report = self.client.get(
            f'/report-card/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(report.status_code, 200)
        self.assertIn(STUDENT_REPORT_CARD_HOLD_MESSAGE.encode(), report.data)

        download = self.client.get(
            f'/download-report-card/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn(STUDENT_REPORT_CARD_HOLD_MESSAGE.encode(), download.data)

    def test_unpublished_is_not_student_visible(self):
        with self.app.app_context():
            Grade.query.filter_by(id=self.created['grades'][0]).update(
                {Grade.submitted: False},
                synchronize_session=False,
            )
            GradeRelease.query.filter_by(id=self.release_id).update(
                {GradeRelease.status: GradeRelease.STATUS_DRAFT},
                synchronize_session=False,
            )
            db.session.commit()
            student = db.session.get(Student, self.student_id)
            state = student_official_documents_state(student, self.year_id)
            self.assertFalse(state['unlocked'])
            self.assertFalse(state['hold'])
            self.assertTrue(state['empty'])

        self._login(self.student_user_id)
        sheet = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertEqual(sheet.status_code, 200)
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), sheet.data)
        self.assertIn(b'No published grades', sheet.data)

    def test_approved_period_unlocks_only_that_period_sheet(self):
        """Approving one period releases its grade sheet, never the report card."""
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            db.session.commit()

        self._login(self.student_user_id)
        sheet = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertEqual(sheet.status_code, 200)
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), sheet.data)
        self.assertIn(b'Published Grade Sheet', sheet.data)
        self.assertIn(b'1st / 1', sheet.data)

        report = self.client.get(
            f'/report-card/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(report.status_code, 200)
        self.assertIn(STUDENT_REPORT_CARD_HOLD_MESSAGE.encode(), report.data)

    def test_report_card_unlocks_when_final_period_is_approved(self):
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            self._add_approved_period(6)
            db.session.commit()
            student = db.session.get(Student, self.student_id)
            state = student_official_documents_state(student, self.year_id)
            self.assertTrue(state['report_card_unlocked'])

        self._login(self.student_user_id)
        report = self.client.get(
            f'/report-card/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(report.status_code, 200)
        self.assertNotIn(STUDENT_REPORT_CARD_HOLD_MESSAGE.encode(), report.data)

    def test_gap_in_earlier_period_keeps_report_card_sealed(self):
        """Final period approved is not enough while an earlier period is pending."""
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_PENDING_VPA
            self._add_approved_period(6)
            db.session.commit()
            student = db.session.get(Student, self.student_id)
            state = student_official_documents_state(student, self.year_id)
            self.assertFalse(state['report_card_unlocked'])
            self.assertIn('Period 1', state['report_card_blocker_note'])

    def test_period_sheet_has_no_yearly_average(self):
        """A single approved period must not print SEM.AVE or YEARLY figures."""
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            db.session.commit()
            student = db.session.get(Student, self.student_id)
            data = build_report_card_structured_data(
                student, self.year_id, approved_only=True, view_period=1,
            )
            self.assertEqual(data['scope'], 'period')
            self.assertIsNone(data['promotion'])
            maths = next(
                row for row in data['subjects']
                if row['name'].lower().startswith('math')
            )
            self.assertEqual(str(maths['p1']), '88')
            self.assertEqual(maths['sem1'], '')
            self.assertEqual(maths['sem2'], '')
            self.assertEqual(maths['final_avg'], '')
            self.assertEqual(maths['yearly'], '')

    def test_republish_resets_approval_and_blocks_students(self):
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            db.session.commit()
            mark_grade_package_pending_vpa(
                self.year_id, self.class_id, 1, actor_id=self.vpa_id,
            )
            db.session.commit()
            release = db.session.get(GradeRelease, self.release_id)
            self.assertEqual(release.status, GradeRelease.STATUS_PENDING_VPA)
            student = db.session.get(Student, self.student_id)
            state = student_official_documents_state(student, self.year_id)
            self.assertTrue(state['hold'])
            self.assertFalse(state['unlocked'])

        self._login(self.student_user_id)
        sheet = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), sheet.data)

    def test_vpa_can_approve_and_staff_can_preview_while_pending(self):
        self._login(self.vpa_id)
        preview = self.client.get(
            f'/report-card/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertEqual(preview.status_code, 200)
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), preview.data)

        approve = self.client.post(
            f'/vpa/grade-releases/{self.release_id}/approve',
            follow_redirects=True,
        )
        self.assertEqual(approve.status_code, 200)
        self.assertIn(b'approved', approve.data.lower())

        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            self.assertEqual(release.status, GradeRelease.STATUS_APPROVED)

        self._login(self.student_user_id)
        sheet = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), sheet.data)

    def test_year_query_param_cannot_bypass_pending_gate(self):
        with self.app.app_context():
            other_year = AcademicYear(
                name=f'Alt-{self.token}',
                start_date=date(2024, 9, 1),
                end_date=date(2025, 6, 30),
                is_active=False,
                created_by=self.vpa_id,
            )
            db.session.add(other_year)
            db.session.flush()
            self.created['years'].append(other_year.id)
            other_grade = Grade(
                student_id=self.student_id,
                academic_year_id=other_year.id,
                class_id=self.class_id,
                subject='Mathematics',
                subject_name='Mathematics',
                score=91,
                marking_period=1,
                period=1,
                submitted=True,
            )
            db.session.add(other_grade)
            db.session.flush()
            self.created['grades'].append(other_grade.id)
            other_release = GradeRelease(
                academic_year_id=other_year.id,
                class_id=self.class_id,
                period=1,
                status=GradeRelease.STATUS_APPROVED,
            )
            db.session.add(other_release)
            db.session.flush()
            self.created['releases'].append(other_release.id)
            db.session.commit()
            other_year_id = other_year.id

        self._login(self.student_user_id)
        pending_year = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), pending_year.data)
        approved_year = self.client.get(f'/student/grade-sheet?academic_year_id={other_year_id}')
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), approved_year.data)
        self.assertIn(b'Published Grade Sheet', approved_year.data)

    def _add_period_two_pending(self):
        with self.app.app_context():
            grade = Grade(
                student_id=self.student_id,
                academic_year_id=self.year_id,
                class_id=self.class_id,
                subject='Mathematics',
                subject_name='Mathematics',
                score=76,
                marking_period=2,
                period=2,
                submitted=True,
            )
            db.session.add(grade)
            db.session.flush()
            self.created['grades'].append(grade.id)
            release = get_or_create_grade_release(self.year_id, self.class_id, 2)
            release.status = GradeRelease.STATUS_PENDING_VPA
            db.session.commit()
            self.created['releases'].append(release.id)
            return release.id

    def _add_approved_period(self, period, score=80):
        """Submit and approve one more marking period for the same class."""
        grade = Grade(
            student_id=self.student_id,
            academic_year_id=self.year_id,
            class_id=self.class_id,
            subject='Mathematics',
            subject_name='Mathematics',
            score=score,
            marking_period=period,
            period=period,
            submitted=True,
        )
        db.session.add(grade)
        db.session.flush()
        self.created['grades'].append(grade.id)
        release = get_or_create_grade_release(self.year_id, self.class_id, period)
        release.status = GradeRelease.STATUS_APPROVED
        db.session.flush()
        self.created['releases'].append(release.id)
        return release.id

    def test_release_is_unique_per_year_class_period(self):
        with self.app.app_context():
            first = get_or_create_grade_release(self.year_id, self.class_id, 1)
            second = get_or_create_grade_release(self.year_id, self.class_id, 1)
            period_two = get_or_create_grade_release(self.year_id, self.class_id, 2)
            self.created['releases'].extend([first.id, second.id, period_two.id])
            self.assertEqual(first.id, second.id)
            self.assertEqual(first.period, 1)
            self.assertNotEqual(first.id, period_two.id)
            self.assertEqual(period_two.period, 2)
            self.assertEqual(period_two.academic_year_id, self.year_id)
            self.assertEqual(period_two.class_id, self.class_id)

    def test_approved_period_stays_visible_when_later_period_is_pending(self):
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            db.session.commit()
            self._add_period_two_pending()
            student = db.session.get(Student, self.student_id)
            state = student_official_documents_state(student, self.year_id)
            self.assertTrue(state['unlocked'])
            self.assertFalse(state['hold'])
            self.assertEqual(state['approved_periods'], [1])
            self.assertEqual(state['pending_periods'], [2])
            self.assertIn('Period 2', state['awaiting_note'])

        self._login(self.student_user_id)
        sheet = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertEqual(sheet.status_code, 200)
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), sheet.data)
        self.assertIn(b'Published Grade Sheet', sheet.data)
        self.assertIn(b'88', sheet.data)
        self.assertIn(b'>AVERAGE<', sheet.data)
        self.assertIn(b'>CONDUCT<', sheet.data)
        self.assertIn(b'RANK IN CLASS:', sheet.data)
        self.assertIn(awaiting_vpa_periods_note([2]).encode(), sheet.data)
        self.assertNotIn(b'>76<', sheet.data)

        # The report card stays sealed: Period 2 is pending and the year is unfinished.
        report = self.client.get(
            f'/report-card/{self.student_id}?academic_year_id={self.year_id}'
        )
        self.assertIn(STUDENT_REPORT_CARD_HOLD_MESSAGE.encode(), report.data)

    def test_single_period_view_gates_only_that_period(self):
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            db.session.commit()
            self._add_period_two_pending()
            student = db.session.get(Student, self.student_id)
            period_one = student_official_documents_state(student, self.year_id, period=1)
            period_two = student_official_documents_state(student, self.year_id, period=2)
            self.assertTrue(period_one['unlocked'])
            self.assertFalse(period_one['hold'])
            self.assertFalse(period_two['unlocked'])
            self.assertTrue(period_two['hold'])

        self._login(self.student_user_id)
        approved_view = self.client.get(
            f'/student/grade-sheet?academic_year_id={self.year_id}&period=1'
        )
        self.assertIn(b'Published Grade Sheet', approved_view.data)
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), approved_view.data)

        pending_view = self.client.get(
            f'/student/grade-sheet?academic_year_id={self.year_id}&period=2'
        )
        self.assertIn(STUDENT_PERIOD_HOLD_MESSAGE.encode(), pending_view.data)
        self.assertNotIn(b'Published Grade Sheet', pending_view.data)

        pending_report = self.client.get(
            f'/report-card/{self.student_id}?academic_year_id={self.year_id}&period=2'
        )
        self.assertIn(STUDENT_REPORT_CARD_HOLD_MESSAGE.encode(), pending_report.data)

    def test_republish_period_two_does_not_hide_period_one(self):
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            db.session.commit()
            period_two_id = self._add_period_two_pending()
            period_two = db.session.get(GradeRelease, period_two_id)
            period_two.status = GradeRelease.STATUS_APPROVED
            db.session.commit()
            mark_grade_package_pending_vpa(
                self.year_id, self.class_id, 2, actor_id=self.vpa_id,
            )
            db.session.commit()
            period_one = db.session.get(GradeRelease, self.release_id)
            period_two = db.session.get(GradeRelease, period_two_id)
            self.assertEqual(period_one.status, GradeRelease.STATUS_APPROVED)
            self.assertEqual(period_two.status, GradeRelease.STATUS_PENDING_VPA)
            student = db.session.get(Student, self.student_id)
            state = student_official_documents_state(student, self.year_id)
            self.assertTrue(state['unlocked'])
            self.assertFalse(state['hold'])
            self.assertEqual(state['approved_periods'], [1])
            self.assertEqual(state['pending_periods'], [2])

        self._login(self.student_user_id)
        sheet = self.client.get(f'/student/grade-sheet?academic_year_id={self.year_id}')
        self.assertNotIn(STUDENT_GRADE_HOLD_MESSAGE.encode(), sheet.data)
        self.assertIn(b'Published Grade Sheet', sheet.data)
        self.assertIn(b'88', sheet.data)

    def test_vpa_queue_lists_each_class_period(self):
        with self.app.app_context():
            release = db.session.get(GradeRelease, self.release_id)
            release.status = GradeRelease.STATUS_APPROVED
            db.session.commit()
            self._add_period_two_pending()

        self._login(self.vpa_id)
        queue = self.client.get('/vpa/grade-releases')
        self.assertEqual(queue.status_code, 200)
        self.assertIn('Period 2'.encode('utf-8'), queue.data)
        self.assertIn(' — Period 2'.encode('utf-8'), queue.data)


class ClassRankTestCase(unittest.TestCase):
    """Class rank uses the same approved yearly average the grade sheet prints."""

    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
        })
        self.token = uuid.uuid4().hex[:8]
        self.created = {
            'users': [], 'classes': [], 'years': [], 'students': [],
            'grades': [], 'releases': [],
        }
        self.prior_active_year_ids = []
        with self.app.app_context():
            self.prior_active_year_ids = [
                y.id for y in AcademicYear.query.filter_by(is_active=True).all()
            ]
            AcademicYear.query.filter_by(is_active=True).update(
                {AcademicYear.is_active: False},
                synchronize_session=False,
            )

            vpa = User(
                email=f'rank-vpa-{self.token}@test.com',
                full_name='Rank VPA',
                role='vpa',
            )
            vpa.set_password('password')
            db.session.add(vpa)
            db.session.flush()
            self.created['users'].append(vpa.id)
            self.vpa_id = vpa.id

            class_a = Class(name=f'Grade 8A {self.token}', grade_level=8)
            class_b = Class(name=f'Grade 8B {self.token}', grade_level=8)
            db.session.add_all([class_a, class_b])
            db.session.flush()
            self.created['classes'].extend([class_a.id, class_b.id])
            self.class_a_id = class_a.id
            self.class_b_id = class_b.id

            year = AcademicYear(
                name=f'Rank-{self.token}',
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=True,
                created_by=vpa.id,
            )
            db.session.add(year)
            db.session.flush()
            self.created['years'].append(year.id)
            self.year_id = year.id

            self.student_ids = {}
            roster = (
                ('ann', class_a.id, 90),
                ('ben', class_a.id, 80),
                ('cam', class_a.id, 80),
                ('dot', class_a.id, 70),
                ('eli', class_b.id, 99),
                ('fay', class_a.id, None),
            )
            for name, class_id, score in roster:
                student = Student(
                    student_id=f'RK{self.token.upper()}{name[:2].upper()}',
                    first_name=name.title(),
                    last_name='Rank',
                    dob=date(2012, 1, 1),
                    gender='F',
                    klass_id=class_id,
                    grade_level=8,
                    academic_year_id=year.id,
                    status='ACTIVE',
                    is_registered=True,
                )
                db.session.add(student)
                db.session.flush()
                self.created['students'].append(student.id)
                self.student_ids[name] = student.id
                if score is None:
                    continue
                grade = Grade(
                    student_id=student.id,
                    academic_year_id=year.id,
                    class_id=class_id,
                    subject='Mathematics',
                    subject_name='Mathematics',
                    score=score,
                    marking_period=1,
                    period=1,
                    submitted=True,
                )
                db.session.add(grade)
                db.session.flush()
                self.created['grades'].append(grade.id)

            for class_id in (class_a.id, class_b.id):
                release = GradeRelease(
                    academic_year_id=year.id,
                    class_id=class_id,
                    period=1,
                    status=GradeRelease.STATUS_APPROVED,
                )
                db.session.add(release)
                db.session.flush()
                self.created['releases'].append(release.id)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            if self.created['years'] or self.created['classes']:
                GradeRelease.query.filter(
                    db.or_(
                        GradeRelease.academic_year_id.in_(self.created['years'] or [0]),
                        GradeRelease.class_id.in_(self.created['classes'] or [0]),
                    )
                ).delete(synchronize_session=False)
            for release_id in self.created['releases']:
                GradeRelease.query.filter_by(id=release_id).delete(synchronize_session=False)
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
            AcademicYear.query.filter(AcademicYear.id.in_(self.prior_active_year_ids)).update(
                {AcademicYear.is_active: True},
                synchronize_session=False,
            )
            db.session.commit()

    def _student(self, name):
        return db.session.get(Student, self.student_ids[name])

    def test_competition_ranking_is_1224(self):
        ranks = _competition_ranks({1: 90, 2: 80, 3: 80, 4: 70})
        self.assertEqual(ranks, {1: 1, 2: 2, 3: 2, 4: 4})
        self.assertEqual(_ordinal_rank(1), '1st')
        self.assertEqual(_ordinal_rank(2), '2nd')
        self.assertEqual(_ordinal_rank(3), '3rd')
        self.assertEqual(_ordinal_rank(4), '4th')
        self.assertEqual(_ordinal_rank(11), '11th')
        self.assertEqual(_ordinal_rank(21), '21st')
        self.assertEqual(_ordinal_rank(113), '113th')

    def test_rank_uses_klass_id_not_grade_level(self):
        with self.app.app_context():
            ann = evaluate_class_rank(self._student('ann'), self.year_id, approved_only=True)
            ben = evaluate_class_rank(self._student('ben'), self.year_id, approved_only=True)
            cam = evaluate_class_rank(self._student('cam'), self.year_id, approved_only=True)
            dot = evaluate_class_rank(self._student('dot'), self.year_id, approved_only=True)
            eli = evaluate_class_rank(self._student('eli'), self.year_id, approved_only=True)
            fay = evaluate_class_rank(self._student('fay'), self.year_id, approved_only=True)

            self.assertEqual(ann['rank'], 1)
            self.assertEqual(ann['of'], 4)
            self.assertEqual(ann['label'], '1st / 4')
            self.assertEqual(ben['rank'], 2)
            self.assertEqual(cam['rank'], 2)
            self.assertEqual(cam['label'], '2nd / 4')
            self.assertEqual(dot['rank'], 4)
            self.assertEqual(dot['label'], '4th / 4')
            # Same grade level, other section — ranked only inside 8B.
            self.assertEqual(eli['rank'], 1)
            self.assertEqual(eli['of'], 1)
            self.assertEqual(eli['label'], '1st / 1')
            # No comparable scores — sheet keeps —.
            self.assertIsNone(fay)

    def test_structured_data_includes_class_rank(self):
        with self.app.app_context():
            data = build_report_card_structured_data(
                self._student('ann'), self.year_id, approved_only=True,
            )
            self.assertEqual(data['class_rank']['label'], '1st / 4')
            empty = build_report_card_structured_data(
                self._student('fay'), self.year_id, approved_only=True,
            )
            self.assertIsNone(empty['class_rank'])

    def test_structured_data_appends_average_and_conduct(self):
        with self.app.app_context():
            data = build_report_card_structured_data(
                self._student('ann'), self.year_id, approved_only=True,
            )
            names = [row['name'] for row in data['subjects']]
            self.assertEqual(names[-2], 'AVERAGE')
            self.assertEqual(names[-1], 'CONDUCT')
            self.assertTrue(data['subjects'][-2]['is_summary'])
            self.assertTrue(data['subjects'][-1]['is_summary'])
            average = data['subjects'][-2]
            conduct = data['subjects'][-1]
            self.assertEqual(average['p1'], 90)
            self.assertEqual(average['final_avg'], '90.00%')
            self.assertEqual(conduct['p1'], '')
            self.assertEqual(conduct['final_avg'], '')

    def test_conduct_grades_fill_conduct_row_not_average(self):
        with self.app.app_context():
            extra = Grade(
                student_id=self.student_ids['ann'],
                academic_year_id=self.year_id,
                class_id=self.class_a_id,
                subject='CONDUCT',
                subject_name='CONDUCT',
                score=40,
                marking_period=1,
                period=1,
                submitted=True,
            )
            db.session.add(extra)
            db.session.flush()
            self.created['grades'].append(extra.id)
            db.session.commit()

            data = build_report_card_structured_data(
                self._student('ann'), self.year_id, approved_only=True,
            )
            names = [row['name'] for row in data['subjects']]
            self.assertEqual(names.count('CONDUCT'), 1)
            self.assertNotIn('CONDUCT', names[:-1])
            average = data['subjects'][-2]
            conduct = data['subjects'][-1]
            self.assertEqual(average['p1'], 90)
            self.assertEqual(conduct['p1'], 40)

    def test_unapproved_period_does_not_change_rank(self):
        with self.app.app_context():
            # Ann's pending P2 would beat Ben if it counted (90+100)/2 vs 80.
            extra = Grade(
                student_id=self.student_ids['ann'],
                academic_year_id=self.year_id,
                class_id=self.class_a_id,
                subject='Mathematics',
                subject_name='Mathematics',
                score=100,
                marking_period=2,
                period=2,
                submitted=True,
            )
            db.session.add(extra)
            db.session.flush()
            self.created['grades'].append(extra.id)
            release = get_or_create_grade_release(self.year_id, self.class_a_id, 2)
            release.status = GradeRelease.STATUS_PENDING_VPA
            db.session.commit()
            self.created['releases'].append(release.id)

            approved = evaluate_class_rank(
                self._student('ann'), self.year_id, approved_only=True,
            )
            staff = evaluate_class_rank(
                self._student('ann'), self.year_id, approved_only=False,
            )
            self.assertEqual(approved['rank'], 1)
            self.assertEqual(approved['of'], 4)
            self.assertEqual(approved['average'], 90)
            # Staff sheet includes submitted P2, so Ann's yearly rises but rank stays 1.
            self.assertGreater(staff['average'], approved['average'])
            self.assertEqual(staff['rank'], 1)


if __name__ == '__main__':
    unittest.main()
