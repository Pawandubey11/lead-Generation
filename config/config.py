import os

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json"
}

OUTPUT_FILE = "output/local_business_leads.csv"
# ============================================
# N8N WEBHOOK CONFIG
# ============================================
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
N8N_WEBHOOK_SECRET = os.environ.get("N8N_WEBHOOK_SECRET", "")
N8N_SEND_ON_COMPLETION = os.environ.get("N8N_SEND_ON_COMPLETION", "false").lower() == "true"