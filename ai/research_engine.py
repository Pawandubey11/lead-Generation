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
            # ── Dify provider: single chatflow call does everything ──────────
            if self.llm.provider == "dify" and self.llm.dify_key:
                result = self._research_via_dify(lead, result, sources)
            else:
                # ── Multi-stage pipeline for all other providers ─────────────
                result = self._research_via_llm(lead, result, sources)

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
    # Dify single-call path
    # ------------------------------------------------------------------

    def _research_via_dify(self, lead: dict, result: dict, sources: List[str]) -> dict:
        """Call the Dify Chatflow — one API call returns everything."""
        name = lead.get("business_name", "")
        website = lead.get("website", "")
        industry = lead.get("spin", lead.get("industry", ""))

        logger.info("Calling Dify chatflow for: %s", name)
        dify_result = self.llm.call_dify_chatflow(
            company_name=name,
            website_url=website,
            industry=industry,
        )

        if website:
            sources.append(website)

        # Map Dify JSON keys → LeadPulse enrichment fields
        # Dify returns: company_description, business_model, products_services,
        # website_analysis, website_problems, recommended_service, opportunity_reason,
        # confidence, opportunity_priority, systemaops_opportunity,
        # meeting_questions, email_subject, email_body, linkedin_message, whatsapp_message
        field_map = {
            # Dify key              → LeadPulse enrichment key
            "company_description":  "company_overview",
            "business_model":       "business_model",
            "products_services":    "products_services",
            "website_analysis":     "website_summary",
            "website_problems":     "website_problems",
            "recommended_service":  "strongest_opportunity",
            "opportunity_reason":   "opportunity_reason",
            "confidence":           "recommendation_confidence",
            "opportunity_priority": "opportunity_priority",
            "systemaops_opportunity": "systemaops_business_opportunity",
            "meeting_questions":    "discovery_questions",
            "email_subject":        "email_subject",
            "email_body":           "personalized_email",
            "linkedin_message":     "linkedin_message",
            "whatsapp_message":     "follow_up_message",
            # pass-through keys (same name in both)
            "industry":             "industry",
            "technology_signals":   "technology_signals",
        }

        for dify_key, lp_key in field_map.items():
            val = dify_result.get(dify_key)
            if val is not None:
                # Convert lists to readable string for CSV compatibility
                if isinstance(val, list):
                    val = "\n".join(f"- {q}" for q in val)
                elif isinstance(val, (int, float)):
                    val = str(val)
                result[lp_key] = val

        # Recommended services (use recommended_service as a list)
        rec = dify_result.get("recommended_service", "")
        result["recommended_services"] = rec

        # Build a website status flag
        website_analysis = dify_result.get("website_analysis", "")
        result["website_status"] = "available" if website_analysis and len(website_analysis) > 20 else "unknown"

        # Build a simple website strength / improvement block from analysis
        result["website_strengths"] = dify_result.get("website_strengths", "")
        result["website_improvement_opportunities"] = dify_result.get("website_improvements", "")
        result["website_recommendations"] = dify_result.get("website_improvements", "")

        # Evidence field
        result["evidence"] = (
            f"Dify AI analysis of {name} website and public information. "
            f"Recommended: {rec}. Confidence: {dify_result.get('confidence', 'unknown')}."
        )
        result["expected_benefit"] = dify_result.get("expected_benefit", "")

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _research_via_llm(self, lead: dict, result: dict, sources: List[str]) -> dict:
        """5-stage pipeline for OpenAI / Gemini / Anthropic / mock."""
        website_text, ws_url = self._fetch_website(lead.get("website", ""))
        if ws_url:
            sources.append(ws_url)

        from ai.prompts import COMPANY_RESEARCH_SYSTEM, company_research_prompt
        step1 = self.llm.complete_json(
            company_research_prompt(lead, website_text), COMPANY_RESEARCH_SYSTEM)
        result.update({k: v for k, v in step1.items() if k in _DEFAULTS})

        from ai.prompts import OPPORTUNITY_MATCHING_SYSTEM, opportunity_matching_prompt
        step2 = self.llm.complete_json(
            opportunity_matching_prompt(lead, result), OPPORTUNITY_MATCHING_SYSTEM)
        result.update({k: v for k, v in step2.items() if k in _DEFAULTS})

        from ai.prompts import SALES_PREP_SYSTEM, sales_prep_prompt
        step3 = self.llm.complete_json(
            sales_prep_prompt(lead, result), SALES_PREP_SYSTEM)
        result.update({k: v for k, v in step3.items() if k in _DEFAULTS})

        from ai.prompts import OUTREACH_SYSTEM, outreach_prompt
        step4 = self.llm.complete_json(
            outreach_prompt(lead, result), OUTREACH_SYSTEM)
        result.update({k: v for k, v in step4.items() if k in _DEFAULTS})

        from ai.prompts import CONTENT_SYSTEM, content_prompt
        step5 = self.llm.complete_json(
            content_prompt(lead, result), CONTENT_SYSTEM)
        result.update({k: v for k, v in step5.items() if k in _DEFAULTS})

        return result

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