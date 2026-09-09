"""Install the Algerian display font used for the school name on official documents.

Algerian ships with Windows/Office and is not redistributable, so it is not
vendored in this repo. Copy ALGER.TTF off a machine that has it, then run:

    python scripts/install_display_font.py path/to/ALGER.TTF

That writes both formats the app needs:

    static/fonts/algerian.ttf     ReportLab embeds this in the grade sheet and
                                  report card PDFs (it cannot read woff2)
    static/fonts/algerian.woff2   browsers download this for the on-screen and
                                  printed HTML documents

See register_display_font() in app.py and templates/partials/display_font.html
for the two places that pick these up. Nothing else needs to change; restart the
app and the school name switches over on every document at once.
"""
import argparse
import os
import shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(REPO_ROOT, 'static', 'fonts')
EXPECTED_FAMILY = 'algerian'


def read_family_name(path):
    """Family name from the font's name table, so a wrong file is caught early."""
    from fontTools.ttLib import TTFont

    with TTFont(path, lazy=True) as font:
        for record in font['name'].names:
            if record.nameID == 1:  # family name
                return record.toUnicode()
    return ''


def main():
    parser = argparse.ArgumentParser(
        description='Install Algerian into static/fonts/ for the PDF and the browser.'
    )
    parser.add_argument('source', help='path to ALGER.TTF')
    parser.add_argument(
        '--force', action='store_true',
        help='install even when the font is not named Algerian',
    )
    args = parser.parse_args()

    if not os.path.isfile(args.source):
        parser.error(f'no such file: {args.source}')

    try:
        family = read_family_name(args.source)
    except Exception as exc:
        parser.error(f'could not read this as a TrueType font: {exc}')

    print(f'Source font family: {family or "(unnamed)"}')
    if EXPECTED_FAMILY not in family.lower() and not args.force:
        parser.error(
            f'expected an Algerian font but got "{family}". '
            'Check you copied ALGER.TTF, or pass --force if this is deliberate.'
        )

    os.makedirs(FONT_DIR, exist_ok=True)
    ttf_out = os.path.join(FONT_DIR, 'algerian.ttf')
    woff2_out = os.path.join(FONT_DIR, 'algerian.woff2')

    shutil.copyfile(args.source, ttf_out)
    print(f'wrote {os.path.relpath(ttf_out, REPO_ROOT)} '
          f'({os.path.getsize(ttf_out):,} bytes) — PDF')

    from fontTools.ttLib import TTFont

    with TTFont(ttf_out) as font:
        font.flavor = 'woff2'
        font.save(woff2_out)
    print(f'wrote {os.path.relpath(woff2_out, REPO_ROOT)} '
          f'({os.path.getsize(woff2_out):,} bytes) — browsers')

    # Prove ReportLab can actually embed it before anyone prints a report card.
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as ReportLabFont

    pdfmetrics.registerFont(ReportLabFont('FLPADisplayCheck', ttf_out))
    print('ReportLab embedded the font successfully.')
    print('\nDone. Restart the app to pick it up.')


if __name__ == '__main__':
    main()
