# AUDIT REPORT 9: API INTEGRATION OPPORTUNITIES

## Status: MULTIPLE HIGH-VALUE INTEGRATIONS IDENTIFIED

---

## Overview

The current system relies entirely on web scraping for data collection and has minimal external service integration. This report identifies API services that could significantly improve lead quality, accuracy, and delivery.

---

## API-OPP-001 — Email Verification APIs (High Impact)

### Problem
Current email "validation" is regex-only. No MX record check. Many stored emails are:
- Placeholder addresses (`info@`, `contact@`)
- Misspelled domains
- Defunct/expired domains
- Spam traps

### Available Services

| Service | Free Tier | Paid | Accuracy | Recommended |
|---------|-----------|------|----------|-------------|
| Hunter.io Email Verifier | 25 verifications/month | $49/mo for 1000 | 95%+ | YES |
| ZeroBounce | 100/month | $16/mo per 1000 | 98%+ | YES |
| Mailboxlayer | 100/day | $14.99/mo for 10k | 90%+ | YES |
| AbstractAPI Email Validation | 100/month free | $14/mo | 92%+ | MAYBE |
| NeverBounce | No free tier | $8/1000 | 97%+ | For bulk |
| Debounce.io | 100 free | $10/mo for 5000 | 96%+ | YES |

### Integration Plan
```python
# config/config.py — add:
EMAIL_VERIFY_API_KEY = os.environ.get("ZEROBOUNCE_API_KEY", "")
EMAIL_VERIFY_ENABLED = os.environ.get("EMAIL_VERIFY_ENABLED", "false").lower() == "true"

# new: scrapers/email_verifier.py
import requests

def verify_email_zerobounce(email: str, api_key: str) -> dict:
    """Returns {'valid': bool, 'status': str, 'sub_status': str, 'did_you_mean': str}"""
    response = requests.get(
        "https://api.zerobounce.net/v2/validate",
        params={"api_key": api_key, "email": email, "ip_address": ""},
        timeout=10
    )
    data = response.json()
    return {
        "valid": data.get("status") == "valid",
        "status": data.get("status", "unknown"),
        "sub_status": data.get("sub_status", ""),
        "did_you_mean": data.get("did_you_mean", "")
    }
```

**Estimated Impact:** Reduce invalid emails from ~40% to <5% with 1000-lead verification for ~$10-16/month.

---

## API-OPP-002 — Google Places API (Official Replacement for Scraping)

### Problem
The current scraper is fragile because it depends on Google Maps' HTML structure, which changes frequently and may trigger bot detection.

### Official Alternative
**Google Places API (New)** provides structured business data with rate limits and terms of service:
- Business name, address, phone, website
- Google rating, review count
- Business hours
- Photos

### Cost
- $17 per 1000 Basic Data requests
- $32 per 1000 Contact Data requests (includes phone)
- Monthly $200 free credit = ~11,700 Contact Data requests free

### Trade-offs

| Factor | Current Scraping | Google Places API |
|--------|-----------------|-------------------|
| Cost | $0 (compute only) | ~$0.032/business |
| Stability | Breaks when UI changes | Stable versioned API |
| Rate Limits | Informal (no guarantees) | 100 req/min, monthly caps |
| Data Quality | Variable | Authoritative |
| Email | Extracted from website | Not provided |
| Social Media | Extracted from website | Not provided |
| Terms of Service | Violates ToS | Compliant |
| Scale | Unlimited (slow) | Metered (fast) |

### Recommendation
Use Google Places API for initial business discovery + existing website crawler for email/social extraction.

---

## API-OPP-003 — LinkedIn Sales Navigator / Apollo.io (B2B Contact Enrichment)

### Problem
Current data has business contact info (email, phone) but no person-level contact data (decision maker name, job title, LinkedIn profile).

### Available Services

| Service | Purpose | Pricing | Notes |
|---------|---------|---------|-------|
| Apollo.io | Contact enrichment | Free 100 credits/mo, $49/mo for 1000 | Best free tier |
| Hunter.io Domain Search | Find emails for domain | 25 searches/mo free | For Germany B2B |
| Lusha | Person + company data | 5 free credits/mo | Expensive at scale |
| Clearbit | Company + person enrichment | Usage-based | Premium |
| PhantomBuster | LinkedIn data extraction | $56/mo | Web scraping |

