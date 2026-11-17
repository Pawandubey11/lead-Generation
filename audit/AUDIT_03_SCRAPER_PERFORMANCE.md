# AUDIT REPORT 3: SCRAPER PERFORMANCE & RELIABILITY

## Status: HIGH-PRIORITY IMPROVEMENTS IDENTIFIED

---

## Overview

The scraper (`scrapers/crawler.py`) is the core engine of the system. It operates via Playwright (headless Chromium) driving Google Maps, supplemented by HTTP requests to business websites for email/social extraction. This report covers performance bottlenecks, reliability gaps, and anti-detection risks.

---

## PERF-001 — Sequential Business Scraping (No Concurrency)

**Location:** `crawler.py` — `scrape_city()` loop (lines 816-834)

**Problem:**
```python
for idx, link in enumerate(business_links):
    lead, browser, page = scrape_business(link, p, browser, page)
```
Each business is scraped one at a time — wait 3-45 seconds per business (Playwright navigation + website crawl). For a city with 20 businesses, this is 60-900 seconds per city.

**Impact:** A full Germany run with 10 cities × 20 businesses = 200 businesses. At avg 15s each = **50 minutes minimum per niche**. With 8 niches in `batch_scraper.py` = **6.7+ hours**.

**Improvement Options:**
1. Use async Playwright (`async_api`) with 3-5 concurrent pages
2. Separate the Maps scrolling (1 browser) from website crawling (concurrent `requests.get()`)
3. Use `ThreadPoolExecutor` for the website crawl phase only (the HTTP requests are already synchronous)

---

## PERF-002 — Website Crawling Blocks Google Maps Scraping Thread

**Location:** `crawler.py` — `extract_socials_and_email()` called inside `scrape_business()` (line 695)

**Problem:** Every call to `scrape_business()` does:
1. Playwright navigation to Google Maps place (slow, browser)
2. Data extraction
3. `extract_socials_and_email(website)` → HTTP GET to external website (up to 15s timeout, synchronous)

Steps 1+2 must use the browser. Step 3 uses plain `requests` and could easily run in a thread pool.

**Fix:** Collect all business data first (name, phone, address, website URL), then process website crawling in a `ThreadPoolExecutor(max_workers=5)`.

---

## PERF-003 — 3-Second Hardcoded Delay Between Scrolls (80 Scrolls Max)

**Location:** `crawler.py` — `scrape_city()` (line 817)

**Problem:**
```python
for i in range(max_scrolls):  # max_scrolls = 80
    scrollable_div.evaluate("(el) => el.scrollTop = el.scrollHeight")
    time.sleep(2 if is_quick else 3)   # 3-second hard sleep
```

Maximum wait for scrolling: 80 × 3 = **240 seconds = 4 minutes** just scrolling Google Maps, even if no new businesses appear. The `same_count >= 6` guard only triggers after 6 identical results = 18 extra seconds of wasted time.

**Fix:** Use an adaptive wait — check if scroll position actually changed, reduce to 1.5s base delay, early exit more aggressively (3 identical counts instead of 6).

---

## PERF-004 — Browser Restart on Every Business (Excessive Overhead)

**Location:** `crawler.py` — `scrape_city()` (lines 820-823)

**Problem:**
```python
# After collecting all business links:
try:
    page.close()
except:
    pass
page = new_page(browser)  # Creates a NEW page for each business link!
```
Then inside `scrape_business()`, for each business:
```python
lead, browser, page = scrape_business(link, p, browser, page)
```
A new page is created for each of 20 businesses per city. Each `new_page()` creates a **new browser context** with cookie injection overhead.

**Fix:** Reuse the same page (just navigate to new URL) rather than creating a new context per business.

---

## REL-001 — No Retry Logic for Wikipedia City Lookup Failures

**Location:** `crawler.py` — `get_cities()` (lines 390-410)

