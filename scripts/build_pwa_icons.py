"""Render the FLPA install icons from static/images/LOGO.png.

Run after the school logo changes:  python scripts/build_pwa_icons.py
"""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'static', 'images', 'LOGO.png')
OUT_DIR = os.path.join(ROOT, 'static', 'icons')
CARD_WHITE = (255, 255, 255, 255)

# name -> (size, crest fraction of the canvas)
# Maskable icons are cropped to a circle by Android, so the crest stays inside 60%.
TARGETS = {
    'icon-192.png': (192, 0.86),
    'icon-512.png': (512, 0.86),
    'icon-maskable-192.png': (192, 0.60),
    'icon-maskable-512.png': (512, 0.60),
    'apple-touch-icon.png': (180, 0.82),
}


def render(source, size, crest_fraction):
    canvas = Image.new('RGBA', (size, size), CARD_WHITE)
    crest = source.copy()
    box = max(1, int(size * crest_fraction))
    crest.thumbnail((box, box), Image.LANCZOS)
    canvas.paste(
        crest,
        ((size - crest.width) // 2, (size - crest.height) // 2),
        crest if crest.mode == 'RGBA' else None,
    )
    return canvas


def main():
    source = Image.open(SOURCE).convert('RGBA')
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, (size, fraction) in TARGETS.items():
        icon = render(source, size, fraction)
        if name == 'apple-touch-icon.png':
            icon = icon.convert('RGB')  # iOS ignores alpha and prints black corners
        icon.save(os.path.join(OUT_DIR, name), format='PNG', optimize=True)
        print('wrote', os.path.join('static', 'icons', name), size)


if __name__ == '__main__':
    main()
