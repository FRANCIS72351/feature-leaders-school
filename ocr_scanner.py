"""OCR-based assignment scanning for teacher grading workflows."""

from __future__ import annotations

import io
import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageDraw = None
    ImageFont = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

_TESSERACT_CONFIGURED = False
WINDOWS_TESSERACT_PATHS = (
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
)


def opencv_available():
    return cv2 is not None and np is not None


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
        'opencv_ready': opencv_available(),
        'tesseract_path': None,
        'tesseract_version': None,
        'barcode_scanner': False,
        'install_steps': [],
    }
    if not status['libraries_installed']:
        status['install_steps'] = [
            'Install Python packages: pip install pytesseract Pillow opencv-python-headless',
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

    if status['engine_ready'] and not status['opencv_ready']:
        status['install_steps'].append(
            'Optional: pip install opencv-python-headless so phone photos are straightened before they are read.'
        )
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


_QUESTION_KEY = re.compile(
    r'^\s*(?:q(?:uestion)?\s*)?(\d{1,3})\s*[:=\-\.]\s*(.+?)\s*$',
    re.IGNORECASE,
)


def parse_answer_key(raw_value):
    """
    Turn the teacher answer key into graded items.

    A plain list still works: Liberia, Monrovia, 1847
    A numbered key matches each question: 1: A; 2: Monrovia; 3: 1847
    """
    items = []
    seen = set()
    for token in parse_scan_keywords(raw_value):
        match = _QUESTION_KEY.match(token)
        if match:
            label = match.group(1)
            expected = match.group(2).strip()
            kind = 'question'
            identity = f'q:{label}'
            display = f'{label}: {expected}'
        else:
            label = token
            expected = token
            kind = 'keyword'
            identity = f'k:{token.lower()}'
            display = token
        if not expected or identity in seen:
            continue
        seen.add(identity)
        items.append({
            'label': label,
            'expected': expected,
            'kind': kind,
            'display': display,
        })
    return items


def _read_stream_bytes(stream):
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream)
    data = stream.read()
    if isinstance(data, str):
        data = data.encode('utf-8')
    return data or b''


def _pillow_enhance(raw_bytes):
    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert('L')
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    return img, {
        'preprocessor': 'pillow',
        'aligned': False,
        'deskewed': False,
        'note': 'Sharpened the photo. Install OpenCV to straighten a tilted page.',
    }


def _order_quad(points):
    rect = np.zeros((4, 2), dtype='float32')
    total = points.sum(axis=1)
    rect[0] = points[np.argmin(total)]
    rect[2] = points[np.argmax(total)]
    diff = np.diff(points, axis=1)
    rect[1] = points[np.argmin(diff)]
    rect[3] = points[np.argmax(diff)]
    return rect


def _warp_document(image, quad):
    rect = _order_quad(quad.astype('float32'))
    (top_left, top_right, bottom_right, bottom_left) = rect
    width = int(max(
        np.linalg.norm(bottom_right - bottom_left),
        np.linalg.norm(top_right - top_left),
    ))
    height = int(max(
        np.linalg.norm(top_right - bottom_right),
        np.linalg.norm(top_left - bottom_left),
    ))
    width = max(width, 1)
    height = max(height, 1)
    destination = np.array([
        [0, 0],
        [width - 1, 0],
        [width - 1, height - 1],
        [0, height - 1],
    ], dtype='float32')
    matrix = cv2.getPerspectiveTransform(rect, destination)
    return cv2.warpPerspective(image, matrix, (width, height))


