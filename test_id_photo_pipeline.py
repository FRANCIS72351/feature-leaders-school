"""ID photo cleanup — synthetic images only, no rembg / no student PII."""
import io
import os
import unittest
from unittest import mock

from PIL import Image, ImageChops, ImageDraw

from app import (
    ID_PHOTO_OUTPUT_PX,
    ID_PHOTO_REMBG_FAIL_MESSAGE,
    _ID_PHOTO_ALPHA_CLEAR,
    _ID_PHOTO_ALPHA_OPAQUE,
    _ID_PHOTO_DENOISE_MIX,
    _ID_PHOTO_ERODE_PX,
    _ID_PHOTO_FEATHER_PX,
    _ID_PHOTO_HEAD_SHOULDERS_RATIO,
    _ID_PHOTO_HEADROOM_FRAC,
    _ID_PHOTO_JPEG_QUALITY,
    _ID_PHOTO_SUBJECT_FRINGE,
    _ID_PHOTO_UNSHARP_PERCENT,
    _ID_PHOTO_WHITE_LUMA,
    _composite_id_cutout_on_white,
    _cover_subject_keep_head,
    _edge_columns_uniformly_white,
    _finish_id_portrait,
    _fit_subject_on_white_square,
    _id_photo_edge_white_frac,
    _id_photo_is_face_only_square,
    _lower_third_side_columns_white,
    _lower_third_white_frac,
    _refine_id_photo_surface,
    _save_id_photo_jpeg,
    _studio_even_light_id_photo,
    _studio_even_light_lut,
    _corners_near_white,
    _id_photo_already_usable_hs,
    _id_photo_needs_background_removal,
    _process_id_card_image_bytes,
    _subject_bbox,
    _top_corners_near_white,
)


def _all_white_edge_columns(img, from_left=True, white_threshold=245, min_white_frac=0.92):
    """How many consecutive all-white-ish columns from one edge."""
    rgb = img.convert('RGB')
    width, height = rgb.size
    pixels = rgb.load()
    count = 0
    columns = range(width) if from_left else range(width - 1, -1, -1)
    for x in columns:
        white = 0
        for y in range(height):
            red, green, blue = pixels[x, y]
            if (0.299 * red + 0.587 * green + 0.114 * blue) >= white_threshold:
                white += 1
        if white / float(height) >= min_white_frac:
            count += 1
        else:
            break
    return count


