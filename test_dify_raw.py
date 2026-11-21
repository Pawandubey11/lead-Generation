"""Print raw Dify JSON to see exact outreach keys."""
import sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from ai.llm_client import LLMClient

client = LLMClient()
result = client.call_dify_chatflow('Sharma Restaurant', 'https://www.sharmarestaurant.com', 'Restaurant')

print("=== TOP-LEVEL KEYS ===")
print(list(result.keys()))
print()
print("=== OUTREACH OBJECT ===")
outreach = result.get("outreach", {})
print(json.dumps(outreach, indent=2, default=str))
print()
print("=== SALES QUESTIONS ===")
print(json.dumps(result.get("sales_questions", []), indent=2))
