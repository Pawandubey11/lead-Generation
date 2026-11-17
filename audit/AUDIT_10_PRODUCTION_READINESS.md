# AUDIT REPORT 10: PRODUCTION READINESS SCORECARD & REMEDIATION ROADMAP

## Overall Production Readiness: 42/100 — NOT PRODUCTION READY

---

## Scorecard Summary

| Category | Score | Max | Grade |
|----------|-------|-----|-------|
| Functionality | 7 | 10 | C+ |
| Security | 2 | 15 | F |
| Data Quality | 5 | 15 | D |
| Performance | 5 | 10 | C |
| Reliability | 4 | 10 | D+ |
| Code Quality | 6 | 10 | C |
| API Design | 5 | 10 | C |
| Infrastructure | 4 | 10 | D+ |
| Documentation | 4 | 10 | C- |
| **TOTAL** | **42** | **100** | **D+** |

---

## Critical Blockers (Must Fix Before Any Production Use)

### 1. BROKEN: Excel Export Returns Nothing (BUG-002)
- **File:** `dashboard/dashboard_service.py` — `export_excel_bytes()` (line 925)
- **Status:** Function body is incomplete — `buf.seek(0)` and `return` are missing
- **Fix Time:** 5 minutes

### 2. CRASH: Missing `List` Import Breaks Dashboard Startup (BUG-003)
- **File:** `dashboard/scraper_service.py` — line 55
- **Status:** `NameError: name 'List' is not defined` on startup
- **Fix Time:** 1 minute

### 3. SECURITY: Authentication Bypass (SEC-001 / BUG-001)
- **File:** `dashboard/app.py` — `get_current_user_id()` (line 86)
- **Status:** Any HTTP request returns all data as "first user" without credentials
- **Fix Time:** 5 minutes

### 4. SECURITY: Hardcoded Default Secret Key (SEC-002)
- **File:** `dashboard/app.py` — line 65
- **Status:** Default key is in public source code → token forgery possible
- **Fix Time:** 10 minutes

### 5. SECURITY: Debug Endpoint Leaks Env Vars (SEC-003)
- **File:** `dashboard/app.py` — `/api/debug/files` (line 544)
- **Status:** Unauthenticated access to `LEADPULSE_SECRET_KEY`, CSV data
- **Fix Time:** 2 minutes (remove endpoint)

---

## Remediation Roadmap

### Phase 1 — Critical Fixes (Target: 1-2 hours)

| ID | Fix | File | Lines Changed |
|----|-----|------|--------------|
| BUG-002 | Complete `export_excel_bytes()` with return value | dashboard_service.py | +6 |
| BUG-003 | Add `List` to scraper_service imports | scraper_service.py | +1 |
| SEC-001 | Raise 401 instead of fallback user in `get_current_user_id()` | app.py | -6, +3 |
| SEC-002 | Fail fast if SECRET_KEY missing/short at startup | app.py | +6 |
| SEC-003 | Remove `/api/debug/files` endpoint | app.py | -32 |
| BUG-010 | Parameterize locale/country for browser context | crawler.py | +8 |

**Expected Score After Phase 1: 58/100**

---

### Phase 2 — High-Impact Improvements (Target: 1-2 days)

| ID | Fix | Effort | Impact |
|----|-----|--------|--------|
| DQ-001 | Improve email validation with blacklist + quality scoring | 2h | Very High |
| DQ-002 | Phone number E.164 normalization during scraping | 2h | High |
| DQ-003 | Cross-spin deduplication in lead_cleaner.py | 1h | High |
| PERF-002 | Concurrent website crawling with ThreadPoolExecutor | 4h | High (40% faster) |
| PERF-003 | Adaptive scroll timing (reduce 3s→1.5s, early exit at 3 same) | 1h | Medium |
| API-001 | Lower page_size cap to 500, server-side pagination in frontend | 3h | Medium |
| SEC-005 | Add slowapi login rate limiting | 1h | Medium |
| INFRA-003 | Atomic CSV writes using temp file + os.replace() | 1h | Medium |
| DQ-005 | Validate social media URLs against profile URL patterns | 2h | Medium |
| DQ-006 | Per-business scraped_at timestamps | 30m | Low |

**Expected Score After Phase 2: 72/100**

---

### Phase 3 — Production Hardening (Target: 1-2 weeks)

| ID | Fix | Effort | Impact |
|----|-----|--------|--------|
| PERF-001 | Async Playwright with 3 concurrent pages | 2 days | Very High |
| CQ-001 | Refactor duplicate Wikipedia parsing logic | 4h | Medium |
| CQ-003 | Bound `_run_history` with deque(maxlen=50) | 30m | Low |
| CQ-006 | Split large files into focused modules | 3 days | High (maintainability) |
| CQ-008 | Add unit test suite (email, scoring, filters, auth) | 3 days | High |
| INFRA-006 | Replace print() with structured logging | 1 day | Medium |
| INFRA-007 | Startup config validation | 2h | Medium |
| SEC-004 | CSRF protection on state-changing endpoints | 2h | Medium |
| REL-001 | Retry logic for Wikipedia API | 1h | Low |
| REL-002 | Random jitter on delays, CAPTCHA detection | 4h | High |
| API-OPP-001 | ZeroBounce email verification integration | 4h | Very High |
| FE-001 | Server-side pagination in dashboard (not all-at-once) | 1 day | High |
| FE-002 | Reduce polling to 5s or implement SSE | 2h | Low |

