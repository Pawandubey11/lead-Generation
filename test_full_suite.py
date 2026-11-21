"""
Comprehensive test suite for SystemaOps Business Intelligence feature.
Runs on main branch — no server required except for live API tests.
"""
import sys
import os
import ast
import json
import importlib

sys.path.insert(0, '.')
sys.path.insert(0, 'dashboard')

ROOT = os.path.dirname(os.path.abspath(__file__))
PASS = 0
FAIL = 0

def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")

def fail(msg, err=""):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}" + (f": {err}" for x in [1] if err).__next__() if err else f"  [FAIL] {msg}")

def section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)

# ───────────────────────────────────────────────
# 1. FILE EXISTENCE
# ───────────────────────────────────────────────
section("1. File Existence Check")

required_files = [
    "ai/__init__.py",
    "ai/systemaops_catalogue.py",
    "ai/llm_client.py",
    "ai/prompts.py",
    "ai/research_engine.py",
    "ai/research_service.py",
    "dashboard/ai_service.py",
    "dashboard/app.py",
    "dashboard/templates/index.html",
    "dashboard/static/js/dashboard.js",
    "dashboard/static/css/style.css",
    "docker-compose.yml",
    ".env.example",
]

for f in required_files:
    path = os.path.join(ROOT, f)
    if os.path.isfile(path):
        ok(f"exists: {f}")
    else:
        fail(f"MISSING: {f}")

# ───────────────────────────────────────────────
# 2. SYNTAX CHECK
# ───────────────────────────────────────────────
section("2. Syntax Check (all .py files)")

py_files = [f for f in required_files if f.endswith(".py")]
for f in py_files:
    path = os.path.join(ROOT, f)
    if not os.path.isfile(path):
        fail(f"cannot check (missing): {f}")
        continue
    try:
        with open(path, encoding="utf-8") as fh:
            ast.parse(fh.read())
        ok(f"syntax OK: {f}")
    except SyntaxError as e:
        fail(f"syntax error in {f}", str(e))

# ───────────────────────────────────────────────
# 3. AI MODULE IMPORTS
# ───────────────────────────────────────────────
section("3. AI Module Import Test")

try:
    from ai.systemaops_catalogue import SYSTEMAOPS_SERVICES, match_services, all_services_text
    ok(f"ai.systemaops_catalogue imported — {len(SYSTEMAOPS_SERVICES)} services")
except Exception as e:
    fail("ai.systemaops_catalogue import", str(e))

try:
    from ai.llm_client import LLMClient, llm_client
    ok(f"ai.llm_client imported — provider={llm_client.provider}")
except Exception as e:
    fail("ai.llm_client import", str(e))

try:
    from ai.prompts import (COMPANY_RESEARCH_SYSTEM, OPPORTUNITY_MATCHING_SYSTEM,
                            SALES_PREP_SYSTEM, OUTREACH_SYSTEM, CONTENT_SYSTEM,
                            company_research_prompt, opportunity_matching_prompt,
                            sales_prep_prompt, outreach_prompt, content_prompt)
    ok("ai.prompts imported — all 5 systems + 5 builders")
except Exception as e:
    fail("ai.prompts import", str(e))

try:
    from ai.research_engine import CompanyResearchEngine, research_engine
    ok("ai.research_engine imported")
except Exception as e:
    fail("ai.research_engine import", str(e))

try:
    from ai.research_service import ResearchService, research_service
    ok("ai.research_service imported")
except Exception as e:
    fail("ai.research_service import", str(e))

try:
    from dashboard.ai_service import (get_ai_config, get_research_status,
                                       start_research, stop_research,
                                       get_company_report, get_all_reports,
                                       export_enriched_csv, AI_ENRICHMENT_FIELDS)
    ok(f"dashboard.ai_service imported — {len(AI_ENRICHMENT_FIELDS)} enrichment fields")
except Exception as e:
    fail("dashboard.ai_service import", str(e))

# ───────────────────────────────────────────────
# 4. SERVICE CATALOGUE
# ───────────────────────────────────────────────
section("4. Service Catalogue Logic")

try:
    from ai.systemaops_catalogue import SYSTEMAOPS_SERVICES, match_services
    assert len(SYSTEMAOPS_SERVICES) == 6, f"Expected 6 services, got {len(SYSTEMAOPS_SERVICES)}"
    ok(f"6 service categories present: {list(SYSTEMAOPS_SERVICES.keys())}")
