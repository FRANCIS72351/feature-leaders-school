"""Student QR / barcode verification and submission sheet scanning helpers."""
import base64
import io
import os
import re
import uuid
from urllib.parse import urlparse

import qrcode
from flask import current_app, has_app_context, has_request_context, request

_LOOPBACK_HOSTS = frozenset({'localhost', '127.0.0.1', '::1', '0.0.0.0'})
_SITE_URL_ENV_KEYS = ('SITE_URL', 'PUBLIC_SITE_URL')

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


def _first_forwarded_value(header_name):
    raw = (request.headers.get(header_name) or '').strip()
    if not raw:
        return ''
    return raw.split(',')[0].strip()


def _hostname_of(url_or_host):
    value = (url_or_host or '').strip()
    if not value:
        return ''
    if '://' not in value:
        value = f'http://{value}'
    try:
        return (urlparse(value).hostname or '').strip().lower()
    except ValueError:
        return ''


def site_url_is_loopback(url_or_host):
    """True when the URL/host is localhost, 127.0.0.1, or another loopback address."""
    host = _hostname_of(url_or_host)
    return bool(host) and host in _LOOPBACK_HOSTS


def _normalize_origin(url):
    return (url or '').strip().rstrip('/')


def _configured_site_urls():
    seen = []
    if has_app_context():
        for key in _SITE_URL_ENV_KEYS:
            value = _normalize_origin(current_app.config.get(key) or os.environ.get(key) or '')
            if value and value not in seen:
                seen.append(value)
    for key in _SITE_URL_ENV_KEYS:
        value = _normalize_origin(os.environ.get(key) or '')
        if value and value not in seen:
            seen.append(value)
    return seen


def _forwarded_public_base_url():
    """Public origin from VS Code / GitHub Dev Tunnels (or Nginx) proxy headers."""
    if not (has_request_context() and request):
        return ''
    forwarded_host = _first_forwarded_value('X-Forwarded-Host')
    if not forwarded_host or site_url_is_loopback(forwarded_host):
        return ''
    forwarded_proto = _first_forwarded_value('X-Forwarded-Proto').lower()
    if forwarded_proto not in ('http', 'https'):
        forwarded_proto = 'https' if request.is_secure else (request.scheme or 'https')
    if forwarded_proto not in ('http', 'https'):
        forwarded_proto = 'https'
    return f'{forwarded_proto}://{forwarded_host}'


def _request_host_base_url():
    if not (has_request_context() and request):
        return ''
    return _normalize_origin(request.host_url)


def _request_is_loopback():
    """True when Flask sees localhost / 127.0.0.1 (typical behind a local Dev Tunnel)."""
    if not (has_request_context() and request):
        return False
    return site_url_is_loopback(request.host) or site_url_is_loopback(request.host_url)


def get_site_base_url():
    """
    Public origin for printed QR links.

    Prefer SITE_URL / PUBLIC_SITE_URL when they are a real public host. Never bake
    localhost or 127.0.0.1 into a QR: if this request is loopback but SITE_URL is
    set, use SITE_URL. Otherwise use a forwarded public host (Dev Tunnels set
    X-Forwarded-Host + X-Forwarded-Proto).
    """
    configured = _configured_site_urls()
    public_configured = next((url for url in configured if not site_url_is_loopback(url)), '')
    forwarded = _forwarded_public_base_url()
    request_base = _request_host_base_url()
    public_request = request_base if request_base and not site_url_is_loopback(request_base) else ''

    # Phones cannot open localhost. Loopback request + public SITE_URL → SITE_URL.
    if public_configured and _request_is_loopback():
        return public_configured
    if public_configured:
        return public_configured
    if forwarded:
        return forwarded
    if public_request:
        return public_request
    if configured:
        return configured[0]
    return request_base


def build_student_portal_qr_url(student, base_url=None):
    """Public URL encoded on the ID card QR — opens student portal sign-in."""
    if not student or not getattr(student, 'secure_qr_token', None):
        return None
    base = (base_url or get_site_base_url()).rstrip('/')
    if not base:
        return None
    return f'{base}/student/id-portal/{student.secure_qr_token}'


def build_student_verify_url(student, base_url=None):
    """Staff identity-check URL (not printed on the student ID QR)."""
    if not student or not getattr(student, 'secure_qr_token', None):
        return None
    base = (base_url or get_site_base_url()).rstrip('/')
    return f'{base}/verify-student/{student.secure_qr_token}'


def generate_student_scanner_code(student, base_url=None):
    """
    Return a base64 data-URI PNG QR image for template embedding.
    Encodes the student portal access URL for this ID card.
    """
    portal_url = build_student_portal_qr_url(student, base_url=base_url)
    if not portal_url:
        return None
    return qr_data_uri_for_url(portal_url)


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
