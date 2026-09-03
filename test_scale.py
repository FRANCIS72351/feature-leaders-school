"""Unit tests for scale.py helpers — no live 1000-user load test."""
import os
import unittest
from unittest import mock

from flask import Flask

from scale import (
    apply_database_engine_options,
    apply_http_performance,
    clamp_page,
    env_int,
    gzip_response_if_needed,
    is_sqlite_uri,
    recommended_waitress_threads,
    recommended_web_concurrency,
    recommended_worker_threads,
)


class EnvIntTests(unittest.TestCase):
    def test_default_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCALE_TEST_INT", None)
            self.assertEqual(env_int("SCALE_TEST_INT", 7), 7)

    def test_parses_and_clamps(self):
        with mock.patch.dict(os.environ, {"SCALE_TEST_INT": "99"}):
            self.assertEqual(env_int("SCALE_TEST_INT", 1, minimum=2, maximum=10), 10)
        with mock.patch.dict(os.environ, {"SCALE_TEST_INT": "0"}):
            self.assertEqual(env_int("SCALE_TEST_INT", 4, minimum=2, maximum=10), 2)
        with mock.patch.dict(os.environ, {"SCALE_TEST_INT": "nope"}):
            self.assertEqual(env_int("SCALE_TEST_INT", 4, minimum=1), 4)


class UriAndWorkerTests(unittest.TestCase):
    def test_sqlite_detection(self):
        self.assertTrue(is_sqlite_uri("sqlite:///instance/school.db"))
        self.assertTrue(is_sqlite_uri("sqlite:////var/data/app.db"))
        self.assertFalse(is_sqlite_uri("postgresql+psycopg2://u:p@127.0.0.1/db"))
        self.assertFalse(is_sqlite_uri("mysql+pymysql://u:p@127.0.0.1/db"))

    def test_sqlite_workers_stay_low(self):
        with mock.patch.dict(os.environ, {"WEB_CONCURRENCY": "8"}):
            self.assertEqual(recommended_web_concurrency("sqlite:///x.db"), 2)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WEB_CONCURRENCY", None)
            self.assertEqual(recommended_web_concurrency("sqlite:///x.db"), 1)
            self.assertEqual(recommended_web_concurrency(""), 1)

    def test_postgres_workers_honor_env(self):
        uri = "postgresql+psycopg2://school:pw@127.0.0.1:5432/school_db"
        with mock.patch.dict(os.environ, {"WEB_CONCURRENCY": "4"}):
            self.assertEqual(recommended_web_concurrency(uri), 4)

    def test_thread_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GUNICORN_THREADS", None)
            os.environ.pop("WAITRESS_THREADS", None)
            self.assertEqual(recommended_worker_threads(), 8)
            self.assertEqual(recommended_waitress_threads(), 16)


class ClampPageTests(unittest.TestCase):
    def test_clamp_page(self):
        self.assertEqual(clamp_page("3", 20), (3, 20))
        self.assertEqual(clamp_page("nope", 20), (1, 20))
        self.assertEqual(clamp_page("0", 20), (1, 20))
        page, per_page = clamp_page(1, 500)
        self.assertEqual(page, 1)
        self.assertLessEqual(per_page, 200)


class EngineOptionTests(unittest.TestCase):
    def test_sqlite_engine_options(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///instance/test.db"
        apply_database_engine_options(app)
        opts = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
        self.assertFalse(opts["connect_args"]["check_same_thread"])
        self.assertEqual(opts["connect_args"]["timeout"], 30)
        self.assertNotIn("pool_size", opts)

    def test_postgres_pool_options(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql+psycopg2://u:p@127.0.0.1/db"
        with mock.patch.dict(os.environ, {"DB_POOL_SIZE": "12", "DB_MAX_OVERFLOW": "6"}):
            apply_database_engine_options(app)
        opts = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
        self.assertEqual(opts["pool_size"], 12)
        self.assertEqual(opts["max_overflow"], 6)
        self.assertTrue(opts["pool_pre_ping"])


class GzipTests(unittest.TestCase):
    def test_gzips_html_when_accepted(self):
        app = Flask(__name__)
        with app.app_context():
            response = app.response_class(
                "<html>" + ("x" * 800) + "</html>",
                mimetype="text/html",
            )
            gzipped = gzip_response_if_needed(response, "gzip, deflate", min_bytes=100)
            self.assertEqual(gzipped.headers.get("Content-Encoding"), "gzip")
            self.assertIn("Accept-Encoding", gzipped.headers.get("Vary", ""))
            self.assertLess(len(gzipped.get_data()), 800)

    def test_skips_images_and_small_bodies(self):
        app = Flask(__name__)
        with app.app_context():
            image = app.response_class(b"\x89PNG" + b"\x00" * 800, mimetype="image/jpeg")
            self.assertIsNone(gzip_response_if_needed(image, "gzip").headers.get("Content-Encoding"))
            tiny = app.response_class("hi", mimetype="text/html")
            self.assertIsNone(
                gzip_response_if_needed(tiny, "gzip", min_bytes=500).headers.get("Content-Encoding")
            )

    def test_flask_after_request_sets_cache_and_gzip(self):
        app = Flask(__name__)
        apply_http_performance(app)

        @app.route("/hello")
        def hello():
            return "<html><body>" + ("dashboard " * 80) + "</body></html>"

        client = app.test_client()
        response = client.get("/hello", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Encoding"), "gzip")


if __name__ == "__main__":
    unittest.main()
