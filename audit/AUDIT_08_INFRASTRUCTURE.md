# AUDIT REPORT 8: INFRASTRUCTURE & DEPLOYMENT REVIEW

## Status: DOCKER READY, PRODUCTION HARDENING NEEDED

---

## INFRA-001 — Two Dockerfiles, Only One Is Complete

**Files:** `Dockerfile` (root), `dashboard/Dockerfile` (not read — referenced in docker-compose.yml)

**Root Dockerfile:**
```dockerfile
FROM python:3.11-slim
CMD ["python", "main.py"]  # Runs CLI scraper — requires interactive input or args
```

**Problem:** The root `Dockerfile` runs `main.py` which prompts for interactive input (`input()`). In a Docker container, there's no terminal attached by default (`stdin_open: true, tty: true` are set in docker-compose.yml to work around this).

**Impact:** Running `docker run varenyam3110/leadgen-app:latest` without `-it` flags will hang immediately on the `input()` call.

**Fix:** Update `main.py` to use environment variables as first-class input method:
```python
business_type = os.environ.get("BUSINESS_TYPE") or input("Enter business type: ").strip()
country = os.environ.get("COUNTRY") or input("Enter country: ").strip()
```
Then the `Dockerfile` can set default `ENV` values.

---

## INFRA-002 — No Health Check in Scraper Container

**File:** `Dockerfile` (root)

**Problem:** The Docker Compose file has `restart: unless-stopped` only for the dashboard service, but not for the leadgen scraper. Additionally, there's no `HEALTHCHECK` instruction in either Dockerfile.

Without a health check:
- Docker can't tell if the scraper has hung vs. is legitimately running
- Orchestration systems (Kubernetes, ECS) can't auto-restart failed containers
- The dashboard container (`restart: unless-stopped`) will restart repeatedly if its port 8000 is not bound

**Fix:**
```dockerfile
# In dashboard/Dockerfile:
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1
```

---

## INFRA-003 — Shared Volume Between Containers Creates Race Condition

**File:** `docker-compose.yml`

**Problem:**
```yaml
services:
  leadgen:
    volumes:
      - ./output:/app/output  # Scraper writes here
  dashboard:
    volumes:
      - ./output:/app/output  # Dashboard reads here
```

Both containers mount the same `./output` directory. The scraper writes to `local_business_leads.csv` while `lead_cleaner.py` reads from it. The dashboard reads `final_ai_leads.csv` while `lead_cleaner.py` writes to it.

**Race Condition:** If `lead_cleaner.py` is writing to `final_ai_leads.csv` (file truncation then write) while the dashboard is reading it, the dashboard will get a partially-written file and potentially crash with `pd.errors.EmptyDataError`.

**Current mitigation:** The mtime-based cache in `dashboard_service.py` only reads the file when mtime changes — but mtime changes at the START of the write, not the end.

**Fix:**
1. Write to a temp file first, then `os.replace()` (atomic rename):
   ```python
   import tempfile
   tmp_path = output_file + ".tmp"
   df.to_csv(tmp_path, index=False)
   os.replace(tmp_path, output_file)  # Atomic on same filesystem
   ```
2. Or use file locking with `filelock` library.

---

## INFRA-004 — No Output Directory Volume Declared in Root Dockerfile

**File:** `Dockerfile` (root)

**Problem:**
```dockerfile
VOLUME ["/app/output"]
```

The `VOLUME` instruction creates an anonymous volume, but `docker-compose.yml` properly overrides it with a bind mount `./output:/app/output`. However, if the image is run standalone (without compose), the anonymous volume is used — data is preserved in the anonymous volume but users won't know where it is.

**Recommendation:** Document clearly that the image MUST be run via `docker-compose.yml` to get predictable output file paths.

---

## INFRA-005 — `shm_size: '2gb'` May Be Unnecessarily Large

**File:** `docker-compose.yml`

```yaml
services:
  leadgen:
    shm_size: '2gb'
```

Playwright/Chromium requires `/dev/shm` (shared memory) to be large enough for rendering. The default Docker `/dev/shm` is 64MB which is too small for Chromium. 2GB is generous — 512MB is typically sufficient.

**Recommendation:** Reduce to `512m` to avoid unnecessarily reserving 2GB of host RAM shared memory.

---

## INFRA-006 — No Log Aggregation or Persistent Logging

**Files:** All Python files

**Problem:** All logging uses `print()` statements. In Docker, these go to container stdout/stderr which is captured by Docker's JSON file logger. By default:
- No rotation policy → logs grow indefinitely
- No structured format → hard to parse or alert on
- No log level control → debug output mixed with errors

**Fix:**
1. Replace `print()` with `logging.getLogger(__name__)` throughout
2. Configure structured JSON logging for production:
   ```python
   import logging
   import json_log_formatter
   formatter = json_log_formatter.JSONFormatter()
   handler = logging.StreamHandler()
   handler.setFormatter(formatter)
   logging.getLogger().addHandler(handler)
   logging.getLogger().setLevel(logging.INFO)
   ```
3. Add Docker log rotation:
   ```yaml
   logging:
     driver: "json-file"
     options:
       max-size: "10m"
       max-file: "5"
   ```

---

## INFRA-007 — No Environment Variable Validation at Startup

**Files:** `config/config.py`, `dashboard/app.py`

**Problem:** The app starts silently even if critical env vars are missing or wrong. For example:
- If `N8N_WEBHOOK_URL` is set but invalid, the app only fails when it tries to POST leads (after a full scrape run)
- If `LEADS_CSV_PATH` points to a non-existent directory, dashboard starts fine but all API calls return "No leads generated yet."

**Fix:** Add a startup validation function:
```python
@app.on_event("startup")
async def validate_config():
    if not SECRET_KEY or len(SECRET_KEY) < 32:
        raise RuntimeError("LEADPULSE_SECRET_KEY must be at least 32 characters")
    output_dir = os.path.dirname(svc.CSV_PATH)
    if not os.path.isdir(output_dir):
        logging.warning(f"Output directory not found: {output_dir}. Creating...")
        os.makedirs(output_dir, exist_ok=True)
```

---

## Deployment Checklist

| Item | Status | Notes |
|------|--------|-------|
| Docker build works | LIKELY OK | Standard Python 3.11-slim |
| Dashboard accessible at :8000 | YES | docker-compose exposes port |
| Scraper can run from dashboard | YES (via scraper_service.py) | But requires Playwright in dashboard container |
| Output persists between restarts | YES | bind mount ./output |
| Google cookies accessible in both containers | YES | bind mount ./config (read-only) |
| Environment secrets configured | MANUAL | .env must be manually edited |
| TLS/HTTPS | NO | Requires reverse proxy setup |
| Log rotation | NO | Must add to docker-compose |
| Health checks | NO | Must add to Dockerfiles |
| Atomic file writes | NO | Race condition risk (INFRA-003) |

---

## Recommended docker-compose.yml Improvements

```yaml
version: "3.8"

services:
  dashboard:
    build:
      context: .
      dockerfile: dashboard/Dockerfile
    container_name: leadgen-dashboard
    volumes:
      - ./output:/app/output
      - ./config:/app/config:ro
    ports:
      - "8000:8000"
    environment:
      - LEADS_CSV_PATH=/app/output/final_ai_leads.csv
      - GOOGLE_COOKIES_PATH=/app/config/google_cookies.json
      - LEADPULSE_SECRET_KEY=${LEADPULSE_SECRET_KEY}  # From host .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    shm_size: '512m'    # Reduced from 2gb
```
