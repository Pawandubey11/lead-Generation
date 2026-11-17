import pandas as pd

df = pd.read_csv(r"c:\MY 📚\project L\lead Generation\output\final_ai_leads.csv")

print("=== City breakdown ===")
print(df["city"].value_counts().to_string())
print()

print("=== Spin value ===")
print(df["spin"].unique())
print()

print("=== Sample addresses (first 20) ===")
for i, row in df.head(20).iterrows():
    name = str(row["business_name"])[:40]
    city = str(row["city"])
    addr = str(row["address"])[:100]
    print(f"  {name} | City: {city} | Addr: {addr}")

print()
print("=== Leads with 'Hyderabad' in address or city ===")
mask = (
    df["city"].astype(str).str.lower().str.contains("hyderabad", na=False)
    | df["address"].astype(str).str.lower().str.contains("hyderabad", na=False)
)
hyd = df[mask]
print(f"Found: {len(hyd)} Hyderabad leads")
for i, row in hyd.head(10).iterrows():
    print(f"  {row['business_name']} | {row['city']} | {str(row['address'])[:80]}")

print()
print("=== Leads with 'India' or 'Telangana' in address ===")
india_mask = (
    df["address"].astype(str).str.lower().str.contains("india|telangana", na=False)
)
india = df[india_mask]
print(f"Found: {len(india)} India/Telangana leads")
for i, row in india.head(10).iterrows():
    print(f"  {row['business_name']} | {row['city']} | {str(row['address'])[:80]}")
