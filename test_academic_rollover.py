import unittest
import uuid
from datetime import date
from types import SimpleNamespace

from app import (
    app,
    check_promotion_criteria,
    evaluate_year_promotion_decision,
    execute_academic_rollover,
    execute_moe_academic_rollover,
    find_academic_year_by_name,
    get_class_registration_fee,
    preview_moe_academic_rollover,
    promotion_pass_score,
    max_failing_subjects_for_promotion,
    repeat_class_failing_subject_threshold,
    save_class_registration_fees,
    build_default_promotion_map,
    build_report_card_structured_data,
    _academic_year_id_prefix,
    _default_id_expiration_date,
    _next_academic_year_name,
    _parse_grade_level,
    _principal_build_class_portfolios,
    _principal_students_for_class,
    _student_ids_with_year_history,
    _students_for_display_year,
    _sync_student_id_card,
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
                    submitted=True,
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

    def _replace_subject_scores(self, student, year, class_id, scores):
        Grade.query.filter_by(student_id=student.id, academic_year_id=year.id).delete(
            synchronize_session=False,
        )
        for subject, score in scores:
            grade = Grade(
                student_id=student.id,
                academic_year_id=year.id,
                class_id=class_id,
                subject=subject,
                subject_name=subject,
                score=score,
                marking_period=1,
                submitted=True,
            )
            db.session.add(grade)
            db.session.flush()
            self.created_ids['grades'].append(grade.id)
        db.session.commit()

    def test_promotion_config_defaults(self):
        with self.app.app_context():
            self.assertEqual(promotion_pass_score(), 70)
            self.assertEqual(max_failing_subjects_for_promotion(), 2)
            self.assertEqual(repeat_class_failing_subject_threshold(), 3)

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
            self.assertEqual(preview['summer_school'], 0)

            next_class = Class(name=f'Grade 11 {uuid.uuid4().hex[:6]}', grade_level=11)
            db.session.add(next_class)
            db.session.flush()
            self.created_ids['classes'].append(next_class.id)
            from app import build_rollover_preview
            classes = Class.query.filter(Class.id.in_([self.class_id, next_class.id])).all()
            wizard_preview = build_rollover_preview(year, classes, [student])
            self.assertEqual(wizard_preview['counts']['repeat'], 1)
            self.assertEqual(wizard_preview['counts']['promote'], 0)

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

    def test_parse_grade_level_accepts_ordinal_and_labeled_values(self):
        self.assertEqual(_parse_grade_level(12), 12)
        self.assertEqual(_parse_grade_level('12'), 12)
        self.assertEqual(_parse_grade_level('12th'), 12)
        self.assertEqual(_parse_grade_level('Grade 12'), 12)
        self.assertEqual(_parse_grade_level('11th'), 11)
        self.assertEqual(_parse_grade_level('10th'), 10)
        self.assertEqual(_parse_grade_level('SSS 3'), 12)
        self.assertIsNone(_parse_grade_level(None))
        self.assertIsNone(_parse_grade_level(''))

    def test_grade_12_ordinal_is_treated_as_graduation(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            student.grade_level = '12th'
            db.session.commit()
            year = db.session.get(AcademicYear, self.year_id)
            decision = evaluate_year_promotion_decision(student, year)
            self.assertTrue(decision['passed'])
            self.assertEqual(decision['code'], 'GRADUATED')

    def test_promotion_map_matches_ordinal_grade_labels(self):
        with self.app.app_context():
            tenth = Class(name=f'G10 {uuid.uuid4().hex[:6]}', grade_level='10th')
            eleventh = Class(name=f'G11 {uuid.uuid4().hex[:6]}', grade_level='11th')
            twelfth = Class(name=f'G12 {uuid.uuid4().hex[:6]}', grade_level='12th')
            db.session.add_all([tenth, eleventh, twelfth])
            db.session.flush()
            self.created_ids['classes'].extend([tenth.id, eleventh.id, twelfth.id])
            promo = build_default_promotion_map([tenth, eleventh, twelfth])
            self.assertEqual(promo[tenth.id], eleventh.id)
            self.assertEqual(promo[eleventh.id], twelfth.id)
            self.assertEqual(promo[twelfth.id], 'graduate')

    def test_moe_rollover_includes_repeat_students_and_clears_status(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            student = db.session.get(Student, self.student_id)
            source_year = db.session.get(AcademicYear, self.year_id)
            student.status = 'REPEAT'
            span_start = 4100 + (uuid.uuid4().int % 400)
            source_year.name = f'{span_start}-{span_start + 1}'
            source_year.start_date = date(span_start, 9, 1)
            source_year.end_date = date(span_start + 1, 6, 30)
            next_class = Class(name=f'Grade 11 {uuid.uuid4().hex[:6]}', grade_level=11)
            db.session.add(next_class)
            db.session.flush()
            self.created_ids['classes'].append(next_class.id)
            for year in AcademicYear.query.filter(AcademicYear.id != source_year.id).all():
                year.is_active = False
            source_year.is_active = True
            db.session.commit()

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                results = execute_moe_academic_rollover(
                    source_year, allow_repeat_today=True,
                )

            db.session.expire_all()
            student = db.session.get(Student, self.student_id)
            self.assertEqual(results['promoted'], 1)
            self.assertNotEqual(student.academic_year_id, source_year.id)
            self.assertEqual(student.status, 'ACTIVE')
            self.assertEqual(_parse_grade_level(student.grade_level), 11)
            if student.academic_year_id and student.academic_year_id not in self.created_ids['years']:
                self.created_ids['years'].append(student.academic_year_id)

    def test_student_id_prefix_normalizes_endash_year_names(self):
        with self.app.app_context():
            year = db.session.get(AcademicYear, self.year_id)
            year.name = '2025–2026'
            self.assertEqual(_academic_year_id_prefix(year), '2526')
            self.assertEqual(_next_academic_year_name('2025–2026'), '2026-2027')
            self.assertEqual(_next_academic_year_name('2026/2027'), '2027-2028')

    def test_id_card_expiration_refreshes_when_prior_year_date_is_stale(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            student.id_expiration_date = date(2024, 6, 30)
            _sync_student_id_card(student, academic_year=year)
            self.assertEqual(student.id_expiration_date, year.end_date)
            self.assertEqual(_default_id_expiration_date(year), year.end_date)

    def test_longevity_year_helpers_work_ten_to_fifteen_years_ahead(self):
        with self.app.app_context():
            self.assertEqual(_parse_grade_level('12th'), 12)
            self.assertEqual(_parse_grade_level('Grade 12'), 12)
            self.assertEqual(_next_academic_year_name('2035-2036'), '2036-2037')
            self.assertEqual(_next_academic_year_name('2035–36'), '2036-2037')
            self.assertEqual(_next_academic_year_name('2040/2041'), '2041-2042')
            self.assertEqual(_next_academic_year_name('2099-00'), '2100-2101')
            year_2035 = SimpleNamespace(name='2035–2036', id=99, end_date=None, start_date=None)
            year_2040 = SimpleNamespace(
                name='2040-2041', id=100, end_date=date(2041, 6, 30), start_date=date(2040, 9, 1),
            )
            year_name_only = SimpleNamespace(
                name='2040-2041', id=101, end_date=None, start_date=None,
            )
            self.assertEqual(_academic_year_id_prefix(year_2035), '3536')
            self.assertEqual(_academic_year_id_prefix(year_2040), '4041')
            self.assertEqual(_default_id_expiration_date(year_2040), date(2041, 6, 30))
            self.assertEqual(_default_id_expiration_date(year_name_only), date(2041, 7, 31))

    def test_promotion_map_advances_kindergarten_and_grade_twelve(self):
        with self.app.app_context():
            token = uuid.uuid4().hex[:6]
            k2 = Class(name=f'K-2 {token}', grade_level='K-2')
            first = Class(name=f'1st {token}', grade_level='1st')
            twelfth = Class(name=f'12 {token}', grade_level='12th')
            db.session.add_all([k2, first, twelfth])
            db.session.flush()
            self.created_ids['classes'].extend([k2.id, first.id, twelfth.id])
            promo = build_default_promotion_map([k2, first, twelfth])
            self.assertEqual(promo[k2.id], first.id)
            self.assertEqual(promo[twelfth.id], 'graduate')

    def test_moe_rollover_finds_existing_endash_next_year(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            student = db.session.get(Student, self.student_id)
            source_year = db.session.get(AcademicYear, self.year_id)
            base = 4300 + (uuid.uuid4().int % 500)
            source_year.name = f'{base}-{base + 1}'
            source_year.start_date = date(base, 9, 1)
            source_year.end_date = date(base + 1, 6, 30)
            next_year = AcademicYear(
                name=f'{base + 1}–{base + 2}',
                start_date=date(base + 1, 9, 1),
                end_date=date(base + 2, 6, 30),
                is_active=False,
                created_by=self.admin_id,
            )
            db.session.add(next_year)
            db.session.flush()
            self.created_ids['years'].append(next_year.id)
            for year in AcademicYear.query.filter(AcademicYear.id != source_year.id).all():
                year.is_active = False
            source_year.is_active = True
            student.status = 'ACTIVE'
            db.session.commit()

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                results = execute_moe_academic_rollover(
                    source_year, allow_repeat_today=True,
                )

            db.session.expire_all()
            found = find_academic_year_by_name(f'{base + 1}-{base + 2}')
            self.assertIsNotNone(found)
            self.assertEqual(found.id, next_year.id)
            self.assertEqual(results['target_year_name'], next_year.name)
            student = db.session.get(Student, self.student_id)
            self.assertEqual(student.academic_year_id, next_year.id)

    def test_grade_twelve_still_graduates_in_2040(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            token = uuid.uuid4().hex[:6]
            twelfth = Class(name=f'Grade 12 {token}', grade_level='12th')
            db.session.add(twelfth)
            db.session.flush()
            self.created_ids['classes'].append(twelfth.id)
            base = 4600 + (uuid.uuid4().int % 300)
            year = AcademicYear(
                name=f'{base}-{base + 1}',
                start_date=date(base, 9, 1),
                end_date=date(base + 1, 6, 30),
                is_active=True,
                created_by=self.admin_id,
            )
            db.session.add(year)
            db.session.flush()
            self.created_ids['years'].append(year.id)
            senior = Student(
                student_id=f'G12{token.upper()}',
                first_name='Future',
                last_name='Graduate',
                dob=date(2023, 5, 1),
                gender='F',
                klass_id=twelfth.id,
                grade_level='12th',
                academic_year_id=year.id,
                status='ACTIVE',
            )
            db.session.add(senior)
            db.session.flush()
            self.created_ids['students'].append(senior.id)
            for subject, score in [('Mathematics', 88), ('English', 84), ('Science', 80)]:
                grade = Grade(
                    student_id=senior.id,
                    academic_year_id=year.id,
                    class_id=twelfth.id,
                    subject=subject,
                    subject_name=subject,
                    score=score,
                    marking_period=1,
                    submitted=True,
                )
                db.session.add(grade)
                db.session.flush()
                self.created_ids['grades'].append(grade.id)
            for other in AcademicYear.query.filter(AcademicYear.id != year.id).all():
                other.is_active = False
            db.session.commit()

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                results = execute_moe_academic_rollover(year, allow_repeat_today=True)

            db.session.expire_all()
            senior = db.session.get(Student, senior.id)
            self.assertEqual(results['graduated'], 1)
            self.assertEqual((senior.status or '').upper(), 'ALUMNI')
            self.assertEqual(senior.academic_year_id, year.id)
            if senior.academic_year_id and senior.academic_year_id not in self.created_ids['years']:
                self.created_ids['years'].append(senior.academic_year_id)
            next_created = find_academic_year_by_name(f'{base + 1}-{base + 2}')
            if next_created and next_created.id not in self.created_ids['years']:
                self.created_ids['years'].append(next_created.id)

    def test_two_failing_yearly_averages_assign_summer_school_not_promote(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 90),
                ('English', 90),
                ('Science', 90),
                ('History', 65),
                ('French', 65),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 2)
            self.assertAlmostEqual(decision['overall_average'], 80.0)
            self.assertFalse(decision['passed'])
            self.assertFalse(check_promotion_criteria(student, year))
            self.assertEqual(decision['code'], 'SUMMER_SCHOOL')
            self.assertEqual(decision['decision'], 'summer_school')
            self.assertEqual(decision['label'], 'Summer School')
            self.assertIn('Summer School', decision['reason'])
            self.assertIn('not promoted', decision['reason'])

            preview = preview_moe_academic_rollover(year)
            self.assertEqual(preview['summer_school'], 1)
            self.assertEqual(preview['promoted'], 0)
            self.assertEqual(preview['retained'], 0)

            from app import build_rollover_preview
            next_class = Class(name=f'Grade 11 {uuid.uuid4().hex[:6]}', grade_level=11)
            db.session.add(next_class)
            db.session.flush()
            self.created_ids['classes'].append(next_class.id)
            classes = Class.query.filter(Class.id.in_([self.class_id, next_class.id])).all()
            wizard_preview = build_rollover_preview(year, classes, [student])
            self.assertEqual(wizard_preview['counts']['summer_school'], 1)
            self.assertEqual(wizard_preview['counts']['promote'], 0)
            self.assertEqual(wizard_preview['counts']['repeat'], 0)

    def test_three_failing_yearly_averages_repeat_despite_high_overall(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 100),
                ('English', 100),
                ('Science', 100),
                ('History', 100),
                ('French', 65),
                ('Physical Education', 65),
                ('Computer Science', 65),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 3)
            self.assertAlmostEqual(decision['overall_average'], 85.0)
            self.assertFalse(decision['passed'])
            self.assertEqual(decision['code'], 'REPEAT')
            self.assertEqual(decision['decision'], 'repeat')
            self.assertEqual(decision['label'], 'Repeat class')
            self.assertIn('regardless of the overall yearly average', decision['reason'])
            self.assertNotIn('reparting', decision['reason'].lower())
            self.assertNotIn('reparting', decision['label'].lower())

    def test_one_failing_yearly_average_promotes_when_overall_meets_moe(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 80),
                ('English', 80),
                ('Science', 80),
                ('History', 60),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 1)
            self.assertAlmostEqual(decision['overall_average'], 75.0)
            self.assertTrue(decision['passed'])
            self.assertTrue(check_promotion_criteria(student, year))
            self.assertEqual(decision['code'], 'PROMOTED')
            self.assertEqual(decision['decision'], 'promote')
            self.assertEqual(decision['label'], 'Promoted')

    def test_conduct_fail_does_not_count_toward_red_marks(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 80),
                ('English', 75),
                ('Science', 72),
                ('CONDUCT', 40),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 0)
            self.assertTrue(decision['passed'])
            self.assertEqual(decision['code'], 'PROMOTED')

            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 90),
                ('English', 90),
                ('Science', 90),
                ('History', 65),
                ('French', 65),
                ('CONDUCT', 40),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 2)
            self.assertEqual(decision['code'], 'SUMMER_SCHOOL')
            self.assertNotEqual(decision['code'], 'REPEAT')

    def test_grade_12_two_reds_summer_school_not_graduate(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            student.grade_level = 12
            db.session.commit()
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 90),
                ('English', 90),
                ('Science', 90),
                ('History', 65),
                ('French', 65),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertFalse(decision['passed'])
            self.assertEqual(decision['code'], 'SUMMER_SCHOOL')
            self.assertEqual(decision['decision'], 'summer_school')
            self.assertEqual(decision['label'], 'Summer School')
            self.assertIn('not eligible to graduate', decision['reason'])

    def test_grade_12_three_reds_repeat_not_graduate(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            student.grade_level = 12
            db.session.commit()
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 100),
                ('English', 100),
                ('Science', 100),
                ('History', 100),
                ('French', 65),
                ('Physical Education', 65),
                ('Computer Science', 65),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertFalse(decision['passed'])
            self.assertEqual(decision['code'], 'REPEAT')
            self.assertEqual(decision['decision'], 'repeat')
            self.assertEqual(decision['label'], 'Repeat class')
            self.assertIn('not eligible to graduate', decision['reason'])

    def test_moe_rollover_keeps_summer_school_students_in_current_class(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            student = db.session.get(Student, self.student_id)
            source_year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, source_year, self.class_id, [
                ('Mathematics', 90),
                ('English', 90),
                ('Science', 90),
                ('History', 65),
                ('French', 65),
            ])
            span_start = 4500 + (uuid.uuid4().int % 400)
            source_year.name = f'{span_start}-{span_start + 1}'
            source_year.start_date = date(span_start, 9, 1)
            source_year.end_date = date(span_start + 1, 6, 30)
            next_class = Class(name=f'Grade 11 {uuid.uuid4().hex[:6]}', grade_level=11)
            db.session.add(next_class)
            db.session.flush()
            self.created_ids['classes'].append(next_class.id)
            for year in AcademicYear.query.filter(AcademicYear.id != source_year.id).all():
                year.is_active = False
            source_year.is_active = True
            db.session.commit()

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                results = execute_moe_academic_rollover(
                    source_year, allow_repeat_today=True,
                )

            db.session.expire_all()
            student = db.session.get(Student, self.student_id)
            self.assertEqual(results['summer_school'], 1)
            self.assertEqual(results['promoted'], 0)
            self.assertEqual(results['retained'], 0)
            self.assertEqual(student.status, 'SUMMER_SCHOOL')
            self.assertEqual(_parse_grade_level(student.grade_level), 10)
            self.assertEqual(student.klass_id, self.class_id)
            self.assertNotEqual(student.academic_year_id, source_year.id)
            if student.academic_year_id and student.academic_year_id not in self.created_ids['years']:
                self.created_ids['years'].append(student.academic_year_id)

    def test_average_footer_row_does_not_count_as_red_subject(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 90),
                ('English', 90),
                ('Science', 90),
                ('History', 65),
                ('French', 65),
                ('AVERAGE', 40),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 2)
            self.assertEqual(decision['code'], 'SUMMER_SCHOOL')
            self.assertNotEqual(decision['code'], 'REPEAT')

            data = build_report_card_structured_data(student, year.id)
            self.assertEqual(data['promotion']['code'], 'SUMMER_SCHOOL')
            self.assertEqual(data['promotion']['label'], 'Summer School')
            printed_names = [row['name'] for row in data['subjects']]
            self.assertIn('AVERAGE', printed_names)

    def test_one_red_repeats_when_overall_below_moe(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 70),
                ('English', 70),
                ('History', 50),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 1)
            self.assertAlmostEqual(decision['overall_average'], 63.33, places=1)
            self.assertFalse(decision['passed'])
            self.assertEqual(decision['code'], 'REPEAT')
            self.assertEqual(decision['label'], 'Repeat class')
            self.assertFalse(check_promotion_criteria(student, year))

    def test_two_reds_with_low_overall_still_summer_school(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 50),
                ('English', 50),
                ('Science', 80),
            ])
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 2)
            self.assertAlmostEqual(decision['overall_average'], 60.0)
            self.assertEqual(decision['code'], 'SUMMER_SCHOOL')
            self.assertEqual(decision['label'], 'Summer School')
            self.assertFalse(check_promotion_criteria(student, year))

    def test_unsubmitted_failing_drafts_do_not_count_as_red_marks(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 80),
                ('English', 80),
                ('Science', 80),
            ])
            for subject, score in [('History', 40), ('French', 40)]:
                grade = Grade(
                    student_id=student.id,
                    academic_year_id=year.id,
                    class_id=self.class_id,
                    subject=subject,
                    subject_name=subject,
                    score=score,
                    marking_period=1,
                    submitted=False,
                )
                db.session.add(grade)
                db.session.flush()
                self.created_ids['grades'].append(grade.id)
            db.session.commit()
            decision = evaluate_year_promotion_decision(student, year)
            self.assertEqual(decision['failing_subject_count'], 0)
            self.assertEqual(decision['code'], 'PROMOTED')

            data = build_report_card_structured_data(student, year.id)
            self.assertEqual(data['promotion']['code'], 'PROMOTED')
            self.assertEqual(data['promotion']['label'], 'Promoted')

    def test_moe_rollover_keeps_repeaters_in_current_class(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            student = db.session.get(Student, self.student_id)
            source_year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, source_year, self.class_id, [
                ('Mathematics', 100),
                ('English', 100),
                ('Science', 100),
                ('History', 100),
                ('French', 65),
                ('Physical Education', 65),
                ('Computer Science', 65),
            ])
            span_start = 4700 + (uuid.uuid4().int % 400)
            source_year.name = f'{span_start}-{span_start + 1}'
            source_year.start_date = date(span_start, 9, 1)
            source_year.end_date = date(span_start + 1, 6, 30)
            next_class = Class(name=f'Grade 11 {uuid.uuid4().hex[:6]}', grade_level=11)
            db.session.add(next_class)
            db.session.flush()
            self.created_ids['classes'].append(next_class.id)
            for year in AcademicYear.query.filter(AcademicYear.id != source_year.id).all():
                year.is_active = False
            source_year.is_active = True
            db.session.commit()

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                results = execute_moe_academic_rollover(
                    source_year, allow_repeat_today=True,
                )

            db.session.expire_all()
            student = db.session.get(Student, self.student_id)
            self.assertEqual(results['retained'], 1)
            self.assertEqual(results['promoted'], 0)
            self.assertEqual(results['summer_school'], 0)
            self.assertEqual(student.status, 'REPEAT')
            self.assertEqual(_parse_grade_level(student.grade_level), 10)
            self.assertEqual(student.klass_id, self.class_id)
            self.assertNotEqual(student.academic_year_id, source_year.id)
            if student.academic_year_id and student.academic_year_id not in self.created_ids['years']:
                self.created_ids['years'].append(student.academic_year_id)

    def test_grade_12_rollover_two_reds_summer_school_not_alumni(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            student = db.session.get(Student, self.student_id)
            twelfth = Class(name=f'Grade 12 {uuid.uuid4().hex[:6]}', grade_level=12)
            db.session.add(twelfth)
            db.session.flush()
            self.created_ids['classes'].append(twelfth.id)
            student.grade_level = 12
            student.klass_id = twelfth.id
            source_year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, source_year, twelfth.id, [
                ('Mathematics', 90),
                ('English', 90),
                ('Science', 90),
                ('History', 65),
                ('French', 65),
            ])
            span_start = 4800 + (uuid.uuid4().int % 400)
            source_year.name = f'{span_start}-{span_start + 1}'
            source_year.start_date = date(span_start, 9, 1)
            source_year.end_date = date(span_start + 1, 6, 30)
            for year in AcademicYear.query.filter(AcademicYear.id != source_year.id).all():
                year.is_active = False
            source_year.is_active = True
            db.session.commit()

            from flask_login import login_user
            with self.app.test_request_context():
                login_user(admin)
                results = execute_moe_academic_rollover(
                    source_year, allow_repeat_today=True,
                )

            db.session.expire_all()
            student = db.session.get(Student, self.student_id)
            if student.academic_year_id and student.academic_year_id not in self.created_ids['years']:
                self.created_ids['years'].append(student.academic_year_id)
            self.assertEqual(results['summer_school'], 1)
            self.assertEqual(results['graduated'], 0)
            self.assertEqual(student.status, 'SUMMER_SCHOOL')
            self.assertNotEqual((student.status or '').upper(), 'ALUMNI')
            self.assertEqual(_parse_grade_level(student.grade_level), 12)
            self.assertEqual(student.klass_id, twelfth.id)

    def test_report_and_grade_sheet_promotion_statement_matches_yrly_reds(self):
        with self.app.app_context():
            student = db.session.get(Student, self.student_id)
            year = db.session.get(AcademicYear, self.year_id)
            self._replace_subject_scores(student, year, self.class_id, [
                ('Mathematics', 100),
                ('English', 100),
                ('Science', 100),
                ('History', 100),
                ('French', 65),
                ('Physical Education', 65),
                ('Computer Science', 65),
            ])
            data = build_report_card_structured_data(student, year.id)
            self.assertEqual(data['promotion']['label'], 'Repeat class')
            self.assertNotIn('reparting', (data['promotion']['label'] or '').lower())
            self.assertNotIn('reparting', (data['promotion']['reason'] or '').lower())
            self.assertEqual(data['promotion']['failing_subject_count'], 3)
            self.assertFalse(data['promotion']['passed'])


if __name__ == '__main__':
    unittest.main()
