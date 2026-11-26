"""
dashboard_service.py
---------------------
Pure data-access / business-logic layer for the Lead Generation Dashboard.

This module ONLY reads from output/final_ai_leads.csv. It never writes to it
and never touches main.py / crawler.py / lead_cleaner.py, so the existing
crawling pipeline keeps working exactly as before.

Every public function in this file is defensive: if the CSV does not exist
yet (the crawler hasn't been run), every function returns an empty / zeroed
result instead of raising, so the dashboard can show
"No leads generated yet." instead of crashing.
"""

from __future__ import annotations

import io
import math
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# dashboard/ lives at <project_root>/dashboard, so the project root is one
# level up from this file's directory.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_THIS_DIR)

# Allow overriding via env var (handy for Docker volumes / tests) while
# defaulting to the real pipeline output location.
CSV_PATH = os.environ.get(
    "LEADS_CSV_PATH",
    os.path.join(PROJECT_ROOT, "output", "final_ai_leads.csv"),
)
LIVE_CSV_PATH = os.path.join(PROJECT_ROOT, "output", "local_business_leads.csv")

NO_DATA_MESSAGE = "No leads generated yet."

# ---------------------------------------------------------------------------
# Column mapping: raw CSV header -> internal snake_case field name
# ---------------------------------------------------------------------------

RAW_COLUMNS = [
    "business_name",
    "phone",
    "website",
    "address",
    "instagram",
    "facebook",
    "linkedin",
    "email",
    "city",
    "Has Website",
    "Has Email",
    "Has Social Media",
    "Contact Completeness %",
    "Lead Score",
    "Priority",
    "spin",
    "scraped_at",
    "source_name",
    "source_url",
]

RENAME_MAP = {
    "Contact Completeness %": "contact_completeness",
    "Lead Score": "lead_score",
    "Priority": "priority",
    "Has Website": "has_website",
    "Has Email": "has_email",
    "Has Social Media": "has_social_media",
}

STRING_FIELDS = [
    "business_name",
    "phone",
    "website",
    "address",
    "instagram",
    "facebook",
    "linkedin",
    "email",
    "city",
    "locality",
    "search_area",
    "business_type",
    "rating",
    "reviews",
    "has_website",
    "has_email",
    "has_social_media",
    "priority",
    "spin",
    "scraped_at",
    "source_name",
    "source_url",
]

TABLE_FIELDS = [
    "id",
    "business_name",
    "phone",
    "email",
    "website",
    "instagram",
    "facebook",
    "linkedin",
    "lead_score",
    "priority",
    "contact_completeness",
    "spin",
    "scraped_at",
    "source_name",
    "source_url",
]

DETAIL_EXTRA_FIELDS = [
    "address", "city", "locality", "search_area", "business_type",
    "rating", "reviews", "has_website", "has_email", "has_social_media",
]

VALID_PRIORITIES = {"Hot", "Warm", "Cold"}

SCORE_BUCKETS = [
    ("0-20", 0, 20),
    ("21-40", 21, 40),
    ("41-60", 41, 60),
    ("61-80", 61, 80),
    ("81-100", 81, 100),
]

COMPLETENESS_BUCKETS = [
    ("0-25%", 0, 25),
    ("26-50%", 26, 50),
    ("51-75%", 51, 75),
    ("76-100%", 76, 100),
]


# ---------------------------------------------------------------------------
# Loading — with mtime-based in-memory cache (Performance Fix #1)
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cached_df: Optional[pd.DataFrame] = None
_cached_mtime: float = 0.0


def csv_exists() -> bool:
    return os.path.isfile(CSV_PATH) or os.path.isfile(LIVE_CSV_PATH)


def _csv_mtime() -> float:
    """Return the newest dashboard CSV modification time."""
    mtimes = []
    for path in (CSV_PATH, LIVE_CSV_PATH):
        try:
            mtimes.append(os.path.getmtime(path))
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0


