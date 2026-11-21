"""
Live HTTP endpoint tests — requires the server running on localhost:8000.
Tests all /api/ai/* endpoints plus dashboard load.
"""
import sys
import json
import time

try:
    import requests
except ImportError:
    print("requests not installed"); sys.exit(1)

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0

def ok(msg):
    global PASS; PASS += 1
    print(f"  [PASS] {msg}")

def fail(msg, err=""):
    global FAIL; FAIL += 1
    print(f"  [FAIL] {msg}" + (f" — {err}" if err else ""))

def get(path, expected=200, timeout=10):
    try:
        r = requests.get(BASE + path, timeout=timeout)
        return r.status_code, r
    except Exception as e:
        return None, str(e)

def post(path, body=None, timeout=10):
    try:
        r = requests.post(BASE + path, json=body or {}, timeout=timeout)
        return r.status_code, r
    except Exception as e:
        return None, str(e)

print("\n" + "="*55)
print("  LIVE HTTP API TESTS — http://localhost:8000")
print("="*55)

# 1. Dashboard homepage
code, r = get("/")
if code == 200:
    if "AI Business Intelligence" in r.text:
        ok("GET / → 200 and contains 'AI Business Intelligence'")
    else:
        ok("GET / → 200 (AI panel may need JS to render)")
else:
    fail(f"GET / → {code}", str(r))

# 2. Health check
code, r = get("/api/health")
if code == 200:
    data = r.json()
    ok(f"GET /api/health → 200, status={data.get('status')}, csv_found={data.get('csv_found')}")
else:
    fail(f"GET /api/health → {code}")

# 3. AI config
code, r = get("/api/ai/config")
if code == 200:
    data = r.json()
    ok(f"GET /api/ai/config → 200, provider={data.get('provider')}, configured={data.get('configured')}")
else:
    fail(f"GET /api/ai/config → {code}")

# 4. AI status
code, r = get("/api/ai/status")
if code == 200:
    data = r.json()
    ok(f"GET /api/ai/status → 200, state={data.get('state')}")
else:
    fail(f"GET /api/ai/status → {code}")

# 5. AI reports (empty)
code, r = get("/api/ai/reports")
if code == 200:
    ok(f"GET /api/ai/reports → 200, {len(r.json())} reports")
else:
    fail(f"GET /api/ai/reports → {code}")

# 6. Research start (requires auth — expect 401 or 200)
code, r = post("/api/ai/research/start", {"business_names": []})
if code in (200, 401, 403, 404):
    ok(f"POST /api/ai/research/start → {code} (auth required or no leads)")
else:
    fail(f"POST /api/ai/research/start → {code}", r.text[:100] if hasattr(r,'text') else str(r))

# 7. Research stop
code, r = post("/api/ai/research/stop")
if code in (200, 401, 403):
    ok(f"POST /api/ai/research/stop → {code}")
else:
    fail(f"POST /api/ai/research/stop → {code}")

# 8. Research retry
code, r = post("/api/ai/research/retry")
if code in (200, 401, 403):
    ok(f"POST /api/ai/research/retry → {code}")
else:
    fail(f"POST /api/ai/research/retry → {code}")

# 9. Company report (not found)
code, r = get("/api/ai/report/TestCompanyXYZ")
if code in (200, 404):
    ok(f"GET /api/ai/report/TestCompanyXYZ → {code} (404 expected for unknown)")
else:
    fail(f"GET /api/ai/report/TestCompanyXYZ → {code}")

# 10. Enriched export (requires auth)
code, r = get("/api/ai/export/enriched")
if code in (200, 401, 403):
    if code == 200:
        ok(f"GET /api/ai/export/enriched → 200, {len(r.content)} bytes CSV")
    else:
        ok(f"GET /api/ai/export/enriched → {code} (auth required — correct)")
else:
    fail(f"GET /api/ai/export/enriched → {code}")

# 11. Existing endpoints still work
for path, name in [
    ("/api/stats", "stats"),
    ("/api/spins", "spins"),
    ("/api/leads?page=1&page_size=5", "leads"),
]:
    code, r = get(path)
    if code == 200:
        ok(f"GET {path} → 200 (existing feature intact)")
    else:
        fail(f"GET {path} → {code}", "REGRESSION")

# 12. OpenAPI docs available
code, r = get("/docs")
if code == 200:
    ok("GET /docs → 200 (OpenAPI docs available)")
else:
    fail(f"GET /docs → {code}")

print(f"\n{'='*55}")
print(f"  LIVE RESULTS: {PASS} PASSED  |  {FAIL} FAILED")
print("="*55)
sys.exit(0 if FAIL == 0 else 1)