**Problem:** If Wikipedia API is unreachable (network blip), the city lookup fails and `generate_leads()` runs with just the country name as a single location. No retry, no exponential backoff.

**Fix:** Add `urllib3.Retry` or simple retry loop with 3 attempts + 2s backoff.

---

## REL-002 — No Rate-Limiting / Backoff on Google Maps

**Location:** `crawler.py` — `scrape_city()` / `scrape_business()`

**Problem:** The scraper sends requests to Google Maps at full speed with only a fixed 2-3 second delay per business. Google Maps will start returning CAPTCHA or empty results after sustained scraping.

**Signs of this problem:** No detection of empty result sets, no CAPTCHA handling, no exponential backoff after consent walls.

**Fix:**
- Detect CAPTCHA interstitials (look for `g-recaptcha` in page source)
- Implement random jitter (sleep 2-5s instead of fixed 3s)
- Detect "No results found" Maps pages and skip gracefully

---

## REL-003 — Error Handling in `scrape_business()` Swallows All Exceptions

**Location:** `crawler.py` — `scrape_business()` (lines 609-703)

**Problem:**
```python
try:
    website = page.locator('a[data-item-id="authority"]').first.get_attribute("href", timeout=8000)
except:
    website = ""
```
Bare `except:` with no logging. If a Google Maps selector changes (and it does!), the scraper silently returns empty strings for phone/address/website. No alert, no log, no metric — the system just produces leads with no contact info.

**Fix:** Log specific selector failures to a debug file, track percentage of fields found per city session, alert if >50% of fields are empty.

---

## REL-004 — `MAX_BIZ_PER_CITY` Environment Variable Not Validated

**Location:** `crawler.py` (lines 826-830)

**Problem:**
```python
max_biz_env = os.environ.get("MAX_BIZ_PER_CITY")
if max_biz_env and max_biz_env.isdigit():
    business_links = business_links[:int(max_biz_env)]
```
`batch_scraper.py` sets `os.environ["MAX_BIZ_PER_CITY"] = "20"`. But `scrape_germany_b2b.py` removes it with `del os.environ["MAX_BIZ_PER_CITY"]`. If these scripts are used together or in the wrong order, the env var state is unpredictable.

**Fix:** Accept as explicit function parameter rather than env var.

---

## REL-005 — No Verification That Scraped Business Is Actually In Target City

**Location:** `crawler.py` — `scrape_business()` (lines 642-700)

**Problem:** Google Maps sometimes returns businesses from neighboring cities or even different countries when the search results are sparse. There's no validation that the extracted address actually contains the target city name.

**Impact:** City column in CSV may contain businesses that are geographically misplaced, reducing data quality.

**Fix:** After extraction, check if `target_city.lower()` appears in `address.lower()` or `city` field. Mark mismatches with a `city_mismatch` flag.

---

## Anti-Detection Gaps

| Risk | Current State | Recommendation |
|------|--------------|----------------|
| User-Agent rotation | Fixed UA string | Rotate from pool of 5-10 UAs |
| IP rotation | No proxy support | Add optional proxy list |
| Headless fingerprint | `--disable-blink-features=AutomationControlled` only | Add full stealth mode (playwright-stealth) |
| Cookie refresh | Cookies loaded once at startup | Re-inject cookies if consent wall seen again |
| Request timing | Fixed delays | Use random jitter (uniform distribution 1.5-5s) |

---

## Performance Benchmark Estimates

| Configuration | Businesses/City | Cities | Est. Time |
|--------------|----------------|--------|-----------|
| Current (batch_scraper) | 20 | 10 | ~1.5-2 hrs/niche |
| Current (germany_b2b) | Unlimited | 20 | 3-8 hrs/niche |
| With PERF-002 fix (concurrent website crawl) | Same | Same | ~40% faster |
| With PERF-001 fix (3 concurrent pages) | Same | Same | ~65% faster |
| With both fixes | Same | Same | ~75% faster |