def load_leads() -> Optional[pd.DataFrame]:
    """
    Load and normalize the leads CSV.

    Uses an in-memory cache keyed on the file's mtime — the CSV is only
    re-read from disk when it has actually been modified.  Returns a
    *copy* so callers can freely mutate without polluting the cache.

    Returns None if the file does not exist (or is empty / unreadable),
    so callers can show the "No leads generated yet." state.
    """
    global _cached_df, _cached_mtime

    if not csv_exists():
        with _cache_lock:
            _cached_df = None
            _cached_mtime = 0.0
        return None

    live_mtime = 0.0
    try:
        live_mtime = os.path.getmtime(LIVE_CSV_PATH)
    except OSError:
        pass

    final_mtime = 0.0
    try:
        final_mtime = os.path.getmtime(CSV_PATH)
    except OSError:
        pass

    # The raw live file is the authoritative live dataset. It is written after
    # every extracted lead, while final is only rewritten after cleaning.
    # Prefer raw whenever it exists so filesystem/restore timestamps cannot hide
    # leads that have already been extracted.
    source_path = LIVE_CSV_PATH if os.path.isfile(LIVE_CSV_PATH) else CSV_PATH
    current_mtime = max(live_mtime, final_mtime)

    # Fast path: return cached copy if file hasn't changed
    with _cache_lock:
        if _cached_df is not None and current_mtime == _cached_mtime:
            return _cached_df.copy()

    # Slow path: re-read from disk
    try:
        df = pd.read_csv(source_path)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        with _cache_lock:
            _cached_df = None
            _cached_mtime = current_mtime
        return None

    if df.empty:
        with _cache_lock:
            _cached_df = None
            _cached_mtime = current_mtime
        return None

    df = df.rename(columns=RENAME_MAP)

    # Make sure every expected internal column exists, even if the CSV is
    # missing one (older runs, partial pipeline, etc.)
    for col in [
        "business_name", "phone", "website", "address", "instagram",
        "facebook", "linkedin", "email", "city", "locality", "search_area",
        "business_type", "rating", "reviews", "has_website", "has_email",
        "has_social_media", "contact_completeness", "lead_score", "priority",
        "spin", "scraped_at", "source_name", "source_url",
    ]:
        if col not in df.columns:
            df[col] = "Legacy Run" if col == "spin" else ("" if col in STRING_FIELDS else 0)

    # Clean string columns
    for col in STRING_FIELDS:
        df[col] = df[col].fillna("").astype(str).replace(["nan", "None", "null"], "").str.strip()
    if "reviews" in df.columns:
        df["reviews"] = df["reviews"].str.replace(r"\.0$", "", regex=True)

    # Clean numeric columns
    df["lead_score"] = pd.to_numeric(df["lead_score"], errors="coerce").fillna(0)
    df["contact_completeness"] = pd.to_numeric(
        df["contact_completeness"], errors="coerce"
    ).fillna(0)

    # Live/raw CSVs do not contain the cleaner's derived columns. Compute them
    # defensively so newly extracted leads appear immediately in the dashboard.
    has_web = df["website"].fillna("").astype(str).str.strip() != ""
    has_em = df["email"].fillna("").astype(str).str.strip() != ""
    has_ig = df["instagram"].fillna("").astype(str).str.strip() != ""
    has_fb = df["facebook"].fillna("").astype(str).str.strip() != ""
    has_li = df["linkedin"].fillna("").astype(str).str.strip() != ""
    has_phone = df["phone"].fillna("").astype(str).str.strip() != ""
    has_social = has_ig | has_fb | has_li

    df["has_website"] = np.where(has_web, "Yes", "No")
    df["has_email"] = np.where(has_em, "Yes", "No")
    df["has_social_media"] = np.where(has_social, "Yes", "No")
    filled = has_phone.astype(int) + has_web.astype(int) + has_em.astype(int) + has_ig.astype(int) + has_fb.astype(int) + has_li.astype(int)
    df["contact_completeness"] = (filled / 6.0 * 100).round(2)
    score = has_phone.astype(int) * 20 + has_web.astype(int) * 20 + has_em.astype(int) * 40 + has_ig.astype(int) * 10 + has_fb.astype(int) * 5 + has_li.astype(int) * 5
    df["lead_score"] = score
    df["priority"] = np.select([score >= 70, score >= 40], ["Hot", "Warm"], default="Cold")

    # Normalize priority casing / unknowns
    df["priority"] = df["priority"].where(df["priority"].isin(VALID_PRIORITIES), "Cold")

    df = df.reset_index(drop=True)
    df["id"] = df.index

    # Pre-compute concatenated lowercase search column (Performance Fix #9)
    df["_search"] = (
        df["business_name"].str.lower() + " " +
        df["phone"].str.lower() + " " +
        df["email"].str.lower() + " " +
        df["website"].str.lower() + " " +
        df["city"].str.lower() + " " +
        df["locality"].str.lower() + " " +
        df["business_type"].str.lower()
    )

    # Store the CSV mtime hash so the frontend can skip no-op refreshes
    df.attrs["_csv_mtime"] = current_mtime

    with _cache_lock:
        _cached_df = df
        _cached_mtime = current_mtime

    return df.copy()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats() -> Dict[str, Any]:
    df = load_leads()

    if df is None:
        return {
            "has_data": False,
            "message": NO_DATA_MESSAGE,
            "total_leads": 0,
            "hot_leads": 0,
            "warm_leads": 0,
            "cold_leads": 0,
            "avg_score": 0,
            "avg_completeness": 0,
        }

    priority_counts = df["priority"].value_counts()

    return {
        "has_data": True,
        "message": None,
        "total_leads": int(len(df)),
        "hot_leads": int(priority_counts.get("Hot", 0)),
        "warm_leads": int(priority_counts.get("Warm", 0)),
        "cold_leads": int(priority_counts.get("Cold", 0)),
        "avg_score": round(float(df["lead_score"].mean()), 1),
        "avg_completeness": round(float(df["contact_completeness"].mean()), 1),
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _bucket_counts(series: pd.Series, buckets: List[Tuple[str, int, int]]) -> Dict[str, int]:
    result = {}
    for label, low, high in buckets:
        result[label] = int(((series >= low) & (series <= high)).sum())
    return result


def get_charts() -> Dict[str, Any]:
    df = load_leads()

    if df is None:
        return {
            "has_data": False,
            "message": NO_DATA_MESSAGE,
            "priority_distribution": {"Hot": 0, "Warm": 0, "Cold": 0},
            "score_distribution": {label: 0 for label, _, _ in SCORE_BUCKETS},
            "completeness_distribution": {label: 0 for label, _, _ in COMPLETENESS_BUCKETS},
        }

    priority_counts = df["priority"].value_counts()
    priority_distribution = {
        "Hot": int(priority_counts.get("Hot", 0)),
        "Warm": int(priority_counts.get("Warm", 0)),
        "Cold": int(priority_counts.get("Cold", 0)),
    }

    score_distribution = _bucket_counts(df["lead_score"], SCORE_BUCKETS)
    completeness_distribution = _bucket_counts(df["contact_completeness"], COMPLETENESS_BUCKETS)

    return {
        "has_data": True,
        "message": None,
        "priority_distribution": priority_distribution,
        "score_distribution": score_distribution,
        "completeness_distribution": completeness_distribution,
    }


# ---------------------------------------------------------------------------
# Filtering / sorting / pagination (shared by /api/leads and exports)
# ---------------------------------------------------------------------------

SORTABLE_COLUMNS = {
    "business_name", "phone", "email", "website", "lead_score",
    "priority", "contact_completeness",
}


def get_unique_spins() -> List[str]:
    """Return a list of all unique spin values in the leads database."""
    df = load_leads()
    if df is None or "spin" not in df.columns:
        return []
    spins = df["spin"].dropna().unique()
    # Sort them nicely, ignoring empty ones
    return sorted([str(s) for s in spins if str(s).strip()])


def get_latest_spin() -> Optional[str]:
    """Return the spin value of the most recent scrape run in the dataset."""
    df = load_leads()
    if df is None or df.empty or "spin" not in df.columns:
        return None
    valid_spins = df[df["spin"].fillna("").str.strip() != "Legacy Run"]
    if valid_spins.empty:
        valid_spins = df
    if "scraped_at" in valid_spins.columns and valid_spins["scraped_at"].str.strip().any():
        sorted_df = valid_spins.sort_values(by="scraped_at", ascending=False)
        return str(sorted_df["spin"].iloc[0])
    return str(valid_spins["spin"].iloc[-1])


def apply_filters(
    df: pd.DataFrame,
    search: Optional[str] = None,
    priority: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    spin: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    city: Optional[str] = None,
    industry: Optional[str] = None,
    country: Optional[str] = None,
) -> pd.DataFrame:
    filtered = df

    # Use pre-computed _search column for fast text search (Performance Fix #9)
    if search:
        s = search.strip().lower()
        if s:
            if "_search" in filtered.columns:
                filtered = filtered[filtered["_search"].str.contains(s, na=False)]
            else:
                mask = (
                    filtered["business_name"].str.lower().str.contains(s, na=False)
                    | filtered["phone"].str.lower().str.contains(s, na=False)
                    | filtered["email"].str.lower().str.contains(s, na=False)
                    | filtered["website"].str.lower().str.contains(s, na=False)
                    | filtered["city"].str.lower().str.contains(s, na=False)
                )
                filtered = filtered[mask]

    if priority and priority.lower() != "all":
        filtered = filtered[filtered["priority"].str.lower() == priority.lower()]

    if min_score is not None:
        filtered = filtered[filtered["lead_score"] >= min_score]

    if max_score is not None:
        filtered = filtered[filtered["lead_score"] <= max_score]

    if city and city.lower() not in ("all", "none", "") and "city" in filtered.columns:
        city_clean = city.strip().lower()
        mask = (
            filtered["city"].astype(str).str.lower().str.contains(city_clean, na=False)
            | filtered["address"].astype(str).str.lower().str.contains(city_clean, na=False)
        )
        if "locality" in filtered.columns:
            mask = mask | (filtered["locality"].astype(str).str.lower().str.contains(city_clean, na=False))
        filtered = filtered[mask]

    if country and country.lower() not in ("all", "none", ""):
        c_clean = country.strip().lower()
        mask = (
            filtered["spin"].astype(str).str.lower().str.contains(c_clean, na=False)
            | filtered["address"].astype(str).str.lower().str.contains(c_clean, na=False)
            | filtered["city"].astype(str).str.lower().str.contains(c_clean, na=False)
        )
        if "country" in filtered.columns:
            mask = mask | (filtered["country"].astype(str).str.lower().str.contains(c_clean, na=False))
        filtered = filtered[mask]

    if industry and industry.lower() not in ("all", "none", ""):
        ind_clean = industry.split("/")[0].strip().lower()
        if ind_clean in ("b2b", "b2b companies", "b2b software", "software"):
            b2b_pattern = "software|it-|saas|cloud|webentwickl|digitalagentur|beratung|cybersecurity|analytics|erp|machine learning|wholesale|b2b|distributor|manufacturing|maschinenbau|logistics"
            mask = (
                filtered["spin"].astype(str).str.lower().str.contains(b2b_pattern, na=False)
                | filtered["business_name"].astype(str).str.lower().str.contains(b2b_pattern, na=False)
            )
        else:
            mask = (
                filtered["spin"].astype(str).str.lower().str.contains(ind_clean, na=False)
                | filtered["business_name"].astype(str).str.lower().str.contains(ind_clean, na=False)
            )
        if "business_type" in filtered.columns:
            mask = mask | (filtered["business_type"].astype(str).str.lower().str.contains(ind_clean, na=False))
        filtered = filtered[mask]

    if spin and spin.lower() != "all":
        filtered = filtered[filtered["spin"].str.lower() == spin.lower()]

    if start_date:
        # compare dates (YYYY-MM-DD)
        filtered = filtered[filtered["scraped_at"].str.slice(0, 10) >= start_date]

    if end_date:
        filtered = filtered[filtered["scraped_at"].str.slice(0, 10) <= end_date]

    return filtered


def apply_sort(df: pd.DataFrame, sort_by: Optional[str], sort_order: Optional[str]) -> pd.DataFrame:
    if not sort_by or sort_by not in SORTABLE_COLUMNS:
        sort_by = "lead_score"
    ascending = (sort_order or "desc").lower() == "asc"

    if df[sort_by].dtype == object:
        return df.sort_values(
            by=sort_by, ascending=ascending, key=lambda c: c.str.lower(), kind="mergesort"
        )
    return df.sort_values(by=sort_by, ascending=ascending, kind="mergesort")


def get_unique_cities() -> List[str]:
    """Return all unique cities in the dataset."""
    df = load_leads()
    if df is None or df.empty or "city" not in df.columns:
        return ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne", "Düsseldorf", "Stuttgart", "Leipzig", "Dresden", "Nuremberg"]
    cities = df["city"].dropna().astype(str).str.strip().unique().tolist()
    valid = sorted([c for c in cities if c and c.lower() not in ("nan", "none", "")])
    return valid if valid else ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne"]


def get_unique_industries() -> List[str]:
    """Return all standard target industries including B2B categories."""
    standard = [
        "Software Companies / Softwareunternehmen",
        "B2B Software & IT Companies",
        "IT Services / IT-Dienstleister",
        "SaaS Companies",
        "Wholesale / B2B Distributors",
        "Manufacturing / Maschinenbau",
        "Logistics / Transport",
        "Handwerk / Trades",
        "Construction Companies",
        "Real Estate / Immobilien",
        "Professional Services",
        "Hotels / Hospitality",
        "Healthcare / Medical Businesses",
        "Automotive Workshops / Dealers"
    ]
    df = load_leads()
    if df is not None and not df.empty and "spin" in df.columns:
        extracted = []
        for s in df["spin"].dropna().unique():
            cat = str(s).split(" in ")[0].split(" (")[0].strip()
            if cat and cat not in standard and cat not in extracted:
                extracted.append(cat)
        return standard + extracted
    return standard


def get_filtered_leads(
    search: Optional[str] = None,
    priority: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    spin: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    city: Optional[str] = None,
    industry: Optional[str] = None,
    country: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Returns the full filtered+sorted DataFrame (no pagination), or None if no data."""
    df = load_leads()
    if df is None:
        return None

    df = apply_filters(df, search, priority, min_score, max_score, spin, start_date, end_date, city=city, industry=industry, country=country)
    df = apply_sort(df, sort_by, sort_order)
    return df


def get_leads_page(
    search: Optional[str] = None,
    priority: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
    spin: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    city: Optional[str] = None,
    industry: Optional[str] = None,
    country: Optional[str] = None,
) -> Dict[str, Any]:
    df = get_filtered_leads(search, priority, min_score, max_score, sort_by, sort_order, spin, start_date, end_date, city=city, industry=industry, country=country)

    if df is None:
        return {
            "has_data": False,
            "message": NO_DATA_MESSAGE,
            "data": [],
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 0,
            "available_cities": get_unique_cities(),
            "available_industries": get_unique_industries(),
        }

    total = len(df)
    page = max(page, 1)
    page_size = max(min(page_size, 5000), 1)
    total_pages = max(math.ceil(total / page_size), 1)
    page = min(page, total_pages)

    start = (page - 1) * page_size
    end = start + page_size
    page_df = df.iloc[start:end]

    records = page_df[TABLE_FIELDS + DETAIL_EXTRA_FIELDS].to_dict(orient="records")

    return {
        "has_data": True,
        "message": "No matching leads found." if total == 0 else None,
        "data": records,
        "total": int(total),
        "page": int(page),
        "page_size": int(page_size),
        "total_pages": int(total_pages),
        "available_cities": get_unique_cities(),
        "available_industries": get_unique_industries(),
    }


# ---------------------------------------------------------------------------
# Export  (legacy internal columns — kept for backward compatibility)
# ---------------------------------------------------------------------------

EXPORT_COLUMNS = [
    "business_name", "phone", "email", "website", "instagram", "facebook",
    "linkedin", "city", "lead_score", "priority", "contact_completeness",
]

EXPORT_HEADERS = [
    "Business Name", "Phone", "Email", "Website", "Instagram", "Facebook",
    "LinkedIn", "City", "Lead Score", "Priority", "Contact Completeness %",
]


def _export_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Legacy internal export — not used by CSV/Excel endpoints anymore."""
    export_df = df[EXPORT_COLUMNS].copy()
    export_df.columns = EXPORT_HEADERS
    return export_df


# ---------------------------------------------------------------------------
# CRM Export — 16-column schema for direct CRM data ingestion
# ---------------------------------------------------------------------------

import re as _re

CRM_EXPORT_COLUMNS = [
    "External ID",
    "Name",
    "Company Name",
    "Contact Name",
    "Email",
    "Job Position",
    "Phone",
    "Mobile",
    "Street",
    "Street2",
    "City",
    "State",
    "Zip",
    "Country",
    "Website",
    "Notes",
]

# RFC 5322 simplified email validation regex
_EMAIL_RE = _re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)

# Indian PIN codes (6 digits) and generic postal/ZIP codes
_ZIP_RE = _re.compile(r"\b(\d{5,6})\b")

# Indian states — used to parse state from address strings
_INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "New Delhi", "NCT of Delhi",
    "Jammu and Kashmir", "Ladakh", "Chandigarh", "Puducherry",
    "Andaman and Nicobar Islands", "Dadra and Nagar Haveli",
    "Daman and Diu", "Lakshadweep",
]
# Pre-compile for fast matching (case-insensitive)
_STATE_RE = _re.compile(
    r"\b(" + "|".join(_re.escape(s) for s in _INDIAN_STATES) + r")\b",
    _re.IGNORECASE,
)

