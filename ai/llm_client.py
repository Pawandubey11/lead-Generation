"""
LLM client supporting OpenAI, Gemini, Anthropic, and mock providers.
Configure via environment variables:
  AI_PROVIDER = openai | gemini | anthropic | mock  (default: mock)
  AI_MODEL    = gpt-4o-mini | gemini-1.5-flash | claude-3-haiku-... (default: gpt-4o-mini)
  OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when LLM call fails after all retries."""


class LLMClient:
    def __init__(self) -> None:
        self.provider: str = os.getenv("AI_PROVIDER", "mock").lower()
        self.model: str = os.getenv("AI_MODEL", "gpt-4o-mini")
        self.openai_key: str = os.getenv("OPENAI_API_KEY", "")
        self.gemini_key: str = os.getenv("GEMINI_API_KEY", "")
        self.anthropic_key: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.max_retries: int = 3
        self.timeout: int = 60

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the configured provider can be called."""
        if self.provider == "mock":
            return True
        if self.provider == "openai":
            return bool(self.openai_key)
        if self.provider == "gemini":
            return bool(self.gemini_key)
        if self.provider == "anthropic":
            return bool(self.anthropic_key)
        return False

    def complete(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        """Call the LLM and return the response text."""
        last_exc: Exception = RuntimeError("No attempt made")
        for attempt in range(self.max_retries):
            try:
                if self.provider == "mock":
                    return self._mock_response(prompt)
                if self.provider == "openai":
                    return self._call_openai(prompt, system, temperature)
                if self.provider == "gemini":
                    return self._call_gemini(prompt, system, temperature)
                if self.provider == "anthropic":
                    return self._call_anthropic(prompt, system, temperature)
                # Unknown provider → mock
                return self._mock_response(prompt)
            except Exception as exc:
                last_exc = exc
                logger.warning("LLM attempt %d/%d failed: %s", attempt + 1, self.max_retries, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        raise LLMError(f"LLM call failed after {self.max_retries} retries: {last_exc}") from last_exc

    def complete_json(self, prompt: str, system: str = "") -> Dict[str, Any]:
        """Call the LLM and parse the JSON response."""
        text = self.complete(prompt, system).strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove opening fence (```json or ```) and closing fence
            inner = lines[1:]
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            text = "\n".join(inner).strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find a JSON object anywhere in the text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise LLMError(f"Could not parse JSON from LLM response: {text[:300]}")

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _call_openai(self, prompt: str, system: str, temperature: float) -> str:
        import requests  # already in requirements

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.openai_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "messages": messages, "temperature": temperature},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_gemini(self, prompt: str, system: str, temperature: float) -> str:
        import requests

        model = self.model if "gemini" in self.model else "gemini-1.5-flash"
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={self.gemini_key}",
            json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": temperature},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _call_anthropic(self, prompt: str, system: str, temperature: float) -> str:
        import requests

        model = self.model if "claude" in self.model else "claude-3-haiku-20240307"
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.anthropic_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2048,
                "temperature": temperature,
                "system": system or "You are a helpful assistant.",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    def _mock_response(self, prompt: str) -> str:  # noqa: ARG002
        """Return a canned JSON response for testing without an API key."""
        return json.dumps({
            "company_overview": "A local business providing products and services to customers in its area.",
            "industry": "Local Services",
            "business_model": "B2C service provider",
            "products_services": "Various products and services as listed on the company website",
            "existing_capabilities": "Basic website, contact information available online",
            "technology_signals": "No specific technology signals identified from public information",
            "website_status": "available",
            "website_summary": "Basic informational website with company and contact details",
            "website_strengths": "Has online presence with contact information visible",
            "website_problems": "Limited digital engagement features; no online booking or inquiry automation",
            "website_improvement_opportunities": "Could benefit from inquiry automation, CRM integration, and WhatsApp contact",
            "website_recommendations": "1. Add automated inquiry form with CRM integration. 2. Implement WhatsApp Business contact. 3. Improve mobile responsiveness.",
            "systemaops_business_opportunity": (
                "This business could benefit from workflow automation and CRM implementation "
                "to manage customer inquiries and operations more efficiently. "
                "An Odoo CRM with automated follow-ups could significantly improve lead conversion."
            ),
            "recommended_services": "Odoo ERP Solutions, AI & Intelligent Automation",
            "strongest_opportunity": "Odoo CRM implementation for customer and inquiry management",
            "opportunity_reason": "Business likely manages customer relationships manually without a proper CRM system",
            "expected_benefit": "Improved customer tracking, faster response times, automated follow-ups, better sales visibility",
            "evidence": "No CRM or ERP system identified from public information; inquiry process appears manual",
            "opportunity_priority": "medium",
            "recommendation_confidence": "medium",
            "potential_business_challenge": "Manual customer management and lack of integrated business systems",
            "meeting_opening": (
                "Hello! I came across your business and was impressed by what you do. "
                "I wanted to reach out from SystemaOps — we help businesses like yours "
                "streamline operations and grow faster through Odoo ERP and intelligent automation."
            ),
            "discovery_questions": (
                "1. How do you currently manage your customer inquiries and follow-ups?\n"
                "2. What software do you use for sales, inventory, or accounting?\n"
                "3. How much time does your team spend on manual data entry per week?\n"
                "4. Are your business applications — like accounting, sales, and inventory — connected?\n"
                "5. What are the biggest operational bottlenecks you face today?"
            ),
            "sales_pitch": (
                "SystemaOps specializes in Odoo ERP implementation and AI-powered workflow automation "
                "that helps growing businesses replace manual processes with integrated, intelligent systems. "
                "Our clients typically save 10+ hours per week in administrative work within the first 90 days. "
                "We work at $25–49/hr with projects starting from $5,000."
            ),
            "suggested_next_action": "Schedule a 30-minute discovery call to map your current processes and identify the top 3 automation opportunities",
            "email_subject": "Streamlining operations for businesses like yours",
            "personalized_email": (
                "Dear Team,\n\n"
                "I came across your business and wanted to share how SystemaOps has been helping "
                "similar companies eliminate manual work and grow more efficiently.\n\n"
                "We specialize in Odoo ERP and AI automation — helping businesses connect their "
                "sales, inventory, and customer management into one intelligent system.\n\n"
                "Would you be open to a quick 20-minute call this week to explore if there's a fit?\n\n"
                "Best regards,\nSystemaOps Team\nhttps://www.systemaops.com"
            ),
            "linkedin_message": (
                "Hi! I noticed your business and thought our Odoo ERP and automation solutions "
                "might be relevant. Would love to connect and share some ideas about streamlining operations."
            ),
            "follow_up_message": (
                "Hi again,\n\nFollowing up on my previous note about workflow automation. "
                "I wanted to share a quick case study of how we helped a similar business "
                "automate their customer management and save 12 hours/week.\n\n"
                "Happy to send it over — just reply here and I'll share it right away.\n\nBest,\nSystemaOps"
            ),
            "post_topic": "How local businesses save 10+ hours per week with workflow automation",
            "post_text": (
                "Many growing businesses are still managing their customers, inventory, and "
                "invoicing through spreadsheets and manual processes — consuming hours every week.\n\n"
                "The good news? Most of this can be automated.\n\n"
                "With Odoo ERP and intelligent workflow automation, businesses can:\n"
                "✅ Track customer inquiries automatically\n"
                "✅ Sync inventory in real time\n"
                "✅ Process invoices without manual entry\n"
                "✅ Follow up with leads using AI-powered workflows\n\n"
                "The result: more time for growth, fewer errors, and better customer experience."
            ),
            "call_to_action": "Comment 'AUTOMATE' to get our free workflow assessment checklist",
        })


# Module-level singleton
llm_client = LLMClient()