**Expected Score After Phase 3: 88/100**

---

### Phase 4 — Feature Enhancements (Optional, Post-Hardening)

| Enhancement | Business Value | Complexity |
|-------------|---------------|------------|
| Apollo.io contact enrichment | Very High | Medium |
| HubSpot/Pipedrive CRM push | High | Medium |
| Google Places API (replace Maps scraping) | Very High | High |
| Proxy rotation support | High | Medium |
| Email campaign generation (AI) | High | High |
| Multi-user support (proper RBAC) | Medium | High |
| Scheduled batch runs (cron integration) | Medium | Low |
| Webhook retry queue | Medium | Low |
| Lead aging/freshness scoring | Medium | Medium |
| Country-specific geo-biasing | Medium | Low |

---

## Quick Win Implementation Guide

### Fix 1: `export_excel_bytes()` (5 min)

```python
# dashboard/dashboard_service.py — replace broken function:
def export_excel_bytes(df: pd.DataFrame, verified_only: bool = True) -> bytes:
    export_df = _build_crm_export_dataframe(df, verified_only=verified_only)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="CRM Leads")
        worksheet = writer.sheets["CRM Leads"]
        for i, col in enumerate(export_df.columns, start=1):
            max_len = max(
                [len(str(col))] +
                [len(str(v)) for v in export_df.iloc[:, i - 1].astype(str)]
            )
            worksheet.column_dimensions[
                worksheet.cell(row=1, column=i).column_letter
            ].width = min(max(max_len + 3, 12), 55)
    buf.seek(0)
    return buf.getvalue()
```

### Fix 2: Missing `List` Import (1 min)

```python
# dashboard/scraper_service.py — line 25:
from typing import Any, Dict, List, Optional  # Add List
```

### Fix 3: Auth Bypass (5 min)

```python
# dashboard/app.py — replace get_current_user_id():
def get_current_user_id(request: Request) -> int:
    token = request.cookies.get("session_token")
    user_id = verify_session_token(token) if token else None
    if not user_id:
        # Auto-create/return first user in development mode only
        dev_mode = os.environ.get("LEADPULSE_DEV_MODE", "false").lower() == "true"
        if dev_mode:
            conn = db.get_db_connection()
            user = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
            conn.close()
            return user["id"] if user else 1
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in."
        )
    return user_id
```

### Fix 4: Hardcoded Secret Key (10 min)

```python
# dashboard/app.py — replace SECRET_KEY assignment:
SECRET_KEY = os.environ.get("LEADPULSE_SECRET_KEY", "")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    import secrets
    if os.environ.get("LEADPULSE_DEV_MODE", "false").lower() == "true":
        # In dev mode, auto-generate and warn
        SECRET_KEY = secrets.token_hex(32)
        import logging
        logging.warning(
            "SECURITY WARNING: LEADPULSE_SECRET_KEY not set. Using auto-generated key. "
            "Sessions will not persist across restarts. "
            "Set LEADPULSE_SECRET_KEY in .env for production."
        )
    else:
        raise RuntimeError(
            "LEADPULSE_SECRET_KEY environment variable must be set to a random string "
            "of at least 32 characters.\n"
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "Then add it to your .env file: LEADPULSE_SECRET_KEY=<generated_value>"
        )
```

### Fix 5: Remove Debug Endpoint (2 min)

```python
# dashboard/app.py — delete the entire /api/debug/files route (lines 544-575)
# Or add auth protection:
@app.get("/api/debug/files")
def debug_files(user_id: int = Depends(get_current_user_id)):
    # ... existing code (but restrict env var leakage)
    return {"cwd": os.getcwd(), "files": files_info}  # Remove env from response
```

---

## Files That Need Changes (Prioritized)

| Priority | File | Changes Needed | Risk |
|----------|------|---------------|------|
| 1 | `dashboard/scraper_service.py` | Add `List` to imports | Zero risk |
| 1 | `dashboard/dashboard_service.py` | Fix `export_excel_bytes()` | Zero risk |
| 1 | `dashboard/app.py` | Fix auth, secret key, remove debug endpoint | Low risk |
| 2 | `scrapers/crawler.py` | Parameterize locale, fix timing, add concurrency | Medium risk |
| 2 | `lead_cleaner.py` | Improve email validation, cross-spin dedup | Low risk |
| 3 | `database/auth_db.py` | Add login attempt tracking | Low risk |
| 3 | `dashboard/static/js/dashboard.js` | Server-side pagination, reduce polling | Medium risk |
| 4 | `config/constants.py` | Extract magic numbers as named constants | Zero risk |
| 4 | `docker-compose.yml` | Health checks, log rotation, reduce shm_size | Zero risk |

---

## Conclusion

The LeadPulse application has solid core architecture — a thoughtful separation between scraper, cleaner, and dashboard; an mtime-based CSV cache; a background threading model for live scraping; and a clean CRM export schema. The bones are good.

However, **three critical production blockers** must be fixed before deployment:
1. The Excel export is broken (zero bytes returned)
2. A missing Python import crashes the dashboard on startup
3. The authentication system is bypassable by design

Additionally, **three security vulnerabilities** must be addressed before exposing the app to any network:
1. Authentication bypass
2. Hardcoded secret key
3. Unauthenticated debug endpoint leaking secrets

Once these 6 issues are resolved (est. 30 minutes total), the application becomes functional and safe enough for private/internal use. The Phase 2 and 3 improvements will bring it to true production quality.
