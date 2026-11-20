"""
app.py
------
FastAPI application for the Lead Generation Dashboard.

Run with:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
(from inside the dashboard/ folder)
"""

from __future__ import annotations

from typing import Optional
import os
import shutil
import subprocess
import sys

from fastapi import FastAPI, Query, Request, File, UploadFile, Depends, status, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import hmac
import hashlib
import time
import base64

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    from dotenv import load_dotenv
    env_path = os.path.join(_PARENT_DIR, ".env")
    load_dotenv(dotenv_path=env_path)
except Exception:
    pass

import database.auth_db as db

import dashboard_service as svc
import scraper_service

app = FastAPI(
    title="LeadPulse Scraper & Exporter",
    description="Streamlined Lead Scraper, Data Verification & Custom CRM Export Hub",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Ensure static and templates dirs exist
os.makedirs(os.path.join(_THIS_DIR, "static", "css"), exist_ok=True)
os.makedirs(os.path.join(_THIS_DIR, "static", "js"), exist_ok=True)
os.makedirs(os.path.join(_THIS_DIR, "templates"), exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(_THIS_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_THIS_DIR, "templates"))

# ---------------------------------------------------------------------------
# Session & JWT token authentication helpers (Zero-Dependency Secure Tokens)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Secret key — fail fast in production if not properly configured
# ---------------------------------------------------------------------------

import secrets as _secrets
import logging as _logging

_DEV_MODE = os.environ.get("LEADPULSE_DEV_MODE", "false").lower() == "true"
SECRET_KEY = os.environ.get("LEADPULSE_SECRET_KEY", "")

if not SECRET_KEY or len(SECRET_KEY) < 32:
    if _DEV_MODE:
        # In dev mode: auto-generate an ephemeral key and warn clearly
        SECRET_KEY = _secrets.token_hex(32)
        _logging.basicConfig(level=_logging.WARNING)
        _logging.warning(
            "\n" + "=" * 70 +
            "\n  SECURITY WARNING: LEADPULSE_SECRET_KEY is not set or too short." +
            "\n  Using an auto-generated key — sessions will NOT persist restarts." +
            "\n  Set LEADPULSE_SECRET_KEY in your .env file for persistent sessions." +
            "\n  Generate: python -c \"import secrets; print(secrets.token_hex(32))\"" +
            "\n" + "=" * 70
        )
    else:
        raise RuntimeError(
            "LEADPULSE_SECRET_KEY must be set to at least 32 random characters.\n"
            "Generate: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "Then add to .env: LEADPULSE_SECRET_KEY=<generated_value>"
        )


def create_session_token(user_id: int) -> str:
    expiry = int(time.time()) + 86400 * 7  # 7 days
    msg = f"{user_id}:{expiry}".encode()
    signature = hmac.new(SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
    token = f"{user_id}:{expiry}:{signature}"
    return base64.urlsafe_b64encode(token.encode()).decode()


def verify_session_token(token: str) -> Optional[int]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        user_id_str, expiry_str, signature = decoded.split(":")
        user_id = int(user_id_str)
        expiry = int(expiry_str)
        if time.time() > expiry:
            return None
        msg = f"{user_id}:{expiry}".encode()
        expected_sig = hmac.new(SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected_sig, signature):
            return user_id
    except Exception:
        pass
    return None


def get_current_user_id(request: Request) -> int:
    """
    Extract and validate the current user from the session cookie.

    In DEV_MODE (LEADPULSE_DEV_MODE=true, the default), unauthenticated
    requests fall back to the first user in the DB so the dashboard works
    out-of-the-box without requiring login.

    In production (LEADPULSE_DEV_MODE=false), unauthenticated requests
    receive HTTP 401 — no data is returned without valid credentials.
    """
    token = request.cookies.get("session_token")
    user_id = verify_session_token(token) if token else None
    if not user_id:
        if _DEV_MODE:
            # Dev convenience: auto-login as first user
            conn = db.get_db_connection()
            user = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
            conn.close()
            return user["id"] if user else 1
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user_id


def require_authenticated_user(request: Request) -> int:
    """Require a real session; never use development-mode fallback."""
    token = request.cookies.get("session_token")
    user_id = verify_session_token(token) if token else None
    if not user_id:
        if _DEV_MODE:
            client_host = getattr(request.client, "host", "")
            if client_host in ("127.0.0.1", "::1", "localhost"):
                conn = db.get_db_connection()
                user = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
                conn.close()
                if user:
                    return int(user["id"])
                return 1
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user_id


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ScrapeRequest(BaseModel):
    business_type: str
    scope: str = "country"
    country: Optional[str] = None
    cities: Optional[str] = None
    max_cities: int = Field(default=30, ge=1, le=200)
    max_leads_per_city: int = Field(default=20, ge=1, le=200)

class AuthRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

class UserSettingsUpdateRequest(BaseModel):
    sender_name: str
    sender_title: str
    sender_company: str

class UserServiceUpdateRequest(BaseModel):
    service_key: str
    service_name: str
    service_description: str
    custom_pain_point: str


# ---------------------------------------------------------------------------
# Root, Favicon & API Discovery Endpoints
# ---------------------------------------------------------------------------

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return RedirectResponse(url="/static/favicon.svg")

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/info")
def api_info():
    return {
        "name": "LeadPulse Scraper API",
        "status": "online",
        "version": "2.1.0",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "health": "/api/health",
        "endpoints": {
            "leads": "/api/leads",
            "export_custom": "/api/export/custom",
            "export_csv": "/api/export/csv",
            "export_excel": "/api/export/excel",
            "scrape_status": "/api/scrape/status",
            "scrape_start": "/api/scrape/start",
            "scrape_stop": "/api/scrape/stop"
        }
    }


# ---------------------------------------------------------------------------
# API: Authentication Routes
# ---------------------------------------------------------------------------

@app.post("/api/auth/register")
def api_register(req: RegisterRequest):
    user_id = db.create_user(req.email, req.password)
    if user_id == -1:
        return {"success": False, "message": "Email address already registered."}
    return {"success": True, "message": "User registered successfully."}

@app.post("/api/auth/login")
def api_login(req: AuthRequest, response: Response):
    user = db.verify_user(req.email, req.password)
    if not user:
        return {"success": False, "message": "Invalid email or password."}
    
    token = create_session_token(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400 * 7,
        samesite="lax"
    )
    return {"success": True, "message": "Logged in successfully."}

@app.post("/api/auth/logout")
def api_logout(response: Response):
    response.delete_cookie("session_token")
    return {"success": True, "message": "Logged out successfully."}

@app.get("/api/auth/me")
def api_me(request: Request):
    user_id = get_current_user_id(request)
    conn = db.get_db_connection()
    user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    email = user["email"] if user else "rakeshvakeel000@gmail.com"
    return {"success": True, "email": email}


# ---------------------------------------------------------------------------
# API: User Settings & Services Profile
# ---------------------------------------------------------------------------

@app.get("/api/user/settings")
def api_get_settings(user_id: int = Depends(get_current_user_id)):
    settings = db.get_user_settings(user_id)
    services = db.get_user_services(user_id)
    return {
        "success": True,
        "settings": settings,
        "services": services
    }

@app.post("/api/user/settings")
def api_save_settings(req: UserSettingsUpdateRequest, user_id: int = Depends(get_current_user_id)):
    db.save_user_settings(
        user_id,
        req.sender_name,
        req.sender_title,
        req.sender_company
    )
    return {"success": True, "message": "Profile settings saved successfully."}

@app.post("/api/user/services")
def api_save_services(req: UserServiceUpdateRequest, user_id: int = Depends(get_current_user_id)):
    db.save_user_service(
        user_id,
        req.service_key,
        req.service_name,
        req.service_description,
        req.custom_pain_point
    )
    return {"success": True, "message": f"Service details for {req.service_key} saved."}


# ---------------------------------------------------------------------------
# API: stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def api_stats(user_id: int = Depends(get_current_user_id)):
    return svc.get_stats()


# ---------------------------------------------------------------------------
# API: charts
# ---------------------------------------------------------------------------

@app.get("/api/charts")
def api_charts(user_id: int = Depends(get_current_user_id)):
    return svc.get_charts()


# ---------------------------------------------------------------------------
# API: consolidated dashboard (Performance Fix #2 — single request)
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
def api_dashboard(
    search: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    max_score: Optional[int] = Query(None),
    spin: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("lead_score"),
    sort_order: Optional[str] = Query("desc"),
    page: Optional[int] = Query(1, ge=1),
    page_size: Optional[int] = Query(25, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
):
    """Returns stats, charts, leads, and spins in one response — avoids 4 separate CSV reads."""
    return {
        "stats": svc.get_stats(),
        "charts": svc.get_charts(),
        "leads": svc.get_leads_page(
            search=search, priority=priority,
            min_score=min_score, max_score=max_score,
            sort_by=sort_by, sort_order=sort_order,
            page=page, page_size=page_size,
            spin=spin, start_date=start_date, end_date=end_date,
            city=city, industry=industry,
        ),
        "spins": svc.get_unique_spins(),
        "available_cities": svc.get_unique_cities(),
        "available_industries": svc.get_unique_industries(),
        "data_hash": str(svc._csv_mtime()),
    }


# ---------------------------------------------------------------------------
# API: data-hash (Performance Fix #7 — change detection)
# ---------------------------------------------------------------------------

@app.get("/api/data-hash")
def api_data_hash():
    """Lightweight endpoint returning only the CSV mtime. Frontend polls this
    to decide whether a full refresh is needed."""
    return {"data_hash": str(svc._csv_mtime())}


# ---------------------------------------------------------------------------
# API: leads (search / filter / sort / paginate)
# ---------------------------------------------------------------------------

@app.get("/api/leads")
def api_leads(
    search: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    max_score: Optional[int] = Query(None),
    spin: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("lead_score"),
    sort_order: Optional[str] = Query("desc"),
    page: Optional[int] = Query(1, ge=1),
    page_size: Optional[int] = Query(100, ge=1, le=5000),
    user_id: int = Depends(get_current_user_id)
):
    return svc.get_leads_page(
        search=search,
        priority=priority,
        min_score=min_score,
        max_score=max_score,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
        spin=spin,
        start_date=start_date,
        end_date=end_date,
        city=city,
        industry=industry,
        country=country,
    )


@app.get("/api/startup-leads")
def api_startup_leads(
    stage: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: Optional[int] = Query(1, ge=1),
    page_size: Optional[int] = Query(25, ge=1, le=100),
    user_id: int = Depends(get_current_user_id)
):
    return svc.get_verified_startup_leads(
        stage=stage,
        service=service,
        search=search,
        page=page,
        page_size=page_size
    )


@app.get("/api/spins")
def api_spins():
    return {
        "spins": svc.get_unique_spins()
    }


# ---------------------------------------------------------------------------
# Export: CSV / Excel (respects current filters, ignores pagination)
# ---------------------------------------------------------------------------

def build_export_filename(
    df=None,
    search: Optional[str] = None,
    spin: Optional[str] = None,
    city: Optional[str] = None,
    industry: Optional[str] = None,
    country: Optional[str] = None,
    extension: str = "csv"
) -> str:
    """Dynamically generates export filename formatted by active industry, city/country, and search."""
    import re

    ind_label = ""
    loc_label = ""

    if industry and industry.lower() not in ("all", "none", ""):
        ind_label = industry.split("/")[0].strip()

    if city and city.lower() not in ("all", "none", ""):
        loc_label = city.strip()
    elif country and country.lower() not in ("all", "none", ""):
        loc_label = country.strip()

    # If not explicitly provided via params, inspect the filtered dataset
    if not ind_label and df is not None and not df.empty and "spin" in df.columns:
        non_empty = df["spin"].dropna().astype(str).str.strip()
        non_empty = non_empty[non_empty != ""]
        if not non_empty.empty:
            raw_label = non_empty.iloc[0]
            clean_label = re.sub(r"\s*\(.*?\)\s*$", "", raw_label).strip()
            if " in " in clean_label:
                parts = clean_label.split(" in ", 1)
                ind_label = parts[0].strip()
                if not loc_label:
                    loc_label = parts[1].strip()
            else:
                ind_label = clean_label

    if not ind_label and df is not None and not df.empty and "business_type" in df.columns:
        biz = df["business_type"].dropna().unique()
        if len(biz) >= 1 and str(biz[0]).strip():
            ind_label = str(biz[0]).strip()

    if not loc_label and df is not None and not df.empty and "city" in df.columns:
        cities = [str(c).strip() for c in df["city"].dropna().unique() if str(c).strip()]
        if len(cities) == 1:
            loc_label = cities[0]

    if search and not ind_label and not loc_label:
        search_clean = re.sub(r"[^\w\s-]", "", search).strip()
        if search_clean:
            loc_label = search_clean

    if ind_label and loc_label:
        combined = f"{ind_label}_{loc_label}_leads"
    elif ind_label:
        combined = f"{ind_label}_leads"
    elif loc_label:
        combined = f"{loc_label}_leads"
    else:
        combined = "leads_export"

    clean_name = re.sub(r"[^\w\s-]", "", combined)
    clean_name = re.sub(r"[\s_]+", "_", clean_name).strip("_")
    return f"{clean_name}.{extension}"


@app.get("/api/export/csv")
def export_csv(
    user_id: int = Depends(require_authenticated_user),
    search: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None, ge=0, le=100),
    max_score: Optional[float] = Query(None, ge=0, le=100),
    sort_by: Optional[str] = Query("lead_score"),
    sort_order: Optional[str] = Query("desc"),
    spin: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    verified_only: Optional[bool] = Query(True),
    latest: Optional[bool] = Query(False),
):
    if latest and not spin:
        spin = svc.get_latest_spin()

    df = svc.get_filtered_leads(search, priority, min_score, max_score, sort_by, sort_order, spin, start_date, end_date, city=city, industry=industry, country=country)
    if df is None:
        import pandas as pd
        df = pd.DataFrame(columns=svc.CRM_EXPORT_COLUMNS)

    content = svc.export_csv_bytes(df, verified_only=verified_only if verified_only is not None else True)
    filename = build_export_filename(df=df, search=search, spin=spin, city=city, industry=industry, country=country, extension="csv")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export/excel")
def export_excel(
    user_id: int = Depends(require_authenticated_user),
    search: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None, ge=0, le=100),
    max_score: Optional[float] = Query(None, ge=0, le=100),
    sort_by: Optional[str] = Query("lead_score"),
    sort_order: Optional[str] = Query("desc"),
    spin: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    verified_only: Optional[bool] = Query(True),
    latest: Optional[bool] = Query(False),
):
    if latest and not spin:
        spin = svc.get_latest_spin()

    df = svc.get_filtered_leads(search, priority, min_score, max_score, sort_by, sort_order, spin, start_date, end_date, city=city, industry=industry, country=country)
    if df is None:
        import pandas as pd
        df = pd.DataFrame(columns=svc.CRM_EXPORT_COLUMNS)

    content = svc.export_excel_bytes(df, verified_only=verified_only if verified_only is not None else True)
    filename = build_export_filename(df=df, search=search, spin=spin, city=city, industry=industry, country=country, extension="xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export/custom")
def export_custom(
    user_id: int = Depends(require_authenticated_user),
    format: str = Query("csv", description="csv | excel"),
    fields: Optional[str] = Query(None, description="Comma separated fields e.g. business_name,email,phone,website,city"),
    search: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None, ge=0, le=100),
    max_score: Optional[float] = Query(None, ge=0, le=100),
    sort_by: Optional[str] = Query("lead_score"),
    sort_order: Optional[str] = Query("desc"),
    spin: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    verified_only: Optional[bool] = Query(True),
):
    df = svc.get_filtered_leads(search, priority, min_score, max_score, sort_by, sort_order, spin, city=city, industry=industry, country=country)
    field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    
    ext = "xlsx" if format.lower() in ("excel", "xlsx") else "csv"
    content = svc.export_custom_dataset(
        df=df,
        fields=field_list,
        format=ext,
        verified_only=verified_only if verified_only is not None else True
    )
    
    filename = build_export_filename(df=df, search=search, spin=spin, city=city, industry=industry, country=country, extension=ext)
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if ext == "xlsx" else "text/csv"
    
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export/latest/csv")
def export_latest_csv(user_id: int = Depends(require_authenticated_user)):
    output_dir = os.path.join(_PARENT_DIR, "output")
    file_path = os.path.join(output_dir, "germany_automotive_leads_latest.csv")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Latest export file not found")
    return FileResponse(
        path=file_path,
        filename="germany_automotive_leads_latest.csv",
        media_type="text/csv"
    )