# Country name → ISO 3166-1 alpha-2 mapping (covers common scrape targets)
_COUNTRY_TO_ISO = {
    "india": "IN", "united states": "US", "usa": "US", "us": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "canada": "CA", "australia": "AU", "germany": "DE", "france": "FR",
    "italy": "IT", "spain": "ES", "brazil": "BR", "mexico": "MX",
    "japan": "JP", "china": "CN", "south korea": "KR", "korea": "KR",
    "singapore": "SG", "malaysia": "MY", "indonesia": "ID",
    "thailand": "TH", "vietnam": "VN", "philippines": "PH",
    "saudi arabia": "SA", "uae": "AE", "united arab emirates": "AE",
    "dubai": "AE", "qatar": "QA", "kuwait": "KW", "bahrain": "BH",
    "oman": "OM", "egypt": "EG", "south africa": "ZA", "nigeria": "NG",
    "kenya": "KE", "russia": "RU", "turkey": "TR", "netherlands": "NL",
    "belgium": "BE", "switzerland": "CH", "sweden": "SE", "norway": "NO",
    "denmark": "DK", "finland": "FI", "poland": "PL", "portugal": "PT",
    "ireland": "IE", "new zealand": "NZ", "pakistan": "PK",
    "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP",
    "argentina": "AR", "colombia": "CO", "chile": "CL", "peru": "PE",
    "israel": "IL", "taiwan": "TW", "hong kong": "HK",
}


