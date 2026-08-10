"""Gunicorn configuration for Linux / VPS deployment."""
import multiprocessing
import os

_default_bind = (
    '0.0.0.0:8000'
    if os.environ.get('DOCKER', '').lower() in ('1', 'true', 'yes')
    else '127.0.0.1:8000'
)
bind = os.environ.get('GUNICORN_BIND', _default_bind)

# SQLite works best with a single worker; use more workers only with PostgreSQL.
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url.startswith('sqlite') or 'sqlite' in _db_url:
    workers = int(os.environ.get('WEB_CONCURRENCY', '1'))
else:
    workers = int(os.environ.get('WEB_CONCURRENCY', max(2, multiprocessing.cpu_count() * 2 + 1)))

threads = int(os.environ.get('GUNICORN_THREADS', '4'))
worker_class = os.environ.get('GUNICORN_WORKER_CLASS', 'gthread')
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT', '30'))
keepalive = int(os.environ.get('GUNICORN_KEEPALIVE', '5'))
max_requests = int(os.environ.get('GUNICORN_MAX_REQUESTS', '1000'))
max_requests_jitter = int(os.environ.get('GUNICORN_MAX_REQUESTS_JITTER', '50'))

accesslog = os.environ.get('GUNICORN_ACCESS_LOG', '-')
errorlog = os.environ.get('GUNICORN_ERROR_LOG', '-')
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
capture_output = True

preload_app = os.environ.get('GUNICORN_PRELOAD', 'true').lower() in ('1', 'true', 'yes')
proc_name = 'school-management'
