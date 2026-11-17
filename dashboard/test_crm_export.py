"""
Quick validation script for the CRM export schema.
Run from the project root: python -m dashboard.test_crm_export
Or directly: cd dashboard && python test_crm_export.py
"""
import sys, os

# Ensure dashboard/ is on path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import dashboard_service as svc
import io, csv

EXPECTED_HEADERS = [
    "External ID", "Name", "Company Name", "Contact Name", "Email",
    "Job Position", "Phone", "Mobile", "Street", "Street2",
    "City", "State", "Zip", "Country", "Website", "Notes",
]

EMAIL_RE = svc._EMAIL_RE

def test_crm_export():
    print("=" * 60)
    print("CRM EXPORT SCHEMA VALIDATION")
    print("=" * 60)

    df = svc.load_leads()
    if df is None:
        print("\n[SKIP] No leads CSV found — cannot test with real data.")
        print("  Testing with empty DataFrame instead...\n")
        import pandas as pd
        df = pd.DataFrame(columns=svc.CRM_EXPORT_COLUMNS)

    csv_bytes = svc.export_csv_bytes(df)
    csv_text = csv_bytes.decode("utf-8")

    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    if not rows:
        print("[FAIL] CSV output is completely empty")
        return False

    headers = rows[0]
    data_rows = rows[1:]
    all_pass = True

    # --- Check 1: Exactly 16 columns ---
    if len(headers) == 16:
        print(f"[PASS] Column count: {len(headers)} (expected 16)")
    else:
        print(f"[FAIL] Column count: {len(headers)} (expected 16)")
        all_pass = False

    # --- Check 2: Header names in exact order ---
    if headers == EXPECTED_HEADERS:
        print("[PASS] Header names and order match the CRM schema")
    else:
        print("[FAIL] Header mismatch:")
        for i, (got, exp) in enumerate(zip(headers, EXPECTED_HEADERS)):
            status = "OK" if got == exp else "MISMATCH"
            print(f"  [{status}] Col {i+1}: got='{got}' expected='{exp}'")
        all_pass = False

    if not data_rows:
        print("[INFO] No data rows to validate (empty export).")
        print("=" * 60)
        return all_pass

    print(f"\n[INFO] Validating {len(data_rows)} data rows...\n")

    errors = []
    for row_idx, row in enumerate(data_rows):
        row_num = row_idx + 2  # 1-indexed, header is row 1

        # Each row must have exactly 16 fields
        if len(row) != 16:
            errors.append(f"  Row {row_num}: has {len(row)} fields (expected 16)")
            continue

        ext_id, name, company, contact, email = row[0], row[1], row[2], row[3], row[4]
        phone, country = row[6], row[13]

        # External ID must be non-null
        if not ext_id.strip():
            errors.append(f"  Row {row_num}: External ID is blank (STRICTLY REQUIRED)")

        # Name must be non-null
        if not name.strip():
            errors.append(f"  Row {row_num}: Name is blank (STRICTLY REQUIRED)")

        # Company Name or Contact Name must be populated
        if not company.strip() and not contact.strip():
            errors.append(f"  Row {row_num}: Both Company Name AND Contact Name are blank (at least one required)")

        # Email must be valid RFC 5322 if present
        if email.strip() and not EMAIL_RE.match(email.strip()):
            errors.append(f"  Row {row_num}: Email '{email}' fails RFC 5322 validation")

        # Country must be 2-letter ISO code if present
        if country.strip():
            if len(country.strip()) != 2 or not country.strip().isalpha():
                errors.append(f"  Row {row_num}: Country '{country}' is not a 2-letter ISO code")

    if errors:
        print(f"[FAIL] {len(errors)} validation error(s):")
        for e in errors[:20]:  # cap output
            print(e)
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
        all_pass = False
    else:
        print("[PASS] All data rows pass schema validation")

    # --- Quick sample output ---
    print(f"\n--- Sample row (row 2) ---")
    if data_rows:
        for h, v in zip(EXPECTED_HEADERS, data_rows[0]):
            print(f"  {h:20s}: {v[:80]}")

    print("\n" + "=" * 60)
    print(f"RESULT: {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
    print("=" * 60)
    return all_pass


if __name__ == "__main__":
    success = test_crm_export()
    sys.exit(0 if success else 1)
