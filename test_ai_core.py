import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'dashboard')

print("Testing AI core modules...")

# Test 1: catalogue
from ai.systemaops_catalogue import SYSTEMAOPS_SERVICES, match_services
svcs = match_services('restaurant', 'food')
assert len(svcs) >= 1, "match_services returned empty"
print(f"[PASS] catalogue match: {svcs[:2]}")

# Test 2: LLM mock
from ai.llm_client import llm_client
import json
r = llm_client.complete('test')
d = json.loads(r)
assert 'company_overview' in d, "mock response missing company_overview"
print(f"[PASS] LLM mock: {len(d)} fields returned")

# Test 3: complete_json
d2 = llm_client.complete_json('test')
assert isinstance(d2, dict), "complete_json did not return dict"
print(f"[PASS] complete_json: {len(d2)} fields")

# Test 4: research engine
from ai.research_engine import research_engine
result = research_engine.research_company({'business_name': 'Test Biz', 'website': '', 'city': 'Delhi'})
assert result['research_status'] == 'completed', f"status={result['research_status']}"
print(f"[PASS] research_engine: status={result['research_status']}")

# Test 5: research service
from ai.research_service import research_service
st = research_service.get_status()
assert st['state'] == 'idle'
print(f"[PASS] research_service: state={st['state']}")

# Test 6: ai_service
from dashboard.ai_service import get_ai_config, get_research_status
cfg = get_ai_config()
assert cfg['provider'] == 'mock'
print(f"[PASS] ai_service: provider={cfg['provider']} configured={cfg['configured']}")

print("\nALL 6 TESTS PASSED")
