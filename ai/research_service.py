"""
Background research queue — thread-based async processing for the dashboard.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResearchService:
    """Thread-safe service that queues and processes company research jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: Dict[str, Any] = {
            "state": "idle",          # idle | running | completed | error
            "total": 0,
            "completed": 0,
            "failed": 0,
            "current_company": "",
            "results": {},            # business_name → enriched dict
            "queue": [],              # remaining business names
            "started_at": None,
            "completed_at": None,
            "error": None,
        }
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return a snapshot of the current status (thread-safe copy)."""
        with self._lock:
            s = dict(self._status)
            s["results"] = {}  # don't copy full results in status
            return s

    def get_result(self, business_name: str) -> Optional[Dict]:
        """Return research result for a single company."""
        with self._lock:
            return self._status["results"].get(business_name)

    def get_all_results(self) -> Dict[str, Dict]:
        """Return all completed research results."""
        with self._lock:
            return dict(self._status["results"])

    def start_research(self, leads: List[Dict]) -> Dict:
        """
        Start background research for a list of lead dicts.
        Returns immediately; check get_status() for progress.
        """
        with self._lock:
            if self._status["state"] == "running":
                return {"ok": False, "error": "Research already running"}

            self._status.update(
                {
                    "state": "running",
                    "total": len(leads),
                    "completed": 0,
                    "failed": 0,
                    "current_company": "",
                    "queue": [
                        ld.get("business_name", f"lead_{i}")
                        for i, ld in enumerate(leads)
                    ],
                    "started_at": datetime.utcnow().isoformat(),
                    "completed_at": None,
                    "error": None,
                }
            )

        self._thread = threading.Thread(
            target=self._worker, args=(leads,), daemon=True
        )
        self._thread.start()
        return {"ok": True, "total": len(leads)}

    def stop_research(self) -> None:
        """Signal the worker to stop after the current company."""
        with self._lock:
            if self._status["state"] == "running":
                self._status["state"] = "idle"

    def retry_failed(self, leads: List[Dict]) -> Dict:
        """Re-queue only the failed companies from a previous run."""
        with self._lock:
            failed_names = {
                name
                for name, res in self._status["results"].items()
                if res.get("research_status") == "failed"
            }
        retry_leads = [ld for ld in leads if ld.get("business_name") in failed_names]
        if not retry_leads:
            return {"ok": False, "error": "No failed companies to retry"}
        return self.start_research(retry_leads)

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _worker(self, leads: List[Dict]) -> None:
        try:
            from ai.research_engine import research_engine

            for lead in leads:
                # Check for stop signal
                with self._lock:
                    if self._status["state"] != "running":
                        break
                    name = lead.get("business_name", "unknown")
                    self._status["current_company"] = name

                try:
                    result = research_engine.research_company(lead)
                    with self._lock:
                        self._status["results"][name] = result
                        if result.get("research_status") == "completed":
                            self._status["completed"] += 1
                        else:
                            self._status["failed"] += 1
                        if name in self._status["queue"]:
                            self._status["queue"].remove(name)
                except Exception as exc:
                    logger.error("Worker error for %s: %s", name, exc)
                    with self._lock:
                        self._status["failed"] += 1
                        self._status["results"][name] = {
                            "research_status": "failed",
                            "research_error": str(exc),
                            "manual_review_required": True,
                        }

                time.sleep(0.3)  # small pause between companies

        except Exception as exc:
            logger.error("Research worker fatal: %s", exc)
            with self._lock:
                self._status["state"] = "error"
                self._status["error"] = str(exc)
            return

        with self._lock:
            if self._status["state"] == "running":
                self._status["state"] = "completed"
            self._status["current_company"] = ""
            self._status["completed_at"] = datetime.utcnow().isoformat()


# Module-level singleton
research_service = ResearchService()