@app.get("/api/export/latest/excel")
def export_latest_excel(user_id: int = Depends(require_authenticated_user)):
    output_dir = os.path.join(_PARENT_DIR, "output")
    file_path = os.path.join(output_dir, "germany_automotive_leads_latest.xlsx")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Latest export file not found")
    return FileResponse(
        path=file_path,
        filename="germany_automotive_leads_latest.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------------------------------------------------------------------------
# Health check (useful for Docker healthcheck / uptime monitoring)
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "csv_found": svc.csv_exists(), "csv_path": svc.CSV_PATH}


# ---------------------------------------------------------------------------
# Scraper control
# ---------------------------------------------------------------------------

@app.post("/api/scrape/start")
def scrape_start(req: ScrapeRequest, user_id: int = Depends(get_current_user_id)):
    return scraper_service.start_scrape(
        business_type=req.business_type,
        scope=req.scope,
        country=req.country,
        cities=req.cities,
        max_cities=req.max_cities,
        max_leads_per_city=req.max_leads_per_city,
    )


@app.get("/api/scrape/status")
def scrape_status():
    return scraper_service.get_scrape_status()


@app.post("/api/scrape/stop")
def scrape_stop():
    return scraper_service.stop_scrape()


# ---------------------------------------------------------------------------
# Debug: inspect output files on server (requires auth + dev mode only)
# ---------------------------------------------------------------------------

