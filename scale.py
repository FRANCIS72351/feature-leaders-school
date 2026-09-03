"""High-volume SIS scaling: engine pooling, SQLite pragmas, and year-scoped indexes.

Historical data stays in the same database, isolated by academic_year_id.
Dashboards must query one year at a time — never scan all years.

SQLite + one Waitress/Gunicorn process can serve many concurrent *readers*
(dozens to low hundreds on a decent VPS). It cannot magically take 1000
concurrent writers. Use PostgreSQL + more Gunicorn workers for that.
"""
from __future__ import annotations

import gzip
import multiprocessing
import os

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

DASHBOARD_PAGE_SIZE = int(os.environ.get("DASHBOARD_PAGE_SIZE", "50"))
GZIP_MIME_TYPES = frozenset({
    "text/html",
    "text/css",
    "text/plain",
    "text/xml",
    "text/javascript",
    "application/json",
    "application/javascript",
    "application/xml",
    "image/svg+xml",
})

SCALE_INDEXES = (
    ("ix_students_year_class", "students", "academic_year_id, klass_id"),
    ("ix_students_year_status", "students", "academic_year_id, status"),
    ("ix_students_klass", "students", "klass_id"),
    ("ix_grades_year_student", "grades", "academic_year_id, student_id"),
    ("ix_grades_year_class", "grades", "academic_year_id, class_id"),
    ("ix_grades_student", "grades", "student_id"),
    ("ix_attendance_year_date", "attendance", "academic_year_id, date"),
    ("ix_attendance_student_date", "attendance", "student_id, date"),
    ("ix_attendance_class_date", "attendance", "class_id, date"),
    ("ix_enrollments_year_student", "enrollments", "academic_year_id, student_id"),
    ("ix_enrollments_year_class", "enrollments", "academic_year_id, class_id"),
    ("ix_payments_year_student", "student_payments", "academic_year_id, student_id"),
    ("ix_payments_student", "student_payments", "student_id"),
    ("ix_biz_year_type_deleted", "business_transactions", "academic_year, type, is_deleted"),
    ("ix_assessments_year_class", "assessments", "academic_year_id, klass_id"),
    ("ix_submissions_activity_student", "submissions", "activity_id, student_id"),
    ("ix_submissions_student", "submissions", "student_id"),
    ("ix_grades_year_teacher", "grades", "academic_year_id, teacher_id"),
    ("ix_users_role", "users", "role"),
    ("ix_users_status", "users", "status"),
    ("ix_registry_docs_year_student", "student_registry_documents", "academic_year_id, student_id"),
    ("ix_students_id_ready_year", "students", "academic_year_id, id_card_ready"),
)


def env_int(name, default, minimum=None, maximum=None):
    """Parse a positive-ish integer from the environment with safe bounds."""
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw not in (None, "") else int(default)
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def is_sqlite_uri(uri):
    text_uri = (uri or "").strip().lower()
    return text_uri.startswith("sqlite") or "sqlite" in text_uri


def recommended_web_concurrency(database_uri=None):
    """Gunicorn workers. SQLite stays at 1 (optionally 2); Postgres uses CPUs."""
    uri = database_uri if database_uri is not None else os.environ.get("DATABASE_URL", "")
    if is_sqlite_uri(uri) or not (uri or "").strip():
        return env_int("WEB_CONCURRENCY", 1, minimum=1, maximum=2)
    default = max(2, multiprocessing.cpu_count() * 2 + 1)
    return env_int("WEB_CONCURRENCY", default, minimum=1, maximum=32)


def recommended_worker_threads():
    """Threads per Gunicorn worker — I/O-bound Flask routes share the GIL."""
    return env_int("GUNICORN_THREADS", 8, minimum=1, maximum=64)


def recommended_waitress_threads():
    """Windows / `python app.py` thread pool (Waitress)."""
    return env_int("WAITRESS_THREADS", 16, minimum=2, maximum=64)


def apply_database_engine_options(app):
    """Connection pooling for Postgres/MySQL; safe SQLite defaults for many readers."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if is_sqlite_uri(uri):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "connect_args": {"check_same_thread": False, "timeout": 30},
            "pool_pre_ping": True,
        }
        return
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": env_int("DB_POOL_SIZE", 10, minimum=2, maximum=80),
        "max_overflow": env_int("DB_MAX_OVERFLOW", 20, minimum=0, maximum=80),
        "pool_pre_ping": True,
        "pool_recycle": env_int("DB_POOL_RECYCLE", 1800, minimum=60, maximum=7200),
    }


def register_sqlite_pragmas(app):
    """WAL + larger cache so multi-year SQLite files stay readable under load."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")

    @event.listens_for(Engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):
        if not is_sqlite_uri(uri):
            return
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=8000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA mmap_size=268435456")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.close()


def ensure_scale_indexes(db):
    """CREATE INDEX IF NOT EXISTS — safe on existing SQLite and Postgres databases."""
    bind = db.engine
    with bind.begin() as conn:
        for name, table, cols in SCALE_INDEXES:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
            except Exception:
                continue


def _append_vary(existing, token):
    parts = [part.strip() for part in (existing or "").split(",") if part.strip()]
    if token not in parts:
        parts.append(token)
    return ", ".join(parts)