def _hard_cutout(size=240, radius=70):
    """Opaque brown ellipse on transparent — jagged rembg-style binary alpha."""
    img = Image.new('RGBA', (size, size), (40, 90, 180, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(92, 58, 42, 255),
    )
    return img


def _punch_interior_alpha(img, alpha, box=(105, 105, 135, 135)):
    """Simulate rembg treating dark skin as background (mid/low interior alpha)."""
    pixels = img.load()
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        for x in range(x0, x1):
            red, green, blue, _old = pixels[x, y]
            pixels[x, y] = (red, green, blue, alpha)
    return img


def _standing_student(canvas_w, canvas_h, left, top):
    """Full-body on white: head narrower than shoulders, navy shirt, green feet."""
    canvas = Image.new('RGB', (canvas_w, canvas_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    # Shoulders 180px wide; head 80px (face-width crop would zoom to eyes only).
    draw.ellipse((left + 50, top, left + 130, top + 100), fill=(180, 70, 40))
    draw.rectangle((left + 70, top + 95, left + 110, top + 125), fill=(180, 70, 40))
    draw.rectangle((left, top + 120, left + 180, top + 340), fill=(16, 20, 80))
    draw.rectangle((left + 40, top + 340, left + 140, top + 920), fill=(16, 20, 80))
    draw.rectangle((left + 40, top + 920, left + 140, top + 1020), fill=(0, 220, 0))
    return canvas


def _outdoor_student(width=640, height=800):
    """Colored outdoor backdrop (blue wall + brown structure) with a dark-skinned student."""
    canvas = Image.new('RGB', (width, height), (40, 120, 210))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, max(8, width // 3), height), fill=(110, 95, 80))
    cx = width // 2
    draw.ellipse((cx - 50, 70, cx + 50, 175), fill=(50, 30, 20))
    draw.rectangle((cx - 90, 170, cx + 90, 520), fill=(12, 12, 12))
    return canvas


def _fake_rembg_cutout(img, disable_on_fail=True, **_kwargs):
    """Keep dark skin / black shirt; drop blue-wall and brown-structure pixels."""
    rgb = img.convert('RGB')
    red, green, _blue = rgb.split()
    mask = ImageChops.multiply(
        red.point(lambda value: 255 if value < 90 else 0),
        green.point(lambda value: 255 if value < 80 else 0),
    )
    rgba = rgb.convert('RGBA')
    rgba.putalpha(mask)
    return rgba


def _is_brown_head(pixel):
    return pixel[0] > 120 and pixel[0] > pixel[2] and sum(pixel) / 3.0 < 220


def _is_navy_shirt(pixel):
    return pixel[2] > pixel[0] and pixel[1] < 80 and sum(pixel) / 3.0 < 140


class IdPhotoPipelineTestCase(unittest.TestCase):
    def test_feather_blends_silhouette_into_white(self):
        cutout = _hard_cutout()
        result = _composite_id_cutout_on_white(cutout)
        self.assertEqual(result.mode, 'RGB')
        # Corners must stay studio white.
        self.assertEqual(result.getpixel((2, 2)), (255, 255, 255))
        # Interior of the subject stays dark (not bleached).
        mid = result.getpixel((120, 120))
        self.assertLess(sum(mid) / 3.0, 120)
        # Hard rembg edges are 0/255; a 1–2px Gaussian leaves a light fringe.
        gray = result.convert('L')
        pixels = gray.get_flattened_data() if hasattr(gray, 'get_flattened_data') else list(gray.getdata())
        fringe = [pixel for pixel in pixels if 20 < pixel < 240]
        self.assertGreater(len(fringe), 40)

    def test_interior_mid_alpha_is_not_punched(self):
        """Dark-skin rembg leftovers (alpha ~70) must stay the subject, not white voids."""
        cutout = _punch_interior_alpha(_hard_cutout(), 70)
        result = _composite_id_cutout_on_white(cutout)
        mid = result.getpixel((120, 120))
        self.assertNotEqual(mid, (255, 255, 255))
        self.assertLess(sum(mid) / 3.0, 100)
        self.assertLess(abs(mid[0] - 92), 24)

    def test_enclosed_transparent_hole_is_filled(self):
        """Fully punched interior alpha (forehead void) is filled from surrounding subject RGB."""
        cutout = _punch_interior_alpha(_hard_cutout(), 0)
        result = _composite_id_cutout_on_white(cutout)
        mid = result.getpixel((120, 120))
        self.assertNotEqual(mid, (255, 255, 255))
        self.assertLess(sum(mid) / 3.0, 100)

    def test_silhouette_is_not_eroded_away(self):
        cutout = _hard_cutout(size=240, radius=70)
        result = _composite_id_cutout_on_white(cutout)
        # ~4px inside the ellipse must remain the person (0px erode).
        inside = result.getpixel((120, 54))
        self.assertLess(sum(inside) / 3.0, 160)
        self.assertEqual(_ID_PHOTO_ERODE_PX, 0)

    def test_shadow_lift_is_disabled(self):
        lut = _studio_even_light_lut(p20=32, p50=70, p90=210, gap=178)
        self.assertEqual(lut[32], 32)
        self.assertEqual(lut, list(range(256)))
        src = Image.new('RGB', (80, 80), (48, 28, 20))
        out = _studio_even_light_id_photo(src)
        self.assertEqual(out.getpixel((40, 40)), (48, 28, 20))

    def test_denoise_leaves_white_and_does_not_bleach(self):
        img = Image.new('RGB', (160, 160), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse((30, 20, 130, 150), fill=(70, 42, 30))
        cleaned = _refine_id_photo_surface(img)
        self.assertEqual(cleaned.getpixel((4, 4)), (255, 255, 255))
        before = img.getpixel((80, 80))
        after = cleaned.getpixel((80, 80))
        # Surface refine is a no-op so rembg RGB is unchanged.
        self.assertEqual(after, before)

    def test_unsharp_is_mild(self):
        src = Image.new('RGB', (64, 64), (80, 50, 40))
        out = _finish_id_portrait(src)
        self.assertEqual(out.size, (64, 64))
        self.assertEqual(_ID_PHOTO_UNSHARP_PERCENT, 70)
        pixel = out.getpixel((32, 32))
        self.assertLess(pixel[0], 200)

    def test_jpeg_quality_92_444(self):
        img = Image.new('RGB', (ID_PHOTO_OUTPUT_PX, ID_PHOTO_OUTPUT_PX), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse((200, 80, 600, 720), fill=(88, 54, 38))
        buffer = io.BytesIO()
        _save_id_photo_jpeg(img, buffer)
        payload = buffer.getvalue()
        self.assertGreater(len(payload), 1000)
        saved = Image.open(io.BytesIO(payload))
        self.assertEqual(saved.format, 'JPEG')
        self.assertEqual(saved.size, (ID_PHOTO_OUTPUT_PX, ID_PHOTO_OUTPUT_PX))
        self.assertEqual(_ID_PHOTO_JPEG_QUALITY, 92)
        self.assertEqual(_ID_PHOTO_ALPHA_CLEAR, 40)
        self.assertEqual(_ID_PHOTO_ALPHA_OPAQUE, 180)
        self.assertAlmostEqual(_ID_PHOTO_FEATHER_PX, 1.5, places=1)
        self.assertLessEqual(_ID_PHOTO_FEATHER_PX, 2.0)
        self.assertAlmostEqual(_ID_PHOTO_DENOISE_MIX, 0.0, places=2)
        sampling = getattr(saved, 'layer', None)
        if sampling:
            # layer tuples are (id, vsamp, hsamp, qtable)
            self.assertTrue(all(item[1] == 1 and item[2] == 1 for item in sampling))

    def test_subject_bbox_keeps_dark_clothes_and_ignores_near_white(self):
        """Luma ~245 is studio white; navy/black clothes stay inside the person box."""
        self.assertEqual(_ID_PHOTO_WHITE_LUMA, 245)
        self.assertAlmostEqual(_ID_PHOTO_SUBJECT_FRINGE, 0.01, places=3)
        self.assertGreaterEqual(_ID_PHOTO_HEAD_SHOULDERS_RATIO, 1.15)
        self.assertLessEqual(_ID_PHOTO_HEAD_SHOULDERS_RATIO, 1.35)
        self.assertGreaterEqual(_ID_PHOTO_HEADROOM_FRAC, 0.08)
        self.assertLessEqual(_ID_PHOTO_HEADROOM_FRAC, 0.12)
        img = Image.new('RGB', (200, 200), (250, 251, 249))
        draw = ImageDraw.Draw(img)
        draw.rectangle((70, 40, 130, 175), fill=(12, 14, 22))
        bbox = _subject_bbox(img)
        self.assertIsNotNone(bbox)
        x0, y0, x1, y1 = bbox
        self.assertLessEqual(x0, 72)
        self.assertGreaterEqual(x1, 128)
        self.assertLessEqual(y0, 42)
        self.assertGreaterEqual(y1, 173)
        self.assertGreater(x0, 20)
        self.assertLess(x1, 180)

    def test_fit_subject_keeps_head_and_shoulders_on_tall_silhouette(self):
        """Tall full-body on white: square shows head + shirt, not eyes-only."""
        canvas = _standing_student(400, 1200, left=110, top=40)
        result = _fit_subject_on_white_square(canvas, 800)
        self.assertEqual(result.size, (800, 800))
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        self.assertNotEqual(result.getpixel((400, 160)), (255, 255, 255))
        # Lower third is the navy shirt — face-width crop would still be forehead/eyes.
        self.assertTrue(_is_navy_shirt(result.getpixel((400, 640))))
        self.assertTrue(_is_navy_shirt(result.getpixel((20, 700))))
        self.assertTrue(_is_navy_shirt(result.getpixel((780, 700))))
        self.assertLess(_id_photo_edge_white_frac(result, True), 0.82)
        self.assertLess(_id_photo_edge_white_frac(result, False), 0.82)
        self.assertFalse(_lower_third_side_columns_white(result))
        self.assertFalse(_edge_columns_uniformly_white(result))
        for y in range(0, 800, 25):
            for x in range(0, 800, 25):
                pixel = result.getpixel((x, y))
                self.assertFalse(pixel[1] > 180 and pixel[0] < 40)

    def test_fit_subject_fills_square_no_side_gutters(self):
        """Off-center standing student fills 800×800 — no rembg-white side bars."""
        canvas = _standing_student(900, 1400, left=620, top=50)
        result = _fit_subject_on_white_square(canvas, 800)
        self.assertEqual(result.size, (800, 800))
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        self.assertNotEqual(result.getpixel((400, 160)), (255, 255, 255))
        self.assertTrue(_is_navy_shirt(result.getpixel((400, 660))))
        self.assertLessEqual(_all_white_edge_columns(result, from_left=True), 2)
        self.assertLessEqual(_all_white_edge_columns(result, from_left=False), 2)
        self.assertLess(_id_photo_edge_white_frac(result, True), 0.82)
        self.assertLess(_id_photo_edge_white_frac(result, False), 0.82)
        self.assertFalse(_lower_third_side_columns_white(result))
        gray = result.convert('L')
        xs = [
            x
            for y in range(0, 800, 4)
            for x in range(0, 800, 4)
            if gray.getpixel((x, y)) < 245
        ]
        self.assertGreater(len(xs), 20)
        mid = sum(xs) / float(len(xs))
        self.assertGreater(mid, 340)
        self.assertLess(mid, 460)

    def test_narrow_blob_on_tall_white_fills_width(self):
        """Tall white canvas + standing student: 800×800 with no all-white L/R columns."""
        canvas = _standing_student(600, 1600, left=210, top=70)
        result = _fit_subject_on_white_square(canvas, 800)
        self.assertEqual(result.size, (800, 800))
        self.assertLessEqual(_all_white_edge_columns(result, from_left=True), 2)
        self.assertLessEqual(_all_white_edge_columns(result, from_left=False), 2)
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        self.assertTrue(_is_navy_shirt(result.getpixel((400, 650))))
        self.assertLess(_id_photo_edge_white_frac(result, True), 0.82)
        self.assertLess(_id_photo_edge_white_frac(result, False), 0.82)
        self.assertFalse(_lower_third_side_columns_white(result))
        # Bust row reaches both sides (allow 1–2px rembg fringe).
        for x in (0, 1, 798, 799):
            pixel = result.getpixel((x, 700))
            self.assertLess(sum(pixel) / 3.0, 245, 'edge x=%s still studio white' % x)

    def test_letterboxed_head_and_shoulders_fills_square(self):
        """Old letterbox JPEG (white pillars, H&S already in frame) must scale edge-to-edge."""
        person = Image.new('RGB', (280, 360), (255, 255, 255))
        draw = ImageDraw.Draw(person)
        draw.ellipse((70, 8, 210, 148), fill=(180, 70, 40))
        draw.rectangle((10, 138, 270, 350), fill=(16, 20, 80))
        canvas = Image.new('RGB', (800, 800), (255, 255, 255))
        canvas.paste(person, (260, 90))
        self.assertGreater(_all_white_edge_columns(canvas, from_left=True), 40)
        self.assertGreater(_all_white_edge_columns(canvas, from_left=False), 40)
        result = _fit_subject_on_white_square(canvas, 800)
        self.assertEqual(result.size, (800, 800))
        self.assertLessEqual(_all_white_edge_columns(result, from_left=True), 2)
        self.assertLessEqual(_all_white_edge_columns(result, from_left=False), 2)
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        self.assertTrue(_is_navy_shirt(result.getpixel((400, 640))))
        self.assertFalse(_is_brown_head(result.getpixel((400, 640))))
        self.assertLess(_id_photo_edge_white_frac(result, True), 0.82)
        self.assertLess(_id_photo_edge_white_frac(result, False), 0.82)
        self.assertFalse(_lower_third_side_columns_white(result))
        for x in (0, 1, 798, 799):
            pixel = result.getpixel((x, 700))
            self.assertLess(sum(pixel) / 3.0, 245, 'edge x=%s still studio white' % x)

    def test_cover_by_width_does_not_crop_shoulders(self):
        """A tall bust-width portrait must fill L/R; extra comes from the bottom."""
        src = Image.new('RGB', (200, 280), (255, 255, 255))
        draw = ImageDraw.Draw(src)
        draw.ellipse((50, 4, 150, 100), fill=(180, 70, 40))
        draw.rectangle((0, 96, 199, 279), fill=(16, 20, 80))
        result = _cover_subject_keep_head(src, 800)
        self.assertEqual(result.size, (800, 800))
        self.assertLessEqual(_all_white_edge_columns(result, from_left=True), 2)
        self.assertLessEqual(_all_white_edge_columns(result, from_left=False), 2)
        self.assertTrue(_is_navy_shirt(result.getpixel((20, 700))))
        self.assertTrue(_is_navy_shirt(result.getpixel((780, 700))))
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        self.assertFalse(_is_brown_head(result.getpixel((400, 0))))

    def test_already_head_and_shoulders_does_not_zoom_to_face(self):
        """Typical rembg selfie (H&S on white): keep shoulders. Face-width crop is eyes-only."""
        canvas = Image.new('RGB', (400, 420), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((160, 20, 240, 120), fill=(180, 70, 40))
        draw.rectangle((180, 115, 220, 145), fill=(180, 70, 40))
        draw.rectangle((110, 140, 290, 400), fill=(16, 20, 80))
        result = _fit_subject_on_white_square(canvas, 800)
        self.assertEqual(result.size, (800, 800))
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        self.assertNotEqual(result.getpixel((400, 160)), (255, 255, 255))
        self.assertTrue(_is_navy_shirt(result.getpixel((400, 640))))
        self.assertFalse(_is_brown_head(result.getpixel((400, 640))))
        self.assertTrue(_is_navy_shirt(result.getpixel((20, 700))))
        self.assertTrue(_is_navy_shirt(result.getpixel((780, 700))))
        self.assertLess(_id_photo_edge_white_frac(result, True), 0.82)
        self.assertLess(_id_photo_edge_white_frac(result, False), 0.82)
        self.assertFalse(_edge_columns_uniformly_white(result))
        self.assertFalse(_lower_third_side_columns_white(result))
        for x in (0, 1, 798, 799):
            pixel = result.getpixel((x, 700))
            self.assertLess(sum(pixel) / 3.0, 245, 'edge x=%s still studio white' % x)

    def test_white_shirt_keeps_sleeve_width_not_face(self):
        """White chest panel is studio-white; crop width must be the red sleeves, not the head."""
        canvas = Image.new('RGB', (400, 700), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((150, 20, 250, 140), fill=(180, 70, 40))
        draw.rectangle((180, 130, 220, 170), fill=(180, 70, 40))
        draw.rectangle((90, 170, 310, 500), fill=(200, 30, 40))
        draw.rectangle((140, 200, 260, 500), fill=(255, 255, 255))
        result = _fit_subject_on_white_square(canvas, 800)
        self.assertEqual(result.size, (800, 800))
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        left = result.getpixel((20, 700))
        right = result.getpixel((780, 700))
        self.assertGreater(left[0], 140)
        self.assertGreater(left[0], left[1] + 20)
        self.assertGreater(right[0], 140)
        self.assertGreater(right[0], right[1] + 20)
        self.assertFalse(_lower_third_side_columns_white(result))
        self.assertLessEqual(_all_white_edge_columns(result, from_left=True), 2)
        self.assertLessEqual(_all_white_edge_columns(result, from_left=False), 2)

    def test_reprocess_writes_new_filename_for_letterboxed_id_photos_file(self):
        """Print-time recrop writes a new timestamped JPEG so caches cannot reuse old bytes."""
        import os
        import tempfile
        from types import SimpleNamespace

        from app import _reprocess_student_id_photo

        person = Image.new('RGB', (280, 360), (255, 255, 255))
        draw = ImageDraw.Draw(person)
        draw.ellipse((70, 8, 210, 148), fill=(180, 70, 40))
        draw.rectangle((10, 138, 270, 350), fill=(16, 20, 80))
        canvas = Image.new('RGB', (800, 800), (255, 255, 255))
        canvas.paste(person, (260, 90))
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_1_old.jpg')
            canvas.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(
                id=1,
                photo=path,
                photo_filename='photo_1_old.jpg',
            )
            student._id_photo_sources = lambda: [path]
            student.user = None
            changed = _reprocess_student_id_photo(student)
            self.assertTrue(changed)
            self.assertNotEqual(student.photo_filename, 'photo_1_old.jpg')
            self.assertTrue(student.photo_filename.startswith('photo_1_'))
            self.assertIn('id_photos', (student.photo or '').replace('\\', '/'))
            saved = Image.open(os.path.join(photo_dir, student.photo_filename))
            self.assertEqual(saved.size, (800, 800))
            self.assertLessEqual(_all_white_edge_columns(saved, from_left=True), 2)
            self.assertLessEqual(_all_white_edge_columns(saved, from_left=False), 2)
            self.assertLess(_id_photo_edge_white_frac(saved, True), 0.82)
            self.assertLess(_id_photo_edge_white_frac(saved, False), 0.82)
            self.assertFalse(_lower_third_side_columns_white(saved))
            self.assertTrue(_is_navy_shirt(saved.getpixel((400, 640))))
            self.assertTrue(_is_brown_head(saved.getpixel((400, 160))))
            self.assertFalse(_is_brown_head(saved.getpixel((400, 640))))
            self.assertFalse(_is_brown_head(saved.getpixel((400, 0))))

    def test_face_only_square_is_detected(self):
        """800×800 forehead / eyes-only JPEGs must not be treated as recrop sources."""
        forehead = Image.new('RGB', (800, 800), (255, 255, 255))
        draw = ImageDraw.Draw(forehead)
        draw.ellipse((220, 20, 580, 300), fill=(180, 70, 40))
        self.assertGreaterEqual(_lower_third_white_frac(forehead), 0.85)
        self.assertTrue(_id_photo_is_face_only_square(forehead))

        filled = Image.new('RGB', (800, 800), (255, 255, 255))
        draw = ImageDraw.Draw(filled)
        draw.ellipse((80, 10, 720, 790), fill=(180, 70, 40))
        self.assertTrue(_id_photo_is_face_only_square(filled))

        bottom_fill = Image.new('RGB', (800, 800), (255, 255, 255))
        draw = ImageDraw.Draw(bottom_fill)
        draw.rectangle((0, 50, 799, 799), fill=(180, 70, 40))
        self.assertEqual(bottom_fill.getpixel((2, 2)), (255, 255, 255))
        self.assertNotEqual(bottom_fill.getpixel((2, 797))[:3], (255, 255, 255))
        self.assertTrue(_id_photo_is_face_only_square(bottom_fill))

        good = _standing_student(400, 700, left=110, top=40)
        good_sq = _fit_subject_on_white_square(good, 800)
        self.assertFalse(_id_photo_is_face_only_square(good_sq))

    def test_reprocess_uses_camera_original_not_forehead_jpeg(self):
        """Destroyed 800×800 must be skipped when a students/ original exists."""
        import os
        import tempfile
        from types import SimpleNamespace

        from app import _reprocess_student_id_photo

        forehead = Image.new('RGB', (800, 800), (255, 255, 255))
        draw = ImageDraw.Draw(forehead)
        draw.ellipse((180, 10, 620, 420), fill=(180, 70, 40))
        original = _standing_student(400, 1200, left=110, top=40)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            students_dir = os.path.join(tmp, 'uploads', 'students')
            os.makedirs(photo_dir)
            os.makedirs(students_dir)
            bad = os.path.join(photo_dir, 'photo_1_forehead.jpg')
            cam = os.path.join(students_dir, 'camera.jpg')
            forehead.save(bad, format='JPEG', quality=92)
            original.save(cam, format='JPEG', quality=92)
            student = SimpleNamespace(
                id=1,
                photo=bad,
                photo_filename='photo_1_forehead.jpg',
            )
            student._id_photo_sources = lambda: [bad]
            student.user = SimpleNamespace(photo=cam)
            changed = _reprocess_student_id_photo(student)
            self.assertTrue(changed)
            self.assertNotEqual(student.photo_filename, 'photo_1_forehead.jpg')
            saved = Image.open(os.path.join(photo_dir, student.photo_filename))
            self.assertEqual(saved.size, (800, 800))
            self.assertTrue(_is_navy_shirt(saved.getpixel((400, 640))))
            self.assertTrue(_is_brown_head(saved.getpixel((400, 160))))
            self.assertFalse(_is_brown_head(saved.getpixel((400, 640))))
            originals = [name for name in os.listdir(photo_dir) if name.startswith('original_1_')]
            self.assertTrue(originals, 'camera original should be copied to original_*')

    def test_head_blob_at_silhouette_top_gets_headroom(self):
        """Tall person with a head blob at the top of the silhouette: crown is not clipped."""
        canvas = Image.new('RGB', (400, 1400), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        # Head blob flush with the top of the person — no source pixels above the crown.
        draw.ellipse((160, 0, 240, 90), fill=(180, 70, 40))
        draw.rectangle((185, 88, 215, 120), fill=(180, 70, 40))
        draw.rectangle((110, 115, 290, 400), fill=(16, 20, 80))
        result = _fit_subject_on_white_square(canvas, 800)
        self.assertEqual(result.size, (800, 800))
        # Head must not touch y=0 of the square.
        self.assertFalse(_is_brown_head(result.getpixel((400, 0))))
        self.assertNotEqual(result.getpixel((400, 0))[:3], (180, 70, 40))
        # Top 5% may be white/headroom.
        for y in range(0, 40):
            pixel = result.getpixel((400, y))
            self.assertGreaterEqual(
                sum(pixel) / 3.0,
                240,
                'top 5%% row y=%s should be headroom white, got %s' % (y, pixel),
            )
        head_ys = [y for y in range(800) if _is_brown_head(result.getpixel((400, y)))]
        self.assertTrue(head_ys, 'head blob missing from the square')
        self.assertGreater(min(head_ys), 0)
        self.assertLess(max(head_ys), 799)
        self.assertTrue(_is_brown_head(result.getpixel((400, 160))))
        self.assertTrue(_is_navy_shirt(result.getpixel((400, 640))))
        self.assertTrue(_is_navy_shirt(result.getpixel((20, 700))))
        self.assertTrue(_is_navy_shirt(result.getpixel((780, 700))))
        self.assertLess(_id_photo_edge_white_frac(result, True), 0.82)
        self.assertLess(_id_photo_edge_white_frac(result, False), 0.82)

    def test_outdoor_800_is_not_already_usable_hs(self):
        outdoor = _outdoor_student(800, 800)
        self.assertTrue(_id_photo_needs_background_removal(outdoor))
        self.assertFalse(_top_corners_near_white(outdoor))
        self.assertFalse(_corners_near_white(outdoor))
        self.assertFalse(_id_photo_already_usable_hs(outdoor))

    def test_outdoor_upload_calls_rembg_and_saves_white_studio(self):
        outdoor = _outdoor_student()
        self.assertFalse(_corners_near_white(outdoor))
        raw = io.BytesIO()
        outdoor.save(raw, format='JPEG', quality=92)
        with mock.patch('app._skip_rembg_requested', return_value=False), mock.patch(
            'app._rembg_cutout_rgba', side_effect=_fake_rembg_cutout
        ) as cutout:
            out, ext = _process_id_card_image_bytes(raw.getvalue(), 'photo', '.jpg')
        self.assertTrue(cutout.called)
        self.assertEqual(ext, '.jpg')
        saved = Image.open(io.BytesIO(out)).convert('RGB')
        self.assertEqual(saved.size, (ID_PHOTO_OUTPUT_PX, ID_PHOTO_OUTPUT_PX))
        self.assertTrue(_top_corners_near_white(saved))
        self.assertNotEqual(saved.getpixel((2, 2))[:3], (40, 120, 210))

    def test_outdoor_upload_fails_when_rembg_missing(self):
        outdoor = _outdoor_student()
        raw = io.BytesIO()
        outdoor.save(raw, format='JPEG', quality=92)
        with mock.patch('app._skip_rembg_requested', return_value=False), mock.patch(
            'app._rembg_cutout_rgba', return_value=None
        ):
            with self.assertRaises(ValueError) as ctx:
                _process_id_card_image_bytes(raw.getvalue(), 'photo', '.jpg')
        self.assertIn('Background could not be removed', str(ctx.exception))
        self.assertEqual(str(ctx.exception), ID_PHOTO_REMBG_FAIL_MESSAGE)

    def test_skip_rembg_allows_outdoor_passthrough_with_warning_path(self):
        outdoor = _outdoor_student()
        raw = io.BytesIO()
        outdoor.save(raw, format='JPEG', quality=92)
        with mock.patch('app._skip_rembg_requested', return_value=True), mock.patch(
            'app._rembg_cutout_rgba'
        ) as cutout:
            out, ext = _process_id_card_image_bytes(raw.getvalue(), 'photo', '.jpg')
        self.assertFalse(cutout.called)
        self.assertEqual(ext, '.jpg')
        saved = Image.open(io.BytesIO(out)).convert('RGB')
        self.assertEqual(saved.size, (ID_PHOTO_OUTPUT_PX, ID_PHOTO_OUTPUT_PX))

    def test_reprocess_outdoor_800_calls_rembg_not_skipped(self):
        """Print recrop of an 800×800 outdoor JPEG must run rembg — size alone is not a skip."""
        import tempfile
        from types import SimpleNamespace

        from app import _reprocess_student_id_photo

        outdoor = _outdoor_student(800, 800)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_9_outdoor.jpg')
            outdoor.save(path, format='JPEG', quality=92)
            original = os.path.join(photo_dir, 'original_9_cam.jpeg')
            _outdoor_student(960, 1280).save(original, format='JPEG', quality=92)
            student = SimpleNamespace(
                id=9,
                photo=path,
                photo_filename='photo_9_outdoor.jpg',
            )
            student._id_photo_sources = lambda: [path]
            student.user = None
            with mock.patch('app._skip_rembg_requested', return_value=False), mock.patch(
                'app._rembg_cutout_rgba', side_effect=_fake_rembg_cutout
            ) as cutout:
                changed = _reprocess_student_id_photo(student)
            self.assertTrue(cutout.called)
            self.assertTrue(changed)
            saved = Image.open(os.path.join(photo_dir, student.photo_filename)).convert('RGB')
            self.assertTrue(_top_corners_near_white(saved))
            self.assertNotEqual(student.photo_filename, 'photo_9_outdoor.jpg')

    def test_reprocess_outdoor_does_not_overwrite_when_rembg_missing(self):
        import tempfile
        from types import SimpleNamespace

        from app import _reprocess_student_id_photo

        outdoor = _outdoor_student(800, 800)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_9_outdoor.jpg')
            outdoor.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(
                id=9,
                photo=path,
                photo_filename='photo_9_outdoor.jpg',
            )
            student._id_photo_sources = lambda: [path]
            student.user = None
            with mock.patch('app._skip_rembg_requested', return_value=False), mock.patch(
                'app._rembg_cutout_rgba', return_value=None
            ):
                changed = _reprocess_student_id_photo(student)
            self.assertFalse(changed)
            self.assertEqual(student.photo_filename, 'photo_9_outdoor.jpg')

    def test_print_prep_uses_existing_jpeg_without_rembg(self):
        """Print/PDF must reuse a finished id_photos JPEG and never load rembg."""
        import tempfile
        from types import SimpleNamespace

        from app import _prepare_id_photo_for_print

        good = _fit_subject_on_white_square(_standing_student(400, 700, left=110, top=40), 800)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_4_ready.jpg')
            good.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(id=4, photo=path, photo_filename='photo_4_ready.jpg')
            student._id_photo_sources = lambda: [path]
            student.user = None
            with mock.patch('app._rembg_cutout_rgba') as cutout, mock.patch(
                'app._get_rembg_session'
            ) as session:
                changed = _prepare_id_photo_for_print(student)
            self.assertFalse(cutout.called)
            self.assertFalse(session.called)
            self.assertFalse(changed)
            self.assertEqual(student.photo_filename, 'photo_4_ready.jpg')

    def test_print_prep_letterbox_is_pil_only(self):
        import tempfile
        from types import SimpleNamespace

        from app import _prepare_id_photo_for_print

        person = Image.new('RGB', (280, 360), (255, 255, 255))
        draw = ImageDraw.Draw(person)
        draw.ellipse((70, 8, 210, 148), fill=(180, 70, 40))
        draw.rectangle((10, 138, 270, 350), fill=(16, 20, 80))
        canvas = Image.new('RGB', (800, 800), (255, 255, 255))
        canvas.paste(person, (260, 90))
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_1_old.jpg')
            canvas.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(id=1, photo=path, photo_filename='photo_1_old.jpg')
            student._id_photo_sources = lambda: [path]
            student.user = None
            with mock.patch('app._rembg_cutout_rgba') as cutout, mock.patch(
                'app._get_rembg_session'
            ) as session:
                changed = _prepare_id_photo_for_print(student)
            self.assertFalse(cutout.called)
            self.assertFalse(session.called)
            self.assertTrue(changed)
            self.assertNotEqual(student.photo_filename, 'photo_1_old.jpg')

    def test_print_prep_outdoor_skips_rembg_when_session_cold(self):
        import tempfile
        from types import SimpleNamespace

        from app import _prepare_id_photo_for_print

        outdoor = _outdoor_student(800, 800)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_9_outdoor.jpg')
            outdoor.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(id=9, photo=path, photo_filename='photo_9_outdoor.jpg')
            student._id_photo_sources = lambda: [path]
            student.user = None
            with mock.patch('app._rembg_session_already_ready', return_value=False), mock.patch(
                'app._rembg_cutout_rgba'
            ) as cutout, mock.patch('app._get_rembg_session') as session:
                changed = _prepare_id_photo_for_print(student)
            self.assertFalse(changed)
            self.assertFalse(cutout.called)
            self.assertFalse(session.called)
            self.assertEqual(student.photo_filename, 'photo_9_outdoor.jpg')

    def test_print_prep_outdoor_short_rembg_when_warm(self):
        import tempfile
        from types import SimpleNamespace

        from app import _PRINT_REMBG_TIMEOUT_SECONDS, _prepare_id_photo_for_print

        outdoor = _outdoor_student(800, 800)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_9_outdoor.jpg')
            outdoor.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(id=9, photo=path, photo_filename='photo_9_outdoor.jpg')
            student._id_photo_sources = lambda: [path]
            student.user = None
            with mock.patch('app._rembg_session_already_ready', return_value=True), mock.patch(
                'app._rembg_cutout_rgba', side_effect=_fake_rembg_cutout
            ) as cutout:
                changed = _prepare_id_photo_for_print(student)
            self.assertTrue(cutout.called)
            self.assertEqual(cutout.call_args.kwargs.get('timeout'), _PRINT_REMBG_TIMEOUT_SECONDS)
            self.assertFalse(cutout.call_args.kwargs.get('load_session'))
            self.assertTrue(changed)
            self.assertNotEqual(student.photo_filename, 'photo_9_outdoor.jpg')

    def test_print_prep_rembg_timeout_stops_class_budget(self):
        import tempfile
        from types import SimpleNamespace

        from app import _prepare_id_photo_for_print

        outdoor = _outdoor_student(800, 800)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_9_outdoor.jpg')
            outdoor.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(id=9, photo=path, photo_filename='photo_9_outdoor.jpg')
            student._id_photo_sources = lambda: [path]
            student.user = None
            budget = {'allow': True}
            with mock.patch('app._rembg_session_already_ready', return_value=True), mock.patch(
                'app._rembg_cutout_rgba', return_value=None
            ):
                changed = _prepare_id_photo_for_print(student, rembg_budget=budget)
            self.assertFalse(changed)
            self.assertFalse(budget['allow'])
            self.assertEqual(student.photo_filename, 'photo_9_outdoor.jpg')

    def test_print_prep_outdoor_uses_camera_original_when_warm(self):
        """Print rembg must run on original_* (PIL cannot fix outdoor 800×800 JPEGs)."""
        import tempfile
        from types import SimpleNamespace

        from app import _PRINT_REMBG_TIMEOUT_SECONDS, _prepare_id_photo_for_print

        outdoor_square = _outdoor_student(800, 800)
        camera = _outdoor_student(960, 1280)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_9_outdoor.jpg')
            outdoor_square.save(path, format='JPEG', quality=92)
            original = os.path.join(photo_dir, 'original_9_cam.jpeg')
            camera.save(original, format='JPEG', quality=92)
            student = SimpleNamespace(id=9, photo=path, photo_filename='photo_9_outdoor.jpg')
            student._id_photo_sources = lambda: [path]
            student.user = None
            with mock.patch('app._rembg_session_already_ready', return_value=True), mock.patch(
                'app._rembg_cutout_rgba', side_effect=_fake_rembg_cutout
            ) as cutout:
                changed = _prepare_id_photo_for_print(student)
            self.assertTrue(cutout.called)
            rembg_img = cutout.call_args.args[0]
            self.assertEqual(rembg_img.size, (960, 1280))
            self.assertEqual(cutout.call_args.kwargs.get('timeout'), _PRINT_REMBG_TIMEOUT_SECONDS)
            self.assertFalse(cutout.call_args.kwargs.get('load_session'))
            self.assertTrue(changed)
            self.assertNotEqual(student.photo_filename, 'photo_9_outdoor.jpg')

    def test_print_prep_budget_allows_two_outdoor_photos(self):
        import tempfile
        from types import SimpleNamespace

        from app import _prepare_id_photo_for_print

        outdoor = _outdoor_student(800, 800)
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = os.path.join(tmp, 'uploads', 'id_photos')
            os.makedirs(photo_dir)
            path = os.path.join(photo_dir, 'photo_9_outdoor.jpg')
            outdoor.save(path, format='JPEG', quality=92)
            student = SimpleNamespace(id=9, photo=path, photo_filename='photo_9_outdoor.jpg')
            student._id_photo_sources = lambda: [path]
            student.user = None
            budget = {'allow': True, 'remaining': 2}
            with mock.patch('app._rembg_session_already_ready', return_value=True), mock.patch(
                'app._rembg_cutout_rgba', side_effect=_fake_rembg_cutout
            ):
                changed = _prepare_id_photo_for_print(student, rembg_budget=budget)
            self.assertTrue(changed)
            self.assertEqual(budget['remaining'], 1)
            self.assertTrue(budget['allow'])

    def test_preload_starts_load_without_waiting(self):
        from app import _start_rembg_session_preload

        with mock.patch('app._skip_rembg_requested', return_value=False), mock.patch(
            'app._start_rembg_session_load'
        ) as start:
            _start_rembg_session_preload()
        start.assert_called_once()

    def test_preload_skipped_when_skip_rembg(self):
        from app import _start_rembg_session_preload

        with mock.patch('app._skip_rembg_requested', return_value=True), mock.patch(
            'app._start_rembg_session_load'
        ) as start:
            _start_rembg_session_preload()
        start.assert_not_called()

    def test_preferred_rembg_model_is_human_seg(self):
        from app import _preferred_rembg_model_names

        with mock.patch('app._u2net_model_status', return_value='missing'):
            names = _preferred_rembg_model_names()
        self.assertEqual(names[0], 'u2net_human_seg')
        self.assertIn('u2net', names)

    def test_signatures_are_unchanged_jpeg_quality(self):
        sig = Image.new('RGBA', (400, 120), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sig)
        draw.line((20, 60, 380, 50), fill=(10, 10, 10, 255), width=3)
        raw = io.BytesIO()
        sig.save(raw, format='PNG')
        out, ext = _process_id_card_image_bytes(raw.getvalue(), 'signature', '.png')
        self.assertEqual(ext, '.png')
        self.assertGreater(len(out), 50)


if __name__ == '__main__':
    unittest.main()
