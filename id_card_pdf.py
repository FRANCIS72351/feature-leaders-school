"""CR80 student ID folder PDF — front + back, matching print_batch.html."""
from __future__ import annotations

import base64
import logging
import math
import os
import re
from io import BytesIO

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas

from school_divisions import SCHOOL_PRINT_NAME

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

CARD_W = 53.98 * mm
CARD_H = 85.6 * mm
CARD_RADIUS = 3.5 * mm
PAIR_GAP = 3 * mm
ROW_GAP = 6 * mm
PAGE_MARGIN = 8 * mm
ROWS_PER_PAGE = 3

NAVY = HexColor('#002d62')
GOLD = HexColor('#c9a227')
INK = HexColor('#1a2332')
MUTED = HexColor('#4b5563')
CARDINAL_DEFAULT = HexColor('#c82828')

# Front banner is the school print name; the back keeps the national title.
ID_CARD_FRONT_HEADER_NAME = SCHOOL_PRINT_NAME
ID_CARD_BACK_HEADER_NAME = 'Republic of Liberia'
ID_CARD_HEADER_NAME = ID_CARD_BACK_HEADER_NAME


def id_card_header_title(*, side='front', uppercase=False):
    """ID card banner title. Front is the school name; back is Republic of Liberia."""
    if (side or 'front').strip().lower() == 'back':
        title = (ID_CARD_BACK_HEADER_NAME or '').strip() or 'Republic of Liberia'
    else:
        title = (ID_CARD_FRONT_HEADER_NAME or '').strip() or SCHOOL_PRINT_NAME
    return title.upper() if uppercase else title


# Solid ID-card footers (download PDF and HTML print). Staff uses brand red;
# students use the same navy as the card header. No stripe pattern.
ID_CARD_STUDENT_FOOTER_HEX = '#002d62'
ID_CARD_STAFF_FOOTER_HEX = '#c82828'
ID_CARD_BACK_FOOTER_MM = 14.0


def id_card_footer_fill(is_staff, cardinal=None):
    """Solid footer fill: staff brand red, student navy."""
    if is_staff:
        return cardinal if cardinal is not None else CARDINAL_DEFAULT
    return NAVY

logger = logging.getLogger(__name__)

_SIG_FONT = None


def id_cards_pdf_filename(klass, display_year, *, single=False):
    """FLPA_ID_Cards_<Class>_<Year>.pdf (or singular card)."""
    class_part = _filename_part(getattr(klass, 'name', None), 'Class')
    year_part = _filename_part(getattr(display_year, 'name', None), 'Year')
    prefix = 'FLPA_ID_Card' if single else 'FLPA_ID_Cards'
    return f'{prefix}_{class_part}_{year_part}.pdf'


def _filename_part(value, fallback):
    text = re.sub(r'[^\w.\-]+', '_', (value or '').strip(), flags=re.UNICODE)
    text = re.sub(r'_+', '_', text).strip('._')
    return (text or fallback)[:60]


def _hex_color(value, default=CARDINAL_DEFAULT):
    raw = (value or '').strip()
    if raw.startswith('#') and len(raw) in (4, 7):
        try:
            return HexColor(raw)
        except Exception:
            return default
    return default


def _register_signature_font():
    """Best available handwriting/italic face for written signatures.

    Drop a licensed script font at static/fonts/signature.ttf to override the
    system faces — Linux servers rarely ship a true handwriting font.
    """
    global _SIG_FONT
    if _SIG_FONT:
        return _SIG_FONT
    windir = os.environ.get('WINDIR') or r'C:\Windows'
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = (
        os.path.join(here, 'static', 'fonts', 'signature.ttf'),
        os.path.join(windir, 'Fonts', 'segoesc.ttf'),
        os.path.join(windir, 'Fonts', 'segoepr.ttf'),
        '/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSerif-Italic.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
        '/usr/share/fonts/TTF/DejaVuSerif-Italic.ttf',
        '/Library/Fonts/Times New Roman Italic.ttf',
    )
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont('IDCardScript', path))
            _SIG_FONT = 'IDCardScript'
            return _SIG_FONT
        except Exception:
            continue
    _SIG_FONT = 'Times-Italic'
    return _SIG_FONT


def _fit_signature_size(c, text, font, max_width, base_size=13.0, min_size=7.5):
    """Shrink a written signature until it fits — a clipped name looks forged."""
    size = base_size
    while size > min_size and c.stringWidth(text, font, size) > max_width:
        size -= 0.25
    return size


def _signature_variants(text):
    """Ways to sign the same name, longest first: full, initialled, surname only."""
    yield text
    parts = text.split()
    if len(parts) > 2:
        yield ' '.join([f'{part[0].upper()}.' for part in parts[:-1]] + [parts[-1]])
    if len(parts) > 1:
        yield f'{parts[0][0].upper()}. {parts[-1]}'
        yield parts[-1]