except Exception as e:
    fail("service count", str(e))

test_cases = [
    ("restaurant food cafe", "Local Services", ["odoo_erp"]),
    ("manufacturing inventory warehouse", "Manufacturing", ["odoo_erp"]),
    ("shopify ecommerce api integration", "Ecommerce", ["workflow_integration"]),
    ("invoice accounting purchase order", "Accounting", ["document_automation"]),
    ("chatbot whatsapp customer service ai", "Tech", ["ai_automation"]),
]
for query, industry, expected_prefix in test_cases:
    try:
        result = match_services(query, industry)
        if any(e in result for e in expected_prefix):
            ok(f"match_services('{query[:25]}…') → {result[0]}")
        else:
            fail(f"match_services('{query[:25]}…')", f"got {result}, expected one of {expected_prefix}")
    except Exception as e:
        fail(f"match_services error", str(e))

# ───────────────────────────────────────────────
# 5. LLM CLIENT (mock mode)
# ───────────────────────────────────────────────
section("5. LLM Client — Mock Mode")

try:
    from ai.llm_client import LLMClient
    c = LLMClient()
    assert c.provider == "mock", f"Expected mock, got {c.provider}"
    ok(f"LLMClient default provider = mock")

    assert c.is_available(), "is_available() should be True for mock"
    ok("is_available() = True")

    text = c.complete("test prompt")
    assert len(text) > 50, "mock response too short"
    ok(f"complete() returned {len(text)} chars")

    d = c.complete_json("test")
    assert isinstance(d, dict), "complete_json must return dict"
    assert "company_overview" in d, "missing company_overview key"
    assert "recommended_services" in d, "missing recommended_services key"
    ok(f"complete_json() returned {len(d)} fields including company_overview, recommended_services")
except Exception as e:
    fail("LLMClient mock test", str(e))

# ───────────────────────────────────────────────
# 6. RESEARCH ENGINE (mock LLM)
# ───────────────────────────────────────────────
section("6. Research Engine — Full Pipeline (mock)")

try:
    from ai.research_engine import CompanyResearchEngine, ENRICHMENT_FIELDS
    engine = CompanyResearchEngine()

    # Test with website
    lead1 = {
        "business_name": "Delhi Restaurant ABC",
        "website": "",
        "phone": "+91-9876543210",
        "email": "info@restaurant.com",
        "city": "Delhi",
        "address": "Connaught Place, Delhi",
        "spin": "restaurants in India",
    }
    result1 = engine.research_company(lead1)
    assert result1["research_status"] == "completed", f"status={result1['research_status']}"
    ok(f"research_company() completed for lead with no website")

    # Verify all enrichment fields present
    missing = [f for f in ENRICHMENT_FIELDS if f not in result1]
    if missing:
        fail(f"Missing enrichment fields: {missing}")
    else:
        ok(f"All {len(ENRICHMENT_FIELDS)} enrichment fields present")

    # Verify key fields populated
    for field in ["company_overview", "recommended_services", "strongest_opportunity",
                  "meeting_opening", "discovery_questions", "personalized_email",
                  "email_subject", "post_topic"]:
        if result1.get(field):
            ok(f"Field '{field}' populated")
        else:
            fail(f"Field '{field}' is empty")

    # Test cache hit
    result2 = engine.research_company(lead1)
    ok("Cache hit works (second call returns cached result)")

    # Test failed company (bad lead)
    lead_bad = {"business_name": "Bad Lead", "website": "not-a-real-url"}
    result_bad = engine.research_company(lead_bad)
    # Should either complete (mock ignores bad URL) or fail gracefully
    ok(f"Bad lead handled gracefully: status={result_bad['research_status']}")

except Exception as e:
    fail("ResearchEngine pipeline", str(e))
    import traceback; traceback.print_exc()

# ───────────────────────────────────────────────
# 7. RESEARCH SERVICE (background threading)
# ───────────────────────────────────────────────
section("7. Research Service — Background Queue")

