"""Gunicorn configuration for Linux / VPS deployment."""
import os

from scale import recommended_web_concurrency, recommended_worker_threads, env_int

_default_bind = (
    '0.0.0.0:8000'
    if os.environ.get('DOCKER', '').lower() in ('1', 'true', 'yes')
    else '127.0.0.1:8000'
)
bind = os.environ.get('GUNICORN_BIND', _default_bind)

# SQLite works best with a single worker; use more workers only with PostgreSQL.
workers = recommended_web_concurrency()
threads = recommended_worker_threads()
worker_class = os.environ.get('GUNICORN_WORKER_CLASS', 'gthread')
timeout = env_int('GUNICORN_TIMEOUT', 120, minimum=30, maximum=600)
graceful_timeout = env_int('GUNICORN_GRACEFUL_TIMEOUT', 30, minimum=5, maximum=120)
keepalive = env_int('GUNICORN_KEEPALIVE', 15, minimum=2, maximum=75)
max_requests = env_int('GUNICORN_MAX_REQUESTS', 1000, minimum=0, maximum=100000)
max_requests_jitter = env_int('GUNICORN_MAX_REQUESTS_JITTER', 50, minimum=0, maximum=500)
backlog = env_int('GUNICORN_BACKLOG', 256, minimum=64, maximum=2048)

accesslog = os.environ.get('GUNICORN_ACCESS_LOG', '-')
errorlog = os.environ.get('GUNICORN_ERROR_LOG', '-')
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
capture_output = True

preload_app = os.environ.get('GUNICORN_PRELOAD', 'true').lower() in ('1', 'true', 'yes')
proc_name = 'school-management'
