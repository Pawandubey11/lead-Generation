# AUDIT REPORT 6: SECURITY REVIEW

## Status: CRITICAL SECURITY GAPS — NOT PRODUCTION READY

---

## SEC-001 — Authentication Is Optional (Auth Bypass by Design)

**File:** `dashboard/app.py` — `get_current_user_id()` (lines 86-91)

**Severity: CRITICAL**

```python
def get_current_user_id(request: Request) -> int:
    token = request.cookies.get("session_token")
    user_id = verify_session_token(token) if token else None
    if not user_id:
        # Returns first user if no token — ANYONE gets access!
        conn = db.get_db_connection()
        user = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        conn.close()
        return user["id"] if user else 1
    return user_id
```

**Attack Scenario:** An external attacker visits `http://yourserver:8000/api/leads` without any cookie and gets full access to all business leads, emails, and phone numbers.

**Fix:**
```python
def get_current_user_id(request: Request) -> int:
    token = request.cookies.get("session_token")
    user_id = verify_session_token(token) if token else None
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in."
        )
    return user_id
```

---

## SEC-002 — Default Secret Key Is Hardcoded in Source

**File:** `dashboard/app.py` (line 65)

**Severity: HIGH**

```python
SECRET_KEY = os.environ.get(
    "LEADPULSE_SECRET_KEY",
    "SystemaOpsLeadPulseSuperSecretAuthenticationKey"  # Hardcoded fallback!
)
```

Since this code is likely in a repository, the default key is public knowledge. An attacker can:
1. Know the key: `SystemaOpsLeadPulseSuperSecretAuthenticationKey`
2. Forge a valid HMAC-SHA256 token for any `user_id`
3. Set the `session_token` cookie with the forged token
4. Get authenticated access to any user's account

The `.env` file shows `LEADPULSE_SECRET_KEY=change-this-to-a-random-64-char-string` — meaning the user is expected to change it, but if they forget, the fallback is insecure.

**Fix:**
```python
SECRET_KEY = os.environ.get("LEADPULSE_SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "LEADPULSE_SECRET_KEY environment variable must be set to a random string of at least 32 characters. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
```

---

## SEC-003 — Debug Endpoint Leaks Environment Variables

**File:** `dashboard/app.py` — `/api/debug/files` (lines 544-575)

**Severity: HIGH**

The `/api/debug/files` endpoint is accessible without authentication and returns:
```json
{
    "env": {
        "LEADPULSE_SECRET_KEY": "...",
        "GOOGLE_COOKIES_PATH": "/app/config/google_cookies.json",
        "LEADS_CSV_PATH": "/app/output/final_ai_leads.csv"
    },
    "files": {
        "final_ai_leads.csv": {
            "preview": "business_name,phone,website,address...<first 1000 chars of lead data>"
        }
    }
}
```

This leaks the secret key (allowing token forgery), file system paths, and partial lead data.

**Fix:** Remove endpoint entirely from production build, or protect with IP whitelist + admin role.

---

## SEC-004 — No CSRF Protection

**File:** `dashboard/app.py`

**Severity: MEDIUM**

The API uses cookie-based session authentication with `SameSite=lax`. While `lax` prevents most CSRF attacks for `POST` from other origins, it does NOT prevent:
- Cross-origin GET requests (which are used for exports and data reads)
- Same-site CSRF (if the server hosts multiple apps)

No CSRF token is implemented.

**Fix:** Add `SameSite=strict` for sensitive actions, or implement CSRF token validation for state-changing POST endpoints.

---

## SEC-005 — No Brute Force Protection on Login

**File:** `dashboard/app.py` — `/api/auth/login` (lines 165-179)

**Severity: MEDIUM**

The login endpoint has no rate limiting, lockout, or captcha:
```python
@app.post("/api/auth/login")
def api_login(req: AuthRequest, response: Response):
    user = db.verify_user(req.email, req.password)
    if not user:
        return {"success": False, "message": "Invalid email or password."}
```

An attacker can send unlimited login attempts to brute-force passwords.

