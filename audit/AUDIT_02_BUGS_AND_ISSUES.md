# AUDIT REPORT 2: BUG & CRITICAL ISSUE TRACKER

## Status: CRITICAL ISSUES FOUND

---

## BUG-001 — Authentication Bypass (CRITICAL SECURITY)
**File:** `dashboard/app.py` — `get_current_user_id()` (line 86-91)

**Problem:**
```python
def get_current_user_id(request: Request) -> int:
    token = request.cookies.get("session_token")
    user_id = verify_session_token(token) if token else None
    if not user_id:
        # FALLBACK: returns first user in DB if no valid session!
        conn = db.get_db_connection()
        user = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        conn.close()
        return user["id"] if user else 1
    return user_id
```

**Impact:** ANY unauthenticated HTTP request to any protected endpoint gets served as the first registered user. All lead data is accessible without authentication.

**Fix:** Return 401 Unauthorized if no valid session token is present.

---

## BUG-002 — Export Excel Function Broken (SILENT TRUNCATION)
**File:** `dashboard/dashboard_service.py` — `export_excel_bytes()` (lines 925-931)

**Problem:**
```python
def export_excel_bytes(df: pd.DataFrame, verified_only: bool = True) -> bytes:
    export_df = _build_crm_export_dataframe(df, verified_only=verified_only)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="CRM Leads")

        # Auto-fit columns so the exported file looks professional out of the box.
CUSTOM_FIELD_LABEL_MAP = {   # <-- THIS IS A BUG: code at module level inside with block!
```

**Impact:** The `with pd.ExcelWriter...` block is never closed properly because the `buf.seek(0)` and `return buf.getvalue()` are MISSING from `export_excel_bytes()`. The function returns nothing (implicit None). Every Excel export via `/api/export/excel` fails silently and returns empty bytes.

**Fix:** Complete the function with column auto-fitting and return statement:
```python
def export_excel_bytes(df: pd.DataFrame, verified_only: bool = True) -> bytes:
    export_df = _build_crm_export_dataframe(df, verified_only=verified_only)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="CRM Leads")
        worksheet = writer.sheets["CRM Leads"]
        for i, col in enumerate(export_df.columns, start=1):
            max_len = max([len(str(col))] + [len(str(v)) for v in export_df.iloc[:, i - 1].astype(str)])
            worksheet.column_dimensions[worksheet.cell(row=1, column=i).column_letter].width = min(max(max_len + 3, 12), 55)
    buf.seek(0)
    return buf.getvalue()
```

---

## BUG-003 — scraper_service.py Missing Import (NameError at startup)
**File:** `dashboard/scraper_service.py` — line 55

**Problem:**
```python
_run_history: List[Dict[str, Any]] = []  # List is used but not imported from typing
```
`List` and `Dict` are referenced in the type annotation but `from typing import ...` only imports `Any, Dict, Optional`. `List` is missing.

**Impact:** `NameError: name 'List' is not defined` at module import time, crashing the entire dashboard on startup.

**Fix:** Add `List` to the import: `from typing import Any, Dict, List, Optional`

---

## BUG-004 — Progress File Not Cleared On Scraper Cancel
**File:** `scrapers/crawler.py` — `generate_leads()` (line 905-915)

**Problem:** The `progress.txt` file is only removed on successful completion:
```python
# Clear progress file on success
if os.path.exists(progress_file):
    os.remove(progress_file)
```
But on `ScrapeCancelled` or any exception, the file is NOT removed. The next scrape run will then skip already-completed cities from the cancelled run, even if the user intended a fresh run.

**Fix:** Also clear `progress.txt` in the `scraper_service._scrape_worker()` before starting, which it already does (line 196-201). This is a partial fix. The real fix is to also clear it in the `finally:` block of `generate_leads()`.

---

## BUG-005 — lead_cleaner.py Uses `hmac.new()` (AttributeError)
**File:** `dashboard/app.py` — `create_session_token()` (line 71)

**Problem:**
```python
signature = hmac.new(SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
```
Python's `hmac` module uses `hmac.new()` which is correct, but the SECRET_KEY default is a plain string — if `LEADPULSE_SECRET_KEY` env var is not set, the app uses `"SystemaOpsLeadPulseSuperSecretAuthenticationKey"` which is a known/public string in the codebase.

**Impact:** Any attacker who reads this source code can forge session tokens for any user_id.

**Fix:** Require the env var to be set, fail loudly at startup if missing.

---

