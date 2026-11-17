# AUDIT REPORT 7: CODE QUALITY & MAINTAINABILITY

## Status: MODERATE — IMPROVABLE WITHOUT BREAKING CHANGES

---

## CQ-001 — Duplicate City Lookup Logic In Two Wikipedia Functions

**File:** `scrapers/crawler.py` — `fetch_cities_from_wikipedia()` and `fetch_cities_via_wikipedia_search()`

**Problem:** Both functions contain identical ~40-line blocks for:
1. Parsing HTML wikitable rows
2. Identifying the city column via header text
3. Filtering via blacklist_terms
4. Returning a list of unique city names

This ~80 lines of duplicated logic means any bug fix or improvement must be applied in two places.

**Fix:** Extract a shared `_parse_wikitable_cities(html_content: str, max_cities: int) -> List[str]` helper and call it from both functions.

---

## CQ-002 — Bare `except:` Clauses Throughout Scraper

**File:** `scrapers/crawler.py` — multiple locations

**Problem:**
```python
try:
    phone = clean_text(page.locator('button[data-item-id*="phone"]').first.inner_text(timeout=8000))
except:
    phone = ""

try:
    address = clean_text(page.locator('button[data-item-id="address"]').first.inner_text(timeout=8000))
except:
    address = ""
```

