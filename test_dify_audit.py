"""
Audit the full Dify response — check all fields, identify gaps.
"""
import sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from ai.llm_client import LLMClient
from ai.research_engine import ENRICHMENT_FIELDS

client = LLMClient()
print("Calling Dify chatflow...")
raw = client.call_dify_chatflow(
    company_name='ABC Pharma Ltd',
    website_url='https://www.abcpharma.com',
    industry='Pharmaceutical Manufacturing'
)

print("\n=== RAW DIFY KEYS & VALUES ===")
print(json.dumps(raw, indent=2, default=str)[:5000])

print("\n\n=== ENRICHMENT FIELDS COVERAGE ===")
from ai.research_engine import CompanyResearchEngine
engine = CompanyResearchEngine()
lead = {'business_name': 'ABC Pharma Ltd', 'website': 'https://www.abcpharma.com', 'spin': 'Pharmaceutical'}
result = engine.research_company(lead)

filled, empty = [], []
for f in ENRICHMENT_FIELDS:
    val = result.get(f, '')
    if val and val not in ('', None, [], {}, 'pending', 'low'):
        filled.append(f)
    else:
        empty.append(f)

print(f"\nFilled ({len(filled)}/{len(ENRICHMENT_FIELDS)}):")
for f in filled:
    print(f"  ✅ {f}: {str(result[f])[:60]}")

print(f"\nEmpty ({len(empty)}/{len(ENRICHMENT_FIELDS)}):")
for f in empty:
    print(f"  ❌ {f}")
