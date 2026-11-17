"""
batch_scraper.py
----------------
Orchestrates multi-niche, multi-city scraping across Germany.
Extracts leads for all requested industries across top 10 German cities,
appends raw leads, and executes lead_cleaner.py for automated scoring & enrichment.
"""

import os
import sys
import time
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

os.environ["MAX_BIZ_PER_CITY"] = "20"

from scrapers.crawler import generate_leads

# Target Cities (10 Major German Hubs)
CITIES = [
    "Berlin",
    "Munich",
    "Hamburg",
    "Frankfurt",
    "Cologne",
    "Düsseldorf",
    "Stuttgart",
    "Leipzig",
    "Dresden",
    "Nuremberg"
]

# Target Remaining Industries / Niches
NICHES = [
    "Manufacturing / Maschinenbau",
    "Logistics / Transport",
    "Real Estate / Immobilien",
    "Wholesale / B2B Distributors",
    "Professional Services",
    "Hotels / Hospitality",
    "Healthcare / Medical Businesses",
    "Automotive Workshops / Dealers"
]

def run_cleaner():
    """Runs lead_cleaner.py to score and export final leads."""
    print("\n" + "=" * 60)
    print("  RUNNING AI LEAD CLEANER & SCORING ENGINE")
    print("=" * 60)
    cleaner_path = os.path.join(PROJECT_ROOT, "lead_cleaner.py")
    try:
        res = subprocess.run([sys.executable, cleaner_path], cwd=PROJECT_ROOT, check=False)
        print(f"Lead cleaner finished with exit code: {res.returncode}")
    except Exception as e:
        print(f"Cleaner execution error: {e}")

def main():
    print("=" * 60)
    print("  GERMANY MULTI-NICHE ENTERPRISE LEAD GENERATION")
    print(f"  Total Niches : {len(NICHES)}")
    print(f"  Total Cities : {len(CITIES)}")
    print(f"  Target Hubs  : {', '.join(CITIES)}")
    print("=" * 60 + "\n")

    total_leads_collected = 0

    for idx, niche in enumerate(NICHES, 1):
        print("\n" + "#" * 60, flush=True)
        print(f"  [{idx}/{len(NICHES)}] STARTING NICHE: {niche}", flush=True)
        print("#" * 60 + "\n", flush=True)

        # Clear progress file so each niche gets all cities scraped
        prog_file = os.path.join(PROJECT_ROOT, "output", "progress.txt")
        if os.path.exists(prog_file):
            try:
                os.remove(prog_file)
            except Exception:
                pass

        try:
            leads = generate_leads(
                business_type=niche,
                country="germany",
                max_cities=len(CITIES),
                custom_cities=CITIES
            )
            count = len(leads) if leads else 0
            total_leads_collected += count
            print(f"\n[DONE] Niche '{niche}' completed. Found: {count} leads (Cumulative total: {total_leads_collected})", flush=True)

            # Run cleaner after each niche to keep dashboard up to date
            run_cleaner()

        except Exception as e:
            print(f"\n[ERROR] Scraping failed for niche '{niche}': {e}")
            run_cleaner()
            continue

        time.sleep(3)

    print("\n" + "=" * 60)
    print("  ALL NICHES & CITIES COMPLETED SUCCESSFULLY!")
    print(f"  Total Leads Generated: {total_leads_collected}")
    print("=" * 60)

if __name__ == "__main__":
    main()
