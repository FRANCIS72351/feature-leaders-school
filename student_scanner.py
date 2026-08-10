"""Student QR / barcode verification and submission sheet scanning helpers."""
import base64
import io
import os
import re
import uuid

import qrcode
from flask import current_app, has_request_context, request

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
except ImportError:
    pyzbar_decode = None

UUID_PATTERN = re.compile(
    r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'
)


def get_site_base_url():
    """Resolve public base URL for QR links (SITE_URL env or current request host)."""
    base = ''
    if current_app:
        base = (current_app.config.get('SITE_URL') or os.environ.get('SITE_URL') or '').strip()
    if not base and has_request_context() and request:
        base = request.host_url.rstrip('/')
    return (base or '').rstrip('/')


def build_student_verify_url(student, base_url=None):
    """Build the public verification URL encoded in the student QR code."""
    if not student or not getattr(student, 'secure_qr_token', None):
        return None
    base = (base_url or get_site_base_url()).rstrip('/')
    return f'{base}/verify-student/{student.secure_qr_token}'


def generate_student_scanner_code(student, base_url=None):
    """
    Return a base64 data-URI PNG QR image for template embedding.
    Encodes the secure verification URL for this student.
    """
    verify_url = build_student_verify_url(student, base_url=base_url)
    if not verify_url:
        return None
    return qr_data_uri_for_url(verify_url)


def build_parent_report_url(student, academic_year_id=None, base_url=None):
    """Public parent report gate URL encoded on report-card QR codes."""
    if not student or not getattr(student, 'parent_report_token', None):
        return None
    base = (base_url or get_site_base_url()).rstrip('/')
    if not base:
        return None
    url = f'{base}/parent/report/{student.parent_report_token}'
    if academic_year_id:
        url = f'{url}?academic_year_id={academic_year_id}'
    return url


def generate_parent_report_qr_code(student, academic_year_id=None, base_url=None):
    """Base64 data-URI PNG QR for parent report access."""
    report_url = build_parent_report_url(student, academic_year_id=academic_year_id, base_url=base_url)
    if not report_url:
        return None
    return qr_data_uri_for_url(report_url)


def generate_submission_scan_code():
    """Return a new uppercase UUID string for a submission answer sheet."""
    return str(uuid.uuid4()).upper()


def qr_data_uri_for_url(url):
    if not url:
        return None
    qr = qrcode.QRCode(version=1, box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f'data:image/png;base64,{encoded}'


def qr_data_uri_for_text(text):
    """QR code PNG data-URI encoding plain text (e.g. submission scan UUID)."""
    if not text:
        return None
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(str(text).strip().upper())
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f'data:image/png;base64,{encoded}'


def barcode_scanner_available():
    return pyzbar_decode is not None and Image is not None


def extract_uuids_from_text(text):
    """Find all UUID-like submission codes in OCR or decoded text."""
    if not text:
        return []
    found = []
    seen = set()
    for match in UUID_PATTERN.findall(text):
        normalized = match.upper()
        if normalized not in seen:
            seen.add(normalized)
            found.append(normalized)
    return found


def decode_barcodes_from_stream(stream):
    """Decode QR / barcode payloads from an image stream (pyzbar when installed)."""
    if not barcode_scanner_available():
        return []
    stream.seek(0)
    img = Image.open(stream)
    if img.mode not in ('L', 'RGB', 'RGBA'):
        img = img.convert('RGB')
    payloads = []
    seen = set()
    for symbol in pyzbar_decode(img):
        raw = (symbol.data or b'').decode('utf-8', errors='ignore').strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        payloads.append(raw)
    return payloads


def collect_scan_identifiers(stream, ocr_text=''):
    """
    Gather submission UUIDs from barcodes/QR and OCR text on one photo.
    Returns normalized uppercase UUID list.
    """
    identifiers = []
    seen = set()

    for payload in decode_barcodes_from_stream(stream):
        for code in extract_uuids_from_text(payload):
            if code not in seen:
                seen.add(code)
                identifiers.append(code)
        cleaned = payload.strip().upper()
        if UUID_PATTERN.fullmatch(cleaned) and cleaned not in seen:
            seen.add(cleaned)
            identifiers.append(cleaned)

    for code in extract_uuids_from_text(ocr_text):
        if code not in seen:
            seen.add(code)
            identifiers.append(code)

    return identifiers