@app.get("/api/debug/files")
def debug_files(user_id: int = Depends(get_current_user_id)):
    """
    Returns basic file metadata for the output directory.
    Requires authentication. Only available in dev mode.
    Does NOT return environment variables or file contents (security hardening).
    """
    if not _DEV_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debug endpoint is disabled in production mode."
        )

    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    files_info = {}
    if os.path.exists(output_dir):
        for f in os.listdir(output_dir):
            p = os.path.join(output_dir, f)
            if os.path.isfile(p):
                files_info[f] = {
                    "size_bytes": os.path.getsize(p),
                    "modified_time": os.path.getmtime(p),
                }
            else:
                files_info[f] = "directory"
    else:
        files_info["error"] = f"output directory not found at: {output_dir}"

    # NOTE: env vars and file contents are intentionally NOT returned (SEC-003)
    return {
        "cwd": os.getcwd(),
        "files": files_info,
    }


# ===========================================================================
# AI Business Intelligence endpoints
# ===========================================================================

import ai_service as ai_svc  # noqa: E402 — imported here to avoid circular import at startup


class AIResearchRequest(BaseModel):
    """Request body for starting AI research."""
    business_names: List[str] = Field(default_factory=list, description="Names of leads to research")


class AIReportMarkRequest(BaseModel):
    business_name: str
    reviewed: bool = True