def _resolve_country_code(row: dict) -> str:
    """
    Resolve ISO 3166-1 alpha-2 country code from available data.

    Priority order:
      1. Explicit ``country`` column value (if already a valid 2-letter code)
      2. Explicit ``country`` column value mapped through _COUNTRY_TO_ISO
      3. Country name extracted from ``spin`` text (e.g. "gym in india …")
      4. Empty string (zero hallucination)
    """
    # Try the explicit country column first
    raw_country = str(row.get("country", "")).strip()
    if raw_country:
        # Already a 2-letter ISO code?
        if len(raw_country) == 2 and raw_country.isalpha():
            return raw_country.upper()
        mapped = _COUNTRY_TO_ISO.get(raw_country.lower())
        if mapped:
            return mapped

    # Try extracting from spin: "gym in india (2026-07-04 23:40)"
    spin = str(row.get("spin", "")).strip()
    if spin:
        # Remove the date suffix in parentheses
        clean = _re.sub(r"\s*\(.*?\)\s*$", "", spin).strip().lower()
        # Try matching " in <country>" pattern
        m = _re.search(r"\bin\s+(.+)$", clean)
        if m:
            country_name = m.group(1).strip()
            mapped = _COUNTRY_TO_ISO.get(country_name)
            if mapped:
                return mapped

    return ""


