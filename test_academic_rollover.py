import unittest
import uuid
from datetime import date

from app import (
    app,
    check_promotion_criteria,
    execute_academic_rollover,
    get_class_registration_fee,
    preview_moe_academic_rollover,
    promotion_pass_score,
    max_failing_subjects_for_promotion,
    save_class_registration_fees,
    _principal_build_class_portfolios,
    _principal_students_for_class,
    _student_ids_with_year_history,
    _students_for_display_year,
    get_active_academic_year,
)
from constants import ROLE_ADMIN
from models import (
    AcademicYear, BusinessTransaction, Class, Enrollment, Grade, RolloverLog,
    SchoolFee, Student, StudentPayment, User, db,
)


class AcademicRolloverTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'PROMOTION_PASS_SCORE': 70,
            'MAX_FAILING_SUBJECTS': 2,
        })
        self.test_email = f'rollover-test-{uuid.uuid4().hex}@test.com'
        self.created_ids = {
            'users': [], 'classes': [], 'years': [], 'students': [], 'grades': [],
            'school_fees': [], 'payments': [], 'transactions': [],
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

            admin = User(email=self.test_email, full_name='Rollover Admin', role=ROLE_ADMIN)
            admin.set_password('password')
            db.session.add(admin)
            db.session.flush()
            self.created_ids['users'].append(admin.id)
            self.admin_id = admin.id

            test_class = Class(name=f'Rollover Class {uuid.uuid4().hex[:8]}', grade_level=10)
            db.session.add(test_class)
            db.session.flush()
            self.created_ids['classes'].append(test_class.id)
            self.class_id = test_class.id

            test_year = AcademicYear(
                name=f'20{uuid.uuid4().hex[:2]}-20{uuid.uuid4().hex[:2]}',
                start_date=date(2025, 9, 1),
                end_date=date(2026, 6, 30),
                is_active=True,
                created_by=admin.id,
            )
            db.session.add(test_year)
            db.session.flush()
            self.created_ids['years'].append(test_year.id)
            self.year_id = test_year.id

            student = Student(
                student_id=f'ROL{uuid.uuid4().hex[:6].upper()}',
                first_name='Promo',
                last_name='Student',
                dob=date(2008, 1, 1),
                gender='M',
                klass_id=test_class.id,
                grade_level=10,
                academic_year_id=test_year.id,
                status='ACTIVE',
            )
            db.session.add(student)
            db.session.flush()
            self.created_ids['students'].append(student.id)
            self.student_id = student.id

            for subject, score in [('Mathematics', 80), ('English', 75), ('Science', 72)]:
                grade = Grade(
                    student_id=student.id,
                    academic_year_id=test_year.id,
                    class_id=test_class.id,
                    subject=subject,
                    subject_name=subject,
                    score=score,
                    marking_period=1,
                )
                db.session.add(grade)
                db.session.flush()
                self.created_ids['grades'].append(grade.id)

            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            RolloverLog.query.filter(RolloverLog.user_id.in_(self.created_ids['users'])).delete(
                synchronize_session=False
            )
            for tx_id in self.created_ids['transactions']:
                BusinessTransaction.query.filter_by(id=tx_id).delete(synchronize_session=False)
            for payment_id in self.created_ids['payments']:
                StudentPayment.query.filter_by(id=payment_id).delete(synchronize_session=False)
            for fee_id in self.created_ids['school_fees']:
                SchoolFee.query.filter_by(id=fee_id).delete(synchronize_session=False)
            for grade_id in self.created_ids['grades']:
                Grade.query.filter_by(id=grade_id).delete(synchronize_session=False)
            for student_id in self.created_ids['students']:
                Student.query.filter_by(id=student_id).delete(synchronize_session=False)
            for year_id in self.created_ids['years']:
                AcademicYear.query.filter_by(id=year_id).delete(synchronize_session=False)
            for class_id in self.created_ids['classes']:
                Class.query.filter_by(id=class_id).delete(synchronize_session=False)
            for user_id in self.created_ids['users']:
                User.query.filter_by(id=user_id).delete(synchronize_session=False)
            for year_id in self.prior_active_year_ids:
                year = db.session.get(AcademicYear, year_id)
                if year:
                    year.is_active = True
            db.session.commit()

    def login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['_fresh'] = True

    def test_promotion_config_defaults(self):
        with self.app.app_context():
            self.assertEqual(promotion_pass_score(), 70)
            self.assertEqual(max_failing_subjects_for_promotion(), 2)

    def test_check_promotion_criteria_passes(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self.assertTrue(check_promotion_criteria(student, year))

    def test_infer_grade_for_year_handles_string_grade_level(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            previous_year = AcademicYear(
                name=f'20{uuid.uuid4().hex[:2]}-20{uuid.uuid4().hex[:2]}',
                start_date=date(2024, 9, 1),
                end_date=date(2025, 6, 30),
                is_active=False,
                created_by=self.admin_id,
            )
            db.session.add(previous_year)
            db.session.flush()
            self.created_ids['years'].append(previous_year.id)

            student.grade_level = '10'
            db.session.commit()

            from app import _infer_student_grade_for_year
            inferred = _infer_student_grade_for_year(student, previous_year.id)
            active_year = get_active_academic_year()
            years_ordered = AcademicYear.query.order_by(
                AcademicYear.start_date.asc(),
            ).all()
            year_index = {year.id: index for index, year in enumerate(years_ordered)}
            expected = 10 - (
                year_index[active_year.id] - year_index[previous_year.id]
            )
            self.assertEqual(inferred, expected)

    def test_failing_student_preview_counts_failed(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)

            Grade.query.filter_by(student_id=student.id).update(
                {Grade.score: 55},
                synchronize_session=False,
            )
            db.session.commit()

            evaluation = check_promotion_criteria(student, year)
            self.assertFalse(evaluation)

            preview = preview_moe_academic_rollover(year)
            self.assertEqual(preview['retained'], 1)
            self.assertEqual(preview['promoted'], 0)
            self.assertEqual(preview['graduated'], 0)

    def test_preview_page_requires_login(self):
        response = self.client.get('/admin/academic-rollover')
        self.assertIn(response.status_code, (302, 401))

    def test_preview_page_shows_counts(self):
        self.login()
        response = self.client.get('/admin/academic-rollover')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Did Not Pass', response.data)
        self.assertIn(b'Execute Rollover', response.data)

    def test_preview_post_json(self):
        self.login()
        response = self.client.post(
            '/admin/academic-rollover',
            data={'preview': '1', 'format': 'json'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn('promoted', payload)
        self.assertEqual(payload['student_total'], 1)

    def test_save_class_registration_fees(self):
        with self.app.app_context():
            saved = save_class_registration_fees(
                self.year_id,
                {self.class_id: 150.0},
                included_class_ids={self.class_id},
            )
            db.session.commit()
            fee = SchoolFee.query.filter_by(
                academic_year_id=self.year_id,
                class_id=self.class_id,
                fee_type='registration',
            ).first()
            self.assertIsNotNone(fee)
            self.created_ids['school_fees'].append(fee.id)
            self.assertEqual(saved, 1)
            self.assertEqual(float(fee.amount), 150.0)
            self.assertEqual(get_class_registration_fee(self.class_id, self.year_id), 150.0)

    def test_wizard_rollover_posts_per_class_registration_income(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            second_class = Class(name=f'Fee Class {uuid.uuid4().hex[:6]}', grade_level=11)
            db.session.add(second_class)
            db.session.flush()
            self.created_ids['classes'].append(second_class.id)

            target_year = AcademicYear(
                name=f'Target {uuid.uuid4().hex[:6]}',
                start_date=date(2026, 9, 1),
                end_date=date(2027, 6, 30),
                is_active=False,
                created_by=admin.id,
            )
            db.session.add(target_year)
            db.session.flush()
            self.created_ids['years'].append(target_year.id)

            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(self.admin_id)
                sess['_fresh'] = True

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                results = execute_academic_rollover(
                    end_current_year=False,
                    target_mode='existing',
                    target_year_id=target_year.id,
                    new_year_name=None,
                    new_year_start=None,
                    new_year_end=None,
                    apply_promotions=False,
                    promotion_map={},
                    reset_tuition_cleared=False,
                    charge_registration_fee=True,
                    class_registration_fees={self.class_id: 200.0, second_class.id: 300.0},
                    included_class_ids={self.class_id, second_class.id},
                    exclude_statuses=set(),
                )

            self.assertEqual(results['fees_configured'], 2)
            self.assertEqual(results['fees_recorded'], 1)

            payment = StudentPayment.query.filter_by(
                student_id=self.student_id,
                academic_year_id=target_year.id,
            ).first()
            self.assertIsNotNone(payment)
            self.created_ids['payments'].append(payment.id)
            self.assertEqual(float(payment.amount_paid), 200.0)
            self.assertIn('registration', (payment.description or '').lower())

            income = BusinessTransaction.query.filter(
                BusinessTransaction.description.like(f'%[SP-{payment.id}]%'),
                BusinessTransaction.is_deleted.is_(False),
            ).first()
            self.assertIsNotNone(income)
            self.created_ids['transactions'].append(income.id)
            self.assertEqual(income.type, 'income')
            self.assertEqual(income.category, 'Registration Fees')
            self.assertEqual(float(income.amount), 200.0)

    def test_wizard_page_lists_class_fee_table(self):
        self.login()
        response = self.client.get('/academic-years/rollover')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Classes &amp; Registration Fees', response.data)
        self.assertIn(b'reg_fee_', response.data)
        self.assertIn(b'include_class_', response.data)

    def test_active_year_roster_uses_strict_enrollment_only(self):
        """Active year must not pull students who only have old-year grade history."""
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            source_year = db.session.get(AcademicYear, self.year_id)
            source_year.is_active = False
            old_year = AcademicYear(
                name=f'Old-{uuid.uuid4().hex[:6]}',
                start_date=date(2023, 9, 1),
                end_date=date(2024, 6, 30),
                is_active=False,
                created_by=admin.id,
            )
            new_year = AcademicYear(
                name=f'New-{uuid.uuid4().hex[:6]}',
                start_date=date(2024, 9, 1),
                end_date=date(2025, 6, 30),
                is_active=True,
                created_by=admin.id,
            )
            db.session.add_all([old_year, new_year])
            db.session.flush()
            self.created_ids['years'].extend([old_year.id, new_year.id])

            ghost = Student(
                student_id=f'GH{uuid.uuid4().hex[:6].upper()}',
                first_name='Ghost',
                last_name='History',
                dob=date(2009, 1, 1),
                gender='F',
                klass_id=self.class_id,
                grade_level=10,
                academic_year_id=new_year.id,
                status='ACTIVE',
            )
            db.session.add(ghost)
            db.session.flush()
            self.created_ids['students'].append(ghost.id)

            grade = Grade(
                student_id=ghost.id,
                academic_year_id=old_year.id,
                class_id=self.class_id,
                subject='Math',
                subject_name='Math',
                score=88,
                marking_period=1,
            )
            db.session.add(grade)
            db.session.flush()
            self.created_ids['grades'].append(grade.id)
            db.session.commit()

            live_ids = {
                s.id for s in _students_for_display_year(new_year, history_mode=False).all()
            }
            hist_ids = set(_student_ids_with_year_history(old_year.id))
            self.assertIn(ghost.id, live_ids)
            self.assertIn(ghost.id, hist_ids)

            live_roster = _principal_students_for_class(
                db.session.get(Class, self.class_id),
                new_year,
                viewing_archived=False,
            )
            self.assertEqual(len(live_roster), 1)
            self.assertEqual(live_roster[0].id, ghost.id)

            archived_roster = _principal_students_for_class(
                db.session.get(Class, self.class_id),
                old_year,
                viewing_archived=True,
            )
            self.assertEqual(len(archived_roster), 1)
            self.assertEqual(archived_roster[0].id, ghost.id)

    def test_rollover_moves_student_off_previous_year_roster(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            source_year = db.session.get(AcademicYear, self.year_id)
            for year in AcademicYear.query.filter(AcademicYear.id != source_year.id).all():
                year.is_active = False
            source_year.is_active = True
            db.session.commit()

            target_year = AcademicYear(
                name=f'Tgt-{uuid.uuid4().hex[:6]}',
                start_date=date(2026, 9, 1),
                end_date=date(2027, 6, 30),
                is_active=False,
                created_by=admin.id,
            )
            db.session.add(target_year)
            db.session.flush()
            self.created_ids['years'].append(target_year.id)

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                execute_academic_rollover(
                    end_current_year=False,
                    target_mode='existing',
                    target_year_id=target_year.id,
                    new_year_name=None,
                    new_year_start=None,
                    new_year_end=None,
                    apply_promotions=False,
                    promotion_map={},
                    reset_tuition_cleared=False,
                    charge_registration_fee=False,
                    class_registration_fees={},
                    included_class_ids=set(),
                    exclude_statuses=set(),
                )

            db.session.expire_all()
            student = db.session.get(Student, self.student_id)
            self.assertEqual(student.academic_year_id, target_year.id)
            self.assertFalse(student.is_registered)
            self.assertTrue(student.is_promoted)
            self.assertEqual(
                _students_for_display_year(source_year, history_mode=False).count(),
                0,
            )

            # Ensure source-year class enrollment is still recorded for historical access
            enrollments = Enrollment.query.filter_by(
                student_id=self.student_id,
                academic_year_id=source_year.id,
            ).all()
            self.assertGreaterEqual(len(enrollments), 1)
            self.assertEqual(enrollments[0].class_id, self.class_id)

            portfolios = _principal_build_class_portfolios(
                target_year, viewing_archived=False,
            )
            klass_portfolio = next(
                p for p in portfolios if p['klass'].id == self.class_id
            )
            self.assertEqual(klass_portfolio['student_count'], 0)


if __name__ == '__main__':
    unittest.main()
