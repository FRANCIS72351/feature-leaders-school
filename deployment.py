"""Production deployment helpers for Linux / VPS hosting."""
import os

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

    # Dev Tunnels / ngrok / Nginx terminate HTTPS and forward HTTP locally.
    # Without ProxyFix, Flask never sees https, so the session/CSRF cookie is dropped.
    trusted_hops = int(os.environ.get('PROXY_FIX_HOPS', '1'))
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=trusted_hops,
        x_proto=trusted_hops,
        x_host=trusted_hops,
        x_port=trusted_hops,
    )

    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')

    if prod:
        app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() != 'false'
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        app.config['WTF_CSRF_SSL_STRICT'] = os.environ.get('WTF_CSRF_SSL_STRICT', 'true').lower() != 'false'
    else:
        app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
        app.config['WTF_CSRF_SSL_STRICT'] = False
        app.config['PREFERRED_URL_SCHEME'] = os.environ.get('PREFERRED_URL_SCHEME', 'https')

    max_mb = int(os.environ.get('MAX_UPLOAD_MB', '16'))
    video_max_mb = int(os.environ.get('SCHOOL_VIDEO_MAX_MB', '150'))
    site_url = (os.environ.get('SITE_URL') or os.environ.get('PUBLIC_SITE_URL') or '').strip().rstrip('/')
    if site_url:
        app.config['SITE_URL'] = site_url
    public_site_url = (os.environ.get('PUBLIC_SITE_URL') or '').strip().rstrip('/')
    if public_site_url:
        app.config['PUBLIC_SITE_URL'] = public_site_url
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

    from scale import apply_http_performance
    apply_http_performance(app)


def configure_sqlite_performance(app, db):
    """WAL, cache, and mmap so multi-year SQLite files stay fast under concurrent reads."""
    from scale import register_sqlite_pragmas
    register_sqlite_pragmas(app)
