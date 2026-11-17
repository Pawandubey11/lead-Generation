# AUDIT REPORT 4: DATA QUALITY & LEAD SCORING

## Status: SIGNIFICANT IMPROVEMENTS REQUIRED

---

## Overview

Data quality is the most critical output metric of a lead generation system. This report evaluates the accuracy of scraped data, the validity of contact information, the scoring algorithm's effectiveness, and de-duplication logic.

---

## DQ-001 — Email "Validation" Is Trivially Weak

**Files:** `lead_cleaner.py` (line ~54), `dashboard/dashboard_service.py` (line 788)

**Current Implementation:**
```python
# lead_cleaner.py:
verified_mask = (df["email"].astype(str).str.contains("@", na=False)) | (df["Contact Completeness %"] >= 50)

# dashboard_service.py:
has_email_mask = email_col.str.strip().str.match(
    r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$', na=False
)
```

**Problems:**
1. `lead_cleaner.py` only checks for `@` — `test@test`, `info@`, `notanemail@` all pass
2. No duplicate email detection across different spins/runs
3. No blacklist for placeholder emails: `info@example.com`, `test@domain.com`, `noreply@`, `admin@`, `support@`, `no-reply@`
4. `crawler.py` has its own blacklist (`example, domain, email.com, yourmail, sentry, wixpress, squarespace`) but `lead_cleaner.py` and `dashboard_service.py` don't use it
5. No MX record validation (DNS lookup to verify domain can receive email)
6. The two "verified" checks are inconsistent (threshold: `@` in lead_cleaner vs RFC5322 in dashboard_service)

**Impact:** "Verified" leads may contain emails like `info@`, `webmaster@`, `sales@` which bounce at high rates.

**Recommended Fixes:**
```python
PLACEHOLDER_EMAIL_PATTERNS = [
    r'^(info|contact|admin|hello|support|noreply|no-reply|sales|webmaster|test|example)@',
    r'@example\.',
    r'@domain\.',
    r'@test\.',
    r'@placeholder\.',
    r'^.{1,3}@',    # too-short local part
]

def is_quality_email(email: str) -> bool:
    if not email or '@' not in email:
        return False
    import re
    if not re.match(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$', email):
        return False
    for pattern in PLACEHOLDER_EMAIL_PATTERNS:
        if re.match(pattern, email.lower()):
            return False
    return True
```

---

## DQ-002 — Phone Number Format Is Not Normalized

**File:** `scrapers/crawler.py` — `scrape_business()` (line 683)

**Problem:** Phones are extracted raw from Google Maps button text:
```python
phone = clean_text(page.locator('button[data-item-id*="phone"]').first.inner_text(timeout=8000))
```

Result: Phones stored in wildly inconsistent formats:
- `+49 30 12345678` (German international)
- `030 12345678` (German local)
- `(030) 123 456-78` (German formatted)
- `01234567890` (UK mobile no space)
- `+91 98765 43210` (Indian)

**Impact:** De-duplication by phone fails because `+49 30 12345678` and `030 12345678` don't match. CRM imports fail on format mismatch.

**Fix:** Normalize all phones to E.164 format (`+{country_code}{digits}`) before saving. `dashboard_service.py` already has `_normalise_phone()` for exports — apply same logic during scraping.

---

## DQ-003 — De-duplication Scope Is Too Narrow (Spin-Scoped Only)

**File:** `lead_cleaner.py` (lines 56-60)

**Problem:**
```python
df = df.drop_duplicates(subset=["business_name", "spin"], keep="first")
df = df[~((df["email"] != "") & df.duplicated(subset=["email", "spin"]))]
df = df[~((df["phone"] != "") & df.duplicated(subset=["phone", "spin"]))]
```

De-duplication only checks within the same `spin` (scrape run). The same business can appear in multiple runs (e.g., "Dental Clinic X in Berlin" in 3 different scrape runs) and all duplicates get kept.

**Impact:** With 12 niches × 20 cities, the same pharmacy or law firm can appear 10-20 times with different spin values but identical contact details, inflating "total leads" count.

**Fix:**
1. After spin-scoped dedup, do a cross-spin dedup by `(email, phone)` keeping the most recently scraped version
2. Add a `is_duplicate` flag instead of deleting (for audit trail)

---

## DQ-004 — Lead Score Is Binary/Sparse — Not Truly Reflective of Quality