def _signature_text_and_size(c, mark, font, max_width, base_size=13.0, min_size=7.5):
    """Pick the fullest form of a signature that fits the ruled line, and its size.

    A surname is never cut mid-word; long names drop to initials instead.
    """
    text = (mark or '').strip()
    if not text:
        return '', base_size
    best = (text, min_size)
    for index, candidate in enumerate(_signature_variants(text)):
        size = _fit_signature_size(c, candidate, font, max_width, base_size, min_size)
        if index == 0:
            best = (candidate, size)
        if c.stringWidth(candidate, font, size) <= max_width:
            return candidate, size
    return best


def _fit_text(c, text, font, size, max_width):
    text = (text or '').replace('\n', ' ').strip()
    if not text:
        return '—'
    if c.stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = '…'
    while text and c.stringWidth(text + ellipsis, font, size) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _wrap_text(c, text, font, size, max_width, max_lines=2):
    words = (text or '').split()
    if not words:
        return ['']
    lines = []
    current = ''
    for word in words:
        trial = f'{current} {word}'.strip()
        if current and c.stringWidth(trial, font, size) > max_width:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
            continue
        current = trial
    if current and len(lines) < max_lines:
        lines.append(current)
    used = sum(len(line.split()) for line in lines)
    unused = words[used:]
    if unused and lines:
        lines[-1] = _fit_text(c, f'{lines[-1]} {" ".join(unused)}', font, size, max_width)
    return lines[:max_lines] or ['']


def _image_reader(path_or_reader):
    if path_or_reader is None:
        return None
    if isinstance(path_or_reader, ImageReader):
        return path_or_reader
    if not path_or_reader or not os.path.isfile(str(path_or_reader)):
        return None
    try:
        return ImageReader(str(path_or_reader))
    except Exception:
        return None


def image_reader_from_data_uri(uri):
    if not uri or not str(uri).startswith('data:'):
        return None
    try:
        _header, payload = str(uri).split(',', 1)
        return ImageReader(BytesIO(base64.b64decode(payload)))
    except Exception:
        return None


def navy_tinted_seal_reader(path):
    """Black/white coat-of-arms tinted to FLPA navy (print_batch.html filter)."""
    if not path or not os.path.isfile(path):
        return None
    if PILImage is None:
        return _image_reader(path)
    try:
        img = PILImage.open(path).convert('RGBA')
        pixels = []
        for red, green, blue, alpha in img.getdata():
            if alpha < 8:
                pixels.append((0, 0, 0, 0))
                continue
            luminance = (red * 299 + green * 587 + blue * 114) / 1000.0
            if luminance > 232 and alpha > 200:
                pixels.append((0, 0, 0, 0))
                continue
            pixels.append((0, 45, 98, max(0, min(255, int(alpha * (1.0 - luminance / 255.0) * 1.15)))))
        img.putdata(pixels)
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return ImageReader(buf)
    except Exception:
        return _image_reader(path)


def faded_logo_reader(path, alpha=0.06):
    if not path or not os.path.isfile(path) or PILImage is None:
        return _image_reader(path)
    try:
        img = PILImage.open(path).convert('RGBA')
        faded = PILImage.new('RGBA', img.size)
        faded.paste(img, mask=img.split()[-1])
        faded.putalpha(img.split()[-1].point(lambda p: int(p * alpha)))
        buf = BytesIO()
        faded.save(buf, format='PNG')
        buf.seek(0)
        return ImageReader(buf)
    except Exception:
        return _image_reader(path)


def _clip_round_card(c, x, y):
    path = c.beginPath()
    path.roundRect(x, y, CARD_W, CARD_H, CARD_RADIUS)
    c.clipPath(path, stroke=0, fill=0)


def _draw_header_logo(c, x, y, size, logo):
    c.setFillColor(white)
    c.circle(x + size / 2.0, y + size / 2.0, size / 2.0, stroke=0, fill=1)
    if logo:
        inset = 0.6 * mm
        try:
            c.drawImage(
                logo,
                x + inset,
                y + inset,
                width=size - 2 * inset,
                height=size - 2 * inset,
                preserveAspectRatio=True,
                mask='auto',
                anchor='c',
            )
        except Exception:
            pass