### Apollo.io Integration
```python
def enrich_lead_apollo(website: str, api_key: str) -> dict:
    """Find contact person at the company via Apollo.io"""
    domain = extract_domain(website)
    response = requests.get(
        "https://api.apollo.io/v1/organizations/enrich",
        params={"domain": domain},
        headers={"X-Api-Key": api_key},
        timeout=15
    )
    if response.status_code == 200:
        org = response.json().get("organization", {})
        return {
            "company_size": org.get("employee_count"),
            "industry": org.get("industry"),
            "founded_year": org.get("founded_year"),
            "linkedin_url": org.get("linkedin_url"),
        }
    return {}
```

---

## API-OPP-004 — N8N Webhook (Already Implemented — Enhancement Needed)

### Current State
`lead_cleaner.py` sends cleaned leads to N8N webhook with:
```json
{
    "total_leads": 150,
    "hot_leads": 32,
    "warm_leads": 68,
    "cold_leads": 50,
    "leads": [...]
}
```

### Gaps
1. Only sent once at the END of a full scrape + clean cycle — no real-time updates
2. If N8N is down at that moment, leads are lost (no retry queue)
3. No webhook signature verification by N8N (N8N webhook expects `X-Webhook-Secret` but doesn't enforce it by default)

### Enhancement: Incremental Webhook + Retry
```python
import time

def send_to_n8n_with_retry(dataframe, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.post(N8N_WEBHOOK_URL, ...)
            if response.status_code in (200, 201):
                return True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
    # Save to failed_webhook.json for manual retry
    with open("output/failed_webhook.json", "w") as f:
        json.dump({"timestamp": time.time(), "count": len(dataframe)}, f)
    return False
```

---

## API-OPP-005 — CRM Direct Integration (Odoo, HubSpot, Pipedrive)

### Problem
Currently users must download CSV/Excel and manually import into their CRM. This is a manual step prone to errors and duplicates.

### Available CRM APIs

| CRM | API Quality | Free Plan | Notes |
|-----|------------|-----------|-------|
| HubSpot | Excellent | Yes (CRM free) | Most popular, REST + webhooks |
| Pipedrive | Good | No | B2B focused, good for sales teams |
| Odoo | Good | Community | Open source, self-hosted |
| Zoho CRM | Good | Free up to 3 users | Full-featured free tier |
| Salesforce | Excellent | No (expensive) | Enterprise only |

### HubSpot Integration Example
```python
def push_to_hubspot(lead: dict, api_key: str) -> bool:
    """Create or update a HubSpot contact from a lead dict."""
    response = requests.post(
        "https://api.hubapi.com/crm/v3/objects/contacts",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "properties": {
                "email": lead.get("email", ""),
                "phone": lead.get("phone", ""),
                "company": lead.get("business_name", ""),
                "website": lead.get("website", ""),
                "city": lead.get("city", ""),
                "hs_lead_status": "NEW",
                "leadscore": str(lead.get("lead_score", 0)),
            }
        },
        timeout=10
    )
    return response.status_code in (200, 201)
```

---

## API-OPP-006 — ProxyMesh / Bright Data (Proxy Rotation for Anti-Blocking)

### Problem
Google Maps will start blocking or serving CAPTCHAs after sustained scraping from the same IP. This is currently unmitigated.

### Available Proxy Services

| Service | Type | Cost | Notes |
|---------|------|------|-------|
| Bright Data (Luminati) | Residential | $500+/mo | Premium, most reliable |
| ProxyMesh | Datacenter | $10-50/mo | Good for initial testing |
| Oxylabs | Residential | $300+/mo | Business focused |
| SmartProxy | Residential | $75/mo | Smaller scale |
| Free rotating proxies | Datacenter | $0 | Unreliable, often blocked |

### Integration with Playwright
```python
def launch_browser(p, proxy_url: str = None):
    kwargs = {
        "headless": True,
        "args": ["--no-sandbox", ...]
    }
    if proxy_url:
        kwargs["proxy"] = {"server": proxy_url}
    return p.chromium.launch(**kwargs)
```

Add `PROXY_URL` env var to `.env`:
```
PROXY_URL=http://user:pass@proxy.brightdata.com:22225
```

---

## Recommended Integration Priority

| Priority | Service | Impact | Cost | Complexity |
|----------|---------|--------|------|-----------|
| 1 (Immediate) | ZeroBounce Email Verification | Very High | Low ($10-16/mo) | Low |
| 2 (Short-term) | Apollo.io Contact Enrichment | High | Low (free tier) | Medium |
| 3 (Short-term) | HubSpot CRM Push | High | Free | Medium |
| 4 (Medium-term) | Google Places API | Very High | Moderate ($17-32/1000) | High |
| 5 (Medium-term) | Proxy Rotation | High | Moderate ($50-75/mo) | Medium |
| 6 (Long-term) | N8N Retry Queue | Medium | Low | Low |
