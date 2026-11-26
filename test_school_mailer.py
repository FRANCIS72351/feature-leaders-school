import unittest
from unittest import mock

import school_mailer as mailer


class SchoolMailerTests(unittest.TestCase):
    def test_status_hides_password(self):
        env = {
            'SMTP_SERVER': 'smtp-relay.brevo.com',
            'SMTP_PORT': '587',
            'SMTP_LOGIN': 'login@smtp-brevo.com',
            'SMTP_PASSWORD': 'secret-key',
            'SENDER_EMAIL': 'flpaschool.notice@flpa2015.com',
            'SENDER_NAME': 'Future Leaders Preparatory Academy',
        }
        with mock.patch.dict('os.environ', env, clear=False):
            status = mailer.mailer_status()
        self.assertTrue(status['configured'])
        blob = str(status)
        self.assertNotIn('secret-key', blob)
        self.assertEqual(status['host'], 'smtp-relay.brevo.com')

    def test_rejects_bad_recipient(self):
        with self.assertRaises(ValueError):
            mailer.build_message(to_addrs='not-an-email', subject='Hi', body_text='x')

    def test_build_message_uses_school_from(self):
        env = {
            'SMTP_LOGIN': 'login@smtp-brevo.com',
            'SMTP_PASSWORD': 'secret-key',
            'SENDER_EMAIL': 'flpaschool.notice@flpa2015.com',
            'SENDER_NAME': 'Future Leaders Preparatory Academy',
        }
        with mock.patch.dict('os.environ', env, clear=False):
            msg, envelope = mailer.build_message(
                to_addrs='parent@example.com',
                subject='New class activity',
                body_text='A task was posted.',
                html_body='<p>A task was posted.</p>',
            )
        self.assertIn('flpaschool.notice@flpa2015.com', msg['From'])
        self.assertEqual(envelope, ['parent@example.com'])
        self.assertTrue(msg.is_multipart())
        self.assertTrue(msg['Date'])
        self.assertIn('flpa2015.com', msg['Message-ID'])
        self.assertIn('notices.flpa2015.com', msg['List-Id'])
        self.assertEqual(msg['Organization'], 'Future Leaders Preparatory Academy')
        self.assertIsNone(msg['List-Unsubscribe'])

    def test_gmail_sender_is_replaced_with_school_domain(self):
        env = {
            'SMTP_LOGIN': 'login@smtp-brevo.com',
            'SMTP_PASSWORD': 'secret-key',
            'SENDER_EMAIL': 'flpaschool.notice@gmail.com',
            'SMTP_REPLY_TO': 'flpaschool.notice@gmail.com',
        }
        with mock.patch.dict('os.environ', env, clear=False):
            cfg = mailer.mail_config()
            msg, _envelope = mailer.build_message(
                to_addrs='parent@gmail.com',
                subject='FLPA notice',
                body_text='Official school notice.',
                cfg=cfg,
            )
        self.assertEqual(cfg['sender_email'], 'flpaschool.notice@flpa2015.com')
        self.assertEqual(cfg['reply_to'], 'flpaschool.notice@flpa2015.com')
        self.assertIn('flpaschool.notice@flpa2015.com', msg['From'])
        self.assertNotIn('gmail.com', msg['From'])

    def test_send_uses_starttls_and_login(self):
        env = {
            'SMTP_SERVER': 'smtp-relay.brevo.com',
            'SMTP_PORT': '587',
            'SMTP_LOGIN': 'login@smtp-brevo.com',
            'SMTP_PASSWORD': 'secret-key',
            'SENDER_EMAIL': 'flpaschool.notice@flpa2015.com',
        }
        smtp = mock.MagicMock()
        smtp.__enter__.return_value = smtp
        with mock.patch.dict('os.environ', env, clear=False):
            with mock.patch('school_mailer.smtplib.SMTP', return_value=smtp) as ctor:
                ok = mailer.send_school_email(
                    'parent@example.com',
                    'FLPA test',
                    'Hello from the academy.',
                )
        self.assertTrue(ok)
        ctor.assert_called()
        smtp.starttls.assert_called()
        smtp.login.assert_called_with('login@smtp-brevo.com', 'secret-key')
        smtp.send_message.assert_called()

    def test_placeholder_emails_are_rejected(self):
        self.assertFalse(mailer.account_email_looks_deliverable(''))
        self.assertFalse(mailer.account_email_looks_deliverable('not-an-email'))
        self.assertFalse(mailer.account_email_looks_deliverable('student@example.com'))
        self.assertFalse(mailer.account_email_looks_deliverable('noreply@flpa2015.com'))
        self.assertTrue(mailer.account_email_looks_deliverable('parent@gmail.com'))
        self.assertEqual(mailer.normalize_account_email('  Parent@Gmail.com '), 'parent@gmail.com')

    def test_public_links_rewrite_localhost_and_http(self):
        env = {'SITE_URL': 'http://127.0.0.1:3000', 'SENDER_EMAIL': 'flpaschool.notice@flpa2015.com'}
        with mock.patch.dict('os.environ', env, clear=False):
            self.assertEqual(mailer.public_site_base(), 'https://flpa2015.com')
            self.assertEqual(
                mailer.public_absolute_url('/account/verify-email/abc'),
                'https://flpa2015.com/account/verify-email/abc',
            )
            self.assertEqual(
                mailer.public_absolute_url('http://localhost:3000/account/verify-email/abc'),
                'https://flpa2015.com/account/verify-email/abc',
            )

    def test_class_notice_includes_unsubscribe_header(self):
        env = {
            'SMTP_LOGIN': 'login@smtp-brevo.com',
            'SMTP_PASSWORD': 'secret-key',
            'SENDER_EMAIL': 'flpaschool.notice@flpa2015.com',
            'SITE_URL': 'https://flpa2015.com',
        }
        with mock.patch.dict('os.environ', env, clear=False):
            msg, _envelope = mailer.build_message(
                to_addrs='parent@gmail.com',
                subject='FLPA class activity',
                body_text='A task was posted.',
                mail_kind='notice',
            )
        self.assertIn('/mail/unsubscribe', msg['List-Unsubscribe'])
        self.assertEqual(msg['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')

    def test_html_escapes_untrusted_text(self):
        html_body = mailer._branded_html(
            'Task <b>one</b>',
            'Hello <script>alert(1)</script>',
            [('Notes', '<img src=x onerror=alert(1)>')],
            button_url='https://flpa2015.com/login',
        )
        self.assertNotIn('<script>', html_body)
        self.assertIn('&lt;script&gt;', html_body)
        self.assertIn('Task &lt;b&gt;one&lt;/b&gt;', html_body)

    def test_account_email_form_rejects_placeholders(self):
        from flask import Flask
        from forms import AccountEmailForm

        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test'
        app.config['WTF_CSRF_ENABLED'] = False
        with app.test_request_context():
            bad = AccountEmailForm(
                new_email='student@example.com',
                current_password='secret12',
            )
            self.assertFalse(bad.validate())
            good = AccountEmailForm(
                new_email='  Parent@Gmail.com ',
                current_password='secret12',
            )
            self.assertTrue(good.validate())
            self.assertEqual(good.new_email.data, 'parent@gmail.com')

    def test_live_grade_notice_draft_copy(self):
        subject, text, html = mailer.compose_student_grade_update(
            student_name='James Kollie',
            first_name='James',
            class_name='Grade 8A',
            teacher_name='Mrs. Williams',
            items=[{
                'title': 'Quiz 3',
                'subject': 'Mathematics',
                'period_label': 'Period 2',
                'score_text': '18 / 20',
                'visibility': 'draft',
            }],
        )
        self.assertIn('live score was posted', subject)
        self.assertIn('James', subject)
        self.assertIn('18 / 20', text)
        self.assertIn('Live draft on My Grades', text)
        self.assertIn('not yet the official report card', text)
        self.assertIn('/student/dashboard?tab=grades', text)
        self.assertIn('Quiz 3', html)
        self.assertIn('Open My Grades', html)
        self.assertNotIn('unsubscribe', html.lower())

    def test_live_grade_notice_published_copy(self):
        subject, text, html = mailer.compose_student_grade_update(
            student_name='James Kollie',
            first_name='James',
            class_name='Grade 11 Science',
            teacher_name='Mr. Toe',
            items=[{
                'title': 'Period standing',
                'subject': 'Biology',
                'period_label': 'Period 4',
                'score': 86,
                'visibility': 'published',
            }],
        )
        self.assertIn('submitted for academic release', subject)
        self.assertIn('86', text)
        self.assertIn('academic office stamps', text)
        self.assertIn('Official Transcript', html)

    def test_digital_receipt_copy(self):
        subject, text, html = mailer.compose_digital_payment_receipt(
            student_name='James Kollie',
            first_name='James',
            student_id='2526-00021',
            class_name='Grade 8A',
            receipt_number='REG-000184',
            amount_text='US$ 150.00',
            particulars='First Semester · 1st Installment',
            fee_label='School fees',
            academic_year='2025-2026',
            paid_on='22 Nov 2026',
            collected_at='Business Office',
            received_by='Business Manager',
            balance_text='US$ 350.00 remaining on school fees this year',
        )
        self.assertIn('digital receipt REG-000184', subject)
        self.assertIn('US$ 150.00', text)
        self.assertIn('2526-00021', text)
        self.assertIn('live digital receipt', text)
        self.assertIn('electronic receipt', html)
        self.assertIn('Open My Account', html)
        self.assertIn('/student/dashboard?tab=account', html)
        self.assertIn('REG-000184', html)

    def test_format_notice_score(self):
        self.assertEqual(mailer._format_notice_score(18, 20), '18 / 20')
        self.assertEqual(mailer._format_notice_score(91.0), '91')

    def test_proprietor_income_notice_copy(self):
        subject, text, html = mailer.compose_proprietor_transaction_notice(
            kind='fee',
            amount_text='US$ 150.00',
            particulars='First Semester · 1st Installment',
            party='James Kollie (2526-00021)',
            receipt_number='REG-000184',
            collected_at='Business Office',
            recorded_by='Business Manager',
            academic_year='2025-2026',
            paid_on='23 Nov 2026 17:24',
            method='Cash',
        )
        self.assertIn('money came in', subject)
        self.assertIn('US$ 150.00', subject)
        self.assertIn('James Kollie', text)
        self.assertIn('REG-000184', text)
        self.assertIn('/proprietor/dashboard', text)
        self.assertIn('School Proprietor only', html)
        self.assertIn('Open live school board', html)

    def test_proprietor_expense_notice_copy(self):
        subject, text, html = mailer.compose_proprietor_transaction_notice(
            kind='expense',
            amount_text='US$ 80.00',
            particulars='Diesel for generator',
            party='Fuel',
            collected_at='Business ledger',
            recorded_by='Business Manager',
            paid_on='23 Nov 2026',
        )
        self.assertIn('money went out', subject)
        self.assertIn('US$ 80.00', text)
        self.assertIn('Diesel for generator', html)


if __name__ == '__main__':
    unittest.main()
