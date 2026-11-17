"""
scrape_germany_b2b.py
---------------------
Scrapes software-related B2B companies across all major German cities.
Targets: IT / Software / SaaS / Cloud / Web Dev / Digital Agencies / Consulting

Usage:
    python scrape_germany_b2b.py
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

# Remove per-city business cap — scrape everything found
if "MAX_BIZ_PER_CITY" in os.environ:
    del os.environ["MAX_BIZ_PER_CITY"]

from scrapers.crawler import generate_leads

# ============================================================
# TARGET CITIES — 20 major German business hubs
# ============================================================
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
    "Nuremberg",
    "Hannover",
    "Bremen",
    "Dortmund",
    "Essen",
    "Mannheim",
    "Karlsruhe",
    "Bonn",
    "Aachen",
    "Heidelberg",
    "Darmstadt",
]

# ============================================================
# TARGET NICHES — Software / IT / Digital B2B
# ============================================================
NICHES = [
    "Software Companies / Softwareunternehmen",
    "IT Services / IT-Dienstleister",
    "SaaS Companies",
    "Cloud Computing Services",
    "Web Development Agencies / Webentwicklung",
    "Digital Marketing Agencies / Digitalagentur",
    "IT Consulting / IT-Beratung",
    "Cybersecurity Companies",
    "Data Analytics / Business Intelligence",
    "ERP Software / Enterprise Solutions",
    "Mobile App Development",
    "AI / Machine Learning Companies",
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
    print("  🇩🇪 GERMANY B2B SOFTWARE LEAD GENERATION")
    print(f"  Total Niches : {len(NICHES)}")
    print(f"  Total Cities : {len(CITIES)}")
    print(f"  Biz Per City : UNLIMITED (scrape all)")
    print(f"  Target Hubs  : {', '.join(CITIES[:5])} + {len(CITIES)-5} more")
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
            count = len(leads) if leads is not None else 0
            total_leads_collected += count
            print(f"\n[DONE] Niche '{niche}' completed. Found: {count} leads (Cumulative total: {total_leads_collected})", flush=True)

            # Run cleaner after each niche to keep dashboard up to date
            run_cleaner()

        except Exception as e:
            print(f"\n[ERROR] Scraping failed for niche '{niche}': {e}")
            run_cleaner()
            continue

        # Brief pause between niches to avoid rate limiting
        time.sleep(5)

    print("\n" + "=" * 60)
    print("  🎯 ALL NICHES & CITIES COMPLETED!")
    print(f"  Total Leads Generated: {total_leads_collected}")
    print("=" * 60)


if __name__ == "__main__":
    main()
