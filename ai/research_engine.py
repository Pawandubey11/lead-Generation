"""
Company research orchestrator for SystemaOps Business Intelligence.
Chains: web fetch → LLM research → opportunity matching → sales prep → outreach → content.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema — every key the enriched lead must have
# ---------------------------------------------------------------------------
ENRICHMENT_FIELDS: List[str] = [
    # metadata
    "research_status", "research_timestamp", "research_sources",
    "research_error", "manual_review_required",
    # company
    "company_overview", "industry", "business_model",
    "products_services", "existing_capabilities", "technology_signals",
    # website
    "website_status", "website_summary", "website_strengths",
    "website_problems", "website_improvement_opportunities", "website_recommendations",
    # opportunity
    "systemaops_business_opportunity", "recommended_services",
    "strongest_opportunity", "opportunity_reason", "expected_benefit",
    "evidence", "opportunity_priority", "recommendation_confidence",
    "potential_business_challenge",
    # sales
    "meeting_opening", "discovery_questions", "sales_pitch", "suggested_next_action",
    # outreach
    "email_subject", "personalized_email", "linkedin_message", "follow_up_message",
    # content
    "post_topic", "post_text", "call_to_action",
]

_DEFAULTS: Dict[str, Any] = {f: "" for f in ENRICHMENT_FIELDS}
_DEFAULTS.update({
    "research_status": "pending",
    "research_sources": [],
    "research_error": None,
    "manual_review_required": False,
    "opportunity_priority": "medium",
    "recommendation_confidence": "low",
})


class CompanyResearchEngine:
    """Orchestrate multi-stage LLM research for a single lead."""

    def __init__(self) -> None:
        from ai.llm_client import llm_client
        self.llm = llm_client
        self._cache: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def research_company(self, lead: dict) -> dict:
        """
        Research a lead and return an enriched dict.

        Parameters
        ----------
        lead : dict
            Keys: business_name, website, phone, email, city, address, spin, …

        Returns
        -------
        dict
            All ENRICHMENT_FIELDS populated (best-effort).
        """
        name: str = lead.get("business_name", "unknown")
        if name in self._cache:
            logger.info("Cache hit for %s", name)
            return self._cache[name]

        result = dict(_DEFAULTS)
        result["research_timestamp"] = datetime.utcnow().isoformat()
        sources: List[str] = []

        try:
            # 1. Fetch website text
            website_text, ws_url = self._fetch_website(lead.get("website", ""))
            if ws_url:
                sources.append(ws_url)

            # 2. Company research + website analysis (single LLM call)
            from ai.prompts import COMPANY_RESEARCH_SYSTEM, company_research_prompt
            step1 = self.llm.complete_json(
                company_research_prompt(lead, website_text),
                COMPANY_RESEARCH_SYSTEM,
            )
            result.update({k: v for k, v in step1.items() if k in _DEFAULTS})

            # 3. Opportunity matching
            from ai.prompts import OPPORTUNITY_MATCHING_SYSTEM, opportunity_matching_prompt
            step2 = self.llm.complete_json(
                opportunity_matching_prompt(lead, result),
                OPPORTUNITY_MATCHING_SYSTEM,
            )
            result.update({k: v for k, v in step2.items() if k in _DEFAULTS})

            # 4. Sales preparation
            from ai.prompts import SALES_PREP_SYSTEM, sales_prep_prompt
            step3 = self.llm.complete_json(
                sales_prep_prompt(lead, result),
                SALES_PREP_SYSTEM,
            )
            result.update({k: v for k, v in step3.items() if k in _DEFAULTS})

            # 5. Outreach generation
            from ai.prompts import OUTREACH_SYSTEM, outreach_prompt
            step4 = self.llm.complete_json(
                outreach_prompt(lead, result),
                OUTREACH_SYSTEM,
            )
            result.update({k: v for k, v in step4.items() if k in _DEFAULTS})

            # 6. Content generation
            from ai.prompts import CONTENT_SYSTEM, content_prompt
            step5 = self.llm.complete_json(
                content_prompt(lead, result),
                CONTENT_SYSTEM,
            )
            result.update({k: v for k, v in step5.items() if k in _DEFAULTS})

            result["research_status"] = "completed"
            result["research_sources"] = sources

        except Exception as exc:
            logger.error("Research failed for %s: %s", name, exc)
            result["research_status"] = "failed"
            result["research_error"] = str(exc)
            result["manual_review_required"] = True

        self._cache[name] = result
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_website(self, url: str) -> Tuple[str, str]:
        """Fetch homepage text. Returns (text[:3000], final_url)."""
        if not url or not url.strip():
            return "", ""
        try:
            import requests
            from bs4 import BeautifulSoup

            if not url.startswith("http"):
                url = "https://" + url

            resp = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LeadPulseBot/1.0)"},
                allow_redirects=True,
            )
            final_url = resp.url
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "head"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            return text[:3000], final_url
        except Exception as exc:
            logger.warning("Could not fetch %s: %s", url, exc)
            return "", url


# Module-level singleton
research_engine = CompanyResearchEngine()