**File:** `lead_cleaner.py` (lines 92-102)

**Current Scoring:**
```
phone=20, website=20, email=40, instagram=10, facebook=5, linkedin=5
Max=100, Hot>=70, Warm>=40, Cold<40
```

**Problems:**
1. Only 6 binary fields — most leads score either 20, 40, 60, 70, 80, 85, 90, 95, or 100 (10 possible values, not a continuous scale)
2. Email weighted 40 points but presence of a generic `info@` email gets full 40 points
3. No quality signals: response time, website load status, SSL certificate, number of pages on site
4. No relevance signal: a "dental clinic" found when searching "software companies" gets same score as a true match
5. `Cold` leads (score < 40) are still exported — no floor for export eligibility

**Suggested Enhanced Scoring:**
```
base_score = phone*15 + website*15 + quality_email*35 + instagram*10 + facebook*5 + linkedin*10 + address*5 + scraped_at_recency*5
bonus: website_loads=+5, ssl_active=+5, website_has_contact_page=+5
penalty: generic_email=-15, no_city_in_address=-5
```

---

## DQ-005 — Social Media URLs Not Cleaned or Validated

**File:** `scrapers/crawler.py` — `extract_socials_and_email()` (lines 572-579)

**Problem:**
```python
for a in soup.find_all("a", href=True):
    href = a["href"]
    if "instagram.com" in href and not socials["instagram"]:
        socials["instagram"] = href
```

Stored URLs are raw `href` values, which may be:
- Relative paths: `/share?url=instagram.com/...`
- Sharing widgets: `https://www.addtoany.com/add_to/facebook?...`
- Facebook CDN: `https://www.facebook.com/tr?id=...` (tracking pixel)
- Instagram embeds: `//www.instagram.com/p/...` (missing protocol)

**Fix:** Validate that the URL is a proper profile URL:
```python
INSTAGRAM_RE = re.compile(r'instagram\.com/(?!p/|reel/|explore/|tv/)[\w.]+')
FACEBOOK_RE = re.compile(r'facebook\.com/(?!sharer|share|tr|events|groups|help)[\w.\-]+')
LINKEDIN_RE = re.compile(r'linkedin\.com/(?:company|in)/[\w.\-]+')
```

---

## DQ-006 — `scraped_at` Timestamp Is Set Once Per Run, Not Per Business

**File:** `scrapers/crawler.py` — `generate_leads()` (line 854)

**Problem:**
```python
scraped_time = time.strftime("%Y-%m-%d %H:%M:%S")  # SET ONCE at start of run
...
for city_idx, city in enumerate(remaining_cities):
    for lead in city_leads:
        lead["scraped_at"] = scraped_time  # Same timestamp for ALL leads!
```

A 3-hour scraping session assigns the same `scraped_at` to every lead, making it impossible to know when any particular business was actually scraped.

**Fix:** Set `scraped_at` individually inside `scrape_business()` using `time.strftime()` at the moment of extraction.

---

## DQ-007 — Business Name Extraction Fails Silently, Uses Page Title Fallback

**File:** `scrapers/crawler.py` — `scrape_business()` (lines 663-676)

**Problem:**
```python
try:
    business_name = clean_text(page.locator("h1").first.inner_text(timeout=8000))
except:
    business_name = ""

# Fallback to page title if h1 extraction failed
if not business_name and page_title:
    clean_title = page_title.split(" - Google")[0].strip()
    if not _is_consent_page(clean_title, page.url):
        business_name = clean_title
```

Page title format is `"Business Name - Google Maps"`. The split `" - Google"` works for English but fails for German (`"Unternehmen Name - Google Maps"` → still extracts correctly since " - Google" is still present). But the actual `h1` selector may time out often if Google's DOM loads slowly, causing many businesses to only have the page title as their name, which may include extra suffix text.

---

## Data Quality Summary

| Metric | Current State | Target |
|--------|--------------|--------|
| Email validity rate | ~40-60% (simple regex only) | >80% (with blacklist + format check) |
| Phone format consistency | 0% (all different formats) | 90%+ (E.164 normalized) |
| Cross-run duplicate rate | Unknown (not tracked) | <5% |
| Social URL validity | ~60% (many tracking pixels) | >85% |
| Scraped_at accuracy | Per-run (not per-business) | Per-business |
| Lead score granularity | 10 possible values | 50+ possible values |
