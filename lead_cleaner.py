import pandas as pd
import numpy as np
import os
import re
import requests
import json
import math
import sys
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
# CLEAN
# ----------------------------------------

# Explicitly cast all potential string/text columns to string to prevent float64 type inference issues
text_cols = ["business_name", "phone", "website", "address", "instagram", "facebook", "linkedin", "email", "city", "business_type", "country", "spin", "scraped_at"]
for col in text_cols:
    if col in df.columns:
        df[col] = df[col].fillna("").astype(str).replace(["nan", "0", "0.0", "None"], "").str.strip()

# Safely handle NaN in all other columns (numeric, boolean, etc.) without raising TypeErrors
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

df = df.drop_duplicates(subset=["business_name", "spin"], keep="first")
df = df[~((df["email"] != "") & df.duplicated(subset=["email", "spin"]))]
df = df[~((df["phone"] != "") & df.duplicated(subset=["phone", "spin"]))]
df = df[df["business_name"].str.strip() != ""]

# ----------------------------------------
# FEATURE ENGINEERING (Vectorized)
# ----------------------------------------
# (numpy already imported at top)

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

filled_count = (has_phone.astype(int) + has_web.astype(int) + has_em.astype(int) +
                has_ig.astype(int) + has_fb.astype(int) + has_li.astype(int))
df["Contact Completeness %"] = (filled_count / 6.0 * 100).round(2)

score = (has_phone.astype(int) * 20 +
         has_web.astype(int) * 20 +
         has_em.astype(int) * 40 +
         has_ig.astype(int) * 10 +
         has_fb.astype(int) * 5 +
         has_li.astype(int) * 5)
df["Lead Score"] = score

priority_conditions = [score >= 70, score >= 40]
priority_choices = ["Hot", "Warm"]
df["Priority"] = np.select(priority_conditions, priority_choices, default="Cold")

df = df.sort_values(by="Lead Score", ascending=False)

# ----------------------------------------
# EMAIL QUALITY FILTERING (DQ-001)
# ----------------------------------------

# Placeholder / generic emails that look valid but bounce or are not decision-maker inboxes
_PLACEHOLDER_EMAIL_RE = re.compile(
    r'^(info|contact|admin|hello|support|noreply|no-reply|sales|webmaster|test|example|postmaster|office)@',
    re.IGNORECASE
)
_EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')

def is_quality_email(email: str) -> bool:
    """Returns True only for syntactically valid, non-placeholder emails."""
    s = str(email).strip()
    if not s or s in ("nan", "0", "None"):
        return False
    if not _EMAIL_RE.match(s):
        return False
    if _PLACEHOLDER_EMAIL_RE.match(s):
        return False
    return True

# Replace the simple '@' check with the quality check for verified export
verified_mask = df["email"].apply(is_quality_email) | (df["Contact Completeness %"] >= 50)
df_verified = df[verified_mask].copy()

# ----------------------------------------
# SAVE (atomic writes to prevent race conditions with dashboard reads — INFRA-003)
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

    # Convert dataframe to list of dicts
    leads_list = dataframe.to_dict(orient="records")

    # Clean NaN/inf values for safe JSON serialization
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