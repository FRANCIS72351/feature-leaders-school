"""Production deployment helpers for Linux / VPS hosting."""
import os

from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix


def is_production():
    return (
        os.environ.get('FLASK_ENV', '').lower() == 'production'
        or os.environ.get('PRODUCTION', '').lower() in ('1', 'true', 'yes')
    )


def is_container():
    """True when running inside Docker / ECS / App Runner / EB container."""
    return os.environ.get('DOCKER', '').lower() in ('1', 'true', 'yes')


def configure_app(app):
    """Apply environment-aware settings for VPS / Linux deployment."""
    prod = is_production()
    app.config['ENV'] = 'production' if prod else 'development'
    app.config['DEBUG'] = not prod and os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')

    secret = os.environ.get('SECRET_KEY', '')
    if prod and (not secret or secret == 'change_this_secret_key'):
        raise RuntimeError(
            'SECRET_KEY must be set to a unique random value in production. '
            'See .env.example'
        )

    if prod:
        app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() != 'false'
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        app.config['WTF_CSRF_SSL_STRICT'] = os.environ.get('WTF_CSRF_SSL_STRICT', 'true').lower() != 'false'

        trusted_hops = int(os.environ.get('PROXY_FIX_HOPS', '1'))
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted_hops,
            x_proto=trusted_hops,
            x_host=trusted_hops,
            x_port=trusted_hops,
        )

    max_mb = int(os.environ.get('MAX_UPLOAD_MB', '16'))
    video_max_mb = int(os.environ.get('SCHOOL_VIDEO_MAX_MB', '150'))
    site_url = (os.environ.get('SITE_URL') or '').strip().rstrip('/')
    if site_url:
        app.config['SITE_URL'] = site_url
    app.config['MAX_CONTENT_LENGTH'] = max(max_mb, video_max_mb) * 1024 * 1024

    default_bind_host = '0.0.0.0' if is_container() else '127.0.0.1'
    bind_host = os.environ.get('BIND_HOST', default_bind_host)
    bind_port = int(os.environ.get('PORT', '8000'))
    app.config['BIND_HOST'] = bind_host
    app.config['BIND_PORT'] = bind_port

    if prod and not (os.environ.get('SITE_URL') or '').strip():
        app.logger.warning(
            'SITE_URL is not set. Parent report-card QR codes and student ID links '
            'may not work on phones until you set SITE_URL to your public HTTPS address.'
        )


def configure_sqlite_performance(app, db):
    """Enable SQLite WAL mode for better concurrent read performance on VPS."""
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')

    @event.listens_for(Engine, 'connect')
    def _sqlite_pragmas(dbapi_connection, connection_record):
        if not uri.startswith('sqlite'):
            return
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.close()
