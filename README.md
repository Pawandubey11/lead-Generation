# LeadPulse Lead Generation

LeadPulse is a Python lead-generation dashboard with a Playwright-based scraper.

## Local setup on Windows

Requirements:

- Python 3.11 or 3.13
- PowerShell
- Internet access for package and Chromium downloads

Clone and start:

```powershell
git clone https://github.com/Pawandubey11/lead-Generation.git
cd lead-Generation
.\setup.ps1
.\run-dashboard.ps1
```

Open <http://127.0.0.1:8000>.

Setup creates `.venv`, installs dependencies and Chromium, and copies `.env.example` to `.env`.
The dashboard works in development mode without manually configuring the environment.

## Run the scraper CLI

```powershell
.\run-scraper.ps1 -BusinessType "gym" -Country "india" -MaxCities 30
```

Generated CSV files are written to `output/`.

## Docker

Docker is optional. Docker Desktop must be running:

```bash
docker compose up --build dashboard
```

Open <http://localhost:8000>.

To run the scraper interactively:

```bash
docker compose run --rm leadgen
```

For non-interactive Docker scraping, set these variables in `docker-compose.yml`:

```yaml
environment:
  - LEADPULSE_BUSINESS_TYPE=gym
  - LEADPULSE_COUNTRY=india
  - LEADPULSE_MAX_CITIES=30
```

## Project structure

- `dashboard/app.py` - FastAPI dashboard
- `dashboard/templates/` - dashboard UI
- `main.py` - scraper CLI entry point
- `scrapers/crawler.py` - Playwright and lead crawling logic
- `lead_cleaner.py` - lead cleanup and export
- `database/` - SQLite authentication database
- `output/` - generated lead exports
- `config/` - optional Google cookies configuration

## Configuration

Copy `.env.example` to `.env` and change values for your environment.

Never commit `.env`, `config/google_cookies.json`, database files, or lead exports.
The repository `.gitignore` already excludes these files.

## Troubleshooting

- Run `python --version`; Python 3.11 or 3.13 is recommended.
- If PowerShell blocks the scripts, run:
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- If Chromium is missing, run:
  `.\.venv\Scripts\python.exe -m playwright install chromium`
- If Docker is unavailable, use the local PowerShell setup above.
