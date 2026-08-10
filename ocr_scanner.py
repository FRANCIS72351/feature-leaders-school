"""OCR-based assignment scanning for teacher grading workflows."""

from __future__ import annotations

import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont
except ImportError:
    pytesseract = None
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageDraw = None
    ImageFont = None

_TESSERACT_CONFIGURED = False
WINDOWS_TESSERACT_PATHS = (
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
)


def ocr_libraries_available():
    return pytesseract is not None and Image is not None


def configure_tesseract():
    """Point pytesseract at the installed binary (Windows-friendly auto-detect)."""
    global _TESSERACT_CONFIGURED
    if _TESSERACT_CONFIGURED or not ocr_libraries_available():
        return

    env_cmd = (os.environ.get('TESSERACT_CMD') or os.environ.get('TESSERACT_PATH') or '').strip()
    candidates = []
    if env_cmd:
        candidates.append(env_cmd)
    which_cmd = shutil.which('tesseract')
    if which_cmd:
        candidates.append(which_cmd)
    candidates.extend(WINDOWS_TESSERACT_PATHS)

    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isdir(candidate):
            candidate = os.path.join(candidate, 'tesseract.exe')
        if not os.path.isfile(candidate):
            continue
        pytesseract.pytesseract.tesseract_cmd = candidate
        try:
            pytesseract.get_tesseract_version()
            _TESSERACT_CONFIGURED = True
            logger.info('Tesseract OCR configured: %s', candidate)
            return
        except Exception:
            continue


configure_tesseract()


def ocr_engine_ready():
    """True when Python packages and the Tesseract binary are available."""
    if not ocr_libraries_available():
        return False
    configure_tesseract()
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def get_ocr_setup_status():
    """Detailed OCR readiness for teacher setup banners."""
    status = {
        'libraries_installed': ocr_libraries_available(),
        'engine_ready': False,
        'tesseract_path': None,
        'tesseract_version': None,
        'barcode_scanner': False,
        'install_steps': [],
    }
    if not status['libraries_installed']:
        status['install_steps'] = [
            'Install Python packages: pip install pytesseract Pillow',
            'Install Tesseract OCR (Windows: winget install UB-Mannheim.TesseractOCR)',
            'Restart the school server after installing Tesseract',
        ]
        return status

    configure_tesseract()
    cmd = getattr(pytesseract.pytesseract, 'tesseract_cmd', None)
    status['tesseract_path'] = cmd
    try:
        status['tesseract_version'] = str(pytesseract.get_tesseract_version())
        status['engine_ready'] = True
    except Exception:
        status['install_steps'] = [
            'Python packages are installed, but the Tesseract program was not found.',
            'Windows: install from https://github.com/UB-Mannheim/tesseract/wiki',
            'Or set TESSERACT_CMD in .env to the full path of tesseract.exe',
            'Restart the server after installation.',
        ]

    try:
        from student_scanner import barcode_scanner_available
        status['barcode_scanner'] = barcode_scanner_available()
    except Exception:
        status['barcode_scanner'] = False

    if status['engine_ready'] and not status['barcode_scanner']:
        status['install_steps'].append(
            'Optional: pip install pyzbar for faster QR/barcode matching on answer sheets.'
        )

    return status


def parse_scan_keywords(raw_value):
    """Split comma/newline-separated keywords into a normalized list."""
    if not raw_value:
        return []
    parts = re.split(r'[,;\n]+', str(raw_value))
    keywords = []
    seen = set()
    for part in parts:
        word = part.strip()
        if not word:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(word)
    return keywords


def preprocess_image_stream(stream):
    """Enhance a photo of handwritten/printed work for OCR."""
    img = Image.open(stream)
    img = img.convert('L')
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    return img


def extract_text_from_stream(stream):
    """Run OCR on an uploaded image stream."""
    if not ocr_engine_ready():
        raise RuntimeError(
            'OCR is not available. Install Tesseract OCR and the pytesseract/Pillow packages.'
        )
    img = preprocess_image_stream(stream)
    text = pytesseract.image_to_string(img)
    return (text or '').strip()


def score_text_against_keywords(text, keywords, max_score=100.0):
    """
    Score detected text by keyword matches (case-insensitive substring search).
    Returns dict with score breakdown for the teacher UI.
    """
    max_score = float(max_score or 100.0)
    normalized = (text or '').lower()
    if not keywords:
        return {
            'suggested_score': None,
            'keywords_matched': [],
            'keywords_missed': [],
            'match_count': 0,
            'keyword_count': 0,
            'max_score': max_score,
        }

    matched = []
    missed = []
    for keyword in keywords:
        if keyword.lower() in normalized:
            matched.append(keyword)
        else:
            missed.append(keyword)

    keyword_count = len(keywords)
    match_count = len(matched)
    suggested = round((match_count / keyword_count) * max_score, 1) if keyword_count else None

    return {
        'suggested_score': suggested,
        'keywords_matched': matched,
        'keywords_missed': missed,
        'match_count': match_count,
        'keyword_count': keyword_count,
        'max_score': max_score,
    }


def build_scan_result(text, keywords, max_score=100.0):
    """Full OCR scan payload for JSON responses."""
    snippet = text[:240].replace('\n', ' ').replace('\r', ' ').strip()
    if len(text) > 240:
        snippet = f'{snippet}…'
    scoring = score_text_against_keywords(text, keywords, max_score)
    return {
        'detected_text': text,
        'detected_text_snippet': snippet,
        **scoring,
    }


def create_demo_scan_image(text='Liberia Monrovia 1847'):
    """Generate a simple test image for local OCR verification."""
    if not ocr_libraries_available():
        raise RuntimeError('Pillow is required to create a demo scan image.')
    img = Image.new('RGB', (900, 220), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((40, 80), text, fill='black')
    return img