def _align_page(image):
    """Find the paper outline and flatten it when the photo includes a desk or table."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 75, 200)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:8]
    page_area = float(image.shape[0] * image.shape[1])
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) != 4:
            continue
        area = cv2.contourArea(approx)
        if area < page_area * 0.2:
            continue
        return _warp_document(image, approx.reshape(4, 2)), True
    return image, False


def _deskew_page(image):
    """Rotate a slightly tilted page back toward level."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(ink > 0))
    if coords.shape[0] < 50:
        return image, False
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.4 or abs(angle) > 15:
        return image, False
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width // 2, height // 2), angle, 1.0)
    rotated = cv2.warpAffine(
        image, matrix, (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated, True


def _prepare_for_reading(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    if min(height, width) < 32:
        return Image.fromarray(gray)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    block = 31 if min(height, width) > 31 else max(3, (min(height, width) // 2) * 2 + 1)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 15,
    )
    return Image.fromarray(binary)


def prepare_scan_image(stream):
    """
    Stage 2: preprocess and align the uploaded paper.
    OpenCV straightens the page when it is installed. Pillow is the fallback.
    """
    raw_bytes = _read_stream_bytes(stream)
    if not raw_bytes:
        raise RuntimeError('The uploaded paper was empty.')
    if opencv_available():
        decoded = cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if decoded is not None:
            height, width = decoded.shape[:2]
            long_edge = max(height, width)
            if long_edge > 1800:
                scale = 1800.0 / float(long_edge)
                decoded = cv2.resize(
                    decoded,
                    (max(int(width * scale), 1), max(int(height * scale), 1)),
                    interpolation=cv2.INTER_AREA,
                )
            aligned, did_align = _align_page(decoded)
            deskewed, did_deskew = _deskew_page(aligned)
            note = 'OpenCV straightened the page before reading.'
            if not did_align and not did_deskew:
                note = 'OpenCV cleaned the photo. No page border was found to align.'
            return _prepare_for_reading(deskewed), {
                'preprocessor': 'opencv',
                'aligned': did_align,
                'deskewed': did_deskew,
                'note': note,
            }
    return _pillow_enhance(raw_bytes)


def preprocess_image_stream(stream):
    """Enhance a photo of handwritten or printed work for OCR."""
    image, _meta = prepare_scan_image(stream)
    return image


def extract_text_from_stream(stream):
    """Stage 3: read the prepared page with Tesseract."""
    if not ocr_engine_ready():
        raise RuntimeError(
            'OCR is not available. Install Tesseract OCR and the pytesseract/Pillow packages.'
        )
    img = preprocess_image_stream(stream)
    text = pytesseract.image_to_string(img)
    return (text or '').strip()


def _answer_window(text, label):
    pattern = re.compile(
        rf'(?<!\d)(?:q(?:uestion)?\s*)?{re.escape(str(label))}\s*[\.\)\:\-]\s*',
        re.IGNORECASE,
    )
    match = pattern.search(text or '')
    if not match:
        return None
    return (text or '')[match.end():match.end() + 80]


def _expected_is_present(window, expected):
    cleaned = (expected or '').strip()
    if not cleaned or not window:
        return False
    if re.fullmatch(r'[A-Da-d]', cleaned):
        return re.search(
            rf'(?<![A-Za-z]){re.escape(cleaned)}(?![A-Za-z])',
            window,
            re.IGNORECASE,
        ) is not None
    return cleaned.lower() in window.lower()


def score_text_against_keywords(text, keywords, max_score=100.0):
    """
    Stage 4: score the page against the answer key.
    Numbered answers are checked beside their question. Plain keywords are
    checked anywhere in the page.
    """
    max_score = float(max_score or 100.0)
    if isinstance(keywords, str) or keywords is None:
        items = parse_answer_key(keywords)
    elif keywords and isinstance(keywords[0], dict):
        items = list(keywords)
    else:
        items = parse_answer_key(', '.join(str(word) for word in keywords))

    if not items:
        return {
            'suggested_score': None,
            'keywords_matched': [],
            'keywords_missed': [],
            'answer_items': [],
            'match_count': 0,
            'keyword_count': 0,
            'max_score': max_score,
        }

    share = max_score / len(items)
    matched = []
    missed = []
    rows = []
    for item in items:
        if item.get('kind') == 'question':
            window = _answer_window(text, item.get('label'))
            if window:
                found = _expected_is_present(window, item.get('expected'))
            elif len((item.get('expected') or '').strip()) > 1:
                found = _expected_is_present(text, item.get('expected'))
            else:
                found = False
        else:
            found = _expected_is_present(text, item.get('expected'))
        points = round(share, 1) if found else 0.0
        display = item.get('display') or item.get('expected')
        if found:
            matched.append(display)
        else:
            missed.append(display)
        rows.append({
            'label': item.get('label'),
            'expected': item.get('expected'),
            'matched': found,
            'points': points,
        })

    suggested = round(sum(row['points'] for row in rows), 1)
    return {
        'suggested_score': suggested,
        'keywords_matched': matched,
        'keywords_missed': missed,
        'answer_items': rows,
        'match_count': len(matched),
        'keyword_count': len(items),
        'max_score': max_score,
    }


def build_scan_result(text, keywords, max_score=100.0, preprocessing=None):
    """Full OCR scan payload for JSON responses."""
    snippet = (text or '')[:240].replace('\n', ' ').replace('\r', ' ').strip()
    if text and len(text) > 240:
        snippet = f'{snippet}…'
    scoring = score_text_against_keywords(text, keywords, max_score)
    payload = {
        'detected_text': text or '',
        'detected_text_snippet': snippet,
        **scoring,
    }
    if preprocessing:
        payload['preprocessing'] = preprocessing
    return payload


def grade_uploaded_paper(stream, keywords, max_score=100.0):
    """
    Run the paper through the four backend stages:
    upload bytes, OpenCV alignment, Tesseract reading, answer-key scoring.
    """
    if not ocr_engine_ready():
        raise RuntimeError(
            'OCR is not available. Install Tesseract OCR and the pytesseract/Pillow packages.'
        )
    image, preprocessing = prepare_scan_image(stream)
    text = (pytesseract.image_to_string(image) or '').strip()
    return build_scan_result(text, keywords, max_score, preprocessing)


def create_demo_scan_image(text='Liberia Monrovia 1847'):
    """Generate a simple test image for local OCR verification."""
    if not ocr_libraries_available():
        raise RuntimeError('Pillow is required to create a demo scan image.')
    img = Image.new('RGB', (900, 220), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((40, 80), text, fill='black')
    return img
