"""ID card folder PDF — filename and CR80 batch bytes, no student PII."""
import base64
import re
import unittest
import zlib
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from reportlab.lib.colors import HexColor


def _pdf_content_text(payload):
    """Decompress ReportLab page streams so tests can see drawn strings."""
    chunks = []
    for match in re.finditer(rb'stream\r?\n(.*?)endstream', payload, re.S):
        raw = match.group(1).strip()
        decoded = raw
        try:
            if raw.endswith(b'~>'):
                decoded = base64.a85decode(raw, adobe=True)
        except Exception:
            decoded = raw
        try:
            decoded = zlib.decompress(decoded)
        except Exception:
            pass
        chunks.append(decoded)
    return b'\n'.join(chunks)

from app import app, persist_student_guardian_name, _id_cards_pdf_attachment_response
from id_card_pdf import (
    CARDINAL_DEFAULT,
    NAVY,
    PHOTO_COVER_SCALE,
    PHOTO_FIT,
    PHOTO_POSITION_Y,
    PHOTO_WELL_MM,
    ID_CARD_STAFF_FOOTER_HEX,
    ID_CARD_STUDENT_FOOTER_HEX,
    PRINCIPAL_SIGNATORY_TITLE,
    id_photo_contain_rect,
    build_class_id_cards_pdf,
    id_card_footer_fill,
    id_card_header_title,
    id_cards_pdf_filename,
    principal_signature_disk_path,
    resolve_id_card_parent_name,
)
from models import resolve_parent_guardian_name


