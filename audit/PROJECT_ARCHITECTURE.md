# LeadPulse — Complete Project Architecture

## 1. High-Level Overview

LeadPulse is a B2B lead generation platform that:
1. Scrapes business listings from Google Maps via Playwright automation
2. Crawls business websites to extract emails and social media links
3. Cleans, scores, and de-duplicates the extracted leads
4. Presents them through a FastAPI-powered web dashboard
5. Exports filtered results as CSV or Excel (CRM-formatted)

---

## 2. Component Map

```
lead Generation/
├── main.py                        ← CLI entry point (interactive/server mode)
├── batch_scraper.py               ← Multi-niche Germany batch orchestrator (8 niches x 10 cities)
├── scrape_germany_b2b.py          ← IT/Software Germany batch orchestrator (12 niches x 20 cities)
├── lead_cleaner.py                ← Cleans, scores, and exports final CSVs
├── check_leads.py                 ← One-off analysis script (city breakdown)
├── export_google_cookies.py       ← Utility to validate Google cookie export

config/
  config.py                        ← HEADERS, OUTPUT_FILE, N8N webhook config (env-driven)
  constants.py                     ← EMAIL_REGEX, keyword filters
  google_cookies.json              ← Injected into Playwright to bypass consent walls

scrapers/
  crawler.py                       ← CORE: Google Maps Playwright scraper + city discovery
  website_scraper.py               ← Legacy website scraper (NOT used by crawler.py)
  email_extractor.py               ← Legacy email extractor (NOT used by crawler.py)
  utils.py                         ← (empty/placeholder)

dashboard/
  app.py                           ← FastAPI application (all routes)
  dashboard_service.py             ← Data layer: CSV loading, filtering, scoring, export
  scraper_service.py               ← Background thread orchestrator for live scraping
  templates/index.html             ← Single-page dashboard HTML
  static/js/dashboard.js           ← Client-side JS: state, filtering, export, polling
  static/css/style.css             ← Dashboard styling

database/
  auth_db.py                       ← SQLite auth: users, settings, services (PBKDF2 hashing)
  mongodb.py                       ← MongoDB connection helper (NOT actively used)
  schemas.py                       ← Minimal lead schema definition (NOT actively used)

output/                            ← Generated at runtime
  local_business_leads.csv         ← Raw scraped leads (crawler writes here)
  final_ai_leads.csv               ← Cleaned/scored leads (lead_cleaner reads here)
  verified_leads_export.csv        ← Filtered verified leads
```

---

## 3. Data Flow Diagram

```
USER (Browser)
    |
    v
[Dashboard UI - index.html + dashboard.js]
    |  POST /api/scrape/start
    v
[FastAPI - app.py]
    |  calls
    v
[scraper_service.py - background thread]
    |  calls generate_leads()
    v
[scrapers/crawler.py]
    |
    +--- [City Discovery]
    |      Wikipedia API > list of cities for target country
    |
    +--- [Google Maps Scraping - Playwright/Chromium]
    |      URL: google.com/maps/search/{business_type}+in+{city}
    |      > Scroll feed > collect /place/ links
    |      > For each business: open link, extract h1, phone, address, website
    |
    +--- [Website Crawling - requests + BeautifulSoup]
    |      extract_socials_and_email(website_url)
    |      > GET website > regex for emails, links for social media
    |
    +--- Saves to: output/local_business_leads.csv
         |
         v
    [lead_cleaner.py - subprocess]
         |  reads local_business_leads.csv
         |  de-duplicates by business_name + spin
         |  scores: phone=20, website=20, email=40, ig=10, fb=5, li=5
         |  classifies: Hot(70+), Warm(40-69), Cold(<40)
         |  saves output/final_ai_leads.csv
         |  saves output/verified_leads_export.csv
         |  optionally POSTs to N8N webhook
         v
    [dashboard_service.py]
         |  reads final_ai_leads.csv (mtime-cached)
         |  provides: stats, charts, filtered leads, exports
         v
    [Dashboard UI] < polls /api/scrape/status every 1 second while running
         |
         v
    [User downloads CSV/Excel via /api/export/custom]
```

---

## 4. Authentication Flow

```
POST /api/auth/register  > db.create_user() > SQLite users table
POST /api/auth/login     > db.verify_user() > creates HMAC session token > Cookie
GET  /api/leads          > Depends(get_current_user_id) > reads cookie > decodes token

CRITICAL FLAW: get_current_user_id() falls back to first user in DB if no token!
Any unauthenticated request gets served as the first registered user.
```

---

## 5. Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Web Framework | FastAPI | 0.132.0 |
| ASGI Server | Uvicorn | 0.41.0 |
| Browser Automation | Playwright (Chromium) | 1.61.0 |
| HTML Parsing | BeautifulSoup4 | 4.14.3 |
| Data Processing | Pandas | 3.0.5 |
| Excel Export | openpyxl | latest |
| Auth Storage | SQLite (WAL mode) | built-in |
| Primary DB | File-based CSV | — |
| Secondary DB | MongoDB | localhost:27017 (unused) |
| Container | Docker + docker-compose | — |
| CRM Integration | N8N webhook | optional |
| Template Engine | Jinja2 | latest |

---

## 6. External API Integrations

| API | Purpose | Type | Auth | Cost |
|-----|---------|------|------|------|
| Wikipedia REST API | City discovery for target countries | HTTP GET | None | Free |
| Google Maps (web) | Business discovery via Playwright | Browser scrape | Cookie injection | Terms risk |
| N8N Webhook | Post-processing lead delivery | HTTP POST | Secret header | Optional |

---

## 7. Lead Scoring Algorithm (lead_cleaner.py lines 92-102)

```
score = phone*20 + website*20 + email*40 + instagram*10 + facebook*5 + linkedin*5
Max score: 100

Hot  = score >= 70
Warm = score >= 40
Cold = score < 40
```

NOTE: "Verified" is based solely on presence of '@' in email string.
No MX record check, no domain validation, no mailbox verification.

---

## 8. Data Model

### Raw Lead (output/local_business_leads.csv)
```
business_name | phone | website | address | instagram | facebook | linkedin | email | city | spin | scraped_at
```

### Cleaned Lead (output/final_ai_leads.csv)
```
business_name | phone | website | address | instagram | facebook | linkedin | email | city |
Has Website | Has Email | Has Social Media | Contact Completeness % | Lead Score | Priority |
spin | scraped_at
```

### CRM Export Schema (16 columns)
```
External ID | Name | Company Name | Contact Name | Email | Job Position |
Phone | Mobile | Street | Street2 | City | State | Zip | Country | Website | Notes
```

### Auth DB (SQLite)
```
users(id, email, password_hash, created_at)
user_settings(user_id, sender_name, sender_title, sender_company)
user_services(user_id, service_key, service_name, service_description, custom_pain_point)
```