## BUG-006 — website_scraper.py and email_extractor.py Are Dead Code
**Files:** `scrapers/website_scraper.py`, `scrapers/email_extractor.py`

**Problem:** These files exist but are **never imported or called** anywhere in the active codebase. `crawler.py` has its own inline `extract_socials_and_email()` function (lines 544-582) which duplicates but supersedes these modules.

**Impact:** Maintenance confusion. Any fixes made to `website_scraper.py` have zero effect on actual scraping behavior.

**Fix:** Delete both files or formally replace crawler's inline function with a proper import from these modules.

---

## BUG-007 — Race Condition in CSV Cache Under Concurrent Requests
**File:** `dashboard/dashboard_service.py` — `load_leads()` (lines 172-239)

**Problem:** The mtime check and cache read are NOT atomic:
```python
current_mtime = _csv_mtime()         # read mtime (outside lock)
with _cache_lock:
    if _cached_df is not None and current_mtime == _cached_mtime:
        return _cached_df.copy()      # cache hit (inside lock)
# between here...
df = pd.read_csv(CSV_PATH)           # slow disk read (no lock!)
# ...and here, another thread could also be doing pd.read_csv()
with _cache_lock:
    _cached_df = df                   # write cache (inside lock)
```
Two concurrent requests arriving simultaneously can both trigger a full CSV re-read.

**Impact:** Minor performance issue, not data corruption (pandas read is idempotent). But under heavy traffic it wastes CPU.

---

## BUG-008 — `_save_debug_artifacts` Calls `page.screenshot()` Without Checking If Browser Is Connected
**File:** `scrapers/crawler.py` — `_save_debug_artifacts()` (lines 497-512)

**Problem:** This function is called after navigation failures, but at that point the browser or page may already be closed/crashed. The `page.screenshot()` call will itself throw an exception which is caught and suppressed — but this means debug screenshots are silently never saved when they're most needed.

---

## BUG-009 — `export_excel_bytes` Called with `None` df Will Crash
**File:** `dashboard/app.py` — `export_excel()` (line 282)

**Problem:**
```python
df = svc.get_filtered_leads(...)
if df is None:
    import pandas as pd
    df = pd.DataFrame(columns=svc.CRM_EXPORT_COLUMNS)  # CRM_EXPORT_COLUMNS is a list of human names
                                                         # but get_filtered_leads returns internal names!
content = svc.export_excel_bytes(df, ...)
```
When `df` is None (no leads), a DataFrame with CRM column names (like "External ID", "Company Name") is created, but `export_excel_bytes` → `_build_crm_export_dataframe()` tries to access `df["business_name"]`, `df["email"]`, etc., causing `KeyError`.

---

## BUG-010 — Google Maps Scraper URL Uses Hardcoded Indian Geolocation
**File:** `scrapers/crawler.py` — `new_context()` (line 455)

**Problem:**
```python
context = browser.new_context(
    locale="en-IN",
    timezone_id="Asia/Kolkata",
    geolocation={"latitude": 20.5937, "longitude": 78.9629},  # India center
    ...
    extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
)
```
And the search URL also uses `?hl=en&gl=in` (India country code). When scraping Germany or USA businesses, Google Maps returns results biased toward the Indian locale, potentially missing local businesses or returning wrong listings.

**Fix:** Accept locale/geolocation as parameters, or at minimum use `gl=de` for Germany and `gl=us` for USA.

---

## Summary Table

| ID | Severity | File | Description |
|----|----------|------|-------------|
| BUG-001 | CRITICAL | app.py | Auth bypass — unauthenticated access returns first user's data |
| BUG-002 | CRITICAL | dashboard_service.py | export_excel_bytes() is broken — missing return value |
| BUG-003 | CRITICAL | scraper_service.py | Missing `List` import causes NameError crash on startup |
| BUG-004 | HIGH | crawler.py | Progress file not cleared on cancel → skips cities on next run |
| BUG-005 | HIGH | app.py | Default SECRET_KEY is hardcoded in public source → token forgery |
| BUG-006 | MEDIUM | website_scraper.py, email_extractor.py | Dead code — never imported, fixes have no effect |
| BUG-007 | LOW | dashboard_service.py | Race condition in CSV cache (cosmetic, not data-corrupting) |
| BUG-008 | LOW | crawler.py | Debug screenshots silently fail when most needed |
| BUG-009 | MEDIUM | app.py | Empty DataFrame fallback uses wrong column schema → KeyError |
| BUG-010 | MEDIUM | crawler.py | Hardcoded India geolocation biases results for non-India scrapes |