def _draw_sunburst(c, x, y, w, h, cardinal):
    """Triangle of alternating cardinal/navy rays (HTML conic sunburst)."""
    c.saveState()
    path = c.beginPath()
    path.moveTo(x, y + h)
    path.lineTo(x + w, y + h)
    path.lineTo(x + w / 2.0, y)
    path.close()
    c.clipPath(path, stroke=0, fill=0)
    apex_x = x + w / 2.0
    apex_y = y + h + 8 * mm
    radius = math.hypot(w, h + 8 * mm) + 4 * mm
    slice_deg = 9
    for index in range(0, 360, slice_deg):
        c.setFillColor(cardinal if (index // slice_deg) % 2 == 0 else NAVY)
        start = math.radians(180 + index)
        end = math.radians(180 + index + slice_deg)
        path = c.beginPath()
        path.moveTo(apex_x, apex_y)
        path.lineTo(apex_x + radius * math.cos(start), apex_y + radius * math.sin(start))
        path.lineTo(apex_x + radius * math.cos(end), apex_y + radius * math.sin(end))
        path.close()
        c.drawPath(path, stroke=0, fill=1)
    c.restoreState()


def _draw_contained_image(c, reader, x, y, w, h):
    if not reader:
        return
    try:
        c.drawImage(reader, x, y, width=w, height=h, preserveAspectRatio=True, mask='auto', anchor='c')
    except Exception:
        pass


# Matches print_batch.html .photo-ring img (contain, centered in a true 24mm square).
PHOTO_PAD_X_MM = 0
PHOTO_PAD_BOTTOM_MM = 0
PHOTO_GOLD_BORDER_MM = 0.7
PHOTO_WELL_MM = 24.0
# CSS object-position: center center. Never slice-from-top (that is forehead-only).
PHOTO_POSITION_Y = 0.5
PHOTO_COVER_SCALE = 1.0
PHOTO_FIT = 'contain'


def id_photo_contain_rect(img_w, img_h, box_w, box_h):
    """Meet/contain: dest (x, y, w, h) relative to the photo box origin.

    The whole JPEG stays visible. Do not use max() scale (cover/slice-from-top).
    """
    if img_w <= 0 or img_h <= 0 or box_w <= 0 or box_h <= 0:
        return (0.0, 0.0, max(0.0, box_w), max(0.0, box_h))
    scale = min(box_w / float(img_w), box_h / float(img_h))
    dw, dh = img_w * scale, img_h * scale
    return ((box_w - dw) / 2.0, (box_h - dh) / 2.0, dw, dh)


def _draw_id_portrait(c, reader, x, y, w, h, position_y=PHOTO_POSITION_Y):
    """object-fit: contain — whole 800×800 JPEG visible in the square well."""
    if not reader:
        return
    try:
        iw, ih = reader.getSize()
    except Exception:
        iw = ih = 0
    if not iw or not ih or w <= 0 or h <= 0:
        return
    _px, _py, dw, dh = id_photo_contain_rect(iw, ih, w, h)
    try:
        c.drawImage(reader, x + _px, y + _py, width=dw, height=dh, preserveAspectRatio=True, mask='auto')
    except Exception:
        pass


def _from_top(card_y, offset_mm, height_mm=0):
    top = card_y + CARD_H - offset_mm * mm
    return top - height_mm * mm


def resolve_id_card_parent_name(student, card=None):
    """Parent / Guardian value for the ID front: payload, typed name, or linked parent."""
    if card:
        payload = card.get('parent_name')
        if payload and str(payload).strip():
            return str(payload).strip()
    if not student:
        return None
    for candidate in (
        getattr(student, 'parent_guardian_name', None),
        getattr(student, 'guardian_name', None),
        getattr(student, 'parent_name', None),
        getattr(getattr(student, 'parent_user', None), 'full_name', None),
    ):
        text = str(candidate).strip() if candidate else ''
        if text:
            return text
    return None


# Staff front geometry, in mm from the top of the card. Kept here so the CSS in
# templates/id_cards/print_batch.html and this canvas stay on the same grid.
STAFF_RAIL_W_MM = 8.6
STAFF_HEADER_MM = 13.0
STAFF_RAIL_TOP_MM = 13.6
STAFF_FOOTER_MM = 7.6
STAFF_PHOTO_TOP_MM = 19.8
STAFF_PHOTO_MM = 26.0


def _tracked_width(c, text, font, size, spacing):
    """Width of text drawn with extra letter spacing."""
    return c.stringWidth(text, font, size) + spacing * max(0, len(text) - 1)


def _draw_tracked(c, text, font, size, spacing, x, y):
    """Draw letterspaced text; canvas has no setCharSpace, text objects do."""
    obj = c.beginText(x, y)
    obj.setFont(font, size)
    obj.setCharSpace(spacing)
    obj.textOut(text)
    c.drawText(obj)


def _fit_font_size(c, text, font, max_width, base_size, min_size):
    """Largest size at or below base_size that keeps text on one line."""
    size = base_size
    while size > min_size and c.stringWidth(text, font, size) > max_width:
        size -= 0.25
    return size


def _draw_staff_front(c, x, y, card, assets):
    """Staff front: navy STAFF rail, gold-ringed portrait, name-led detail block."""
    student = card['student']
    brand = assets['brand']
    cardinal = assets['cardinal']
    logo = assets['logo']
    photo = assets.get('photo')
    watermark = assets.get('watermark')
    signature = assets.get('signature')
    sig_font = assets['sig_font']

    rail_w = STAFF_RAIL_W_MM * mm
    body_left = x + rail_w + 2.6 * mm
    body_right = x + CARD_W - 3.4 * mm
    body_w = body_right - body_left

    c.saveState()
    _clip_round_card(c, x, y)
    c.setFillColor(white)
    c.rect(x, y, CARD_W, CARD_H, stroke=0, fill=1)

    # Header
    header_y = _from_top(y, 0, STAFF_HEADER_MM)
    header_h = STAFF_HEADER_MM * mm
    c.setFillColor(NAVY)
    c.rect(x, header_y, CARD_W, header_h, stroke=0, fill=1)
    logo_size = 8.0 * mm
    _draw_header_logo(c, x + 2.6 * mm, header_y + (header_h - logo_size) / 2.0, logo_size, logo)
    name_x = x + 2.6 * mm + logo_size + 2.0 * mm
    name_w = CARD_W - (name_x - x) - 2.4 * mm
    lines = _wrap_text(c, id_card_header_title(side='front', uppercase=True), 'Helvetica-Bold', 6.0, name_w, 2)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 6.0)
    text_y = header_y + header_h / 2.0 + (5.0 if len(lines) > 1 else 1.8)
    for line in lines:
        c.drawString(name_x, text_y, line)
        text_y -= 7.0
    c.setFillColor(GOLD)
    c.setFont('Helvetica-Bold', 4.6)
    c.drawString(name_x, text_y + 0.6, '(F.L.P.A)')

    c.setFillColor(GOLD)
    c.rect(x, _from_top(y, STAFF_HEADER_MM, 0.6), CARD_W, 0.6 * mm, stroke=0, fill=1)

    # Full-height navy rail with the STAFF wordmark reversed out of it.
    rail_top = STAFF_RAIL_TOP_MM
    rail_bottom = CARD_H / mm - STAFF_FOOTER_MM - 0.6
    rail_h = rail_bottom - rail_top
    c.setFillColor(NAVY)
    c.rect(x, _from_top(y, rail_bottom), rail_w, rail_h * mm, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.rect(x + rail_w - 0.6 * mm, _from_top(y, rail_bottom), 0.6 * mm, rail_h * mm, stroke=0, fill=1)

    banner_len = _tracked_width(c, 'STAFF', 'Helvetica-Bold', 12.5, 2.2)
    c.saveState()
    c.setFillColor(white)
    c.translate(x + rail_w / 2.0 + 4.4, _from_top(y, (rail_top + rail_bottom) / 2.0) - banner_len / 2.0)
    c.rotate(90)
    _draw_tracked(c, 'STAFF', 'Helvetica-Bold', 12.5, 2.2, 0, 0)
    c.restoreState()

    # Address, muted small caps across the body column only.
    addr_lines = _wrap_text(
        c, (brand.get('full_address') or '').upper(), 'Helvetica-Bold', 4.5, body_w, 2
    )
    addr_y = _from_top(y, 16.4)
    c.setFillColor(MUTED)
    c.setFont('Helvetica-Bold', 4.5)
    for line in addr_lines:
        c.drawCentredString(body_left + body_w / 2.0, addr_y, line)
        addr_y -= 2.1 * mm

    if watermark:
        _draw_contained_image(
            c, watermark, body_left, y + 26 * mm, body_w, 24 * mm,
        )

    # Portrait: thin navy hairline, gold ring, white well, rounded corners.
    photo_size = STAFF_PHOTO_MM * mm
    photo_x = body_left + (body_w - photo_size) / 2.0
    photo_y = _from_top(y, STAFF_PHOTO_TOP_MM, STAFF_PHOTO_MM)
    for inset, radius, colour in (
        (0.95 * mm, 2.6 * mm, NAVY),
        (0.55 * mm, 2.3 * mm, GOLD),
        (0.15 * mm, 2.0 * mm, white),
    ):
        c.setFillColor(colour)
        c.roundRect(
            photo_x - inset, photo_y - inset,
            photo_size + 2 * inset, photo_size + 2 * inset,
            radius, stroke=0, fill=1,
        )
    c.saveState()
    clip = c.beginPath()
    clip.roundRect(photo_x, photo_y, photo_size, photo_size, 1.9 * mm)
    c.clipPath(clip, stroke=0, fill=0)
    _draw_id_portrait(c, photo, photo_x, photo_y, photo_size, photo_size)
    c.restoreState()

    # Name leads, position underneath, then a gold rule and the ID chip.
    full_name = getattr(student, 'full_name', None) or '—'
    name_size = _fit_font_size(c, full_name, 'Helvetica-Bold', body_w, 9.5, 6.4)
    c.setFillColor(NAVY)
    c.setFont('Helvetica-Bold', name_size)
    c.drawString(body_left, _from_top(y, 50.6), full_name)

    position = (card.get('position') or 'Staff').upper()
    pos_size = _fit_font_size(c, position, 'Helvetica-Bold', body_w - 6, 5.6, 4.0)
    c.setFillColor(cardinal)
    _draw_tracked(c, position, 'Helvetica-Bold', pos_size, 0.5, body_left, _from_top(y, 54.6))

    c.setFillColor(GOLD)
    c.rect(body_left, _from_top(y, 57.2, 0.35), body_w, 0.35 * mm, stroke=0, fill=1)

    staff_id = str(card.get('staff_id') or '—')
    chip_font = 6.4
    chip_w = min(body_w, c.stringWidth(staff_id, 'Helvetica-Bold', chip_font) + 6.5 * mm)
    chip_h = 4.6 * mm
    chip_y = _from_top(y, 63.0, 4.6)
    c.setFillColor(NAVY)
    c.roundRect(body_left, chip_y, chip_w, chip_h, chip_h / 2.0, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', chip_font)
    c.drawCentredString(body_left + chip_w / 2.0, chip_y + 1.5 * mm, staff_id)

    # Signature over a hairline, right aligned under the detail block.
    sig_w = min(26 * mm, body_w)
    sig_right = body_right
    if signature:
        _draw_contained_image(c, signature, sig_right - sig_w, _from_top(y, 72.8), sig_w, 5.0 * mm)
    else:
        mark = card.get('signature_mark') or full_name or 'Authorized Staff'
        sig_text, sig_size = _signature_text_and_size(c, mark, sig_font, sig_w, base_size=10.5)
        c.setFillColor(NAVY)
        c.setFont(sig_font, sig_size)
        c.drawRightString(sig_right, _from_top(y, 72.0), sig_text)
    c.setStrokeColor(HexColor('#9aa3b2'))
    c.setLineWidth(0.3 * mm)
    c.line(sig_right - sig_w, _from_top(y, 73.0), sig_right, _from_top(y, 73.0))
    caption = "HOLDER'S SIGNATURE"
    c.setFillColor(MUTED)
    _draw_tracked(
        c, caption, 'Helvetica-Bold', 4.2, 0.3,
        sig_right - _tracked_width(c, caption, 'Helvetica-Bold', 4.2, 0.3),
        _from_top(y, 75.5),
    )

    # Footer: gold hairline, solid brand-red band, motto.
    footer_h = STAFF_FOOTER_MM * mm
    c.setFillColor(GOLD)
    c.rect(x, y + footer_h, CARD_W, 0.8 * mm, stroke=0, fill=1)
    c.setFillColor(id_card_footer_fill(True, cardinal))
    c.rect(x, y, CARD_W, footer_h, stroke=0, fill=1)
    motto = (brand.get('motto') or '').upper()
    motto_lines = _wrap_text(c, motto, 'Helvetica-Bold', 4.2, CARD_W - 5 * mm, 2)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 4.2)
    motto_y = y + footer_h / 2.0 + (2.4 if len(motto_lines) > 1 else -1.2)
    for line in motto_lines:
        c.drawCentredString(x + CARD_W / 2.0, motto_y, line)
        motto_y -= 5.2

    c.restoreState()
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.3 * mm)
    c.roundRect(x, y, CARD_W, CARD_H, CARD_RADIUS, stroke=1, fill=0)


def _draw_front(c, x, y, card, assets):
    if card.get('card_kind') == 'staff':
        _draw_staff_front(c, x, y, card, assets)
        return
    student = card['student']
    brand = assets['brand']
    cardinal = assets['cardinal']
    logo = assets['logo']
    photo = assets.get('photo')
    watermark = assets.get('watermark')
    year_label = assets.get('year_label') or ''

    c.saveState()
    _clip_round_card(c, x, y)
    c.setFillColor(white)
    c.rect(x, y, CARD_W, CARD_H, stroke=0, fill=1)

    header_h = 11.5 * mm
    header_y = _from_top(y, 0, 11.5)
    c.setFillColor(cardinal)
    c.rect(x, header_y, CARD_W, header_h, stroke=0, fill=1)

    logo_size = 8.2 * mm
    _draw_header_logo(c, x + 3 * mm, header_y + (header_h - logo_size) / 2.0, logo_size, logo)
    name_x = x + 3 * mm + logo_size + 2.0 * mm
    name_w = CARD_W - (name_x - x) - 2.5 * mm
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 6.2)
    lines = _wrap_text(c, id_card_header_title(side='front', uppercase=True), 'Helvetica-Bold', 6.2, name_w, 2)
    text_y = header_y + header_h / 2.0 + (3.2 if len(lines) > 1 else 0)
    for line in lines:
        c.drawString(name_x, text_y, line)
        text_y -= 7.2

    sun_h = 16 * mm
    sun_y = _from_top(y, 11.5, 16)
    _draw_sunburst(c, x, sun_y, CARD_W, sun_h, cardinal)

    # Navy band sits under the photo (HTML: after photo-wrap, margin-top -11mm).
    photo_top_off = 18.5
    photo_size = PHOTO_WELL_MM * mm
    band_top_off = 31.5
    band_y = _from_top(y, band_top_off, 8)
    c.setFillColor(NAVY)
    c.rect(x, band_y, CARD_W, 8 * mm, stroke=0, fill=1)

    if watermark:
        _draw_contained_image(
            c,
            watermark,
            x + 8 * mm,
            y + 18 * mm,
            CARD_W - 16 * mm,
            28 * mm,
        )

    photo_x = x + (CARD_W - photo_size) / 2.0
    photo_y = _from_top(y, photo_top_off, PHOTO_WELL_MM)
    # Navy then gold rings (HTML: 0.7mm gold + 0.45mm navy shadow)
    c.setFillColor(NAVY)
    c.roundRect(photo_x - 0.45 * mm, photo_y - 0.45 * mm, photo_size + 0.9 * mm, photo_size + 0.9 * mm, 1.1 * mm, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.roundRect(photo_x - 0.15 * mm, photo_y - 0.15 * mm, photo_size + 0.3 * mm, photo_size + 0.3 * mm, 0.95 * mm, stroke=0, fill=1)
    gold = PHOTO_GOLD_BORDER_MM * mm
    well_x = photo_x + gold
    well_y = photo_y + gold
    well_w = photo_size - 2 * gold
    well_h = photo_size - 2 * gold
    c.setFillColor(white)
    c.roundRect(well_x, well_y, well_w, well_h, 0.6 * mm, stroke=0, fill=1)
    # Square inner well: draw the full JPEG with contain (meet), not cover/slice.
    pad_x = PHOTO_PAD_X_MM * mm
    pad_bottom = PHOTO_PAD_BOTTOM_MM * mm
    img_x = well_x + pad_x
    img_y = well_y + pad_bottom
    img_w = well_w - 2 * pad_x
    img_h = well_h - pad_bottom
    c.saveState()
    clip = c.beginPath()
    clip.roundRect(well_x, well_y, well_w, well_h, 0.6 * mm)
    c.clipPath(clip, stroke=0, fill=0)
    _draw_id_portrait(c, photo, img_x, img_y, img_w, img_h)
    c.restoreState()

    parent_name = resolve_id_card_parent_name(student, card)
    phone = getattr(student, 'parent_phone', None) or brand.get('phones')
    rows = [
        ('Student Name:', getattr(student, 'full_name', None) or '—'),
        ('Parent / Guardian:', parent_name or '—'),
        ('Student ID:', getattr(student, 'student_id', None) or '—'),
        ('Class:', card.get('class_label') or assets.get('class_label') or '—'),
        ('Phone:', phone or '—'),
    ]
    if year_label:
        rows.append(('Session:', year_label))

    body_top = 50.5
    label_w = 20 * mm
    value_w = CARD_W - 8.4 * mm - label_w - 1 * mm
    row_y = _from_top(y, body_top) - 6
    for label, value in rows:
        c.setFillColor(cardinal)
        c.setFont('Helvetica-Bold', 6.1)
        c.drawString(x + 4.2 * mm, row_y, label)
        c.setFillColor(INK)
        c.setFont('Helvetica', 6.1)
        if label.startswith('Parent'):
            parent_lines = _wrap_text(c, str(value), 'Helvetica', 6.1, value_w, 2)
            line_y = row_y
            for line in parent_lines:
                c.drawString(x + 4.2 * mm + label_w, line_y, line)
                line_y -= 7.2
            row_y -= 9.2 if len(parent_lines) < 2 else 16.4
            continue
        c.drawString(x + 4.2 * mm + label_w, row_y, _fit_text(c, str(value), 'Helvetica', 6.1, value_w))
        row_y -= 9.2

    footer_h = 7.2 * mm
    c.setFillColor(GOLD)
    c.rect(x, y + footer_h, CARD_W, 1.2 * mm, stroke=0, fill=1)
    c.setFillColor(id_card_footer_fill(False, cardinal))
    c.rect(x, y, CARD_W, footer_h, stroke=0, fill=1)
    motto = (brand.get('motto') or '').upper()
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 4.4)
    motto_w = CARD_W - 5 * mm
    motto_lines = _wrap_text(c, motto, 'Helvetica-Bold', 4.4, motto_w, 2)
    motto_y = y + footer_h / 2.0 + (2.4 if len(motto_lines) > 1 else -1.2)
    for line in motto_lines:
        c.drawCentredString(x + CARD_W / 2.0, motto_y, line)
        motto_y -= 5.4

    c.restoreState()
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.3 * mm)
    c.roundRect(x, y, CARD_W, CARD_H, CARD_RADIUS, stroke=1, fill=0)