def _parse_address(address: str) -> dict:
    """
    Best-effort parse of a free-text address into Street, State, Zip.

    Returns dict with keys: street, state, zip.
    Unparseable components → empty string (zero hallucination).
    """
    result = {"street": "", "state": "", "zip": ""}
    if not address or not address.strip():
        return result

    addr = address.strip()

    # Extract ZIP/PIN code
    zip_match = _ZIP_RE.search(addr)
    if zip_match:
        result["zip"] = zip_match.group(1)

    # Extract state
    state_match = _STATE_RE.search(addr)
    if state_match:
        result["state"] = state_match.group(1).title()

    # Street = full address (the most reliable representation)
    result["street"] = addr

    return result


def _validate_email(email: str) -> str:
    """Return the email if it passes RFC 5322 validation, else empty string."""
    if not email or not email.strip():
        return ""
    email = email.strip()
    return email if _EMAIL_RE.match(email) else ""


# Country-code → international dialing code for phone normalisation
_COUNTRY_DIAL_CODE = {
    "IN": "+91", "US": "+1",  "GB": "+44", "AU": "+61", "CA": "+1",
    "DE": "+49", "FR": "+33", "IT": "+39", "ES": "+34", "BR": "+55",
    "MX": "+52", "JP": "+81", "CN": "+86", "KR": "+82", "SG": "+65",
    "MY": "+60", "ID": "+62", "TH": "+66", "PH": "+63", "SA": "+966",
    "AE": "+971", "QA": "+974", "KW": "+965", "EG": "+20", "ZA": "+27",
    "NG": "+234", "KE": "+254", "PK": "+92", "BD": "+880", "LK": "+94",
    "NP": "+977", "TR": "+90", "NL": "+31", "BE": "+32", "CH": "+41",
    "SE": "+46", "NO": "+47", "DK": "+45", "FI": "+358", "PL": "+48",
    "PT": "+351", "IE": "+353", "NZ": "+64", "AR": "+54", "CO": "+57",
    "CL": "+56", "PE": "+51", "IL": "+972", "TW": "+886", "HK": "+852",
    "RU": "+7", "VN": "+84",
}


def _normalise_phone(phone: str, country_code: str) -> str:
    """
    Normalise a phone number to international format (e.g. +91 98765 43210).
    - If the number already starts with '+', return it unchanged.
    - Otherwise, strip a leading '0' (local trunk prefix) and prepend the
      international dialling code for the given country.
    - If no dial code is known, return the original number.
    """
    p = phone.strip()
    if not p:
        return ""
    if p.startswith("+"):
        return p  # already international format
    dial = _COUNTRY_DIAL_CODE.get(country_code, "")
    if not dial:
        return p  # unknown country — leave as-is
    # Strip leading trunk zero
    local = p.lstrip("0") if p.startswith("0") else p
    return f"{dial} {local}"