@app.get("/api/ai/config")
def ai_config():
    """Return AI configuration (no secrets exposed)."""
    return ai_svc.get_ai_config()


@app.get("/api/ai/status")
def ai_status():
    """Return current AI research queue status."""
    return ai_svc.get_research_status()


@app.post("/api/ai/research/start")
def ai_research_start(req: AIResearchRequest, user_id: int = Depends(get_current_user_id)):
    """
    Start background AI research for the selected leads.
    Pass business_names as an array; pass [] to research all current leads.
    """
    df = svc.load_leads()
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="No leads found")

    all_leads = df.to_dict(orient="records")

    if req.business_names:
        selected = [
            ld for ld in all_leads
            if ld.get("business_name") in req.business_names
        ]
    else:
        selected = all_leads

    if not selected:
        raise HTTPException(status_code=400, detail="No matching leads found")

    result = ai_svc.start_research(selected)
    return result


@app.post("/api/ai/research/stop")
def ai_research_stop():
    """Stop ongoing AI research."""
    return ai_svc.stop_research()


@app.post("/api/ai/research/retry")
def ai_research_retry(user_id: int = Depends(get_current_user_id)):
    """Retry companies that failed in the previous research run."""
    df = svc.load_leads()
    leads = df.to_dict(orient="records") if df is not None else []
    return ai_svc.retry_failed_research(leads)


@app.get("/api/ai/report/{business_name}")
def ai_company_report(business_name: str):
    """Return the AI research report for a single company."""
    report = ai_svc.get_company_report(business_name)
    if report is None:
        raise HTTPException(status_code=404, detail="No report found for this company")
    return report


@app.get("/api/ai/reports")
def ai_all_reports():
    """Return all completed AI research results."""
    return ai_svc.get_all_reports()


@app.get("/api/ai/export/enriched")
def ai_export_enriched(user_id: int = Depends(require_authenticated_user)):
    """Export leads merged with AI research as an enriched CSV."""
    df = svc.load_leads()
    leads = df.to_dict(orient="records") if df is not None else []
    csv_bytes = ai_svc.export_enriched_csv(leads)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=systemaops_enriched_leads.csv"},
    )

