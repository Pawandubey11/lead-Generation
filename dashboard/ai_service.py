"""
AI Business Intelligence service layer — called from dashboard/app.py endpoints.
"""
from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENRICHED_CSV_PATH: str = os.getenv("ENRICHED_CSV_PATH", "output/ai_enriched_leads.csv")

# AI-added columns (preserve all original lead columns)
AI_ENRICHMENT_FIELDS: List[str] = [
    "research_status", "research_timestamp", "research_sources",
    "research_error", "manual_review_required",
    "company_overview", "industry", "business_model",
    "products_services", "existing_capabilities", "technology_signals",
    "website_status", "website_summary", "website_strengths",
    "website_problems", "website_improvement_opportunities", "website_recommendations",
    "systemaops_business_opportunity", "recommended_services",
    "strongest_opportunity", "opportunity_reason", "expected_benefit",
    "evidence", "opportunity_priority", "recommendation_confidence",
    "potential_business_challenge",
    "meeting_opening", "discovery_questions", "sales_pitch", "suggested_next_action",
    "email_subject", "personalized_email", "linkedin_message", "follow_up_message",
    "post_topic", "post_text", "call_to_action",
]


# ---------------------------------------------------------------------------
# Status & control
# ---------------------------------------------------------------------------

def get_research_status() -> Dict[str, Any]:
    """Return current research queue status."""
    try:
        from ai.research_service import research_service
        return research_service.get_status()
    except Exception as exc:
        return {"state": "error", "error": str(exc)}


def start_research(leads: List[Dict]) -> Dict:
    """Start background research for a list of lead dicts."""
    try:
        from ai.research_service import research_service
        return research_service.start_research(leads)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def stop_research() -> Dict:
    """Stop ongoing research."""
    try:
        from ai.research_service import research_service
        research_service.stop_research()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def retry_failed_research(leads: List[Dict]) -> Dict:
    """Retry companies whose research previously failed."""
    try:
        from ai.research_service import research_service
        return research_service.retry_failed(leads)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Results access
# ---------------------------------------------------------------------------

def get_company_report(business_name: str) -> Optional[Dict]:
    """Get research result for a specific company."""
    try:
        from ai.research_service import research_service
        return research_service.get_result(business_name)
    except Exception as exc:
        return {"research_status": "error", "research_error": str(exc)}


def get_all_reports() -> Dict[str, Dict]:
    """Return all completed research results keyed by business_name."""
    try:
        from ai.research_service import research_service
        return research_service.get_all_results()
    except Exception as exc:
        logger.error("get_all_reports error: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_enriched_csv(leads: List[Dict]) -> bytes:
    """Merge leads with AI research results and return CSV bytes."""
    try:
        results = get_all_reports()
        enriched: List[Dict] = []
        for lead in leads:
            name = lead.get("business_name", "")
            row = dict(lead)
            ai_data = results.get(name, {})
            for field in AI_ENRICHMENT_FIELDS:
                val = ai_data.get(field, "")
                if isinstance(val, list):
                    val = "; ".join(str(v) for v in val)
                row[field] = val
            enriched.append(row)

        output = io.StringIO()
        if enriched:
            fieldnames = list(enriched[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(enriched)
        return output.getvalue().encode("utf-8")
    except Exception as exc:
        logger.error("export_enriched_csv error: %s", exc)
        return b""


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def llm_is_configured() -> bool:
    """Return True if any LLM provider is configured."""
    try:
        from ai.llm_client import llm_client
        return llm_client.is_available()
    except Exception:
        return False


def get_ai_config() -> Dict[str, Any]:
    """Return AI configuration info (no secrets exposed)."""
    provider = os.getenv("AI_PROVIDER", "mock").lower()
    return {
        "provider": provider,
        "model": os.getenv("AI_MODEL", "gpt-4o-mini"),
        "configured": llm_is_configured(),
        "mock_mode": provider == "mock",
        "dify_mode": provider == "dify",
        "dify_url": os.getenv("DIFY_API_URL", "https://api.dify.ai/v1") if provider == "dify" else None,
    }