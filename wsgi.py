"""
WSGI entry point for Gunicorn / production servers on Linux.

  gunicorn -c gunicorn.conf.py wsgi:application

Or with Waitress (Windows-friendly, also works on Linux):

  waitress-serve --host=127.0.0.1 --port=8000 --threads=16 wsgi:application

  python app.py
  # Waitress threads come from WAITRESS_THREADS (default 16). For Linux VPS
  # prefer: gunicorn -c gunicorn.conf.py wsgi:application

PythonAnywhere: see deploy/pythonanywhere/wsgi.py and PYTHONANYWHERE.md
"""
import os

# Ensure SQLite and uploads resolve correctly on hosted platforms (PythonAnywhere, etc.)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app import app as application, _start_rembg_session_preload

_start_rembg_session_preload()

# Gunicorn looks for `application`; some hosts expect `app`.
app = application
