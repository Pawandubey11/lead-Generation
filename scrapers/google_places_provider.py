"""
google_places_provider.py
-------------------------
Optional Google Places API (v1 Text Search) discovery provider for LeadPulse.

- Activated ONLY when GOOGLE_PLACES_API_KEY is configured in environment AND
  explicitly requested.
- Never replaces Playwright Google Maps extraction or OSM locality discovery.
- Never fabricates missing phone, email, address, rating, or website fields.
- Tags every returned record with source_name="Google Places API".
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.websiteUri,places.nationalPhoneNumber,places.internationalPhoneNumber,"
    "places.rating,places.userRatingCount,places.primaryTypeDisplayName,"
    "places.googleMapsUri"
)


def is_google_places_configured() -> bool:
    return bool(os.environ.get("GOOGLE_PLACES_API_KEY", "").strip())


def discover_via_google_places(
    business_type: str,
    location: str,
    max_results: int = 20,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search businesses via Google Places API v1 Text Search.
    Returns [] cleanly if GOOGLE_PLACES_API_KEY is not set or request fails.
    """
    key = (api_key if api_key is not None else os.environ.get("GOOGLE_PLACES_API_KEY", "")).strip()
    if not key:
        logger.info("GOOGLE_PLACES_API_KEY not set — skipping Google Places API provider.")
        return []

    page_size = max(1, min(int(max_results), 20))
    payload = {
        "textQuery": f"{business_type.strip()} in {location.strip()}",
        "pageSize": page_size,
        "languageCode": "en",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    try:
        resp = requests.post(PLACES_TEXT_SEARCH_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code != 200:
            logger.warning("Google Places API returned HTTP %d: %s", resp.status_code, resp.text[:200])
            return []

        places = resp.json().get("places", [])
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        results: List[Dict[str, Any]] = []
        for p in places:
            name = (p.get("displayName") or {}).get("text", "").strip()
            if not name:
                continue
            rating = p.get("rating")
            rev_count = p.get("userRatingCount")
            primary_type = (p.get("primaryTypeDisplayName") or {}).get("text", "")
            results.append({
                "business_name": name,
                "phone": (p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber") or "").strip(),
                "website": (p.get("websiteUri") or "").strip(),
                "address": (p.get("formattedAddress") or "").strip(),
                "instagram": "",
                "facebook": "",
                "linkedin": "",
                "email": "",
                "rating": str(rating) if rating is not None else "",
                "reviews": str(rev_count) if rev_count is not None else "",
                "business_type": primary_type or business_type.strip(),
                "city": location.strip(),
                "source_name": "Google Places API",
                "source_url": (p.get("googleMapsUri") or p.get("id") or "").strip(),
                "scraped_at": now_str,
            })
        return results
    except Exception as exc:
        logger.warning("Google Places API request error: %s", exc)
        return []
