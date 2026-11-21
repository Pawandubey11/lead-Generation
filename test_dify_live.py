"""Quick live test for Dify integration through the research engine."""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'dashboard')

from dotenv import load_dotenv
load_dotenv('.env')

from ai.research_engine import CompanyResearchEngine

engine = CompanyResearchEngine()

lead = {
    'business_name': 'Sharma Restaurant',
    'website': 'https://www.sharmarestaurant.com',
    'spin': 'Restaurant',
    'city': 'Delhi',
    'phone': '+91-9876543210',
}

print("Researching via Dify chatflow...")
result = engine.research_company(lead)
print()
print("=== RESULT ===")
print("Status         :", result["research_status"])
print("Company        :", str(result.get("company_overview",""))[:120])
print("Business Model :", str(result.get("business_model",""))[:80])
print("Top Service    :", result.get("strongest_opportunity",""))
print("Priority       :", result.get("opportunity_priority",""))
print("Confidence     :", result.get("recommendation_confidence",""))
print("Email Subject  :", result.get("email_subject",""))
print("LinkedIn Msg   :", str(result.get("linkedin_message",""))[:120])
print("Questions      :", str(result.get("discovery_questions",""))[:200])
print()
filled = sum(1 for v in result.values() if v and v not in ["", None, [], {}])
print(f"Fields populated: {filled}/{len(result)}")
if result.get("research_error"):
    print("ERROR:", result["research_error"])