def _draw_back(c, x, y, card, assets):
    student = card['student']
    is_staff = card.get('card_kind') == 'staff'
    brand = assets['brand']
    logo = assets['logo']
    seal = assets.get('seal')
    qr = assets.get('qr')
    signature = assets.get('signature')
    sig_font = assets['sig_font']
    cardinal = assets['cardinal']

    c.saveState()
    _clip_round_card(c, x, y)
    c.setFillColor(white)
    c.rect(x, y, CARD_W, CARD_H, stroke=0, fill=1)

    header_h = 11.5 * mm
    header_y = _from_top(y, 0, 11.5)
    c.setFillColor(NAVY)
    c.rect(x, header_y, CARD_W, header_h, stroke=0, fill=1)
    logo_size = 8.2 * mm
    _draw_header_logo(c, x + 3 * mm, header_y + (header_h - logo_size) / 2.0, logo_size, logo)
    name_x = x + 3 * mm + logo_size + 2.0 * mm
    name_w = CARD_W - (name_x - x) - 2.5 * mm
    c.setFillColor(GOLD)
    c.setFont('Helvetica-Bold', 6.2)
    lines = _wrap_text(c, id_card_header_title(side='back', uppercase=True), 'Helvetica-Bold', 6.2, name_w, 2)
    text_y = header_y + header_h / 2.0 + (3.2 if len(lines) > 1 else 0)
    for line in lines:
        c.drawString(name_x, text_y, line)
        text_y -= 7.2

    rule_y = _from_top(y, 11.5, 1.3)
    c.setFillColor(GOLD)
    c.rect(x, rule_y, CARD_W, 1.3 * mm, stroke=0, fill=1)

    if seal:
        plate = 22 * mm
        plate_x = x + (CARD_W - plate) / 2.0
        plate_y = _from_top(y, 13.6, 22)
        c.setFillColor(NAVY)
        c.circle(plate_x + plate / 2.0, plate_y + plate / 2.0, plate / 2.0 + 0.35 * mm, stroke=0, fill=1)
        c.setFillColor(GOLD)
        c.circle(plate_x + plate / 2.0, plate_y + plate / 2.0, plate / 2.0, stroke=0, fill=1)
        c.setFillColor(HexColor('#fffef8'))
        c.circle(plate_x + plate / 2.0, plate_y + plate / 2.0, plate / 2.0 - 0.4 * mm, stroke=0, fill=1)
        _draw_contained_image(c, seal, plate_x + 1.5 * mm, plate_y + 1.5 * mm, plate - 3 * mm, plate - 3 * mm)

    copy_y = _from_top(y, 38.2)
    c.setFillColor(MUTED)
    c.setFont('Helvetica', 6)
    c.drawCentredString(x + CARD_W / 2.0, copy_y, 'This ID card is the property of this school.')
    c.drawCentredString(x + CARD_W / 2.0, copy_y - 10, 'If found, please return it to the location below.')
    c.setFillColor(NAVY)
    c.setFont('Helvetica-Bold', 6.2)
    address = (brand.get('full_address') or '').upper()
    addr_w = CARD_W - 8 * mm
    addr_lines = _wrap_text(c, address, 'Helvetica-Bold', 6.2, addr_w, 2)
    addr_y = copy_y - 22
    for line in addr_lines:
        c.drawCentredString(x + CARD_W / 2.0, addr_y, line)
        addr_y -= 8

    expires = card.get('expiration_date') or getattr(student, 'id_expiration_date', None)
    expire_text = f"Expire Date: {expires.strftime('%m/%d/%Y')}" if expires else (
        'Authorized Staff ID' if is_staff else 'Expire Date: —'
    )
    c.setFillColor(cardinal)
    c.setFont('Helvetica-Bold', 7)
    c.drawCentredString(x + CARD_W / 2.0, y + 32.5 * mm, expire_text)

    sig_w = 32 * mm
    sig_x = x + (CARD_W - sig_w) / 2.0
    sig_y = y + 22.5 * mm
    mark = card.get('signature_mark') or getattr(student, 'official_signature_mark', None) or ''
    if is_staff and not mark:
        mark = 'Authorized Staff'
    if signature:
        _draw_contained_image(c, signature, sig_x, sig_y, sig_w, 7 * mm)
    elif mark:
        c.setFillColor(NAVY)
        sig_text, sig_size = _signature_text_and_size(c, mark, sig_font, sig_w)
        c.setFont(sig_font, sig_size)
        c.drawCentredString(x + CARD_W / 2.0, sig_y + 1.5 * mm, _fit_text(c, sig_text, sig_font, sig_size, sig_w))
    c.setStrokeColor(HexColor('#9ca3af'))
    c.setLineWidth(0.35 * mm)
    c.line(sig_x, sig_y, sig_x + sig_w, sig_y)
    c.setFillColor(MUTED)
    c.setFont('Helvetica-Bold', 6.5)
    c.drawCentredString(x + CARD_W / 2.0, sig_y - 8, 'SIGNATURE')

    if qr:
        qr_size = 13 * mm
        qr_x = x + CARD_W - 2.2 * mm - qr_size
        qr_y = y + 18.8 * mm
        c.setFillColor(white)
        c.setStrokeColor(HexColor('#e5e7eb'))
        c.setLineWidth(0.25 * mm)
        c.rect(qr_x - 0.4 * mm, qr_y - 0.4 * mm, qr_size + 0.8 * mm, qr_size + 0.8 * mm, stroke=1, fill=1)
        _draw_contained_image(c, qr, qr_x, qr_y, qr_size, qr_size)
        c.setFillColor(NAVY)
        c.setFont('Helvetica-Bold', 3.6)
        c.drawCentredString(qr_x + qr_size / 2.0, y + 15.6 * mm, 'SCAN FOR PORTAL')

    # Solid footer bar (14mm): staff brand red, student navy. No stripes.
    footer_h = ID_CARD_BACK_FOOTER_MM * mm
    c.setFillColor(id_card_footer_fill(is_staff, cardinal))
    c.rect(x, y, CARD_W, footer_h, stroke=0, fill=1)

    c.restoreState()
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.3 * mm)
    c.roundRect(x, y, CARD_W, CARD_H, CARD_RADIUS, stroke=1, fill=0)