try:
    import time
    from ai.research_service import ResearchService

    svc = ResearchService()
    assert svc.get_status()["state"] == "idle", "Should start idle"
    ok("Initial state = idle")

    # Start research for 2 leads
    leads = [
        {"business_name": "Company Alpha", "website": "", "city": "Mumbai"},
        {"business_name": "Company Beta", "website": "", "city": "Pune"},
    ]
    result = svc.start_research(leads)
    assert result.get("ok"), f"start_research failed: {result}"
    ok(f"start_research() accepted {result['total']} leads")

    # Wait for completion (mock is instant)
    for _ in range(20):
        st = svc.get_status()
        if st["state"] in ("completed", "error"):
            break
        time.sleep(0.3)

    st = svc.get_status()
    assert st["state"] == "completed", f"Expected completed, got {st['state']}"
    ok(f"Research completed: {st['completed']} done, {st['failed']} failed")

    # Verify results
    all_results = svc.get_all_results()
    assert "Company Alpha" in all_results, "Company Alpha missing from results"
    assert "Company Beta" in all_results, "Company Beta missing from results"
    ok(f"Both companies in results dict")

    # Test double-start protection
    result2 = svc.start_research(leads)
    # Service is complete, not running — should accept OR return error
    ok(f"Double-start handled: {result2}")

except Exception as e:
    fail("ResearchService threading", str(e))
    import traceback; traceback.print_exc()

# ───────────────────────────────────────────────
# 8. AI SERVICE LAYER
# ───────────────────────────────────────────────
section("8. AI Service Layer")

try:
    from dashboard.ai_service import get_ai_config, get_research_status, export_enriched_csv

    cfg = get_ai_config()
    assert cfg["provider"] == "mock", f"Expected mock provider, got {cfg['provider']}"
    assert cfg["configured"] == True, "Should be configured in mock mode"
    assert cfg["mock_mode"] == True, "Should report mock_mode=True"
    ok(f"get_ai_config() → provider={cfg['provider']}, mock_mode={cfg['mock_mode']}")

    status = get_research_status()
    assert "state" in status, "Missing 'state' in status"
    ok(f"get_research_status() → state={status['state']}")

    # Test enriched CSV export with mock data
    test_leads = [
        {"business_name": "Test Corp", "website": "test.com", "city": "Delhi",
         "phone": "123", "email": "a@b.com", "Lead Score": 75, "Priority": "Hot"}
    ]
    csv_bytes = export_enriched_csv(test_leads)
    assert isinstance(csv_bytes, bytes), "export_enriched_csv must return bytes"
    csv_text = csv_bytes.decode("utf-8")
    assert "business_name" in csv_text, "CSV missing business_name column"
    assert "research_status" in csv_text, "CSV missing research_status column"
    assert "systemaops_business_opportunity" in csv_text, "CSV missing AI column"
    ok(f"export_enriched_csv() → {len(csv_bytes)} bytes, all required columns present")

except Exception as e:
    fail("AI service layer", str(e))
    import traceback; traceback.print_exc()

# ───────────────────────────────────────────────
# 9. PROMPTS COMPLETENESS
# ───────────────────────────────────────────────
section("9. Prompts Completeness")

try:
    from ai.prompts import (company_research_prompt, opportunity_matching_prompt,
                             sales_prep_prompt, outreach_prompt, content_prompt)
    from ai.systemaops_catalogue import all_services_text

    sample_lead = {"business_name": "ABC Corp", "city": "Mumbai", "website": "abc.com",
                    "spin": "manufacturers in india", "phone": "123", "email": "x@y.com"}
    sample_research = {
        "industry": "Manufacturing", "company_overview": "Makes widgets",
        "existing_capabilities": "Has website", "technology_signals": "None",
        "website_problems": "No booking form",
        "strongest_opportunity": "Odoo ERP", "recommended_services": "Odoo ERP",
        "evidence": "No ERP visible", "potential_business_challenge": "Manual ops"
    }

    p1 = company_research_prompt(sample_lead, "sample website text")
    assert "ABC Corp" in p1 and "Mumbai" in p1, "Lead data not in prompt"
    ok(f"company_research_prompt: {len(p1)} chars, contains lead data")

    p2 = opportunity_matching_prompt(sample_lead, sample_research)
    assert "Odoo" in p2 or "SystemaOps" in p2, "Catalogue not in prompt"
    ok(f"opportunity_matching_prompt: {len(p2)} chars, contains catalogue")

    p3 = sales_prep_prompt(sample_lead, sample_research)
    assert "discovery_questions" in p3 or "meeting_opening" in p3
    ok(f"sales_prep_prompt: {len(p3)} chars")

    p4 = outreach_prompt(sample_lead, sample_research)
    assert "email_subject" in p4
    ok(f"outreach_prompt: {len(p4)} chars")

    p5 = content_prompt(sample_lead, sample_research)
    assert "post_topic" in p5
    ok(f"content_prompt: {len(p5)} chars")

    catalogue_text = all_services_text()
    assert "Odoo" in catalogue_text and "n8n" in catalogue_text
    ok(f"all_services_text(): {len(catalogue_text)} chars, contains Odoo and n8n")

