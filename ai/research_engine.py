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
        d = self.llm.call_dify_chatflow(
            company_name=name,
            website_url=website,
            industry=industry,
        )

        if website:
            sources.append(website)

        def _to_str(val, sep="\n") -> str:
            """Recursively convert any value to a readable string."""
            if val is None:
                return ""
            if isinstance(val, str):
                return val
            if isinstance(val, (int, float)):
                return str(val)
            if isinstance(val, list):
                parts = []
                for item in val:
                    if isinstance(item, dict):
                        parts.append(", ".join(f"{k}: {v}" for k, v in item.items()))
                    else:
                        parts.append(str(item))
                return sep.join(f"- {p}" for p in parts)
            if isinstance(val, dict):
                return sep.join(f"{k}: {v}" for k, v in val.items())
            return str(val)

        # ── company_profile ────────────────────────────────────────────
        cp = d.get("company_profile", {}) or {}
        result["company_overview"] = _to_str(cp.get("overview", ""))
        result["business_model"] = _to_str(cp.get("business_model", ""))
        result["products_services"] = _to_str(cp.get("products_services", []))
        result["industry"] = _to_str(cp.get("industry", industry))
        result["technology_signals"] = _to_str(cp.get("technology_signals", ""))
        result["existing_capabilities"] = _to_str(cp.get("target_customers", []))

        # ── website_issues ─────────────────────────────────────────────
        wi = d.get("website_issues", {}) or {}
        confirmed = wi.get("confirmed", []) or []
        assumed = wi.get("assumed", []) or []
        all_issues = confirmed + assumed
        result["website_status"] = "available" if website else "unknown"
        result["website_problems"] = _to_str(all_issues)
        result["website_summary"] = _to_str(d.get("website_analysis", wi))
        result["website_strengths"] = _to_str(wi.get("positives", []))
        result["website_improvement_opportunities"] = _to_str(assumed[:5])
        result["website_recommendations"] = _to_str(d.get("website_recommendations", assumed[:3]))

        # ── recommended_services ───────────────────────────────────────
        rec_list = d.get("recommended_services", []) or []
        if rec_list and isinstance(rec_list[0], dict):
            top = rec_list[0]
            result["strongest_opportunity"] = top.get("service", "")
            result["opportunity_reason"] = top.get("reason", "")
            conf = top.get("confidence", 0)
            result["recommendation_confidence"] = (
                "HIGH" if conf >= 0.7 else "MEDIUM" if conf >= 0.4 else "LOW"
            )
            impact = top.get("impact", 3)
            result["opportunity_priority"] = (
                "HIGH" if impact >= 4 else "MEDIUM" if impact >= 2 else "LOW"
            )
            # All services as a summary string
            result["recommended_services"] = _to_str(
                [f"{r.get('service','')}: {r.get('reason','')[:80]}" for r in rec_list]
            )
        elif rec_list:
            result["strongest_opportunity"] = str(rec_list[0])
            result["recommended_services"] = _to_str(rec_list)

        # ── outreach ───────────────────────────────────────────────────
        outreach = d.get("outreach", {}) or {}
        email_obj = outreach.get("email", {}) or {}
        result["email_subject"] = _to_str(
            email_obj.get("subject") or d.get("email_subject", ""))
        result["personalized_email"] = _to_str(
            email_obj.get("body") or d.get("email_body", ""))
        # Dify returns linkedin_message and whatsapp_message inside outreach{}
        result["linkedin_message"] = _to_str(
            outreach.get("linkedin_message") or
            outreach.get("linkedin") or
            d.get("linkedin_message") or "")
        result["follow_up_message"] = _to_str(
            outreach.get("whatsapp_message") or
            outreach.get("whatsapp") or
            d.get("whatsapp_message") or "")

        # ── meeting questions ──────────────────────────────────────────
        questions = d.get("sales_questions", d.get("meeting_questions", []))
        result["discovery_questions"] = _to_str(questions)

        # ── opportunity summary ────────────────────────────────────────
        result["systemaops_business_opportunity"] = _to_str(
            d.get("systemaops_opportunity",
                  d.get("opportunity_summary",
                        f"{name} could benefit from {result.get('strongest_opportunity', 'SystemaOps services')}. "
                        f"{result.get('opportunity_reason', '')}"))
        )

        # ── technology_signals (derive from profile + website) ─────────
        tech_raw = _to_str(cp.get("technology_signals", ""))
        if not tech_raw:
            # Infer from industry and website issues
            tech_raw = _to_str(d.get("technology_signals",
                f"No specific technology signals publicly identified for {name}. "
                "Likely uses standard industry software — to be confirmed in meeting."))
        result["technology_signals"] = tech_raw

        # ── website_strengths (derive from profile) ────────────────────
        result["website_strengths"] = _to_str(
            d.get("website_strengths") or
            wi.get("positives") or
            (f"{name} has an online presence at {website}. " if website else
             "No website publicly identified."))

        # ── expected_benefit (derive from top service) ─────────────────
        top_svc = result.get("strongest_opportunity", "")
        opp_reason = result.get("opportunity_reason", "")
        result["expected_benefit"] = _to_str(
            d.get("expected_benefit") or
            (f"Implementing {top_svc} could help {name} streamline operations, "
             f"reduce manual work, and improve business visibility. {opp_reason}" if top_svc else ""))

        # ── potential_business_challenge ───────────────────────────────
        challenges = _to_str(
            d.get("challenges") or d.get("pain_points") or d.get("problems") or "")
        if not challenges and all_issues:
            challenges = _to_str(all_issues[:3])
        result["potential_business_challenge"] = challenges or (
            f"Likely faces manual processes and disconnected systems based on "
            f"industry norms for {industry} companies.")

        # ── evidence ──────────────────────────────────────────────────
        conf_str = result.get("recommendation_confidence", "MEDIUM")
        result["evidence"] = (
            f"Dify AI analysis of {name}. "
            f"Top recommendation: {top_svc}. Confidence: {conf_str}. "
            f"Based on company profile and website analysis."
        )

        # ── meeting_opening ────────────────────────────────────────────
        result["meeting_opening"] = _to_str(
            d.get("meeting_opening") or
            (f"Hello! I came across {name} and was impressed by what you do. "
             f"I'm reaching out from SystemaOps — we help {industry} businesses "
             f"like yours streamline operations through {top_svc or 'Odoo ERP and AI automation'}. "
             f"I'd love to learn more about your current setup and share a few ideas."))

        # ── sales_pitch ────────────────────────────────────────────────
        result["sales_pitch"] = _to_str(
            d.get("sales_pitch") or
            (f"SystemaOps specializes in {top_svc or 'Odoo ERP and AI automation'} "
             f"for {industry} businesses. {opp_reason} "
             f"Our clients typically reduce manual work by 10+ hours/week within the first 90 days. "
             f"We work with projects starting from $5,000 at $25–49/hr."))

        # ── suggested_next_action ──────────────────────────────────────
        result["suggested_next_action"] = _to_str(
            d.get("suggested_next_action") or
            d.get("next_step") or
            d.get("call_to_action") or
            f"Schedule a 30-minute discovery call to map {name}'s current processes "
            f"and identify the top 3 automation opportunities with SystemaOps.")

        # ── content fields ─────────────────────────────────────────────
        result["post_topic"] = _to_str(
            d.get("blog_topic") or d.get("content_idea") or d.get("post_topic") or
            f"How {industry} businesses like {name} save 10+ hours/week with "
            f"{top_svc or 'Odoo ERP and workflow automation'}")

        result["post_text"] = _to_str(
            d.get("post_text") or
            (f"Many {industry} businesses are still managing operations through "
             f"disconnected systems and manual processes.\n\n"
             f"The challenge: data silos, manual entry, slow reporting.\n\n"
             f"The solution: {top_svc or 'integrated ERP and automation'}.\n\n"
             f"With SystemaOps, businesses like {name} can:\n"
             f"✅ Centralise operations in one platform\n"
             f"✅ Automate repetitive document and data tasks\n"
             f"✅ Get real-time visibility into their business\n\n"
             f"The result: more time for growth, fewer errors, better decisions."))

        result["call_to_action"] = _to_str(
            d.get("call_to_action") or
            f"Comment 'AUTOMATE' to get our free {industry} business automation checklist")

        # ── meta flags ─────────────────────────────────────────────────
        result["research_error"] = None
        result["manual_review_required"] = False

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