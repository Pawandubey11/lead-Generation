"""
opportunity_scorer.py
---------------------
Explainable Business Opportunity Score (0-100) tailored for SystemaOps.

Distinct from Lead Score (which measures contact field completeness).
Four weighted dimensions:
  1. SystemaOps Service Compatibility (0-35): evidence-backed fit for Odoo ERP,
     Workflow/n8n Integration, Document Automation, AI Automation, Custom Dev.
  2. Digital & Website Gaps        (0-25): real observed website/audit deficits.
  3. Commercial Viability          (0-25): Google reviews, rating, active footprint.
  4. Contact Accessibility         (0-15): direct email, phone, LinkedIn/social reach.

Rule: Missing information reduces `data_confidence` (0.0-1.0 / LOW|MEDIUM|HIGH)
and is NEVER fabricated into fake business problems.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ai.systemaops_catalogue import SYSTEMAOPS_SERVICES, match_services

# Industries with strong evidence of multi-department ERP / automation ROI
HIGH_COMPLEXITY_ERP_TERMS = (
    "manufactur", "wholesale", "distribut", "logistics", "pharma",
    "hospital", "clinic", "real estate", "construction", "automotive",
    "trading", "supply", "import", "export", "warehouse",
)

TECH_AUTOMATION_TERMS = (
    "software", "it ", "it-", "saas", "agency", "digital marketing",
    "consulting", "account", "finance", "legal", "ecommerce", "hotel",
    "restaurant", "retail",
)


def compute_opportunity_score(
    lead: Dict[str, Any],
    audit: Optional[Dict[str, Any]] = None,
    ai_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute an explainable 0-100 SystemaOps Business Opportunity Score.

    Returns breakdown, human-readable reasons, recommended services (with evidence),
    and separate `data_confidence` reflecting how much verified data was available.
    """
    name = str(lead.get("business_name") or "").strip()
    biz_type = str(lead.get("business_type") or lead.get("spin") or "").strip()
    industry = str((ai_report or {}).get("industry") or biz_type).strip()
    website = str(lead.get("website") or "").strip()
    phone = str(lead.get("phone") or "").strip()
    email = str(lead.get("email") or "").strip()
    has_social = bool(lead.get("instagram") or lead.get("facebook") or lead.get("linkedin"))

    # Parse rating & review count safely (never fabricate defaults!)
    try:
        rating_val = float(str(lead.get("rating") or "").replace(",", ".").strip())
    except ValueError:
        rating_val = None
    try:
        review_val = int(float(str(lead.get("reviews") or "").replace(",", "").strip()))
    except ValueError:
        review_val = None

    # Track verified evidence signals for confidence calculation
    known_signals = 0
    total_possible_signals = 6
    if biz_type:
        known_signals += 1
    if website:
        known_signals += 1
    if phone or email:
        known_signals += 1
    if rating_val is not None:
        known_signals += 1
    if review_val is not None:
        known_signals += 1
    if audit is not None or ai_report is not None:
        known_signals += 1

    confidence_ratio = round(known_signals / total_possible_signals, 2)
    confidence_label = (
        "HIGH" if confidence_ratio >= 0.75
        else "MEDIUM" if confidence_ratio >= 0.45
        else "LOW"
    )

    # ------------------------------------------------------------------
    # 1. SystemaOps Service Compatibility (0-35)
    # ------------------------------------------------------------------
    context_text = " ".join([
        biz_type,
        industry,
        str((ai_report or {}).get("company_overview") or ""),
        str((ai_report or {}).get("potential_business_challenge") or ""),
        str((ai_report or {}).get("technology_signals") or ""),
    ]).lower()

    matched_keys = match_services(
        business_type=biz_type,
        industry=industry,
        website=website,
        signals=[context_text] if context_text.strip() else [],
    )

    service_fit_score = 10  # baseline if industry known else reduced below
    service_reasons: List[str] = []

    if not biz_type and not ai_report:
        service_fit_score = 5
        service_reasons.append("Limited industry/operational data; compatibility confidence is reduced.")
    else:
        if any(term in context_text for term in HIGH_COMPLEXITY_ERP_TERMS):
            service_fit_score = 30
            service_reasons.append(
                f"Industry profile ({industry or biz_type}) typically involves multi-stage operations "
                "(inventory, billing, CRM, or compliance) matching Odoo ERP & Document Automation."
            )
        elif any(term in context_text for term in TECH_AUTOMATION_TERMS):
            service_fit_score = 26
            service_reasons.append(
                f"Service/digital business ({industry or biz_type}) aligns strongly with Workflow "
                "Integration (n8n), AI Automation, and CRM pipelines."
            )
        else:
            service_fit_score = 18
            service_reasons.append(f"General B2B/local service profile ({industry or biz_type}) eligible for CRM/automation.")

        if ai_report and ai_report.get("research_status") == "completed":
            prio = str(ai_report.get("opportunity_priority") or "").upper()
            if prio == "HIGH":
                service_fit_score = min(35, service_fit_score + 5)
                service_reasons.append("AI research confirmed high operational improvement potential.")
            elif prio == "MEDIUM":
                service_fit_score = min(35, service_fit_score + 2)

    recommended_services = [
        SYSTEMAOPS_SERVICES[k]["name"]
        for k in matched_keys[:3]
        if k in SYSTEMAOPS_SERVICES
    ]

    # ------------------------------------------------------------------
    # 2. Digital & Website Gaps (0-25) — evidence-based ONLY
    # ------------------------------------------------------------------
    digital_gap_score = 0
    digital_reasons: List[str] = []
    web_focus_recommended = False

    if audit is not None:
        w_status = audit.get("website_status", "NO_WEBSITE")
        if w_status == "NO_WEBSITE":
            digital_gap_score = 22
            digital_reasons.append("Confirmed no official website listed — missing digital lead capture.")
            web_focus_recommended = True
        elif w_status == "SOCIAL_ONLY":
            digital_gap_score = 20
            digital_reasons.append(f"Relies only on {audit.get('social_platform', 'social')} directory rather than owned web portal.")
            web_focus_recommended = True
        elif w_status == "BROKEN_OR_INACTIVE":
            digital_gap_score = 24
            digital_reasons.append(f"Website unreachable or erroring ({audit.get('technical_issues_summary', 'error')}).")
            web_focus_recommended = True
        else:
            # ACTIVE_OFFICIAL: sum measurable gaps
            if not audit.get("has_valid_ssl"):
                digital_gap_score += 8
                digital_reasons.append("Missing valid HTTPS/SSL security.")
                web_focus_recommended = True
            if not audit.get("mobile_responsive"):
                digital_gap_score += 7
                digital_reasons.append("Missing mobile viewport responsiveness.")
                web_focus_recommended = True
            perf = audit.get("performance_score")
            if isinstance(perf, (int, float)) and perf < 60:
                digital_gap_score += 6
                digital_reasons.append(f"Low mobile PageSpeed performance ({perf}/100).")
                web_focus_recommended = True
            bl = audit.get("broken_links", {})
            if isinstance(bl, dict) and bl.get("broken_count", 0) > 0:
                digital_gap_score += 5
                digital_reasons.append(f"{bl['broken_count']} broken internal link(s) detected.")
                web_focus_recommended = True
            seo_sc = audit.get("seo_basic_score") or (audit.get("seo_checks") or {}).get("seo_basic_score")
            if isinstance(seo_sc, (int, float)) and seo_sc < 70:
                digital_gap_score += 4
                digital_reasons.append(f"Incomplete on-page SEO metadata ({seo_sc}/100).")
            if digital_gap_score == 0:
                digital_gap_score = 4
                digital_reasons.append("Website passes baseline SSL, mobile, and SEO checks.")
    else:
        # Without running audit, inspect what raw lead tells us without inventing flaws
        if not website:
            digital_gap_score = 18
            digital_reasons.append("No website URL found in listing (website audit not run).")
            web_focus_recommended = True
        else:
            digital_gap_score = 8
            digital_reasons.append("Website present; run technical website audit to measure performance/SSL/SEO.")

    digital_gap_score = min(25, digital_gap_score)

    # ------------------------------------------------------------------
    # 3. Commercial Viability (0-25)
    # ------------------------------------------------------------------
    viability_score = 0
    viability_reasons: List[str] = []

    if review_val is not None:
        if review_val >= 200:
            viability_score += 13
            viability_reasons.append(f"Strong customer volume ({review_val} reviews).")
        elif review_val >= 50:
            viability_score += 9
            viability_reasons.append(f"Established customer activity ({review_val} reviews).")
        elif review_val >= 10:
            viability_score += 5
            viability_reasons.append(f"Moderate review footprint ({review_val} reviews).")
        else:
            viability_score += 2
            viability_reasons.append(f"Low review count ({review_val} reviews).")
    else:
        viability_reasons.append("Review count unavailable (reduces confidence, not penalized as failure).")

    if rating_val is not None:
        if rating_val >= 4.2:
            viability_score += 8
            viability_reasons.append(f"High reputation rating ({rating_val}/5.0).")
        elif rating_val >= 3.5:
            viability_score += 5
            viability_reasons.append(f"Healthy rating ({rating_val}/5.0).")
        else:
            viability_score += 2
            viability_reasons.append(f"Rating {rating_val}/5.0.")

    if website or phone:
        viability_score += 4

    viability_score = min(25, viability_score)

    # ------------------------------------------------------------------
    # 4. Contact Accessibility (0-15)
    # ------------------------------------------------------------------
    contact_score = 0
    contact_reasons: List[str] = []
    if email:
        contact_score += 8
        contact_reasons.append("Direct email available.")
    if phone:
        contact_score += 5
        contact_reasons.append("Direct phone number available.")
    if has_social:
        contact_score += 2
        contact_reasons.append("Social profile(s) available.")
    if not contact_reasons:
        contact_reasons.append("No direct phone or email extracted; outreach requires lookup.")

    contact_score = min(15, contact_score)

    # ------------------------------------------------------------------
    # Final Score & Grounded Pitch Focus
    # ------------------------------------------------------------------
    total = max(0, min(100, service_fit_score + digital_gap_score + viability_score + contact_score))
    grade = "A" if total >= 75 else "B" if total >= 55 else "C" if total >= 35 else "D"

    # Grounded SystemaOps note: don't recommend Odoo solely for a slow website
    if web_focus_recommended and digital_gap_score >= 15 and service_fit_score < 25:
        pitch_focus = "Website Modernization, SSL/Performance Fixes & Lead Capture"
    else:
        pitch_focus = ", ".join(recommended_services[:2]) if recommended_services else "Workflow & CRM Automation"

    return {
        "business_name": name,
        "opportunity_score": total,
        "opportunity_grade": grade,
        "data_confidence": confidence_ratio,
        "confidence_label": confidence_label,
        "sub_scores": {
            "service_fit": service_fit_score,
            "digital_gap": digital_gap_score,
            "commercial_viability": viability_score,
            "contact_accessibility": contact_score,
        },
        "max_weights": {
            "service_fit": 35,
            "digital_gap": 25,
            "commercial_viability": 25,
            "contact_accessibility": 15,
        },
        "reasons": {
            "service_fit": service_reasons,
            "digital_gap": digital_reasons,
            "commercial_viability": viability_reasons,
            "contact_accessibility": contact_reasons,
        },
        "recommended_services": recommended_services,
        "pitch_focus": pitch_focus,
    }
