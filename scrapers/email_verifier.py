"""
email_verifier.py
-----------------
Zero-dependency email syntax + disposable domain + DNS MX verification helper.
Uses Google DNS-over-HTTPS (dns.google) cleanly with in-memory domain caching
and short timeouts so extraction is never blocked and no new pip packages are needed.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}$")

DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "10minutemail.com",
    "sharklasers.com", "yopmail.com", "trashmail.com", "discard.email",
}

_MX_CACHE: Dict[str, Dict[str, Any]] = {}


def verify_email_mx(email: Optional[str], lookup_dns: bool = True, timeout: float = 3.0) -> Dict[str, Any]:
    """
    Validate email syntax, check disposable domains, and optionally query MX records.
    Returns: {"email": str, "status": str, "mx_host": str | None, "confidence": float}
    Statuses: UNAVAILABLE | INVALID_SYNTAX | DISPOSABLE | VERIFIED_DELIVERABLE | NO_MX_RECORDS | UNVERIFIED
    """
    if not email or not str(email).strip():
        return {"email": "", "status": "UNAVAILABLE", "mx_host": None, "confidence": 0.0}

    em = str(email).strip()
    if not _EMAIL_RE.match(em):
        return {"email": em, "status": "INVALID_SYNTAX", "mx_host": None, "confidence": 0.0}

    domain = em.rsplit("@", 1)[-1].lower()
    if domain in DISPOSABLE_DOMAINS:
        return {"email": em, "status": "DISPOSABLE", "mx_host": None, "confidence": 0.1}

    if not lookup_dns:
        return {"email": em, "status": "SYNTAX_VALID", "mx_host": None, "confidence": 0.6}

    if domain in _MX_CACHE:
        cached = dict(_MX_CACHE[domain])
        cached["email"] = em
        return cached

    try:
        resp = requests.get(
            "https://dns.google/resolve",
            params={"name": domain, "type": "MX"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            answers = data.get("Answer", [])
            if answers:
                # Format in Answer data is "<pref> <host>."
                hosts = []
                for ans in answers:
                    parts = str(ans.get("data", "")).split()
                    if len(parts) >= 2:
                        try:
                            pref = int(parts[0])
                        except ValueError:
                            pref = 99
                        hosts.append((pref, parts[1].rstrip(".").lower()))
                hosts.sort(key=lambda x: x[0])
                primary_mx = hosts[0][1] if hosts else str(answers[0].get("data", "")).rstrip(".")
                res = {"email": em, "status": "VERIFIED_DELIVERABLE", "mx_host": primary_mx, "confidence": 0.95}
                _MX_CACHE[domain] = dict(res)
                return res
            res = {"email": em, "status": "NO_MX_RECORDS", "mx_host": None, "confidence": 0.2}
            _MX_CACHE[domain] = dict(res)
            return res
    except Exception as exc:
        logger.debug("MX lookup skipped/failed for %s: %s", domain, exc)

    return {"email": em, "status": "UNVERIFIED", "mx_host": None, "confidence": 0.5}
