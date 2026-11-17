# AUDIT REPORT 5: DASHBOARD & API REVIEW

## Status: FUNCTIONAL WITH NOTABLE GAPS

---

## Overview

The dashboard is a FastAPI-powered single-page application with a vanilla HTML/CSS/JS frontend. It provides lead viewing, filtering, scraper control, and CSV/Excel export. This report covers API design, frontend behavior, UX gaps, and security issues.

---

## API-001 — `/api/leads` Page Size Limit Is Dangerously High

**File:** `dashboard/app.py` (line 243)

**Problem:**
```python
page_size: Optional[int] = Query(100, ge=1, le=5000),
```

Allowing page_size up to 5000 means a single request can serialize and transmit up to 5000 lead records as JSON. For large datasets (10k+ leads), this can produce multi-MB JSON responses that:
- Saturate server memory (pandas DataFrame → Python dicts → JSON serialization all in-memory)
- Cause browser to freeze rendering a 5000-row table
- Hit FastAPI/uvicorn response timeout limits

The frontend (`dashboard.js` line 149) calls: `fetch('/api/leads?page=1&page_size=2000')` — loading ALL leads at once into the browser's JavaScript state.

**Fix:** Cap at 500. Implement virtual scrolling or server-side pagination in the frontend.

---

## API-002 — No Rate Limiting on Any Endpoint

**File:** `dashboard/app.py`

**Problem:** All endpoints — especially `/api/scrape/start` and `/api/export/csv` — have zero rate limiting. Anyone who can reach the server can:
1. Start unlimited concurrent scrape jobs (rejected by `already_running` check, but only one at a time)
2. Download the entire lead database as CSV/Excel without authentication (due to BUG-001)
3. Spam `/api/leads` with 5000-row requests

**Fix:** Add `slowapi` rate limiter middleware:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/api/export/csv")
@limiter.limit("10/minute")
def export_csv(...): ...
```

---

## API-003 — Debug Endpoint Exposes Sensitive Data

**File:** `dashboard/app.py` — `/api/debug/files` (lines 544-575)

**Problem:**
```python
@app.get("/api/debug/files")
def debug_files():
    return {
        "cwd": os.getcwd(),
        "env": {k: v for k, v in os.environ.items() if "LEAD" in k or "COOKIE" in k},
        "files": files_info  # includes first 1000 chars of every CSV!
    }
```

This endpoint:
1. Is unprotected (no auth dependency)
2. Returns environment variables containing `LEADPULSE_SECRET_KEY`, `LEADS_CSV_PATH`, `GOOGLE_COOKIES_PATH`
3. Returns previews of CSV data (up to 1000 chars per file = business names, emails, phones)

**Fix:** Remove this endpoint in production, or at minimum add auth + restrict to admin users.

---

## API-004 — `/api/export/latest/csv` and `/api/export/latest/excel` Are Hardcoded

**File:** `dashboard/app.py` (lines 526-545)

**Problem:**
```python
file_path = os.path.join(output_dir, "germany_automotive_leads_latest.csv")
```

These endpoints return a hardcoded file name (`germany_automotive_leads_latest.csv`) that may not exist. The file is never created by any other part of the application, making these endpoints permanently broken with 404.

**Fix:** Remove these endpoints or replace with dynamic latest-export generation.

---

## API-005 — CORS Not Configured

**File:** `dashboard/app.py`

**Problem:** No CORS headers are set. While this doesn't matter for same-origin browser requests, it means:
1. Any third-party integration (Zapier, Make.com, N8N webhook caller) cannot call the API from browser
2. No protection against CSRF (the session cookie uses `Samesite=lax` only)

**Fix:** Add `CORSMiddleware` with explicit allowed origins.

---

## FE-001 — Frontend Loads All 2000 Leads Into Memory At Once

**File:** `dashboard/static/js/dashboard.js` (line 149)

**Problem:**
```javascript
const res = await fetch('/api/leads?page=1&page_size=2000');
state.leads = data.data || data.leads || [];
```

All filtering is then done client-side in JavaScript (`applyLocalFilter()`). This means:
1. 2000 leads × (average 15 fields each) = large in-memory JS array
2. All filter operations (city, country, industry, search) run client-side on this array
3. Any lead added after the initial load is NOT visible until `reloadLeads()` is manually clicked

**Impact:** With large datasets (5000+ leads), the initial load will be slow and table rendering will freeze the browser tab.

**Fix:** Use server-side filtering via `/api/leads` with debounced search, switching to true pagination rather than loading everything upfront.

---

## FE-002 — Scraper Status Polling Every 1 Second (Excessive)

**File:** `dashboard/static/js/dashboard.js` (line 530)

**Problem:**
```javascript
state.scraper.pollingInterval = setInterval(checkScraperStatus, 1000);
```

Polling every 1 second means 60 HTTP requests per minute to `/api/scrape/status`. During a multi-hour batch run, this generates thousands of unnecessary requests.

**Fix:** Use 5-second polling or implement Server-Sent Events (SSE) for real-time push updates.

---

## FE-003 — Export Uses `window.location.href` (No Error Feedback)

**File:** `dashboard/static/js/dashboard.js` (line 584)

**Problem:**
```javascript
function exportData(format) {
    const url = `/api/export/custom?format=${format}&...`;
    showToast(`Downloading ${format.toUpperCase()} export...`);
    window.location.href = url;  // Browser redirect — no error handling!
}
```

If the export endpoint returns an error (e.g., the broken `export_excel_bytes()` from BUG-002), the browser either shows an error page or silently downloads an empty/corrupt file. The user sees no feedback.

**Fix:** Use `fetch()` with explicit error handling, or check the HTTP response status before triggering download.

---

## FE-004 — Verification Logic Is Inconsistent Between Frontend and Backend

**File:** `dashboard/static/js/dashboard.js` (line 164-170)

**Problem:**
```javascript
function isLeadVerified(lead) {
    const hasValidEmail = email.includes('@') && email.includes('.') && ...
    return hasValidEmail || (completeness >= 40 && hasPhone);
}
```

Backend (`dashboard_service.py` line 787-803) uses:
```python
has_email_mask = email_col.str.strip().str.match(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
high_completeness_mask = completeness >= 50
verified_mask = has_email_mask | (high_completeness_mask & has_phone_mask)
```

Differences:
- Frontend: completeness threshold = **40**, Backend: completeness threshold = **50**
- Frontend: simple `includes('@')` check, Backend: proper regex
- Result: leads shown as "Verified" in the UI may NOT be included in the backend's verified export

**Fix:** Standardize on one definition in a shared constant. Use 50% completeness with RFC5322 email check consistently everywhere.

---

## API Endpoint Coverage Summary

| Endpoint | Auth? | Rate Limit? | Tested? |
|----------|-------|-------------|---------|
| GET /api/leads | Soft (fallback to user 1) | No | Likely yes |
| GET /api/export/csv | No auth | No | Likely yes |
| GET /api/export/excel | No auth | No | Broken (BUG-002) |
| GET /api/export/custom | No auth | No | Likely yes |
| POST /api/scrape/start | Soft auth | No | Likely yes |
| GET /api/scrape/status | No auth | No | Likely yes |
| GET /api/debug/files | No auth! | No | Security risk |
| GET /api/export/latest/* | No auth | No | 404 always |
| GET /api/health | No auth | No | Fine (health check) |
| GET /api/stats | Soft auth | No | Likely yes |
| GET /api/charts | Soft auth | No | Likely yes |
| POST /api/auth/login | No auth | No (brute force risk) | Likely yes |