class IdCardPdfTestCase(unittest.TestCase):
    def test_class_folder_filename(self):
        klass = SimpleNamespace(name='Grade 6A')
        year = SimpleNamespace(name='2025/2026')
        self.assertEqual(
            id_cards_pdf_filename(klass, year),
            'FLPA_ID_Cards_Grade_6A_2025_2026.pdf',
        )

    def test_single_card_filename(self):
        klass = SimpleNamespace(name='KG 1')
        year = SimpleNamespace(name='2025-2026')
        self.assertEqual(
            id_cards_pdf_filename(klass, year, single=True),
            'FLPA_ID_Card_KG_1_2025-2026.pdf',
        )

    def test_filename_normalizes_future_endash_year(self):
        klass = SimpleNamespace(name='12')
        year = SimpleNamespace(name='2040–2041')
        self.assertEqual(
            id_cards_pdf_filename(klass, year),
            'FLPA_ID_Cards_12_2040_2041.pdf',
        )

    def _school_brand(self):
        return {
            'name': 'Future Leaders Preparatory Academy',
            'full_address': 'Center Street, South Beach, Monrovia, Liberia',
            'phones': '0770000000',
            'motto': 'Honor, Excellence, Academics, Discipline, Success',
            'brand_red': '#c82828',
        }

    def _assert_front_and_back_headers(self, drawn):
        """Front draws the school name; back keeps Republic of Liberia."""
        self.assertIn(b'FUTURE LEADERS', drawn)
        self.assertIn(b'PREPARATORY', drawn)
        self.assertIn(b'ACADEMY', drawn)
        self.assertIn(b'REPUBLIC OF LIBERIA', drawn)

    def test_id_card_header_title_helper(self):
        self.assertEqual(id_card_header_title(), 'Future Leaders Preparatory Academy')
        self.assertEqual(
            id_card_header_title(side='front'),
            'Future Leaders Preparatory Academy',
        )
        self.assertEqual(
            id_card_header_title(side='front', uppercase=True),
            'FUTURE LEADERS PREPARATORY ACADEMY',
        )
        self.assertEqual(id_card_header_title(side='back'), 'Republic of Liberia')
        self.assertEqual(
            id_card_header_title(side='back', uppercase=True),
            'REPUBLIC OF LIBERIA',
        )

    def test_student_pdf_front_is_school_name_back_is_republic(self):
        student = SimpleNamespace(
            id=1,
            full_name='Test Student',
            student_id='FLPA-1001',
            parent_user=SimpleNamespace(full_name='Test Parent'),
            parent_phone='0770000000',
            id_expiration_date=date(2026, 7, 31),
            official_signature_mark='Student T.',
            signature_url=None,
        )
        buf = build_class_id_cards_pdf(
            [{'student': student, 'class_label': 'Grade 6A', 'qr_code_data_uri': None}],
            klass=SimpleNamespace(name='Grade 6A'),
            display_year=SimpleNamespace(name='2025-2026'),
            brand=self._school_brand(),
        )
        drawn = _pdf_content_text(buf.getvalue())
        self._assert_front_and_back_headers(drawn)

    def test_staff_pdf_front_is_school_name_back_is_republic(self):
        staff = SimpleNamespace(
            id=9,
            full_name='Test Staff',
            student_id='FLPA-0009',
            parent_user=None,
            parent_phone=None,
            telephone_number='0770000000',
            id_expiration_date=date(2027, 7, 31),
            official_signature_mark='Test S.',
            signature_url=None,
        )
        buf = build_class_id_cards_pdf(
            [
                {
                    'student': staff,
                    'card_kind': 'staff',
                    'staff_id': 'FLPA-0009',
                    'position': 'Teacher',
                    'qr_code_data_uri': None,
                    'signature_mark': 'Test S.',
                }
            ],
            brand=self._school_brand(),
        )
        drawn = _pdf_content_text(buf.getvalue())
        self._assert_front_and_back_headers(drawn)
        self.assertIn(b'STAFF', drawn)
        self.assertIn(b'F.L.P.A', drawn)

    def test_print_batch_front_school_name_back_republic(self):
        from pathlib import Path

        html = Path(__file__).with_name('templates').joinpath('id_cards', 'print_batch.html').read_text(
            encoding='utf-8'
        )
        self.assertEqual(html.count('class="header-name">{{ front_header_name }}'), 2)
        self.assertEqual(html.count('class="header-name">{{ back_header_name }}'), 1)
        self.assertNotIn('class="header-name">{{ brand.name }}', html)
        self.assertNotIn('class="header-name">{{ header_name }}', html)
        self.assertIn("id_card_front_header_name or 'Future Leaders Preparatory Academy'", html)
        self.assertIn("id_card_back_header_name or 'Republic of Liberia'", html)
        with app.test_request_context('/id-cards/print/class/1'):
            from flask import render_template_string

            rendered = render_template_string(
                '<div class="front">{{ id_card_front_header_name }}</div>'
                '<div class="back">{{ id_card_back_header_name }}</div>'
            )
        self.assertIn('Future Leaders Preparatory Academy', rendered)
        self.assertIn('Republic of Liberia', rendered)
        self.assertIn('<div class="front">Future Leaders Preparatory Academy</div>', rendered)
        self.assertIn('<div class="back">Republic of Liberia</div>', rendered)

    def test_id_card_footer_fill_staff_red_student_navy(self):
        self.assertEqual(ID_CARD_STUDENT_FOOTER_HEX.lower(), '#002d62')
        self.assertEqual(ID_CARD_STAFF_FOOTER_HEX.lower(), '#c82828')
        self.assertEqual(id_card_footer_fill(False).hexval(), NAVY.hexval())
        self.assertEqual(id_card_footer_fill(True).hexval(), CARDINAL_DEFAULT.hexval())
        custom = HexColor('#aa1122')
        self.assertEqual(id_card_footer_fill(True, custom).hexval(), custom.hexval())
        self.assertEqual(id_card_footer_fill(False, custom).hexval(), NAVY.hexval())

    def test_print_batch_footer_is_solid_blue_or_red(self):
        from pathlib import Path

        html = Path(__file__).with_name('templates').joinpath('id_cards', 'print_batch.html').read_text(
            encoding='utf-8'
        )
        self.assertIn('--student-footer: var(--navy)', html)
        self.assertIn('--staff-footer: var(--cardinal)', html)
        self.assertIn('.front-footer {', html)
        self.assertIn('background: var(--student-footer)', html)
        self.assertIn('.staff-front .front-footer', html)
        self.assertIn('background: var(--staff-footer)', html)
        self.assertIn('.staff-pair .back-footer', html)
        self.assertIn('card-pair{% if is_staff %} staff-pair{% endif %}', html)
        self.assertIn('class="back-footer"', html)
        self.assertNotIn('repeating-linear-gradient', html)
        self.assertNotIn('class="stripes"', html)
        self.assertNotIn('band-navy', html)
        self.assertNotIn('band-cardinal', html)

        pdf_src = Path(__file__).with_name('id_card_pdf.py').read_text(encoding='utf-8')
        self.assertIn('id_card_footer_fill(is_staff, cardinal)', pdf_src)
        self.assertNotIn('stripe_h', pdf_src)
        self.assertNotIn('stripe_clip', pdf_src)
        self.assertNotIn('repeating-linear-gradient', pdf_src)

    def test_batch_pdf_has_header_and_pages(self):
        student = SimpleNamespace(
            id=1,
            full_name='Test Student',
            student_id='FLPA-1001',
            parent_user=SimpleNamespace(full_name='Test Parent'),
            parent_phone='0770000000',
            id_expiration_date=date(2026, 7, 31),
            official_signature_mark='Student T.',
            signature_url=None,
        )
        cards = [
            {
                'student': student,
                'class_label': 'Grade 6A',
                'qr_code_data_uri': None,
            }
        ]
        brand = {
            'name': 'Future Leaders Preparatory Academy',
            'full_address': 'Center Street, South Beach, Monrovia, Liberia',
            'phones': '0770000000',
            'motto': 'Honor, Excellence, Academics, Discipline, Success',
            'brand_red': '#c82828',
        }
        buf = build_class_id_cards_pdf(
            cards,
            klass=SimpleNamespace(name='Grade 6A'),
            display_year=SimpleNamespace(name='2025-2026'),
            brand=brand,
        )
        payload = buf.getvalue()
        self.assertTrue(payload.startswith(b'%PDF'))
        self.assertIn(b'/Type /Page', payload)
        self.assertGreater(len(payload), 2000)
        self.assertEqual(
            resolve_id_card_parent_name(student, cards[0]),
            'Test Parent',
        )

    def test_batch_pdf_two_students_missing_photos_still_valid(self):
        """A class PDF must be a complete %PDF with pages even if photos are missing."""
        def _student(pk, name, sid):
            return SimpleNamespace(
                id=pk,
                full_name=name,
                student_id=sid,
                parent_user=SimpleNamespace(full_name='Test Parent'),
                parent_phone='0770000000',
                id_expiration_date=date(2027, 7, 31),
                official_signature_mark='Student T.',
                signature_url=None,
            )

        cards = [
            {
                'student': _student(1, 'Alpha Student', 'FLPA-1001'),
                'class_label': '8th',
                'qr_code_data_uri': None,
                'photo_path': r'C:\missing\photo_1.jpg',
            },
            {
                'student': _student(2, 'Beta Student', 'FLPA-1002'),
                'class_label': '8th',
                'qr_code_data_uri': None,
                'photo_path': None,
            },
        ]
        buf = build_class_id_cards_pdf(
            cards,
            klass=SimpleNamespace(name='8th'),
            display_year=SimpleNamespace(name='2026-2027'),
            brand={'name': 'FLPA', 'full_address': 'Monrovia', 'phones': '077', 'motto': 'Honor'},
        )
        payload = buf.getvalue()
        self.assertTrue(payload.startswith(b'%PDF'))
        self.assertIn(b'/Type /Page', payload)
        self.assertGreaterEqual(payload.count(b'/Type /Page'), 1)
        self.assertGreater(len(payload), 2000)
        self.assertIn(b'%%EOF', payload)

    def test_print_payload_does_not_reprocess_or_rembg(self):
        from app import _id_card_print_payload

        student = SimpleNamespace(
            id=3,
            student_id='FLPA-1003',
            student_id_code='FLPA-1003',
            secure_qr_token='tok',
            academic_year_id=1,
            guardian_name='Mary Johnson',
            parent_user=None,
            photo_url=None,
        )
        year = SimpleNamespace(id=1, name='2026-2027')
        with app.test_request_context('/id-cards/print/class/1'):
            with mock.patch('app._reprocess_student_id_photo') as recrop, mock.patch(
                'app._prepare_id_photo_for_print'
            ) as prep, mock.patch('app.ensure_student_secure_qr_token'), mock.patch(
                'app.generate_student_scanner_code', return_value=None
            ), mock.patch(
                'app.build_student_portal_qr_url', return_value=''
            ), mock.patch(
                'app.get_site_base_url', return_value='http://localhost'
            ), mock.patch(
                'app.format_student_class_name', return_value='8th'
            ), mock.patch(
                'app._student_id_photo_disk_path', return_value=None
            ), mock.patch(
                'app._student_signature_disk_path', return_value=None
            ), mock.patch(
                'app._cache_busted_photo_url', return_value=None
            ):
                payload = _id_card_print_payload(student, year)
        recrop.assert_not_called()
        prep.assert_not_called()
        self.assertIs(payload['student'], student)
        self.assertEqual(payload['parent_name'], 'Mary Johnson')

    def test_resolve_parent_name_uses_guardian_then_linked_parent(self):
        typed = SimpleNamespace(
            guardian_name='Mary Johnson',
            parent_name=None,
            parent_user=SimpleNamespace(full_name='Linked Account'),
        )
        self.assertEqual(resolve_parent_guardian_name(typed), 'Mary Johnson')
        self.assertEqual(resolve_id_card_parent_name(typed), 'Mary Johnson')

        linked_only = SimpleNamespace(
            guardian_name=None,
            parent_name=None,
            parent_user=SimpleNamespace(full_name='Linked Account'),
        )
        self.assertEqual(resolve_parent_guardian_name(linked_only), 'Linked Account')

        empty = SimpleNamespace(guardian_name='', parent_name=None, parent_user=None)
        self.assertIsNone(resolve_parent_guardian_name(empty))
        self.assertIsNone(resolve_id_card_parent_name(empty, {'parent_name': ''}))
        self.assertEqual(
            resolve_id_card_parent_name(empty, {'parent_name': 'Payload Guardian'}),
            'Payload Guardian',
        )

    def test_pdf_uses_guardian_name_without_parent_user(self):
        student = SimpleNamespace(
            id=2,
            full_name='Child Student',
            student_id='FLPA-1002',
            guardian_name='Agnes Kollie',
            parent_user=None,
            parent_phone='0771111111',
            id_expiration_date=date(2026, 7, 31),
            official_signature_mark='Child S.',
            signature_url=None,
        )
        card = {'student': student, 'class_label': 'Grade 4', 'qr_code_data_uri': None}
        buf = build_class_id_cards_pdf(
            [card],
            klass=SimpleNamespace(name='Grade 4'),
            display_year=SimpleNamespace(name='2025-2026'),
            brand={'name': 'FLPA', 'full_address': 'Monrovia', 'phones': '077', 'motto': 'Honor'},
        )
        payload = buf.getvalue()
        drawn = _pdf_content_text(payload)
        self.assertTrue(payload.startswith(b'%PDF'))
        self.assertIn(b'Agnes Kollie', drawn)
        self.assertIn(b'Parent / Guardian:', drawn)
        self.assertEqual(resolve_id_card_parent_name(student, card), 'Agnes Kollie')

    def test_print_payload_includes_guardian_name(self):
        student = SimpleNamespace(
            guardian_name='Mary Johnson',
            parent_name=None,
            parent_user=None,
        )
        card = {
            'student': student,
            'parent_name': resolve_parent_guardian_name(student) or '',
        }
        self.assertEqual(card['parent_name'], 'Mary Johnson')
        self.assertEqual(resolve_id_card_parent_name(student, card), 'Mary Johnson')

    def test_persist_guardian_name_from_request_and_form(self):
        student = SimpleNamespace(guardian_name=None)
        form = SimpleNamespace(guardian_name=SimpleNamespace(data='Form Guardian'))
        with app.test_request_context(
            '/edit-student/1',
            method='POST',
            data={'guardian_name': 'Posted Guardian'},
        ):
            self.assertEqual(persist_student_guardian_name(student, form), 'Posted Guardian')
            self.assertEqual(student.guardian_name, 'Posted Guardian')

        leftover = SimpleNamespace(guardian_name='Keep Me')
        with app.test_request_context('/edit-student/1', method='POST', data={}):
            self.assertEqual(persist_student_guardian_name(leftover, form), 'Form Guardian')
            self.assertEqual(leftover.guardian_name, 'Form Guardian')

        empty = SimpleNamespace(guardian_name='Was Set')
        with app.test_request_context(
            '/edit-student/1',
            method='POST',
            data={'guardian_name': '   '},
        ):
            self.assertIsNone(persist_student_guardian_name(empty, form))
            self.assertIsNone(empty.guardian_name)

    def test_download_response_is_attachment_not_inline(self):
        filename = 'FLPA_ID_Cards_Grade_6A_2025_2026.pdf'
        with app.test_request_context('/id-cards/download/class/1'):
            response = _id_cards_pdf_attachment_response(BytesIO(b'%PDF-1.4 test'), filename)
        disposition = response.headers.get('Content-Disposition', '')
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertEqual(disposition, f'attachment; filename="{filename}"')
        self.assertNotIn('inline', disposition.lower())
        self.assertTrue(disposition.startswith('attachment;'))
        self.assertEqual(response.headers.get('Content-Length'), str(len(b'%PDF-1.4 test')))

    def test_portrait_contain_matches_css_square_well(self):
        self.assertEqual(PHOTO_FIT, 'contain')
        self.assertEqual(PHOTO_COVER_SCALE, 1.0)
        self.assertEqual(PHOTO_WELL_MM, 24.0)
        self.assertGreaterEqual(PHOTO_POSITION_Y, 0.45)
        self.assertLessEqual(PHOTO_POSITION_Y, 0.55)

    def test_contain_rect_fills_square_with_square_jpeg(self):
        px, py, dw, dh = id_photo_contain_rect(800, 800, 24, 24)
        self.assertAlmostEqual(px, 0.0)
        self.assertAlmostEqual(py, 0.0)
        self.assertAlmostEqual(dw, 24.0)
        self.assertAlmostEqual(dh, 24.0)

    def test_square_hs_jpeg_fully_visible_in_layout(self):
        """800×800 with head in the upper half and chest in the lower third.

        Contain in the 24mm square maps every source row into the well.
        Cover+top in a tall well (the Safari regression) would not.
        """
        img_w = img_h = 800
        head_y = 160  # upper half
        chest_y = 640  # lower third
        box = 24.0
        px, py, dw, dh = id_photo_contain_rect(img_w, img_h, box, box)

        def dest_y(src_y):
            return py + dh * (src_y / float(img_h))

        self.assertGreaterEqual(dest_y(0), py)
        self.assertLessEqual(dest_y(img_h), py + dh)
        self.assertGreaterEqual(dest_y(head_y), py)
        self.assertLessEqual(dest_y(head_y), py + dh)
        self.assertGreaterEqual(dest_y(chest_y), py)
        self.assertLessEqual(dest_y(chest_y), py + dh)
        # Chest is in the lower third of the well, not clipped.
        self.assertGreater(dest_y(chest_y), py + dh * 0.6)

        from PIL import Image, ImageDraw

        src = Image.new('RGB', (800, 800), (255, 255, 255))
        draw = ImageDraw.Draw(src)
        draw.ellipse((280, 80, 520, 360), fill=(180, 70, 40))
        draw.rectangle((180, 530, 620, 799), fill=(16, 20, 80))
        well_px = 96
        bpx, bpy, bdw, bdh = id_photo_contain_rect(800, 800, well_px, well_px)
        dest = Image.new('RGB', (well_px, well_px), (200, 200, 200))
        dest.paste(src.resize((int(round(bdw)), int(round(bdh)))), (int(round(bpx)), int(round(bpy))))
        head = dest.getpixel((48, 26))
        chest = dest.getpixel((48, 80))
        self.assertGreater(head[0], head[2] + 40)
        self.assertLess(head[1], 120)
        self.assertGreater(chest[2], chest[0])
        self.assertLess(chest[1], 80)

        # Tall well (Safari stretch): contain letterboxes; chest still maps inside dest image.
        tall_w, tall_h = 24.0, 40.0
        tpx, tpy, tdw, tdh = id_photo_contain_rect(img_w, img_h, tall_w, tall_h)
        self.assertAlmostEqual(tdw, 24.0)
        self.assertAlmostEqual(tdh, 24.0)
        self.assertGreater(tpy, 0.0)
        chest_in_tall = tpy + tdh * (chest_y / float(img_h))
        self.assertLessEqual(chest_in_tall, tpy + tdh)
        self.assertGreaterEqual(chest_in_tall, tpy)

        # Cover+top in a landscape well slices the lower third (why we do not use it).
        cover_scale = max(40.0 / img_w, 24.0 / img_h)
        cover_dh = img_h * cover_scale
        visible_src_h = img_h * (24.0 / cover_dh)
        self.assertLess(visible_src_h, chest_y)

    def test_print_batch_css_square_contain_not_cover_top(self):
        from pathlib import Path

        html = Path(__file__).with_name('templates').joinpath('id_cards', 'print_batch.html').read_text(
            encoding='utf-8'
        )
        start = html.find('.photo-ring img {')
        self.assertGreater(start, 0)
        block = html[start:html.find('}', start) + 1]
        self.assertIn('object-fit: contain', block)
        self.assertIn('object-position: center center', block)
        self.assertIn('height: auto !important', block)
        self.assertNotIn('object-fit: cover', block)
        self.assertNotIn('center top', block)
        self.assertNotIn('22%', block)
        self.assertNotIn('position: absolute', block)

    def test_back_uses_principal_signature_not_holder(self):
        from pathlib import Path

        html = Path(__file__).with_name('templates').joinpath('id_cards', 'print_batch.html').read_text(
            encoding='utf-8'
        )
        start = html.find('class="principal-block"')
        self.assertGreater(start, 0)
        block = html[start:html.find('class="back-qr"', start)]
        self.assertIn('principal_signature_url', block)
        self.assertIn('Issuing authority', block)
        self.assertIn('Proprietor', block)
        self.assertNotIn('>Principal<', block)
        self.assertNotIn('card.signature_url', block)
        self.assertNotIn('student.signature_url', block)
        self.assertNotIn('official_signature_mark', block)
        self.assertIn('class="student-sign"', html)
        self.assertIn("Holder's Signature", html)

        student = SimpleNamespace(
            id=1,
            full_name='Test Student',
            student_id='FLPA-1001',
            parent_user=SimpleNamespace(full_name='Test Parent'),
            parent_phone='0770000000',
            id_expiration_date=date(2026, 7, 31),
            official_signature_mark='Student T.',
            signature_url=None,
        )
        drawn = _pdf_content_text(
            build_class_id_cards_pdf(
                [{'student': student, 'class_label': 'Grade 6A', 'qr_code_data_uri': None}],
                klass=SimpleNamespace(name='Grade 6A'),
                display_year=SimpleNamespace(name='2025-2026'),
                brand=self._school_brand(),
            ).getvalue()
        )
        self.assertIn(b'ISSUING AUTHORITY', drawn)
        self.assertIn(PRINCIPAL_SIGNATORY_TITLE.encode(), drawn)
        self.assertIn(b"HOLDER'S SIGNATURE", drawn)
        principal_path = Path(principal_signature_disk_path() or '')
        self.assertTrue(principal_path.is_file())
        self.assertEqual(principal_path.name, 'principal_signature.png')
        well = html[html.find('.photo-ring {'):html.find('.photo-ring img {')]
        self.assertIn('aspect-ratio: 1 / 1 !important', well)
        self.assertIn('height: auto !important', well)
        self.assertIn('min-height: 0 !important', well)
        self.assertIn('overflow: hidden', well)
        self.assertIn('width: 100%', well)