def gzip_response_if_needed(response, accept_encoding, min_bytes=500):
    """Gzip HTML/JSON/CSS/JS when the client accepts it. Safe no-op otherwise."""
    if response is None or getattr(response, "direct_passthrough", False):
        return response
    status = getattr(response, "status_code", 200)
    if status < 200 or status >= 300:
        return response
    headers = response.headers
    if headers.get("Content-Encoding"):
        return response
    if "gzip" not in (accept_encoding or "").lower():
        return response
    mime = (response.content_type or "").split(";")[0].strip().lower()
    if mime not in GZIP_MIME_TYPES:
        return response
    try:
        data = response.get_data()
    except Exception:
        return response
    if not data or len(data) < max(1, int(min_bytes)):
        return response
    compressed = gzip.compress(data, compresslevel=6)
    if len(compressed) >= len(data):
        return response
    response.set_data(compressed)
    headers["Content-Encoding"] = "gzip"
    headers["Vary"] = _append_vary(headers.get("Vary"), "Accept-Encoding")
    headers["Content-Length"] = str(len(compressed))
    return response


def apply_http_performance(app):
    """Gzip text responses and cache hashed/static files for slow networks."""
    max_age = env_int("STATIC_CACHE_SECONDS", 2592000, minimum=0, maximum=31536000)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = max_age
    min_bytes = env_int("GZIP_MIN_BYTES", 500, minimum=0, maximum=1048576)

    @app.after_request
    def _compress_and_cache(response):
        try:
            from flask import request
        except Exception:
            return response
        path = (request.path or "")
        if path.startswith("/static/"):
            if path.startswith("/static/uploads/"):
                # Timestamped upload names; cache but allow revalidation.
                response.headers.setdefault(
                    "Cache-Control",
                    "public, max-age=86400, stale-while-revalidate=604800",
                )
            elif max_age:
                response.headers.setdefault(
                    "Cache-Control",
                    f"public, max-age={max_age}",
                )
        try:
            accept = request.headers.get("Accept-Encoding", "")
        except Exception:
            accept = ""
        return gzip_response_if_needed(response, accept, min_bytes=min_bytes)

    return app


def clamp_page(page, per_page=DASHBOARD_PAGE_SIZE):
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1
    per_page = max(1, min(int(per_page or DASHBOARD_PAGE_SIZE), 200))
    return page, per_page


def seal_academic_year_folders(db):
    """Put untagged rows into a year folder so old years never mix with the live year.

    NULL academic_year_id is copied from the student when possible, then from the
    active year. Historical rows that already have a year id are never moved.
    """
    bind = db.engine
    sealed = 0
    with bind.begin() as conn:
        active = conn.execute(text(
            "SELECT id, name FROM academic_years WHERE is_active = 1 "
            "ORDER BY start_date DESC LIMIT 1"
        )).fetchone()
        if not active:
            active = conn.execute(text(
                "SELECT id, name FROM academic_years ORDER BY start_date DESC LIMIT 1"
            )).fetchone()
        if not active:
            return 0
        year_id, year_name = active[0], active[1]
        statements = (
            "UPDATE students SET academic_year_id = :y WHERE academic_year_id IS NULL",
            """UPDATE grades SET academic_year_id = (
                 SELECT academic_year_id FROM students WHERE students.id = grades.student_id
               ) WHERE academic_year_id IS NULL
                 AND EXISTS (
                   SELECT 1 FROM students
                   WHERE students.id = grades.student_id AND students.academic_year_id IS NOT NULL
                 )""",
            "UPDATE grades SET academic_year_id = :y WHERE academic_year_id IS NULL",
            """UPDATE attendance SET academic_year_id = (
                 SELECT academic_year_id FROM students WHERE students.id = attendance.student_id
               ) WHERE academic_year_id IS NULL
                 AND EXISTS (
                   SELECT 1 FROM students
                   WHERE students.id = attendance.student_id AND students.academic_year_id IS NOT NULL
                 )""",
            "UPDATE attendance SET academic_year_id = :y WHERE academic_year_id IS NULL",
            """UPDATE enrollments SET academic_year_id = (
                 SELECT academic_year_id FROM students WHERE students.id = enrollments.student_id
               ) WHERE academic_year_id IS NULL
                 AND EXISTS (
                   SELECT 1 FROM students
                   WHERE students.id = enrollments.student_id AND students.academic_year_id IS NOT NULL
                 )""",
            "UPDATE enrollments SET academic_year_id = :y WHERE academic_year_id IS NULL",
            "UPDATE assessments SET academic_year_id = :y WHERE academic_year_id IS NULL",
            "UPDATE student_registry_documents SET academic_year_id = :y WHERE academic_year_id IS NULL",
            "UPDATE school_media SET academic_year_id = :y WHERE academic_year_id IS NULL",
            "UPDATE business_transactions SET academic_year = :n "
            "WHERE academic_year IS NULL OR TRIM(academic_year) = ''",
        )
        for sql in statements:
            try:
                result = conn.execute(text(sql), {"y": year_id, "n": year_name})
                sealed += int(result.rowcount or 0)
            except Exception:
                continue
    return sealed