def build_class_id_cards_pdf(
    cards,
    *,
    klass=None,
    display_year=None,
    brand=None,
    logo_path=None,
    seal_path=None,
    photo_paths=None,
    signature_paths=None,
):
    """Return a BytesIO PDF of ready CR80 ID cards (front + back per student)."""
    brand = brand or {}
    cardinal = _hex_color(brand.get('brand_red'))
    logo = _image_reader(logo_path)
    watermark = faded_logo_reader(logo_path)
    seal = navy_tinted_seal_reader(seal_path)
    sig_font = _register_signature_font()
    year_label = getattr(display_year, 'name', None) or ''
    class_label = getattr(klass, 'name', None) or ''
    photo_paths = photo_paths or {}
    signature_paths = signature_paths or {}

    buffer = BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4)
    class_name = getattr(klass, 'name', None) or 'Class'
    c.setTitle(f'FLPA ID Cards — {class_name}' + (f' — {year_label}' if year_label else ''))
    c.setAuthor(brand.get('name') or 'Future Leaders Preparatory Academy')

    page_w, page_h = A4
    pair_w = CARD_W * 2 + PAIR_GAP
    origin_x = (page_w - pair_w) / 2.0
    top_y = page_h - PAGE_MARGIN

    assets_base = {
        'brand': brand,
        'cardinal': cardinal,
        'logo': logo,
        'watermark': watermark,
        'seal': seal,
        'sig_font': sig_font,
        'year_label': year_label,
        'class_label': class_label,
    }

    row = 0
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        student = card.get('student')
        student_id = getattr(student, 'id', None)
        assets = dict(assets_base)
        try:
            assets['photo'] = _image_reader(photo_paths.get(student_id) or card.get('photo_path'))
        except Exception:
            logger.exception('ID card PDF photo failed for student %s', student_id)
            assets['photo'] = None
        try:
            assets['signature'] = _image_reader(
                signature_paths.get(student_id) or card.get('signature_path')
            )
        except Exception:
            logger.exception('ID card PDF signature failed for student %s', student_id)
            assets['signature'] = None
        try:
            assets['qr'] = image_reader_from_data_uri(card.get('qr_code_data_uri'))
        except Exception:
            logger.exception('ID card PDF QR failed for student %s', student_id)
            assets['qr'] = None
        if card.get('class_label'):
            assets['class_label'] = card['class_label']

        if row >= ROWS_PER_PAGE:
            c.showPage()
            row = 0
        card_top = top_y - row * (CARD_H + ROW_GAP)
        card_y = card_top - CARD_H
        try:
            _draw_front(c, origin_x, card_y, card, assets)
        except Exception:
            logger.exception('ID card PDF front failed for student %s', student_id)
            try:
                c.restoreState()
            except Exception:
                pass
        try:
            _draw_back(c, origin_x + CARD_W + PAIR_GAP, card_y, card, assets)
        except Exception:
            logger.exception('ID card PDF back failed for student %s', student_id)
            try:
                c.restoreState()
            except Exception:
                pass
        row += 1

    c.save()
    buffer.seek(0)
    return buffer
