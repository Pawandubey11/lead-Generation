import pandas as pd
import numpy as np
import os
import re
import requests
import json
import math
import sys
from urllib.parse import unquote

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

sys.path.insert(0, PROJECT_ROOT)
from config.config import N8N_WEBHOOK_URL, N8N_WEBHOOK_SECRET, N8N_SEND_ON_COMPLETION

input_file = os.path.join(OUTPUT_DIR, "local_business_leads.csv")

if not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
    print("No leads CSV found (or file is empty) — skipping cleaner.")
    print("LEAD_CLEANER_STATUS: NO_LEADS")
    sys.exit(2)

try:
    df = pd.read_csv(input_file)
except pd.errors.EmptyDataError:
    print("Leads CSV exists but has no rows/columns to parse — skipping cleaner.")
    print("LEAD_CLEANER_STATUS: NO_LEADS")
    sys.exit(2)

if df.empty:
    print("Leads CSV parsed but contains 0 rows — skipping cleaner.")
    print("LEAD_CLEANER_STATUS: NO_LEADS")
    sys.exit(2)

print(f"\nOriginal Leads: {len(df)}")

# ----------------------------------------
# CLEAN & NORMALIZE
# ----------------------------------------

text_cols = [
    "business_name", "phone", "website", "address", "instagram", "facebook",
    "linkedin", "email", "city", "locality", "search_area", "business_type",
    "country", "spin", "scraped_at", "source_name", "source_url", "rating", "reviews"
]
for col in text_cols:
    if col in df.columns:
        df[col] = df[col].fillna("").astype(str).replace(["nan", "0", "0.0", "None", "null"], "").str.strip()

for col in df.columns:
    if col not in text_cols:
        if df[col].dtype == 'object':
            df[col] = df[col].fillna("")
        else:
            df[col] = df[col].fillna(0)

if "spin" not in df.columns:
    df["spin"] = "Legacy Run"
if "scraped_at" not in df.columns:
    df["scraped_at"] = ""

# Drop booking-widget / non-place noise records (e.g. "Haus Dentist - Book online")
if "source_url" in df.columns:
    reserve_mask = df["source_url"].astype(str).str.contains("/maps/reserve/", case=False, na=False)
    if reserve_mask.any():
        print(f"Removed {int(reserve_mask.sum())} booking-widget noise rows (/maps/reserve/)")
        df = df[~reserve_mask]

# Clean & normalize emails (URL-unquote %20, strip placeholder junk)
_EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}$')
_JUNK_EMAIL_RE = re.compile(
    r'^(you|yourname|name|username|user|johndoe|john\.doe|janedoe|test|example|sample|demo|noreply|no-reply|donotreply|mailer-daemon|postmaster)@'
    r'|@(example\.com|domain\.com|email\.com|company\.com|yourdomain\.com|wixpress\.com|sentry\.io|ueni\.com)$',
    re.IGNORECASE,
)

def _clean_email_val(val: str) -> str:
    s = unquote(str(val or "")).strip().strip(".,;:<>\"'")
    if not s or s.lower() in ("nan", "0", "none"):
        return ""
    if not _EMAIL_RE.match(s) or _JUNK_EMAIL_RE.search(s):
        return ""
    return s

if "email" in df.columns:
    df["email"] = df["email"].apply(_clean_email_val)

# Remove rows with empty business name
df = df[df["business_name"].str.strip() != ""].copy()

# Deduplication:
# 1. Deduplicate exact same Google Maps Place URL within the same spin
# 2. Deduplicate same (business_name, address, spin) when address is present
#    so distinct branches at different addresses are preserved!
# 3. For listings without address, deduplicate by (business_name, spin)
df["_name_norm"] = df["business_name"].str.lower().str.strip()
df["_addr_norm"] = df["address"].str.lower().str.strip() if "address" in df.columns else ""
df["_phone_norm"] = df["phone"].astype(str).str.replace(r"[^\d+]", "", regex=True)

if "source_url" in df.columns:
    has_url = df["source_url"].str.strip() != ""
    df = df[~(has_url & df.duplicated(subset=["source_url", "spin"], keep="first"))]

has_addr = df["_addr_norm"] != ""
df = df[~(has_addr & df.duplicated(subset=["_name_norm", "_addr_norm", "spin"], keep="first"))]
df = df[~((~has_addr) & df.duplicated(subset=["_name_norm", "spin"], keep="first"))]

has_ph = df["_phone_norm"].str.len() >= 7
df = df[~(has_ph & df.duplicated(subset=["_phone_norm", "_name_norm", "spin"], keep="first"))]

df.drop(columns=["_name_norm", "_addr_norm", "_phone_norm"], inplace=True, errors="ignore")

# ----------------------------------------
# FEATURE ENGINEERING (Vectorized)
# ----------------------------------------

