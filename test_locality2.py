"""Core logic smoke tests — offline only, no network calls."""
import sys
sys.path.insert(0, r"c:\Users\pawan\OneDrive\Desktop\Leadgreartion\lead Generation")

passed = 0
failed = 0

def ok(msg):
    global passed; passed += 1; print(f"[PASS] {msg}")

def fail(msg, err):
    global failed; failed += 1; print(f"[FAIL] {msg}: {err}")

# 1. LocalityDiscovery fallback for Delhi
try:
    from scrapers.location_discovery import LocalityDiscovery
    ld = LocalityDiscovery("Delhi", "India")
    locs = ld._discover_via_fallback()          # offline — uses hardcoded dict
    q = ld.get_search_queries("Restaurants")    # calls discover() -> fallback
    assert len(locs) >= 10
    first = q[0]["query"]
    assert "Delhi" in first
    ok(f"LocalityDiscovery Delhi — {len(q)} queries, first: {first}")
except Exception as e:
    fail("LocalityDiscovery Delhi", e)

# 2. Manual override
try:
    ld2 = LocalityDiscovery("Mumbai", "India", manual_localities=["Bandra", "Juhu"])
    r = ld2.discover()
    assert len(r) == 2 and r[0]["source"] == "manual"
    ok("Manual locality override — 2 localities, source=manual")
except Exception as e:
    fail("Manual override", e)

# 3. Bengaluru alias
try:
    ld3 = LocalityDiscovery("Bengaluru", "India")
    r3 = ld3._discover_via_fallback()
    assert len(r3) > 0
    ok(f"Bengaluru alias — {len(r3)} localities found")
except Exception as e:
    fail("Bengaluru alias", e)

# 4. Unknown city falls back to city-itself (offline path)
try:
    ld4 = LocalityDiscovery("Gotham City", "Fictional")
    r4 = ld4._discover_via_fallback()          # only checks hardcoded dict
    assert isinstance(r4, list)                 # empty list is fine
    ok(f"Unknown city fallback — _discover_via_fallback returns list ({len(r4)} items)")
except Exception as e:
    fail("Unknown city fallback", e)

# 5. Config keys present
try:
    from config.config import MAX_LOCALITIES, MAX_BIZ_PER_LOCALITY
    assert MAX_LOCALITIES == 30 and MAX_BIZ_PER_LOCALITY > 0
    ok(f"Config keys — MAX_LOCALITIES={MAX_LOCALITIES}, MAX_BIZ_PER_LOCALITY={MAX_BIZ_PER_LOCALITY}")
except Exception as e:
    fail("Config keys", e)

# 6. generate_leads has is_locality_mode param
try:
    import inspect
    from scrapers.crawler import generate_leads
    sig = inspect.signature(generate_leads)
    assert "is_locality_mode" in sig.parameters
    ok(f"generate_leads params — {list(sig.parameters.keys())}")
except Exception as e:
    fail("generate_leads signature", e)

# 7. scraper_service has all locality _status fields
try:
    from dashboard.scraper_service import _status
    required = [
        "is_locality_mode", "localities", "current_locality",
        "locality_index", "total_localities", "localities_completed",
        "localities_failed", "locality_lead_counts",
    ]
    missing = [f for f in required if f not in _status]
    assert not missing, f"Missing: {missing}"
    ok(f"scraper_service._status — all {len(required)} locality fields present")
except Exception as e:
    fail("scraper_service._status", e)

# 8. app.py AST check for new route functions
try:
    import ast
    src = open(
        r"c:\Users\pawan\OneDrive\Desktop\Leadgreartion\lead Generation\dashboard\app.py",
        encoding="utf-8"
    ).read()
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "scrape_coverage" in funcs, "scrape_coverage missing"
    assert "locality_discover" in funcs, "locality_discover missing"
    ok("app.py — scrape_coverage and locality_discover functions present")
except Exception as e:
    fail("app.py route check", e)

print()
print(f"Results: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