class StaffSignatureMarkTestCase(unittest.TestCase):
    """Staff who never upload a handwritten signature are signed from their name."""

    def mark(self, full_name, profile=None):
        from app import _staff_signature_mark

        return _staff_signature_mark(SimpleNamespace(full_name=full_name, teacher_profile=profile))

    def test_given_name_middle_initial_surname(self):
        self.assertEqual(self.mark('Othello B. Gbarjuewaye'), 'Othello B. Gbarjuewaye')
        self.assertEqual(self.mark('Emmanuel Dahn'), 'Emmanuel Dahn')
        self.assertEqual(self.mark('Mary Jane Watson'), 'Mary J. Watson')

    def test_casing_is_repaired_without_breaking_real_spellings(self):
        self.assertEqual(self.mark('JOSEPH T. KOLLIE'), 'Joseph T. Kollie')
        self.assertEqual(self.mark('patrick o brien'), 'Patrick O. Brien')
        self.assertEqual(self.mark('James McDonald'), 'James McDonald')
        self.assertEqual(self.mark('Grace Nyanti-Sirleaf'), 'Grace Nyanti-Sirleaf')

    def test_titles_dropped_and_suffixes_kept(self):
        self.assertEqual(self.mark('Rev. Samuel Weah Jr.'), 'Samuel Weah Jr.')
        self.assertEqual(self.mark('Dr. Anthony Kollie III'), 'Anthony Kollie III')

    def test_surname_particles_stay_with_the_surname(self):
        self.assertEqual(self.mark('Grace van Dyke'), 'Grace van Dyke')

    def test_teacher_profile_names_win_over_display_name(self):
        profile = SimpleNamespace(first_name='Othello', last_name='Gbarjuewaye')
        self.assertEqual(self.mark('wrong name here', profile), 'Othello Gbarjuewaye')

    def test_single_and_empty_names(self):
        self.assertEqual(self.mark('Madonna'), 'Madonna')
        self.assertEqual(self.mark(''), 'Authorized Staff')
        self.assertEqual(self.mark('   '), 'Authorized Staff')

    def test_signature_fits_the_ruled_line_without_clipping(self):
        from reportlab.lib.units import mm
        from reportlab.pdfgen.canvas import Canvas

        from id_card_pdf import _fit_text, _register_signature_font, _signature_text_and_size

        canvas = Canvas(BytesIO())
        font = _register_signature_font()
        line_w = 32 * mm

        for mark in ('Emmanuel Dahn', 'Othello B. Gbarjuewaye', 'Othello B. Gbarjuewaye-Nyanti'):
            text, size = _signature_text_and_size(canvas, mark, font, line_w)
            self.assertLessEqual(size, 13.0)
            self.assertGreaterEqual(size, 7.5)
            self.assertLessEqual(canvas.stringWidth(text, font, size), line_w, mark)
            # Never truncated mid-name, and the surname always survives.
            self.assertEqual(_fit_text(canvas, text, font, size, line_w), text)
            self.assertNotIn('…', text)
            self.assertIn(mark.split()[-1], text)

    def test_short_signature_keeps_the_full_written_name(self):
        from reportlab.lib.units import mm
        from reportlab.pdfgen.canvas import Canvas

        from id_card_pdf import _register_signature_font, _signature_text_and_size

        canvas = Canvas(BytesIO())
        font = _register_signature_font()
        text, size = _signature_text_and_size(canvas, 'Emmanuel Dahn', font, 32 * mm)
        # Script faces are wide, so the size drops, but the name is written in full.
        self.assertEqual(text, 'Emmanuel Dahn')
        self.assertLessEqual(size, 13.0)
        self.assertGreater(size, 7.5)


if __name__ == '__main__':
    unittest.main()