def filter_verified_leads(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter DataFrame to include ONLY verified leads:
    - Must have a valid email address (RFC 5322) OR high contact completeness (>= 50%).
    - Excludes unverified leads missing both valid email and phone contact info.
    """
    if df is None or df.empty:
        return df

    # Vectorized email validation using str.match() (Performance Fix #8)
    email_col = df["email"].fillna("").astype(str) if "email" in df.columns else pd.Series([""] * len(df), index=df.index)
    has_email_mask = email_col.str.strip().str.match(
        r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$', na=False
    )

    # Check for contact completeness (>= 50%)
    comp_col = "contact_completeness" if "contact_completeness" in df.columns else ("Contact Completeness %" if "Contact Completeness %" in df.columns else None)
    if comp_col:
        completeness = pd.to_numeric(df[comp_col], errors="coerce").fillna(0)
    else:
        completeness = pd.Series([0] * len(df), index=df.index)
    high_completeness_mask = completeness >= 50

    # Phone contact check
    phone_col = df["phone"].fillna("").astype(str) if "phone" in df.columns else pd.Series([""] * len(df), index=df.index)
    has_phone_mask = phone_col.str.strip() != ""

    verified_mask = has_email_mask | (high_completeness_mask & has_phone_mask)
    filtered_df = df[verified_mask].copy()
    
    # If filtering returned empty, return original df so export schema is preserved
    return filtered_df if not filtered_df.empty else df


def _build_crm_export_dataframe(df: pd.DataFrame, verified_only: bool = True) -> pd.DataFrame:
    """
    Transform the internal leads DataFrame into the strict 16-column CRM
    ingestion schema.

    - Filters for verified leads only when verified_only is True
    - Generates unique External IDs
    - Validates emails (RFC 5322)
    - Parses addresses into Street / State / Zip
    - Resolves country to ISO 3166-1 alpha-2
    - Builds Notes from business context only (no SPI)
    - Leaves unavailable fields blank (zero hallucination)

    Performance Fix #5: Vectorized — no iterrows().
    """
    if verified_only and df is not None and not df.empty:
        df = filter_verified_leads(df)

    if df is None or df.empty:
        return pd.DataFrame(columns=CRM_EXPORT_COLUMNS)

    # Work on a clean copy
    w = df.reset_index(drop=True).copy()
    n = len(w)

    # --- External IDs ---
    ext_ids = [f"crm_lead_{i + 1}" for i in range(n)]

    # --- String columns (safe fillna + strip) ---
    biz_name = w["business_name"].fillna("").astype(str).str.strip()
    address_col = w["address"].fillna("").astype(str).str.strip()
    city_col = w["city"].fillna("").astype(str).str.strip()
    website_col = w["website"].fillna("").astype(str).str.strip()
    email_raw = w["email"].fillna("").astype(str).str.strip()
    phone_raw = w["phone"].fillna("").astype(str).str.strip()
    priority_col = w["priority"].fillna("").astype(str).str.strip()
    score_col = w["lead_score"].fillna(0)
    comp_col = w["contact_completeness"].fillna(0)

    # --- Vectorized email validation ---
    valid_email_mask = email_raw.str.match(
        r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$', na=False
    )
    validated_emails = email_raw.where(valid_email_mask, "")

    # --- Address parsing (vectorized where possible) ---
    zip_extracted = address_col.str.extract(r'\b(\d{5,6})\b', expand=False).fillna("")
    state_extracted = address_col.str.extract(
        r'\b(' + '|'.join(_re.escape(s) for s in _INDIAN_STATES) + r')\b',
        expand=False, flags=_re.IGNORECASE
    ).fillna("").str.title()

    # --- Country resolution (vectorized for common cases) ---
    country_raw = w["country"].fillna("").astype(str).str.strip() if "country" in w.columns else pd.Series([""] * n, index=w.index)
    spin_col = w["spin"].fillna("").astype(str).str.strip() if "spin" in w.columns else pd.Series([""] * n, index=w.index)
    # Apply per-row only for country resolution (complex logic)
    country_codes = pd.Series(
        [_resolve_country_code({"country": c, "spin": s}) for c, s in zip(country_raw, spin_col)],
        index=w.index
    )

    # --- Phone normalisation (vectorized) ---
    phones_normalised = pd.Series(
        [_normalise_phone(p, cc) for p, cc in zip(phone_raw, country_codes)],
        index=w.index
    )

    # --- Notes (vectorized string concat) ---
    notes_priority = "Priority: " + priority_col
    notes_score = np.where(score_col != 0, " | Score: " + score_col.astype(str), "")
    notes_comp = np.where(comp_col != 0, " | Completeness: " + comp_col.astype(str) + "%", "")

    ig_col = w["instagram"].fillna("").astype(str).str.strip()
    fb_col = w["facebook"].fillna("").astype(str).str.strip()
    li_col = w["linkedin"].fillna("").astype(str).str.strip()
    notes_ig = np.where(ig_col != "", " | Instagram: " + ig_col, "")
    notes_fb = np.where(fb_col != "", " | Facebook: " + fb_col, "")
    notes_li = np.where(li_col != "", " | Linkedin: " + li_col, "")

    notes_all = notes_priority + notes_score + notes_comp + notes_ig + notes_fb + notes_li

    # --- Build the CRM DataFrame ---
    crm_df = pd.DataFrame({
        "External ID": ext_ids,
        "Name": biz_name,
        "Company Name": biz_name,
        "Contact Name": "",
        "Email": validated_emails,
        "Job Position": "",
        "Phone": phones_normalised,
        "Mobile": "",
        "Street": address_col,
        "Street2": "",
        "City": city_col,
        "State": state_extracted,
        "Zip": zip_extracted,
        "Country": country_codes,
        "Website": website_col,
        "Notes": notes_all,
    })

    return crm_df[CRM_EXPORT_COLUMNS]


# ---------------------------------------------------------------------------
# Public export functions (CSV + Excel)
# ---------------------------------------------------------------------------

def export_csv_bytes(df: pd.DataFrame, verified_only: bool = True) -> bytes:
    export_df = _build_crm_export_dataframe(df, verified_only=verified_only)
    buf = io.StringIO()
    export_df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def export_excel_bytes(df: pd.DataFrame, verified_only: bool = True) -> bytes:
    export_df = _build_crm_export_dataframe(df, verified_only=verified_only)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="CRM Leads")

        # Auto-fit columns so the exported file looks professional out of the box.
        worksheet = writer.sheets["CRM Leads"]
        for i, col in enumerate(export_df.columns, start=1):
            max_len = max(
                [len(str(col))] +
                [len(str(v)) for v in export_df.iloc[:, i - 1].astype(str)]
            )
            worksheet.column_dimensions[
                worksheet.cell(row=1, column=i).column_letter
            ].width = min(max(max_len + 3, 12), 55)
    buf.seek(0)
    return buf.getvalue()


CUSTOM_FIELD_LABEL_MAP = {
    "business_name": "Company Name",
    "email": "Email Address",
    "phone": "Phone Number",
    "website": "Website",
    "address": "Street Address",
    "city": "City",
    "locality": "Locality",
    "business_type": "Category / Industry",
    "rating": "Rating",
    "reviews": "Reviews",
    "lead_score": "Lead Quality Score",
    "priority": "Priority",
    "contact_completeness": "Contact Completeness %",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "spin": "Search Query / Niche",
    "scraped_at": "Extracted Date",
    "source_name": "Data Source",
    "source_url": "Source URL",
}

def export_custom_dataset(
    df: pd.DataFrame,
    fields: Optional[List[str]] = None,
    format: str = "csv",
    verified_only: bool = True
) -> bytes:
    """Exports dataset with custom selected columns in CSV or Excel format."""
    if verified_only and df is not None and not df.empty:
        df = filter_verified_leads(df)

    if df is None or df.empty:
        df = pd.DataFrame(columns=["business_name", "email", "phone", "website", "city"])

    # Default fields if none specified
    if not fields:
        fields = ["business_name", "email", "phone", "website", "city", "address", "lead_score", "priority"]

    # Filter available columns
    available_cols = [f for f in fields if f in df.columns]
    if not available_cols:
        available_cols = [c for c in ["business_name", "email", "phone", "website", "city"] if c in df.columns]

    out_df = df[available_cols].copy()

    # Rename columns to human-friendly headers
    rename_dict = {col: CUSTOM_FIELD_LABEL_MAP.get(col, col.replace("_", " ").title()) for col in available_cols}
    out_df = out_df.rename(columns=rename_dict)

    if format.lower() == "excel" or format.lower() == "xlsx":
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            out_df.to_excel(writer, index=False, sheet_name="Scraped Leads")
            worksheet = writer.sheets["Scraped Leads"]
            for i, col in enumerate(out_df.columns, start=1):
                max_len = max([len(str(col))] + [len(str(v)) for v in out_df.iloc[:, i - 1].astype(str)])
                worksheet.column_dimensions[worksheet.cell(row=1, column=i).column_letter].width = min(max(max_len + 3, 12), 55)
        buf.seek(0)
        return buf.getvalue()
    else:
        buf = io.StringIO()
        out_df.to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Verified Startup Leads Classification & Pipeline
# ---------------------------------------------------------------------------

def get_verified_startup_leads(
    stage: Optional[str] = None,
    service: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
) -> Dict[str, Any]:
    df = load_leads()
    if df is None or df.empty:
        return {
            "has_data": False,
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 0,
            "beginning_count": 0,
            "mid_count": 0,
            "leads": [],
        }

    # Filter for Verified Leads: Must have a valid email or high completeness (>= 50%)
    has_email_mask = df["email"].str.contains("@", na=False)
    high_completeness_mask = df["contact_completeness"] >= 50
    verified_mask = has_email_mask | high_completeness_mask
    v_df = df[verified_mask].copy()

    if v_df.empty:
        return {
            "has_data": False,
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 0,
            "beginning_count": 0,
            "mid_count": 0,
            "leads": [],
        }

    # Assign Startup Stage & Required Service Pitch
    # Vectorized classify_startup (Performance Fix #4 — replaces slow .apply(axis=1))
    has_web = v_df["has_website"].str.strip().str.lower().isin(["yes", "true", "1"])
    has_em = v_df["has_email"].str.strip().str.lower().isin(["yes", "true", "1"])
    has_social = v_df["has_social_media"].str.strip().str.lower().isin(["yes", "true", "1"])
    score = v_df["lead_score"]

    # Stage classification:
    # Mid-Level: Lead score >= 75 or established contact details
    # Beginning-Stage: everything else
    is_mid = (score >= 75) | (has_web & has_em & has_social)
    v_df["startup_stage"] = np.where(is_mid, "Mid-Level Startup", "Beginning-Stage Startup")
    v_df["stage_key"] = np.where(is_mid, "mid", "beginning")

    # Service Requirement Mapping (priority order via np.select)
    svc_conditions = [
        ~has_web,
        ~has_social,
        has_em,
    ]
    svc_names = ["Web Design & Digital Presence", "Social Media Growth & Marketing", "B2B Cold Email Outreach"]
    svc_keys = ["web_design", "seo", "email_outreach"]
    v_df["required_service"] = np.select(svc_conditions, svc_names, default="CRM Lead Automation & Scaling")
    v_df["service_key"] = np.select(svc_conditions, svc_keys, default="automation")

    # Calculate overall counts before filtering
    beginning_count = int((v_df["stage_key"] == "beginning").sum())
    mid_count = int((v_df["stage_key"] == "mid").sum())

    # Apply stage filter
    if stage and stage.lower() in ("beginning", "mid"):
        v_df = v_df[v_df["stage_key"] == stage.lower()]

    # Apply service filter
    if service and service.lower() != "all":
        v_df = v_df[v_df["service_key"] == service.lower()]

    # Apply search filter
    if search:
        s = search.strip().lower()
        if s:
            search_mask = (
                v_df["business_name"].str.lower().str.contains(s, na=False)
                | v_df["email"].str.lower().str.contains(s, na=False)
                | v_df["phone"].str.lower().str.contains(s, na=False)
                | v_df["city"].str.lower().str.contains(s, na=False)
                | v_df["required_service"].str.lower().str.contains(s, na=False)
            )
            v_df = v_df[search_mask]

    # Sort by lead score desc
    v_df = v_df.sort_values(by="lead_score", ascending=False)

    total_records = len(v_df)
    total_pages = max(1, math.ceil(total_records / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_df = v_df.iloc[start_idx:end_idx]

    records = page_df.to_dict("records")
    for r in records:
        r["id"] = int(r["id"]) if "id" in r else 0

    return {
        "has_data": True,
        "total": total_records,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "beginning_count": beginning_count,
        "mid_count": mid_count,
        "leads": records,
    }


# ---------------------------------------------------------------------------
# Advanced Sales, Audit & Pipeline Analytics
# ---------------------------------------------------------------------------

def get_advanced_analytics() -> Dict[str, Any]:
    """
    Aggregate deep LeadPulse analytics combining:
    - Geography (by city and locality)
    - Industry breakdown
    - Contact qualification & completeness stats
    - Website audit issue categories (from persisted audits + raw signals)
    - Explainable Business Opportunity Score distribution
    - CRM pipeline funnel, follow-up metrics, & conversion rates
    - AI research usage stats
    """
    from scoring.opportunity_scorer import compute_opportunity_score
    import crm_service as crm_svc
    import ai_service as ai_svc

    df = load_leads()
    crm_map = crm_svc.get_all_crm_map()
    audits_map = crm_svc.get_all_audits_map()
    ai_reports = ai_svc.get_all_reports() or {}
    ai_status = ai_svc.get_research_status() or {}
    ai_cfg = ai_svc.get_ai_config() or {}

    stage_counts = {s: 0 for s in crm_svc.CRM_STAGES}
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    overdue_followups = 0
    scheduled_followups = 0

    if df is None or df.empty:
        return {
            "has_data": False,
            "total_leads": 0,
            "qualified_leads": 0,
            "unqualified_leads": 0,
            "by_city": {},
            "by_locality": {},
            "by_industry": {},
            "contact_stats": {"with_email": 0, "with_phone": 0, "with_website": 0, "with_social": 0, "avg_completeness": 0.0},
            "opportunity_distribution": {"0-25": 0, "26-50": 0, "51-75": 0, "76-100": 0},
            "avg_opportunity_score": 0.0,
            "website_issues": {"NO_WEBSITE": 0, "SOCIAL_ONLY": 0, "BROKEN_OR_INACTIVE": 0, "NO_SSL": 0, "NOT_MOBILE": 0, "SLOW_PERFORMANCE": 0, "BROKEN_LINKS": 0, "AUDITED_HEALTHY": 0},
            "crm_funnel": stage_counts,
            "conversion_rates": {"qualification_rate": 0.0, "meeting_rate": 0.0, "proposal_rate": 0.0, "win_rate": 0.0, "overdue_followups": 0, "scheduled_followups": 0},
            "ai_usage": {
                "provider": ai_cfg.get("provider", "mock"),
                "model": ai_cfg.get("model", ""),
                "total_researched": len(ai_reports),
                "completed": ai_status.get("completed", 0),
                "failed": ai_status.get("failed", 0),
            },
        }

    records = df.to_dict(orient="records")
    total = len(records)

    by_city: Dict[str, int] = {}
    by_locality: Dict[str, int] = {}
    by_industry: Dict[str, int] = {}
    opp_buckets = {"0-25": 0, "26-50": 0, "51-75": 0, "76-100": 0}
    opp_scores: List[int] = []
    web_issues = {
        "NO_WEBSITE": 0,
        "SOCIAL_ONLY": 0,
        "BROKEN_OR_INACTIVE": 0,
        "NO_SSL": 0,
        "NOT_MOBILE": 0,
        "SLOW_PERFORMANCE": 0,
        "BROKEN_LINKS": 0,
        "AUDITED_HEALTHY": 0,
    }

    qualified = 0
    with_email = 0
    with_phone = 0
    with_website = 0
    with_social = 0

    for rec in records:
        name = str(rec.get("business_name") or "").strip()
        key = name.lower()

        city = str(rec.get("city") or "").strip() or "Unspecified"
        by_city[city] = by_city.get(city, 0) + 1

        loc = str(rec.get("locality") or "").strip()
        if loc:
            by_locality[loc] = by_locality.get(loc, 0) + 1

        ind = str(rec.get("business_type") or "").strip()
        if not ind:
            spin = str(rec.get("spin") or "").strip()
            ind = spin.split(" in ")[0].split(" (")[0].strip() if spin else "Unspecified"
        by_industry[ind] = by_industry.get(ind, 0) + 1

        has_em = bool(str(rec.get("email") or "").strip())
        has_ph = bool(str(rec.get("phone") or "").strip())
        has_web = bool(str(rec.get("website") or "").strip())
        has_soc = bool(str(rec.get("instagram") or "").strip() or str(rec.get("facebook") or "").strip() or str(rec.get("linkedin") or "").strip())

        if has_em:
            with_email += 1
        if has_ph:
            with_phone += 1
        if has_web:
            with_website += 1
        if has_soc:
            with_social += 1

        score_val = float(rec.get("lead_score") or 0)
        if has_em or (has_ph and score_val >= 40):
            qualified += 1

        # Persisted audit + opportunity score
        cached = audits_map.get(key)
        audit_obj = cached.get("audit") if cached else None
        ai_rep = ai_reports.get(name)

        if cached and cached.get("opportunity"):
            opp = cached["opportunity"]
        else:
            opp = compute_opportunity_score(rec, audit=audit_obj, ai_report=ai_rep)

        osc = int(opp.get("opportunity_score") or 0)
        opp_scores.append(osc)
        if osc <= 25:
            opp_buckets["0-25"] += 1
        elif osc <= 50:
            opp_buckets["26-50"] += 1
        elif osc <= 75:
            opp_buckets["51-75"] += 1
        else:
            opp_buckets["76-100"] += 1

        # Website issue categorization
        if audit_obj:
            ws = audit_obj.get("website_status", "ACTIVE_OFFICIAL")
            if ws in ("NO_WEBSITE", "SOCIAL_ONLY", "BROKEN_OR_INACTIVE"):
                web_issues[ws] += 1
            else:
                had_issue = False
                if not audit_obj.get("has_valid_ssl"):
                    web_issues["NO_SSL"] += 1
                    had_issue = True
                if not audit_obj.get("mobile_responsive"):
                    web_issues["NOT_MOBILE"] += 1
                    had_issue = True
                perf = audit_obj.get("performance_score")
                if isinstance(perf, (int, float)) and perf < 50:
                    web_issues["SLOW_PERFORMANCE"] += 1
                    had_issue = True
                bl = audit_obj.get("broken_links") or {}
                if isinstance(bl, dict) and bl.get("broken_count", 0) > 0:
                    web_issues["BROKEN_LINKS"] += 1
                    had_issue = True
                if not had_issue:
                    web_issues["AUDITED_HEALTHY"] += 1
        elif not has_web:
            web_issues["NO_WEBSITE"] += 1

        # CRM pipeline stage
        crm_rec = crm_map.get(key)
        stage = (crm_rec or {}).get("stage") or "New"
        if stage in stage_counts:
            stage_counts[stage] += 1
        else:
            stage_counts["New"] += 1
        fup = str((crm_rec or {}).get("follow_up_date") or "").strip()
        if fup:
            scheduled_followups += 1
            if fup < today_str and stage not in ("Won", "Lost"):
                overdue_followups += 1

    # Top sorted breakdowns
    top_cities = dict(sorted(by_city.items(), key=lambda x: -x[1])[:20])
    top_localities = dict(sorted(by_locality.items(), key=lambda x: -x[1])[:20])
    top_industries = dict(sorted(by_industry.items(), key=lambda x: -x[1])[:15])

    contacted_or_further = sum(stage_counts[s] for s in ("Contacted", "Meeting Scheduled", "Proposal Sent", "Won"))
    meetings = sum(stage_counts[s] for s in ("Meeting Scheduled", "Proposal Sent", "Won"))
    proposals = sum(stage_counts[s] for s in ("Proposal Sent", "Won"))
    won = stage_counts["Won"]

    denom_outreach = max(contacted_or_further, 1)
    return {
        "has_data": True,
        "total_leads": total,
        "qualified_leads": qualified,
        "unqualified_leads": total - qualified,
        "by_city": top_cities,
        "by_locality": top_localities,
        "by_industry": top_industries,
        "contact_stats": {
            "with_email": with_email,
            "with_phone": with_phone,
            "with_website": with_website,
            "with_social": with_social,
            "avg_completeness": round(float(df["contact_completeness"].mean()), 1),
        },
        "opportunity_distribution": opp_buckets,
        "avg_opportunity_score": round(sum(opp_scores) / max(len(opp_scores), 1), 1),
        "website_issues": web_issues,
        "crm_funnel": stage_counts,
        "conversion_rates": {
            "qualification_rate": round((qualified / total) * 100, 1),
            "meeting_rate": round((meetings / denom_outreach) * 100, 1) if contacted_or_further else 0.0,
            "proposal_rate": round((proposals / denom_outreach) * 100, 1) if contacted_or_further else 0.0,
            "win_rate": round((won / denom_outreach) * 100, 1) if contacted_or_further else 0.0,
            "overdue_followups": overdue_followups,
            "scheduled_followups": scheduled_followups,
        },
        "ai_usage": {
            "provider": ai_cfg.get("provider", "mock"),
            "model": ai_cfg.get("model", ""),
            "total_researched": len(ai_reports),
            "completed": ai_status.get("completed", 0),
            "failed": ai_status.get("failed", 0),
        },
    }