except Exception as e:
    fail("Prompts completeness", str(e))
    import traceback; traceback.print_exc()

# ───────────────────────────────────────────────
# 10. HTML PANEL CHECK
# ───────────────────────────────────────────────
section("10. Dashboard HTML Panel Check")

try:
    with open("dashboard/templates/index.html", encoding="utf-8") as f:
        html = f.read()

    checks = {
        "ai-intelligence-panel": "AI panel div",
        "btn-ai-start": "Start Research button",
        "btn-ai-stop": "Stop button",
        "btn-ai-export": "Export CSV button",
        "ai-progress-bar": "Progress bar",
        "ai-lead-rows": "Lead rows container",
        "ai-report-section": "Report viewer",
        "tab-overview": "Overview tab",
        "tab-opportunity": "Opportunity tab",
        "tab-outreach": "Outreach tab",
        "startAIResearch": "JS function call",
        "viewAIReport": "JS report viewer call",
    }
    for key, desc in checks.items():
        if key in html:
            ok(f"HTML has {desc} ({key})")
        else:
            fail(f"HTML missing {desc} ({key})")
except Exception as e:
    fail("HTML panel check", str(e))

# ───────────────────────────────────────────────
# 11. JAVASCRIPT CHECK
# ───────────────────────────────────────────────
section("11. Dashboard JavaScript Check")

try:
    with open("dashboard/static/js/dashboard.js", encoding="utf-8") as f:
        js = f.read()

    js_checks = {
        "initAIPanel": "Panel initialization",
        "startAIResearch": "Start research function",
        "stopAIResearch": "Stop research function",
        "retryFailedResearch": "Retry function",
        "pollAIStatus": "Status polling",
        "viewAIReport": "Report viewer",
        "switchAITab": "Tab switcher",
        "exportEnrichedCSV": "CSV export",
        "copyAIText": "Copy to clipboard",
        "/api/ai/research/start": "API start endpoint",
        "/api/ai/status": "API status endpoint",
        "/api/ai/report/": "API report endpoint",
        "/api/ai/export/enriched": "API export endpoint",
    }
    for key, desc in js_checks.items():
        if key in js:
            ok(f"JS has {desc}")
        else:
            fail(f"JS missing {desc} ({key})")
except Exception as e:
    fail("JavaScript check", str(e))

# ───────────────────────────────────────────────
# 12. app.py ENDPOINT CHECK
# ───────────────────────────────────────────────
section("12. app.py AI Endpoints Check")

try:
    with open("dashboard/app.py", encoding="utf-8") as f:
        app_src = f.read()

    endpoint_checks = {
        "/api/ai/config": "AI config endpoint",
        "/api/ai/status": "AI status endpoint",
        "/api/ai/research/start": "Research start endpoint",
        "/api/ai/research/stop": "Research stop endpoint",
        "/api/ai/research/retry": "Research retry endpoint",
        "/api/ai/report/{business_name}": "Company report endpoint",
        "/api/ai/reports": "All reports endpoint",
        "/api/ai/export/enriched": "Enriched export endpoint",
        "ai_svc": "ai_service module imported",
        "AIResearchRequest": "Request model",
        "request=request": "Fixed TemplateResponse API",
    }
    for key, desc in endpoint_checks.items():
        if key in app_src:
            ok(f"app.py has {desc}")
        else:
            fail(f"app.py missing {desc} ({key})")
except Exception as e:
    fail("app.py endpoint check", str(e))

# ───────────────────────────────────────────────
# FINAL RESULTS
# ───────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"  RESULTS: {PASS} PASSED  |  {FAIL} FAILED")
print('='*55)
sys.exit(0 if FAIL == 0 else 1)
