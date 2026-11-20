"""
Centralized LLM prompts for SystemaOps Business Intelligence.
Each prompt function returns a string; system constants are top-level strings.
"""
from __future__ import annotations

from ai.systemaops_catalogue import all_services_text

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

COMPANY_RESEARCH_SYSTEM = """\
You are a B2B business intelligence analyst for SystemaOps, a technology services company \
based in Hyderabad, India. Your job: research businesses and identify automation/ERP \
opportunities. Always return valid JSON. Never invent facts. Mark unknown info as "Unknown". \
Base recommendations only on observable evidence from the website or company name/category."""

OPPORTUNITY_MATCHING_SYSTEM = """\
You are a SystemaOps sales strategist. Match business research findings to relevant \
SystemaOps services. Return only genuinely relevant recommendations with business evidence. \
Never recommend all services to every company. If no strong opportunity exists, say so and \
set priority to low. Always return valid JSON."""

SALES_PREP_SYSTEM = """\
You are a SystemaOps sales coach preparing a team member for a first business meeting. \
Generate practical, specific materials tailored to the actual company. Always return valid JSON."""

OUTREACH_SYSTEM = """\
You are a SystemaOps business development specialist writing personalized outreach. \
Write professional, specific messages that reference real business observations. \
Never sound like mass marketing. Keep messages concise. Always return valid JSON."""

CONTENT_SYSTEM = """\
You are a SystemaOps content strategist. Create content ideas demonstrating expertise. \
IMPORTANT: Never name the researched company as a SystemaOps customer or imply \
SystemaOps has already implemented a solution for them. Always return valid JSON."""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def company_research_prompt(lead: dict, website_text: str = "") -> str:
    return f"""\
Research this business and return a JSON object with the fields listed below.

BUSINESS INFORMATION:
  Name     : {lead.get('business_name', 'Unknown')}
  Category : {lead.get('spin', '')}
  City     : {lead.get('city', '')}
  Website  : {lead.get('website', 'None')}
  Phone    : {lead.get('phone', '')}
  Email    : {lead.get('email', '')}
  Address  : {lead.get('address', '')}

WEBSITE TEXT (first 2 000 chars — may be empty):
{website_text[:2000] if website_text else '[No website or could not be fetched]'}

Return ONLY this JSON object — no explanation, no markdown, no extra text:
{{
  "company_overview": "2–3 sentence description of what this company does",
  "industry": "primary industry category (single phrase)",
  "business_model": "B2B | B2C | B2B2C | mixed | unknown",
  "products_services": "comma-separated list of products/services offered",
  "existing_capabilities": "systems or capabilities publicly visible (or 'Unknown')",
  "technology_signals": "any technology, software, or platform clues found (or 'None identified')",
  "website_status": "available | unavailable | no_website",
  "website_summary": "brief summary of website purpose and content",
  "website_strengths": "what the website does well (or 'N/A — no website')",
  "website_problems": "observable problems or missing elements",
  "website_improvement_opportunities": "specific improvements that would help the business",
  "website_recommendations": "top 2–3 actionable recommendations"
}}

Rules:
- If website_text is empty: set website_status to "no_website" or "unavailable".
- Never claim a company uses or doesn't use software unless there is clear evidence.
- Use "Unknown" for fields where information is not available.
- Be concise and factual; avoid speculation."""


def opportunity_matching_prompt(lead: dict, research: dict) -> str:
    return f"""\
Based on this business research, identify realistic SystemaOps service opportunities.

COMPANY      : {lead.get('business_name', 'Unknown')}
Industry     : {research.get('industry', 'Unknown')}
Overview     : {research.get('company_overview', '')}
Capabilities : {research.get('existing_capabilities', '')}
Tech signals : {research.get('technology_signals', '')}
Website gaps : {research.get('website_problems', '')}

SYSTEMAOPS SERVICE CATALOGUE:
{all_services_text()}

Pricing: $25–49/hr | Minimum project: ~$5 000

Return ONLY this JSON object:
{{
  "systemaops_business_opportunity": "plain-English explanation of the main opportunity (2–3 sentences)",
  "recommended_services": "comma-separated list of 1–3 most relevant SystemaOps service names",
  "strongest_opportunity": "single most relevant service and specific application for this company",
  "opportunity_reason": "why this opportunity exists, based on evidence",
  "expected_benefit": "specific business benefit this company would gain",
  "evidence": "observable facts that support this recommendation",
  "opportunity_priority": "high | medium | low",
  "recommendation_confidence": "high | medium | low",
  "potential_business_challenge": "the business problem SystemaOps would solve"
}}

Rules:
- Priority = high only when need is obvious from evidence.
- Confidence = high only when clearly supported by facts.
- If no strong opportunity exists, set priority and confidence to "low" and explain why.
- Do not recommend building something the company already has."""


def sales_prep_prompt(lead: dict, research: dict) -> str:
    return f"""\
Prepare meeting materials for a SystemaOps first sales call with this company.

COMPANY           : {lead.get('business_name', 'Unknown')}
Industry          : {research.get('industry', 'Unknown')}
Overview          : {research.get('company_overview', '')}
Strongest opp.    : {research.get('strongest_opportunity', '')}
Recommended svcs. : {research.get('recommended_services', '')}
SystemaOps pricing: $25–49/hr, minimum project ~$5 000

Return ONLY this JSON object:
{{
  "meeting_opening": "2–3 sentence personalized conversation opener referencing the company",
  "discovery_questions": "5 specific numbered questions tailored to this company's industry and situation",
  "sales_pitch": "3–4 sentence pitch explaining SystemaOps value specifically for this company",
  "suggested_next_action": "specific next step to propose at the end of the first meeting"
}}"""


def outreach_prompt(lead: dict, research: dict) -> str:
    return f"""\
Write personalized outreach for this company from SystemaOps.

COMPANY    : {lead.get('business_name', 'Unknown')}
Email      : {lead.get('email', 'unknown')}
Industry   : {research.get('industry', 'Unknown')}
Overview   : {research.get('company_overview', '')}
Opportunity: {research.get('strongest_opportunity', '')}
Evidence   : {research.get('evidence', '')}

Return ONLY this JSON object:
{{
  "email_subject": "concise subject line under 60 characters",
  "personalized_email": "full professional email (150–200 words) referencing a specific business observation",
  "linkedin_message": "connection request message under 300 characters",
  "follow_up_message": "follow-up email if no response after 1 week (100–150 words)"
}}"""


def content_prompt(lead: dict, research: dict) -> str:
    return f"""\
Create a content idea inspired by this business type and opportunity.
DO NOT name the researched company as a customer or imply SystemaOps has worked with them.

Industry   : {research.get('industry', 'Unknown')}
Challenge  : {research.get('potential_business_challenge', '')}
Solution   : {research.get('strongest_opportunity', '')}

Return ONLY this JSON object:
{{
  "post_topic": "content topic title (hook-style)",
  "post_text": "150-word post explaining the business challenge and how automation/ERP helps",
  "call_to_action": "single CTA line"
}}"""
