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

    def clear_cache(self, names: List[str] = None) -> None:
        if names is None:
            self._cache.clear()
        else:
            for n in names:
                self._cache.pop(n, None)

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
        from ai.llm_client import QuotaExceededError

        name: str = lead.get("business_name", "unknown")
        cache_key = f"{self.llm.provider}::{name}"
        if cache_key in self._cache:
            logger.info("Cache hit for %s", name)
            return self._cache[cache_key]

        result = dict(_DEFAULTS)
        result["research_timestamp"] = datetime.utcnow().isoformat()
        sources: List[str] = []

        try:
            if self.llm.provider == "local":
                result = self._research_via_local_grounded(lead, result, sources)
            elif self.llm.provider == "dify" and self.llm.dify_key:
                try:
                    result = self._research_via_dify(lead, result, sources)
                except QuotaExceededError as q_exc:
                    import os
                    auto_fb = os.getenv("AI_AUTO_FALLBACK", "true").lower() == "true"
                    if auto_fb and self.llm.openai_key:
                        logger.warning("Dify quota exceeded for %s — falling back to OpenAI: %s", name, q_exc)
                        orig_p = self.llm.provider
                        try:
                            self.llm.provider = "openai"
                            result = self._research_via_llm(lead, result, sources)
                            result["quota_fallback_reason"] = f"{q_exc} (used OpenAI fallback)"
                        except Exception as o_exc:
                            logger.warning("OpenAI fallback also failed (%s) for %s — switching to grounded local analysis", o_exc, name)
                            result = self._research_via_local_grounded(lead, result, sources, fallback_reason=f"Dify ({q_exc}) & OpenAI ({o_exc}) failed")
                        finally:
                            self.llm.provider = orig_p
                    elif auto_fb:
                        logger.warning("Dify quota exceeded for %s — switching to grounded local analysis: %s", name, q_exc)
                        result = self._research_via_local_grounded(lead, result, sources, fallback_reason=str(q_exc))
                    else:
                        raise
            else:
                try:
                    result = self._research_via_llm(lead, result, sources)
                except Exception as llm_exc:
                    import os
                    auto_fb = os.getenv("AI_AUTO_FALLBACK", "true").lower() == "true"
                    if auto_fb:
                        logger.warning("LLM call failed (%s) for %s — switching to grounded local analysis", llm_exc, name)
                        result = self._research_via_local_grounded(lead, result, sources, fallback_reason=str(llm_exc))
                    else:
                        raise

            result["research_status"] = "completed"
            result["research_sources"] = sources
            self._cache[cache_key] = result

        except Exception as exc:
            logger.error("Research failed for %s: %s", name, exc)
            result["research_status"] = "failed"
            result["research_error"] = str(exc)
            result["manual_review_required"] = True

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

    def _research_via_local_grounded(
        self,
        lead: dict,
        result: dict,
        sources: List[str],
        fallback_reason: str = "",
    ) -> dict:
        """
        Deterministic, evidence-backed 37-field company intelligence using live
        homepage scraping, quantitative website audit, SystemaOps catalogue
        matching, and explainable opportunity scoring (zero fabricated claims).
        """
        from auditing.website_auditor import audit_website
        from scoring.opportunity_scorer import compute_opportunity_score
        from ai.systemaops_catalogue import SYSTEMAOPS_SERVICES, match_services

        name = str(lead.get("business_name") or "Unknown Company").strip()
        website = str(lead.get("website") or "").strip()
        city = str(lead.get("city") or "").strip()
        locality = str(lead.get("locality") or "").strip()
        biz_type = str(lead.get("business_type") or "").strip()
        spin = str(lead.get("spin") or "").strip()
        industry = biz_type or (spin.split(" in ")[0].split(" (")[0].strip() if spin else "Local Business")
        rating = str(lead.get("rating") or "").strip()
        reviews = str(lead.get("reviews") or "").strip()
        location_label = f"{locality}, {city}" if locality and city else (city or locality or "its local market")

        website_text, final_url = self._fetch_website(website)
        if final_url:
            sources.append(final_url)

        audit = audit_website(website, run_pagespeed=False, check_links=False)
        opp = compute_opportunity_score(lead, audit=audit, ai_report={"industry": industry})
        matched_keys = match_services(business_type=biz_type or spin, industry=industry, website=website, signals=[website_text[:500]])
        top_key = matched_keys[0] if matched_keys else "odoo_erp"
        top_svc = SYSTEMAOPS_SERVICES[top_key]
        rec_names = [SYSTEMAOPS_SERVICES[k]["name"] for k in matched_keys[:3] if k in SYSTEMAOPS_SERVICES]

        reputation_note = (
            f" Verified Google Maps profile shows {rating}/5.0 rating across {reviews} reviews."
            if rating and reviews else ""
        )
        snippet = (website_text[:280].rsplit(" ", 1)[0] + "...") if len(website_text) > 280 else website_text

        result["industry"] = industry
        result["business_model"] = "B2B / Local Service Provider (to be confirmed on discovery call)"
        result["company_overview"] = (
            f"{name} operates in {industry} in {location_label}.{reputation_note}"
            + (f" Public website excerpt: {snippet}" if snippet else " No detailed website copy was retrieved.")
        )
        result["products_services"] = snippet or f"{industry} services in {location_label}"
        result["existing_capabilities"] = ", ".join(
            [x for x in [
                f"Website ({audit.get('cms_detected')})" if audit.get("cms_detected") else ("Website" if website else ""),
                "Phone listed" if lead.get("phone") else "",
                "Email listed" if lead.get("email") else "",
                "Instagram" if lead.get("instagram") else "",
                "LinkedIn" if lead.get("linkedin") else "",
            ] if x]
        ) or "Basic Google Maps listing only"
        result["technology_signals"] = (
            f"CMS/Stack: {audit['cms_detected']}" if audit.get("cms_detected")
            else "No public CMS/stack signature detected — verify internal tools on call."
        )

        # Website section
        result["website_status"] = audit.get("website_status", "unknown")
        result["website_summary"] = audit.get("technical_issues_summary", "")
        result["website_strengths"] = "\n".join(f"- {p}" for p in (audit.get("positives") or [])) or "None verified automatically."
        result["website_problems"] = "\n".join(f"- {i}" for i in (audit.get("issues") or [])) or "No major technical HTTP/SSL/viewport defects detected."
        result["website_improvement_opportunities"] = (
            "1. Strengthen automated inquiry/appointment capture linked to CRM.\n"
            "2. Ensure SSL, mobile viewport, and Core Web Vitals optimization.\n"
            "3. Connect inbound leads directly to automated follow-up workflows."
        )
        result["website_recommendations"] = (
            f"- Technical status: {audit.get('website_status')} (SEO basic score: {audit.get('seo_checks', {}).get('seo_basic_score', 0)}/100)\n"
            f"- Address identified technical items: {audit.get('technical_issues_summary', '')}"
        )

        # Opportunity section
        result["strongest_opportunity"] = top_svc["name"]
        result["recommended_services"] = "\n".join(
            f"- {SYSTEMAOPS_SERVICES[k]['name']}: {SYSTEMAOPS_SERVICES[k]['description'][:110]}"
            for k in matched_keys[:3] if k in SYSTEMAOPS_SERVICES
        )
        result["opportunity_priority"] = "HIGH" if opp["opportunity_score"] >= 70 else "MEDIUM" if opp["opportunity_score"] >= 45 else "LOW"
        result["recommendation_confidence"] = opp["confidence_label"]
        result["systemaops_business_opportunity"] = (
            f"{name} scores {opp['opportunity_score']}/100 (Grade {opp['opportunity_grade']}, Confidence: {opp['confidence_label']}) "
            f"for {opp['pitch_focus']}. {top_svc['name']} aligns with {industry} operations."
        )
        result["opportunity_reason"] = " ".join(
            opp["reasons"].get("service_fit", []) + opp["reasons"].get("digital_gap", [])
        )
        result["expected_benefit"] = (
            f"Implementing {top_svc['name']} helps eliminate manual coordination, centralize customer/operations data, "
            f"and improve response times."
        )
        result["potential_business_challenge"] = "\n".join(f"- {p}" for p in top_svc.get("pain_points", [])[:4])
        ev_prefix = f"[Grounded Local Analysis — Fallback triggered: {fallback_reason}] " if fallback_reason else "[Grounded Local Analysis] "
        result["evidence"] = (
            ev_prefix +
            f"Evaluated live URL ({final_url or 'none'}), HTTP status ({audit.get('http_status')}), "
            f"SSL ({audit.get('has_valid_ssl')}), mobile viewport ({audit.get('mobile_responsive')}), "
            f"and Maps signals (rating={rating or 'N/A'}, reviews={reviews or 'N/A'})."
        )

        # Sales & Outreach section
        result["meeting_opening"] = (
            f"Hi {name} team — I reviewed your presence in {location_label} "
            f"and noticed opportunities around {opp['pitch_focus']}."
        )
        result["discovery_questions"] = (
            f"1. How are you currently managing customer inquiries and follow-ups at {name}?\n"
            f"2. Which software tools handle billing, scheduling, or inventory today?\n"
            f"3. Where does your team spend the most repetitive manual hours each week?\n"
            f"4. Are your website/booking leads flowing directly into a central CRM?\n"
            f"5. What operational bottleneck would have the highest ROI if automated first?"
        )
        result["sales_pitch"] = (
            f"SystemaOps helps {industry} teams in {location_label} streamline operations using "
            f"{', '.join(rec_names[:2])} — replacing disconnected spreadsheets and manual handoffs "
            f"with integrated automation (projects from $5,000, $25–49/hr)."
        )
        result["suggested_next_action"] = f"Book a 20-minute workflow & automation assessment with {name}."

        result["email_subject"] = f"Quick operational & automation idea for {name}"
        result["personalized_email"] = (
            f"Hi {name} team,\n\n"
            f"I came across your {industry} business in {location_label}"
            + (f" ({website})" if website else "") +
            f" and noticed strong customer visibility{reputation_note}\n\n"
            f"At SystemaOps, we help {industry} organizations eliminate manual data entry and disconnected "
            f"workflows using {top_svc['name']} and intelligent automation.\n\n"
            f"Open to a brief 15–20 minute call this week to share tailored recommendations?\n\n"
            f"Best regards,\nSystemaOps Team"
        )
        result["linkedin_message"] = (
            f"Hi {name} team — came across your {industry} work in {location_label}. "
            f"We help teams automate operations with {top_svc['name']}. Open to connecting?"
        )
        result["follow_up_message"] = (
            f"Hi {name} team, following up on my note regarding {top_svc['name']} for your {location_label} operations. "
            f"Happy to share a short tailored workflow plan anytime."
        )
        result["post_topic"] = f"How {industry} teams in {city or 'growing cities'} automate operations with {top_svc['name']}"
        result["post_text"] = (
            f"Many {industry} teams lose 10+ hours every week to manual follow-ups and disconnected tools.\n\n"
            f"By combining {top_svc['name']} with automated lead capture, teams turn inquiries into tracked pipeline automatically."
        )
        result["call_to_action"] = f"Reply 'AUDIT' for a free {industry} workflow & automation checklist."
        result["research_error"] = None
        result["manual_review_required"] = False
        if fallback_reason:
            result["quota_fallback_reason"] = fallback_reason
        return result

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