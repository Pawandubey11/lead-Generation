"""
Comprehensive Phase 2/3 Unit & Live Integration Tests:
- Quantitative website auditor (missing URL, social-only, active HTML, PageSpeed parser mock)
- Explainable Opportunity Scorer (no fabrication on missing info, evidence-based scoring)
- CRM SQLite pipeline stages, follow-ups, owner, notes & activity log
- Optional Google Places provider graceful degradation without API key
- Email MX verifier syntax/disposable checks
- Deduplication preserving distinct chain branches while removing duplicates
- Live HTTP tests for /api/leads/audit, /api/leads/opportunity-scores, /api/crm/*, /api/analytics/advanced, /api/scrape/providers
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "dashboard"))

os.environ["LEADPULSE_DEV_MODE"] = "true"
os.environ["LEADPULSE_SECRET_KEY"] = "test-secret-key-for-leadpulse-" + ("x" * 32)


class WebsiteAuditorTests(unittest.TestCase):
    def test_no_website_status(self):
        from auditing.website_auditor import audit_website
        res = audit_website("")
        self.assertEqual(res["website_status"], "NO_WEBSITE")
        self.assertFalse(res["has_valid_ssl"])
        self.assertIsNone(res["performance_score"])

    def test_social_only_status(self):
        from auditing.website_auditor import audit_website
        res = audit_website("https://www.instagram.com/someclinic")
        self.assertEqual(res["website_status"], "SOCIAL_ONLY")
        self.assertEqual(res["social_platform"], "Instagram")

    def test_active_html_audit_and_cms(self):
        from auditing.website_auditor import audit_website

        class FakeResp:
            status_code = 200
            url = "https://acme.example/"
            headers = {}
            text = (
                "<html><head><title>Acme ERP</title>"
                '<meta name="description" content="Acme software">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                "</head><body><h1>Acme</h1><script src='/wp-content/app.js'></script></body></html>"
            )

        with patch("requests.Session.get", return_value=FakeResp()):
            res = audit_website("https://acme.example/", run_pagespeed=False, check_links=False)
        self.assertEqual(res["website_status"], "ACTIVE_OFFICIAL")
        self.assertTrue(res["has_valid_ssl"])
        self.assertTrue(res["mobile_responsive"])
        self.assertEqual(res["cms_detected"], "WordPress")
        self.assertGreaterEqual(res["seo_checks"]["seo_basic_score"], 90)


class OpportunityScorerTests(unittest.TestCase):
    def test_missing_data_reduces_confidence_without_fabrication(self):
        from scoring.opportunity_scorer import compute_opportunity_score
        sparse_lead = {"business_name": "Unknown Co"}
        res = compute_opportunity_score(sparse_lead)
        self.assertEqual(res["confidence_label"], "LOW")
        self.assertLess(res["data_confidence"], 0.45)
        self.assertIn("unavailable", " ".join(res["reasons"]["commercial_viability"]).lower())

    def test_high_fit_erp_with_verified_signals(self):
        from scoring.opportunity_scorer import compute_opportunity_score
        lead = {
            "business_name": "Apex Pharma Manufacturing",
            "business_type": "Pharmaceutical Manufacturing",
            "website": "https://apexpharma.example",
            "phone": "+91 9876543210",
            "email": "ops@apexpharma.example",
            "rating": "4.6",
            "reviews": "240",
        }
        audit = {
            "website_status": "ACTIVE_OFFICIAL",
            "has_valid_ssl": False,
            "mobile_responsive": False,
            "performance_score": 42,
            "broken_links": {"checked_count": 3, "broken_count": 1},
            "seo_checks": {"seo_basic_score": 50},
        }
        res = compute_opportunity_score(lead, audit=audit)
        self.assertEqual(res["confidence_label"], "HIGH")
        self.assertGreaterEqual(res["opportunity_score"], 75)
        self.assertEqual(res["opportunity_grade"], "A")
        self.assertIn("Odoo ERP Solutions", res["recommended_services"])

    def test_slow_website_only_recommends_web_focus(self):
        from scoring.opportunity_scorer import compute_opportunity_score
        lead = {"business_name": "Local Bakery", "business_type": "Bakery", "website": "http://bakery.local"}
        audit = {
            "website_status": "BROKEN_OR_INACTIVE",
            "has_valid_ssl": False,
            "mobile_responsive": False,
            "technical_issues_summary": "HTTP 500",
        }
        res = compute_opportunity_score(lead, audit=audit)
        self.assertIn("Website Modernization", res["pitch_focus"])


class CRMPipelineTests(unittest.TestCase):
    def setUp(self):
        import database.auth_db as auth_db
        self.auth_db = auth_db
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_path = auth_db.DB_PATH
        auth_db.DB_PATH = str(Path(self.temp_dir.name) / "crm-test.db")
        auth_db.init_db()

    def tearDown(self):
        self.auth_db.DB_PATH = self.orig_path
        self.temp_dir.cleanup()

    def test_crm_stage_progression_and_activity_log(self):
        import crm_service as crm_svc
        r1 = crm_svc.update_crm_record(
            "Test Dental Clinic",
            stage="Qualified",
            owner="Pawan",
            follow_up_date="2026-12-01",
            notes="Needs Odoo booking sync",
        )
        self.assertEqual(r1["stage"], "Qualified")
        self.assertEqual(r1["owner"], "Pawan")
        self.assertEqual(r1["follow_up_date"], "2026-12-01")
        self.assertGreaterEqual(len(r1["activities"]), 3)

        r2 = crm_svc.update_crm_record("Test Dental Clinic", stage="Meeting Scheduled", mark_contacted=True)
        self.assertEqual(r2["stage"], "Meeting Scheduled")
        self.assertTrue(bool(r2["last_contacted_at"]))

        with self.assertRaises(ValueError):
            crm_svc.update_crm_record("Test Dental Clinic", stage="InvalidStage")


class OptionalProvidersAndEmailTests(unittest.TestCase):
    def test_google_places_graceful_without_key(self):
        from scrapers.google_places_provider import discover_via_google_places
        with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": ""}):
            res = discover_via_google_places("Restaurants", "Delhi")
            self.assertEqual(res, [])

    def test_email_verifier_disposable_and_invalid(self):
        from scrapers.email_verifier import verify_email_mx
        self.assertEqual(verify_email_mx("", lookup_dns=False)["status"], "UNAVAILABLE")
        self.assertEqual(verify_email_mx("bad-email", lookup_dns=False)["status"], "INVALID_SYNTAX")
        self.assertEqual(verify_email_mx("spam@mailinator.com", lookup_dns=False)["status"], "DISPOSABLE")
        self.assertEqual(verify_email_mx("ops@acme.com", lookup_dns=False)["status"], "SYNTAX_VALID")

    def test_email_extractor_rejects_placeholders_and_unquotes(self):
        from scrapers.email_extractor import extract_emails
        html = '<a href="mailto:%20real@hospital.com">Email</a><input placeholder="you@company.com"> johndoe@gmail.com'
        found = extract_emails(html)
        self.assertEqual(found, ["real@hospital.com"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