has_phone = df["phone"].astype(str).str.strip() != ""
has_web = df["website"].astype(str).str.strip() != ""
has_em = df["email"].astype(str).str.strip() != ""
has_ig = df["instagram"].astype(str).str.strip() != ""
has_fb = df["facebook"].astype(str).str.strip() != ""
has_li = df["linkedin"].astype(str).str.strip() != ""

has_social = has_ig | has_fb | has_li

df["Has Website"] = np.where(has_web, "Yes", "No")
df["Has Email"] = np.where(has_em, "Yes", "No")
df["Has Social Media"] = np.where(has_social, "Yes", "No")

filled_count = (
    has_phone.astype(int) + has_web.astype(int) + has_em.astype(int) +
    has_ig.astype(int) + has_fb.astype(int) + has_li.astype(int)
)
df["Contact Completeness %"] = (filled_count / 6.0 * 100).round(2)

score = (
    has_phone.astype(int) * 20 +
    has_web.astype(int) * 20 +
    has_em.astype(int) * 40 +
    has_ig.astype(int) * 10 +
    has_fb.astype(int) * 5 +
    has_li.astype(int) * 5
)
df["Lead Score"] = score

priority_conditions = [score >= 70, score >= 40]
priority_choices = ["Hot", "Warm"]
df["Priority"] = np.select(priority_conditions, priority_choices, default="Cold")

df = df.sort_values(by="Lead Score", ascending=False)

# ----------------------------------------
# EMAIL QUALITY FILTERING
# ----------------------------------------

_NON_CONTACTABLE_PREFIX_RE = re.compile(
    r'^(noreply|no-reply|donotreply|mailer-daemon|test|example|postmaster|you|johndoe|janedoe|sample)@',
    re.IGNORECASE
)

def is_quality_email(email: str) -> bool:
    """Returns True for deliverable, non-placeholder emails (accepts info@, contact@, sales@, etc. for B2B SMEs)."""
    s = str(email).strip()
    if not s or s in ("nan", "0", "None"):
        return False
    if not _EMAIL_RE.match(s):
        return False
    if _NON_CONTACTABLE_PREFIX_RE.match(s) or _JUNK_EMAIL_RE.search(s):
        return False
    return True

verified_mask = df["email"].apply(is_quality_email) | (df["Contact Completeness %"] >= 50)
df_verified = df[verified_mask].copy()

# ----------------------------------------
# SAVE (atomic writes)
# ----------------------------------------

output_file = os.path.join(OUTPUT_DIR, "final_ai_leads.csv")
_tmp = output_file + ".tmp"
df.to_csv(_tmp, index=False)
os.replace(_tmp, output_file)

verified_output_file = os.path.join(OUTPUT_DIR, "verified_leads_export.csv")
_tmp_v = verified_output_file + ".tmp"
df_verified.to_csv(_tmp_v, index=False)
os.replace(_tmp_v, verified_output_file)

# ----------------------------------------
# SUMMARY
# ----------------------------------------

hot  = len(df[df["Priority"] == "Hot"])
warm = len(df[df["Priority"] == "Warm"])
cold = len(df[df["Priority"] == "Cold"])

print(f"Cleaned Leads : {len(df)}")
print(f"Verified Leads: {len(df_verified)}")
print(f"  Hot  (70+)  : {hot}")
print(f"  Warm (40-69): {warm}")
print(f"  Cold (<40)  : {cold}")
print(f"\nSaved to: {output_file}")
print(f"Verified Leads Saved to: {verified_output_file}")
print("\nLead Cleaning Complete!")

# ----------------------------------------
# SEND TO N8N WEBHOOK
# ----------------------------------------

def send_to_n8n(dataframe):
    if not N8N_SEND_ON_COMPLETION:
        print("\n[N8N] Webhook sending is disabled in config. Skipping.")
        return

    print(f"\n[N8N] Sending {len(dataframe)} leads to N8N webhook...")
    headers = {"Content-Type": "application/json"}
    if N8N_WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = N8N_WEBHOOK_SECRET

    leads_list = dataframe.to_dict(orient="records")

    def clean_value(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    leads_list = [{k: clean_value(v) for k, v in row.items()} for row in leads_list]

    payload = {
        "total_leads": len(leads_list),
        "hot_leads": hot,
        "warm_leads": warm,
        "cold_leads": cold,
        "leads": leads_list
    }

    try:
        response = requests.post(
            N8N_WEBHOOK_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=30
        )
        if response.status_code in (200, 201):
            print(f"[N8N] OK - Successfully sent to N8N! Status: {response.status_code}")
        else:
            print(f"[N8N] FAIL - N8N returned status {response.status_code}: {response.text[:200]}")
    except requests.exceptions.Timeout:
        print("[N8N] FAIL - Request timed out. Leads still saved locally.")
    except requests.exceptions.ConnectionError:
        print("[N8N] FAIL - Could not connect to N8N. Check the URL. Leads still saved locally.")
    except Exception as e:
        print(f"[N8N] FAIL - Unexpected error: {e}. Leads still saved locally.")

send_to_n8n(df)