**Fix:** Implement account lockout after 5 failed attempts (15-minute lockout), or add `slowapi` rate limiting.

---

## SEC-006 — Google Cookies File Contains Sensitive Authentication Tokens

**File:** `config/google_cookies.json`

**Severity: MEDIUM**

The `google_cookies.json` file contains Google authentication cookies that allow the browser to bypass consent walls. If this file is:
- Committed to a git repository
- Accessible via the debug endpoint (SEC-003)
- Shared without redaction

It exposes Google session tokens that could be used to impersonate the cookie owner's Google account.

**Fix:**
1. Add `config/google_cookies.json` to `.gitignore`
2. Ensure the debug endpoint doesn't serve this file
3. Document clearly that this file must NEVER be shared

---

## SEC-007 — SQL Injection Risk in Auth DB (Low Probability)

**File:** `database/auth_db.py`

**Severity: LOW**

The auth database uses parameterized queries throughout, which prevents SQL injection. However, the raw SQL `SELECT id FROM users ORDER BY id ASC LIMIT 1` in `app.py` (line 89) constructs no user input, so it's safe.

The main risk is that future developers might copy the pattern and interpolate strings.

**Recommendation:** Use an ORM (SQLAlchemy) rather than raw SQLite to enforce safe query practices.

---

## SEC-008 — HTTPS Not Enforced

**File:** `dashboard/app.py`, `docker-compose.yml`

**Severity: MEDIUM**

The application runs on plain HTTP (port 8000). Session cookies transmitted over HTTP can be intercepted via:
- Network eavesdropping (café WiFi, ISP)
- Man-in-the-middle attacks

The `HttpOnly=True` cookie flag is set (good), but `Secure=False` means cookies are transmitted over HTTP.

**Fix:** Deploy behind a TLS-terminating reverse proxy (Nginx/Traefik), set `Secure=True` on cookies, enforce HTTPS redirect.

---

## SEC-009 — Playwright Runs with `--no-sandbox` (Browser Sandbox Disabled)

**File:** `scrapers/crawler.py` — `launch_browser()` (line 441)

**Severity: LOW (acceptable in controlled environment)**

```python
browser = p.chromium.launch(
    headless=True,
    args=["--no-sandbox", "--disable-setuid-sandbox", ...]
)
```

`--no-sandbox` is required in Docker containers (Linux) where user namespaces aren't available. However, if the browser is somehow exploited (e.g., via a malicious website during scraping), the entire container is compromised with no browser sandbox protection.

**Mitigation (not fix):** Use Docker's `--cap-drop` and `seccomp` profiles to limit container syscalls even if sandbox is disabled.

---

## Security Risk Matrix

| ID | Description | Severity | Exploitability | Effort to Fix |
|----|-------------|----------|---------------|--------------|
| SEC-001 | Auth bypass — anyone gets user 1's data | CRITICAL | Very Easy | Low |
| SEC-002 | Hardcoded default secret key | HIGH | Easy (key is in source) | Low |
| SEC-003 | Debug endpoint leaks env vars + lead data | HIGH | Easy (no auth) | Low |
| SEC-004 | No CSRF protection | MEDIUM | Moderate | Medium |
| SEC-005 | No login rate limiting / brute force | MEDIUM | Easy | Low |
| SEC-006 | Google cookies in potentially tracked file | MEDIUM | Low (requires access) | Low |
| SEC-007 | SQL injection (future risk, not current) | LOW | Low | Medium |
| SEC-008 | HTTP only, no TLS enforcement | MEDIUM | Moderate | Medium |
| SEC-009 | No-sandbox Chromium | LOW | Very Low | Low |

---

## Immediate Action Items (Fix Before Production)

1. **SEC-001**: Throw 401 from `get_current_user_id()` instead of returning first user
2. **SEC-002**: Fail fast at startup if `LEADPULSE_SECRET_KEY` is not set or too short
3. **SEC-003**: Remove `/api/debug/files` endpoint or add auth + IP restriction
4. **SEC-005**: Add `slowapi` rate limiting to login (5 attempts per 5 minutes)
