"""ID-card QR origin: SITE_URL wins over localhost; portal path is /student/id-portal/<token>."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from student_scanner import build_student_portal_qr_url, get_site_base_url, site_url_is_loopback

TUNNEL = 'https://wb9jv14t-3000.uks1.devtunnels.ms'


class SiteBaseUrlTests(unittest.TestCase):
    def test_loopback_request_uses_public_site_url(self):
        app = Flask(__name__)
        app.config['SITE_URL'] = TUNNEL
        with patch.dict(os.environ, {'SITE_URL': TUNNEL, 'PUBLIC_SITE_URL': TUNNEL}):
            with app.test_request_context('/id-cards/print/class/1', base_url='http://localhost:3000'):
                self.assertEqual(get_site_base_url(), TUNNEL)

    def test_trailing_slash_stripped(self):
        app = Flask(__name__)
        app.config['SITE_URL'] = TUNNEL + '/'
        with patch.dict(os.environ, {'SITE_URL': TUNNEL + '/', 'PUBLIC_SITE_URL': ''}):
            with app.test_request_context('/', base_url='http://127.0.0.1:3000'):
                self.assertEqual(get_site_base_url(), TUNNEL)

    def test_portal_qr_url_pattern(self):
        student = SimpleNamespace(secure_qr_token='TokEn_Example')
        self.assertEqual(
            build_student_portal_qr_url(student, base_url=TUNNEL),
            f'{TUNNEL}/student/id-portal/TokEn_Example',
        )

    def test_localhost_portal_url_is_loopback(self):
        self.assertTrue(site_url_is_loopback('http://localhost:3000/student/id-portal/abc'))
        self.assertFalse(site_url_is_loopback(f'{TUNNEL}/student/id-portal/abc'))


if __name__ == '__main__':
    unittest.main()
