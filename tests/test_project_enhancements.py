import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["LEADPULSE_DEV_MODE"] = "true"
os.environ["LEADPULSE_SECRET_KEY"] = "test-secret-key-for-leadpulse-" + ("x" * 32)


class PasswordStorageTests(unittest.TestCase):
    def setUp(self):
        import database.auth_db as auth_db

        self.auth_db = auth_db
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = auth_db.DB_PATH
        auth_db.DB_PATH = str(Path(self.temp_dir.name) / "auth-test.db")
        auth_db.init_db()

    def tearDown(self):
        self.auth_db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_new_password_uses_unique_salt(self):
        first = "security-test-a@example.invalid"
        second = "security-test-b@example.invalid"
        self.assertNotEqual(self.auth_db.create_user(first, "PasswordOne!"), -1)
        self.assertNotEqual(self.auth_db.create_user(second, "PasswordOne!"), -1)

        conn = self.auth_db.get_db_connection()
        rows = conn.execute(
            "SELECT password_salt FROM users WHERE email IN (?, ?) ORDER BY email",
            (first, second),
        ).fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(rows[0]["password_salt"])
        self.assertIsNotNone(rows[1]["password_salt"])
        self.assertNotEqual(rows[0]["password_salt"], rows[1]["password_salt"])

    def test_bad_password_is_rejected(self):
        email = "security-test-c@example.invalid"
        self.assertNotEqual(self.auth_db.create_user(email, "CorrectPassword!"), -1)
        self.assertIsNone(self.auth_db.verify_user(email, "WrongPassword!"))
        self.assertIsNotNone(self.auth_db.verify_user(email, "CorrectPassword!"))

    def test_legacy_password_is_migrated_after_login(self):
        email = "security-test-d@example.invalid"
        password = "LegacyPassword!"
        legacy_hash = self.auth_db.hash_password(password)
        conn = self.auth_db.get_db_connection()
        conn.execute(
            "INSERT INTO users (email, password_hash, password_salt, "
            "password_iterations, created_at) VALUES (?, ?, NULL, NULL, '2026-11-20')",
            (email, legacy_hash),
        )
        conn.commit()
        conn.close()

        self.assertIsNotNone(self.auth_db.verify_user(email, password))
        conn = self.auth_db.get_db_connection()
        row = conn.execute(
            "SELECT password_salt, password_iterations FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row["password_salt"])
        self.assertGreaterEqual(row["password_iterations"], 310000)


class SecurityAndScrapeRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from dashboard.app import app

        cls.client = TestClient(app)

    def test_exports_require_authentication(self):
        for path in (
            "/api/export/csv",
            "/api/export/excel",
            "/api/export/custom",
            "/api/export/latest/csv",
            "/api/export/latest/excel",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)

    def test_listing_depth_validation(self):
        from dashboard.app import ScrapeRequest

        request = ScrapeRequest(
            business_type="dentist",
            scope="country",
            country="india",
            max_cities=5,
            max_leads_per_city=50,
        )
        self.assertEqual(request.max_leads_per_city, 50)

        with self.assertRaises(Exception):
            ScrapeRequest(
                business_type="dentist",
                scope="country",
                country="india",
                max_cities=5,
                max_leads_per_city=201,
            )

    def test_city_country_location_label(self):
        from dashboard.scraper_service import build_target_location

        self.assertEqual(
            build_target_location(["Bihar"], "india"),
            "Bihar, india",
        )
        self.assertEqual(
            build_target_location(["London"], "United Kingdom"),
            "London, United Kingdom",
        )
        self.assertEqual(
            build_target_location(["Delhi"], "Delhi"),
            "Delhi",
        )

    def test_safe_website_url_rule(self):
        def is_safe(raw_url):
            from urllib.parse import urlparse
            parsed = urlparse(raw_url)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)

        self.assertTrue(is_safe("https://example.com"))
        self.assertFalse(is_safe("javascript:alert(document.cookie)"))
        self.assertFalse(is_safe("data:text/html,test"))


if __name__ == "__main__":
    unittest.main()
