"""Registry Day Book — collect fees, receipt numbers, daily handover."""
import uuid
import unittest
from datetime import date

from app import app, ensure_legacy_sqlite_schema, money
from constants import ROLE_BUSINESS, ROLE_REGISTRAR, ROLE_TEACHER
from models import AcademicYear, BusinessTransaction, Class, RegistryDailyHandover, Student, StudentPayment, User, db
from registry_desk import COLLECTION_DESK_REGISTRY, HANDOVER_ACKNOWLEDGED, HANDOVER_OPEN, HANDOVER_SUBMITTED


class RegistryDayBookTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()
        self.unique = uuid.uuid4().hex[:8]
        self.ids = {'users': [], 'students': [], 'classes': [], 'years': [], 'payments': [], 'handovers': []}
        with self.app.app_context():
            ensure_legacy_sqlite_schema()
            registrar = User(
                email=f'reg-desk-{self.unique}@test.com',
                full_name='Desk Registrar',
                role=ROLE_REGISTRAR,
            )
            registrar.set_password('password')
            teacher = User(
                email=f'teach-desk-{self.unique}@test.com',
                full_name='Desk Teacher',
                role=ROLE_TEACHER,
            )
            teacher.set_password('password')
            business = User(
                email=f'biz-desk-{self.unique}@test.com',
                full_name='Desk Business',
                role=ROLE_BUSINESS,
            )
            business.set_password('password')
            db.session.add_all([registrar, teacher, business])
            db.session.flush()
            self.registrar_id = registrar.id
            self.teacher_id = teacher.id
            self.business_id = business.id
            self.ids['users'].extend([registrar.id, teacher.id, business.id])

            klass = Class(name=f'Day Book {self.unique}', grade_level='6th')
            db.session.add(klass)
            db.session.flush()
            self.class_id = klass.id
            self.ids['classes'].append(klass.id)

            year = AcademicYear(
                name=f'20{self.unique[:2]}/20{self.unique[2:4]}',
                start_date=date(2099, 9, 1),
                end_date=date(2100, 6, 30),
                is_active=True,
                created_by=registrar.id,
            )
            db.session.add(year)
            db.session.flush()
            self.year_id = year.id
            self.ids['years'].append(year.id)

            student = Student(
                student_id=f'88{self.unique[:2]}-{int(self.unique[:4], 16) % 90000 + 10000:05d}',
                first_name='Kofi',
                last_name='Till',
                dob=date(2014, 1, 2),
                gender='Male',
                klass_id=klass.id,
                academic_year_id=year.id,
                is_registered=True,
            )
            db.session.add(student)
            db.session.commit()
            self.student_id = student.id
            self.student_code = student.student_id
            self.ids['students'].append(student.id)

    def tearDown(self):
        with self.app.app_context():
            StudentPayment.query.filter(StudentPayment.student_id.in_(self.ids['students'] or [0])).delete(synchronize_session=False)
            RegistryDailyHandover.query.filter(RegistryDailyHandover.opened_by_user_id.in_(self.ids['users'] or [0])).delete(synchronize_session=False)
            Student.query.filter(Student.id.in_(self.ids['students'] or [0])).delete(synchronize_session=False)
            Class.query.filter(Class.id.in_(self.ids['classes'] or [0])).delete(synchronize_session=False)
            AcademicYear.query.filter(AcademicYear.id.in_(self.ids['years'] or [0])).delete(synchronize_session=False)
            User.query.filter(User.id.in_(self.ids['users'] or [0])).delete(synchronize_session=False)
            db.session.commit()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True

    def test_teacher_cannot_open_day_book(self):
        self._login(self.teacher_id)
        response = self.client.get('/registrar/day-book', follow_redirects=False)
        self.assertIn(response.status_code, (302, 401, 403))

    def test_registrar_sees_day_book(self):
        self._login(self.registrar_id)
        response = self.client.get('/registrar/day-book')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('Registry Day Book', body)
        self.assertIn('Pick class', body)
        self.assertIn('Process fee', body)
        self.assertIn('Review &amp; send', body)
        self.assertIn('US$', body)

    def test_class_list_then_student_fee(self):
        self._login(self.registrar_id)
        classes = self.client.get(f'/registrar/day-book?academic_year_id={self.year_id}')
        self.assertEqual(classes.status_code, 200)
        self.assertIn(f'Day Book {self.unique}', classes.get_data(as_text=True))
        roster = self.client.get(
            f'/registrar/day-book?academic_year_id={self.year_id}&class_id={self.class_id}'
        )
        self.assertEqual(roster.status_code, 200)
        body = roster.get_data(as_text=True)
        self.assertIn('Kofi', body)
        self.assertIn(self.student_code, body)
        desk = self.client.get(
            f'/registrar/day-book?academic_year_id={self.year_id}&class_id={self.class_id}&student_id={self.student_id}'
        )
        self.assertEqual(desk.status_code, 200)
        self.assertIn('Specific fee', desk.get_data(as_text=True))
        posted = self.client.post(
            '/registrar/day-book',
            data={
                'student_id': str(self.student_id),
                'class_id': str(self.class_id),
                'fee_kind': 'registration',
                'amount': '40',
                'term': '1',
                'day_book_action': 'collect',
            },
            follow_redirects=False,
        )
        self.assertEqual(posted.status_code, 302)
        self.assertIn('/registrar/day-book/receipts/', posted.headers.get('Location', ''))

    def test_collect_posts_ledger_and_receipt(self):
        self._login(self.registrar_id)
        response = self.client.post(
            '/registrar/day-book',
            data={
                'student_code': self.student_code,
                'fee_kind': 'registration',
                'amount': '75.50',
                'term': '1',
                'day_book_action': 'collect',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/registrar/day-book/receipts/', response.headers.get('Location', ''))
        with self.app.app_context():
            payment = StudentPayment.query.filter_by(student_id=self.student_id).order_by(StudentPayment.id.desc()).first()
            self.assertIsNotNone(payment)
            self.assertEqual(money(payment.amount_paid), 75.50)
            self.assertTrue((payment.receipt_number or '').startswith('REG-'))
            self.assertEqual(payment.collection_desk, COLLECTION_DESK_REGISTRY)
            self.assertEqual(payment.fee_kind, 'registration')
            handover = RegistryDailyHandover.query.filter_by(business_date=payment.paid_on.date() if payment.paid_on else None).order_by(RegistryDailyHandover.id.desc()).first()
            if handover is None:
                handover = RegistryDailyHandover.query.order_by(RegistryDailyHandover.id.desc()).first()
            self.assertIsNotNone(handover)
            self.assertEqual(handover.status, HANDOVER_OPEN)
            self.assertGreaterEqual(handover.receipt_count, 1)
        desk = self.client.get('/registrar/dashboard')
        self.assertEqual(desk.status_code, 200)
        self.assertIn('Daily collection report', desk.get_data(as_text=True))
        sheet = self.client.get('/registrar/day-book/sheet')
        self.assertEqual(sheet.status_code, 200)
        self.assertIn('Draft', sheet.get_data(as_text=True))
        self.assertIn('not sent', sheet.get_data(as_text=True).lower())
        self.client.get('/logout')
        self._login(self.business_id)
        inbox = self.client.get('/business/registry-records')
        self.assertEqual(inbox.status_code, 200)
        self.assertNotIn(self.student_code, inbox.get_data(as_text=True))

    def test_collect_lrd_prints_liberian_symbol(self):
        self._login(self.registrar_id)
        posted = self.client.post(
            '/registrar/day-book',
            data={
                'student_code': self.student_code,
                'fee_kind': 'documents',
                'amount': '185000',
                'currency': 'LRD',
                'term': '1',
                'day_book_action': 'collect',
            },
            follow_redirects=False,
        )
        self.assertEqual(posted.status_code, 302)
        location = posted.headers.get('Location', '')
        self.assertIn('/registrar/day-book/receipts/', location)
        with self.app.app_context():
            payment = StudentPayment.query.filter_by(student_id=self.student_id).order_by(StudentPayment.id.desc()).first()
            self.assertEqual(payment.currency, 'LRD')
        receipt = self.client.get(location)
        self.assertEqual(receipt.status_code, 200)
        body = receipt.get_data(as_text=True)
        self.assertIn('L$', body)
        self.assertIn('185,000.00', body)
        self.assertNotIn('Installment paid for', body)
        self.assertNotIn('First Semester', body)
        desk = self.client.get('/registrar/day-book')
        desk_body = desk.get_data(as_text=True)
        self.assertIn('US$', desk_body)
        self.assertIn('L$', desk_body)

    def test_close_day_and_business_acknowledge(self):
        self._login(self.registrar_id)
        self.client.post(
            '/registrar/day-book',
            data={
                'student_code': self.student_code,
                'fee_kind': 'id_card',
                'amount': '10',
                'term': '1',
                'day_book_action': 'collect',
            },
        )
        with self.app.app_context():
            payment = StudentPayment.query.filter_by(student_id=self.student_id).order_by(StudentPayment.id.desc()).first()
            payment_id = payment.id
        edited = self.client.post(
            '/registrar/day-book/sheet',
            data={
                'sheet_action': 'save_line',
                'payment_id': str(payment_id),
                'fee_kind': 'id_card',
                'amount': '10',
                'line_note': 'Corrected after count',
            },
            follow_redirects=False,
        )
        self.assertEqual(edited.status_code, 302)
        close = self.client.post(
            '/registrar/day-book/sheet',
            data={'sheet_action': 'send', 'notes': 'Cash counted.'},
            follow_redirects=False,
        )
        self.assertEqual(close.status_code, 302)
        self.assertIn('/registrar/day-book/record/', close.headers.get('Location', ''))
        with self.app.app_context():
            handover = RegistryDailyHandover.query.filter_by(opened_by_user_id=self.registrar_id).order_by(RegistryDailyHandover.id.desc()).first()
            if handover is None:
                handover = RegistryDailyHandover.query.order_by(RegistryDailyHandover.id.desc()).first()
            self.assertIsNotNone(handover)
            self.assertEqual(handover.status, HANDOVER_SUBMITTED)
            handover_id = handover.id
        self.client.get('/logout')
        self._login(self.business_id)
        inbox = self.client.get('/business/registry-records')
        self.assertEqual(inbox.status_code, 200)
        self.assertIn('Registry daily records', inbox.get_data(as_text=True))
        with self.app.app_context():
            payment = StudentPayment.query.filter_by(student_id=self.student_id).order_by(StudentPayment.id.desc()).first()
            marker = f'[SP-{payment.id}]'
            before = BusinessTransaction.query.filter(
                BusinessTransaction.description.like(f'%{marker}%'),
                BusinessTransaction.is_deleted.is_(False),
            ).first()
            self.assertIsNone(before)
        ack = self.client.post(
            f'/business/registry-records/{handover_id}/acknowledge',
            data={'business_notes': 'Cash received.'},
            follow_redirects=True,
        )
        self.assertEqual(ack.status_code, 200)
        self.assertIn('official school income', ack.get_data(as_text=True).lower())
        with self.app.app_context():
            row = db.session.get(RegistryDailyHandover, handover_id)
            self.assertEqual(row.status, HANDOVER_ACKNOWLEDGED)
            payment = StudentPayment.query.filter_by(student_id=self.student_id).order_by(StudentPayment.id.desc()).first()
            marker = f'[SP-{payment.id}]'
            income = BusinessTransaction.query.filter(
                BusinessTransaction.description.like(f'%{marker}%'),
                BusinessTransaction.is_deleted.is_(False),
            ).first()
            self.assertIsNotNone(income)
            self.assertEqual(money(income.amount), 10)


class LiberiaSchoolFeePlanTestCase(unittest.TestCase):
    def test_semester_and_installment_labels(self):
        from constants import billing_period_label, installment_label, semester_label
        self.assertEqual(semester_label(1), 'First Semester')
        self.assertEqual(semester_label(2), 'Second Semester')
        self.assertEqual(installment_label(1), '1st Installment')
        self.assertEqual(installment_label(3), '3rd Installment')
        self.assertEqual(billing_period_label(1, 2), 'First Semester · 2nd Installment')
        self.assertEqual(billing_period_label(2, 0), 'Second Semester · Full year settlement')

    def test_year_splits_into_two_semesters_and_three_installments(self):
        from types import SimpleNamespace
        from registry_desk import build_school_fee_plan
        payments = [
            SimpleNamespace(term=1, installment=1, amount_paid=100, fee_kind='tuition', description=''),
        ]
        plan = build_school_fee_plan(600, payments)
        self.assertEqual(plan['installment_fee'], 200.0)
        first = plan['installments']
        self.assertEqual(len(first), 3)
        self.assertEqual(first[0]['status'], 'partial')
        self.assertEqual(first[1]['status'], 'open')
        self.assertEqual(plan['suggested_installment'], 1)

    def test_only_school_fees_and_registration_reduce_yearly_bill(self):
        from types import SimpleNamespace
        from registry_desk import classify_student_payment, counts_toward_yearly_fee, payment_shows_semester_installment
        tuition = SimpleNamespace(fee_kind='tuition', description='School fees')
        registration = SimpleNamespace(fee_kind='registration', description='Registration fee')
        identity = SimpleNamespace(fee_kind='id_card', description='ID card replacement')
        self.assertTrue(counts_toward_yearly_fee(tuition))
        self.assertTrue(counts_toward_yearly_fee(registration))
        self.assertFalse(counts_toward_yearly_fee(identity))
        self.assertTrue(payment_shows_semester_installment(tuition))
        self.assertFalse(payment_shows_semester_installment(registration))
        self.assertFalse(payment_shows_semester_installment(identity))
        self.assertEqual(classify_student_payment(identity), 'other')
        from registry_desk import normalize_charge_period, registry_payment_description
        self.assertEqual(normalize_charge_period('id_card', 2, 3), (1, None))
        self.assertNotIn('Semester', registry_payment_description('documents', term=1, installment=2))
        id_payment = SimpleNamespace(term=1, installment=1, amount_paid=25, fee_kind='id_card', description='ID')
        from registry_desk import build_school_fee_plan
        plan = build_school_fee_plan(600, [id_payment])
        self.assertEqual(plan['installments'][0]['paid'], 0.0)


class LiberiaCurrencyFormatTestCase(unittest.TestCase):
    def test_professional_usd_and_lrd_symbols(self):
        from constants import format_dual_money, format_school_money, normalize_currency
        self.assertEqual(format_school_money(15000, 'USD'), 'US$ 15,000.00')
        self.assertEqual(format_school_money(185000, 'lrd'), 'L$ 185,000.00')
        self.assertEqual(normalize_currency('L$'), 'LRD')
        self.assertEqual(format_dual_money({'USD': 15, 'LRD': 200}), 'US$ 15.00  ·  L$ 200.00')


if __name__ == '__main__':
    unittest.main()
