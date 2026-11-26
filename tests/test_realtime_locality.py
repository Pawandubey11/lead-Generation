"""
Regression & Integration Tests for Real-Time Locality-Wise Extracted Data Visibility.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import unittest
import requests
from dashboard.app import scraper_service as ss, scrape_coverage, scrape_coverage_locality


class RealtimeLocalityVisibilityTests(unittest.TestCase):
    def setUp(self):
        ss._reset_status()

    def tearDown(self):
        ss._reset_status()

    def test_realtime_locality_extraction_and_deduplication(self):
        with ss._lock:
            ss._status.update({
                "state": "running",
                "is_locality_mode": True,
                "country": "Greater Noida",
                "business_type": "Dentist",
                "localities": ["Alpha 1", "Pari Chowk"],
                "current_locality": "Alpha 1",
                "locality_index": 1,
                "total_localities": 2,
            })

        ss._progress_callback("locality_start", {"locality": "Alpha 1", "locality_index": 1, "total_localities": 2})
        ss._progress_callback("business_item", {
            "city": "Alpha 1, Greater Noida",
            "business_index": 1,
            "total_businesses": 5,
            "lead": {
                "business_name": "Alpha Dental Hub",
                "business_type": "Dentist",
                "phone": "+91 99999 11111",
                "rating": "4.8",
                "source_url": "https://maps.google.com/?cid=1",
            },
        })
        # Duplicate business_item in same locality should be deduplicated
        ss._progress_callback("business_item", {
            "city": "Alpha 1, Greater Noida",
            "business_index": 2,
            "total_businesses": 5,
            "lead": {
                "business_name": "Alpha Dental Hub",
                "business_type": "Dentist",
                "phone": "+91 99999 11111",
                "rating": "4.8",
                "source_url": "https://maps.google.com/?cid=1",
            },
        })

        # Second locality starts
        ss._progress_callback("locality_start", {"locality": "Pari Chowk", "locality_index": 2, "total_localities": 2})
        ss._progress_callback("business_item", {
            "city": "Pari Chowk, Greater Noida",
            "business_index": 1,
            "total_businesses": 5,
            "lead": {
                "business_name": "Pari Chowk Smile Care",
                "business_type": "Dentist",
                "address": "Pari Chowk, Greater Noida",
                "website": "https://parismile.in",
                "source_url": "https://maps.google.com/?cid=2",
            },
        })

        cov = scrape_coverage()
        self.assertEqual(cov["lead_counts"]["Alpha 1"], 1)
        self.assertEqual(cov["lead_counts"]["Pari Chowk"], 1)
        self.assertEqual(cov["locality_leads"]["Alpha 1"][0]["business_name"], "Alpha Dental Hub")
        self.assertEqual(cov["locality_leads"]["Pari Chowk"][0]["business_name"], "Pari Chowk Smile Care")

        # Targeted locality endpoint
        loc_data = scrape_coverage_locality("Pari Chowk")
        self.assertEqual(loc_data["count"], 1)
        self.assertEqual(loc_data["leads"][0]["website"], "https://parismile.in")

    def test_ui_and_js_controls_present_on_live_server(self):
        html = requests.get("http://127.0.0.1:8000/", timeout=5).text
        for elem in [
            "coverage-live-records-wrap",
            "coverage-selected-locality-name",
            "coverage-live-records-body",
            "btn-follow-active-locality",
        ]:
            self.assertIn(elem, html)

        js = requests.get("http://127.0.0.1:8000/static/js/dashboard.js", timeout=5).text
        for fn in ["selectCoverageLocality", "followActiveLocality", "renderCoverageLiveRecords"]:
            self.assertIn(fn, js)

    def test_live_coverage_endpoints_http_200(self):
        r1 = requests.get("http://127.0.0.1:8000/api/scrape/coverage", timeout=5)
        self.assertEqual(r1.status_code, 200)
        data = r1.json()
        self.assertIn("locality_leads", data)
        self.assertIn("live_leads", data)

        r2 = requests.get("http://127.0.0.1:8000/api/scrape/coverage/locality/Alpha%201", timeout=5)
        self.assertEqual(r2.status_code, 200)
        self.assertIn("leads", r2.json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