Using bare `except:` (without an exception type) catches **everything** including:
- `KeyboardInterrupt` (can't Ctrl+C out of a stuck scrape)
- `SystemExit` (can't stop the process cleanly)
- `MemoryError` (hides OOM conditions)
- `playwright._impl._errors.TargetClosedError` (hides browser crashes)

**Fix:** Replace with specific exception types:
```python
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
try:
    phone = clean_text(page.locator(...).first.inner_text(timeout=8000))
except (PlaywrightTimeoutError, Exception) as e:
    phone = ""
    _log_field_miss("phone", str(e))
```

---

## CQ-003 — `_run_history` Is Never Bounded (Memory Leak Risk)

**File:** `dashboard/scraper_service.py` (line 55)

**Problem:**
```python
_run_history: List[Dict[str, Any]] = []
```

Every call to `start_scrape()` appends a new entry to `_run_history`. This list lives in memory for the lifetime of the FastAPI process. After 1000 scrape runs, it contains 1000 entries of run metadata.

While each entry is small, there's no eviction policy. A long-running production server accumulates unbounded history.

**Fix:** Use `collections.deque(maxlen=50)` for `_run_history`.

---

## CQ-004 — Magic Numbers Without Constants

**Files:** Multiple

**Examples:**
```python
# crawler.py
time.sleep(2 if is_quick else 3)       # What does 2 or 3 mean?
max_scrolls = 2 if is_quick else 80    # Why 80?
same_count >= 6                         # Why 6?
timeout=8000                            # Why 8000ms and not 10000?
timeout=45000                           # Why 45000?

# lead_cleaner.py
score = phone*20 + website*20 + email*40 + instagram*10 + facebook*5 + linkedin*5

# scraper_service.py
MAX_LOG_LINES = 100                     # This one IS a constant — good!
```

**Fix:** Define all magic numbers as named constants in `config/constants.py`:
```python
SCROLL_DELAY_SECONDS = 3
QUICK_SCROLL_DELAY_SECONDS = 2
MAX_FEED_SCROLLS = 80
SCROLL_STALL_THRESHOLD = 6
PLAYWRIGHT_ELEMENT_TIMEOUT_MS = 8000
PLAYWRIGHT_PAGE_TIMEOUT_MS = 45000

SCORE_PHONE = 20
SCORE_WEBSITE = 20
SCORE_EMAIL = 40
SCORE_INSTAGRAM = 10
SCORE_FACEBOOK = 5
SCORE_LINKEDIN = 5
```

---

## CQ-005 — `import re as _re` At Module Level In Middle Of File

**File:** `dashboard/dashboard_service.py` (line 597)

**Problem:** Python convention requires all imports at the top of the file. Having `import re as _re` appear at line 597 (after hundreds of lines of function definitions) violates PEP 8 and confuses code analysis tools (pylint, pyright).

**Fix:** Move all imports to the top of the file.

---

## CQ-006 — Large Monolithic Files With Mixed Responsibilities

| File | Lines | Issues |
|------|-------|--------|
| `scrapers/crawler.py` | 958 | City discovery + browser management + scraping + data extraction + file I/O all in one file |
| `dashboard/dashboard_service.py` | 1110 | CSV loading + filtering + pagination + exports + CRM transformation + verified leads + startup classification all in one file |
| `dashboard/app.py` | 648 | Routes + auth + token management + filename generation + export logic all in one file |

**Recommended Split:**
- `crawler.py` → `city_discovery.py` + `browser_manager.py` + `business_scraper.py` + `website_crawler.py`
- `dashboard_service.py` → `data_loader.py` + `filters.py` + `exports.py` + `crm_transformer.py`
- `app.py` → `routes/auth.py` + `routes/leads.py` + `routes/exports.py` + `routes/scraper.py` + `auth_middleware.py`

---

## CQ-007 — Type Annotations Are Inconsistent

**Files:** All Python files

**Problem:** Some functions have full type annotations, others have none:
```python
# Good (dashboard_service.py):
def apply_filters(df: pd.DataFrame, search: Optional[str] = None, ...) -> pd.DataFrame:

# Missing (crawler.py):
def scrape_business(link, p, browser, page):  # No types!
def scrape_city(business_type, city, p, browser, page):  # No types!
def extract_socials_and_email(url):  # No types!
```

**Fix:** Add type annotations to all public functions in `crawler.py`. Use `playwright.sync_api.Browser`, `playwright.sync_api.Page`, `playwright.sync_api.Playwright` as types.

---

## CQ-008 — No Unit Tests

**Files:** Entire codebase

**Problem:** There are zero test files. The entire system is tested only via manual runs. This means:
1. No regression detection — a code change could break scoring, filtering, or exports silently
2. No way to test the scraper logic without running Playwright
3. No way to validate the email/phone normalization logic
4. No CI/CD pipeline integration possible

**Recommended Test Coverage:**
```
tests/
  test_email_validation.py    — test is_quality_email() with edge cases
  test_phone_normalization.py — test _normalise_phone() for each country code
  test_lead_scoring.py        — test score calculation for all combinations
  test_filters.py             — test apply_filters() with real DataFrames
  test_crm_export.py          — test _build_crm_export_dataframe() output schema
  test_city_parser.py         — test _parse_wikitable_cities() with mock HTML
  test_auth.py                — test create/verify session tokens, bypass attempts
```

---

## CQ-009 — `website_scraper.py` Uses Generic User-Agent (Detection Risk)

**File:** `scrapers/website_scraper.py` (line 20)

**Problem:**
```python
headers = {"User-Agent": "Mozilla/5.0"}
```

This is the most obviously automated user-agent string possible. Many websites that check user-agents will block or return garbage HTML for this string.

(Note: This file is dead code — see BUG-006 — but if it were ever activated, it would immediately trigger blocks.)

---

## Code Quality Score by File

| File | Type Safety | Error Handling | Test Coverage | Docs | Overall |
|------|------------|----------------|---------------|------|---------|
| crawler.py | C (no types) | D (bare except) | F (0%) | B | D+ |
| dashboard_service.py | B (mostly typed) | B (defensive) | F (0%) | A | C+ |
| app.py | B (FastAPI types) | C (some gaps) | F (0%) | B | C |
| lead_cleaner.py | C (no types) | B (try/except) | F (0%) | C | C- |
| scraper_service.py | C (partial types) | B (locked) | F (0%) | B | C |
| database/auth_db.py | B (typed) | B (defensive) | F (0%) | B | C+ |
