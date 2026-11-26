"""
website_auditor.py
------------------
Quantitative website auditing engine for LeadPulse:
- Fast deterministic inspection: availability, SSL/HTTPS, mobile viewport,
  basic SEO metadata, CMS/tech stack detection, response TTFB, and sampled
  broken-link detection.
- Optional Google PageSpeed Insights v5 API integration (mobile + desktop
  performance scores and Core Web Vitals: LCP, CLS, INP, FCP).

Never fabricates metrics: missing or unavailable signals are reported explicitly
as None / "UNKNOWN" / unavailable.
"""

from __future__ import annotations

import logging
import os
import re
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

SOCIAL_OR_DIRECTORY_DOMAINS = (
    "facebook.com", "instagram.com", "linkedin.com", "justdial.com",
    "indiamart.com", "zomato.com", "swiggy.com", "linktr.ee",
    "sulekha.com", "tripadvisor.com", "yelp.com", "practo.com",
)

CMS_SIGNATURES = [
    ("WordPress", ("wp-content", "wp-includes", "wordpress")),
    ("Shopify", ("cdn.shopify.com", "shopify.theme", "myshopify")),
    ("Wix", ("wix.com", "wixstatic.com", "_wix")),
    ("Squarespace", ("squarespace.com", "static1.squarespace")),
    ("Webflow", ("webflow.com", "website-files.com")),
    ("Odoo Website", ("web.assets_frontend", "/web/login", "odoo")),
    ("Next.js", ("/_next/static", "__next")),
    ("React SPA", ("react-root", "data-reactroot")),
    ("Laravel / PHP", ("laravel", "csrf-token")),
]


def _detect_cms(html_lower: str, soup: BeautifulSoup, headers: dict) -> Optional[str]:
    gen = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
    if gen and gen.get("content"):
        return str(gen["content"]).strip()[:60]
    powered = str(headers.get("X-Powered-By", "")).strip()
    for label, markers in CMS_SIGNATURES:
        if any(m in html_lower for m in markers):
            return label
    if powered:
        return powered[:40]
    return None


def _check_broken_links(base_url: str, soup: BeautifulSoup, session: requests.Session, limit: int = 5) -> Dict[str, Any]:
    """Sample up to `limit` internal/navigation links via HEAD/GET to detect broken links."""
    base_host = urlparse(base_url).netloc.lower()
    checked: List[str] = []
    broken: List[Dict[str, Any]] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != base_host:
            continue
        if full in seen or full.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(full)
        checked.append(full)
        if len(checked) >= limit:
            break

    if not checked:
        return {"checked_count": 0, "broken_count": 0, "broken_links": []}

    def _probe(link_url: str):
        try:
            r = session.head(link_url, timeout=4, allow_redirects=True, verify=False)
            if r.status_code == 405:
                r = session.get(link_url, timeout=4, allow_redirects=True, verify=False)
            return link_url, r.status_code
        except Exception:
            return link_url, 0

    with ThreadPoolExecutor(max_workers=min(limit, 4)) as pool:
        for link_url, code in pool.map(_probe, checked):
            if code == 0 or code >= 400:
                broken.append({"url": link_url, "status_code": code})

    return {
        "checked_count": len(checked),
        "broken_count": len(broken),
        "broken_links": broken,
    }


def fetch_pagespeed(
    url: str,
    strategy: str = "mobile",
    api_key: Optional[str] = None,
    timeout: float = 20.0,
) -> Optional[Dict[str, Any]]:
    """
    Query Google PageSpeed Insights v5 API for mobile or desktop Core Web Vitals.
    Works optionally with GOOGLE_PAGESPEED_API_KEY (or unauthenticated quota if omitted).
    Returns None cleanly if unreachable or rate-limited.
    """
    if not url or not url.startswith("http"):
        return None

    key = api_key if api_key is not None else os.environ.get("GOOGLE_PAGESPEED_API_KEY", "").strip()
    params: Dict[str, Any] = {
        "url": url,
        "strategy": strategy if strategy in ("mobile", "desktop") else "mobile",
        "category": ["performance", "seo", "accessibility", "best-practices"],
    }
    if key:
        params["key"] = key

    try:
        resp = requests.get(PAGESPEED_API_URL, params=params, timeout=timeout)
        if resp.status_code != 200:
            logger.debug("PageSpeed (%s) HTTP %d for %s", strategy, resp.status_code, url)
            return None

        data = resp.json()
        lh = data.get("lighthouseResult", {})
        cats = lh.get("categories", {})
        audits = lh.get("audits", {})

        def _score(cat_key: str) -> Optional[int]:
            val = cats.get(cat_key, {}).get("score")
            return int(round(val * 100)) if isinstance(val, (int, float)) else None

        def _metric_ms(audit_key: str) -> Optional[int]:
            val = audits.get(audit_key, {}).get("numericValue")
            return int(round(val)) if isinstance(val, (int, float)) else None

        cls_raw = audits.get("cumulative-layout-shift", {}).get("numericValue")
        cls_val = round(float(cls_raw), 3) if isinstance(cls_raw, (int, float)) else None

        inp_ms = (
            _metric_ms("interaction-to-next-paint")
            or _metric_ms("experimental-interaction-to-next-paint")
            or _metric_ms("max-potential-fid")
        )

        return {
            "strategy": strategy,
            "performance_score": _score("performance"),
            "seo_score": _score("seo"),
            "accessibility_score": _score("accessibility"),
            "best_practices_score": _score("best-practices"),
            "lcp_ms": _metric_ms("largest-contentful-paint"),
            "fcp_ms": _metric_ms("first-contentful-paint"),
            "cls": cls_val,
            "inp_ms": inp_ms,
        }
    except Exception as exc:
        logger.debug("PageSpeed (%s) failed for %s: %s", strategy, url, exc)
        return None


def audit_website(
    raw_url: Optional[str],
    run_pagespeed: bool = False,
    check_links: bool = True,
) -> Dict[str, Any]:
    """
    Perform a comprehensive, non-fabricating technical audit of a business website.

    Returns dict with:
    - website_url, website_status (NO_WEBSITE | SOCIAL_ONLY | BROKEN_OR_INACTIVE | ACTIVE_OFFICIAL)
    - social_platform, http_status, has_valid_ssl, mobile_responsive
    - seo_checks (has_title, title_length, has_meta_description, has_h1, has_canonical, seo_basic_score)
    - cms_detected, response_time_ms, broken_links_info
    - mobile_metrics, desktop_metrics (from PageSpeed Insights when run_pagespeed=True)
    - issues (list of confirmed technical issues), positives (list of confirmed strengths)
    """
    base_result: Dict[str, Any] = {
        "website_url": None,
        "website_status": "NO_WEBSITE",
        "social_platform": None,
        "http_status": None,
        "has_valid_ssl": False,
        "mobile_responsive": False,
        "cms_detected": None,
        "response_time_ms": None,
        "seo_checks": {
            "has_title": False,
            "title_length": 0,
            "has_meta_description": False,
            "has_h1": False,
            "has_canonical": False,
            "seo_basic_score": 0,
        },
        "broken_links": {"checked_count": 0, "broken_count": 0, "broken_links": []},
        "mobile_pagespeed": None,
        "desktop_pagespeed": None,
        "performance_score": None,
        "seo_score": None,
        "lcp_ms": None,
        "cls": None,
        "inp_ms": None,
        "issues": [],
        "positives": [],
        "technical_issues_summary": "",
        "audited_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not raw_url or not str(raw_url).strip():
        base_result["issues"] = ["No official website listed"]
        base_result["technical_issues_summary"] = "No official website listed on business profile."
        return base_result

    url = str(raw_url).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    base_result["website_url"] = url

    domain = urlparse(url).netloc.lower()
    for s_dom in SOCIAL_OR_DIRECTORY_DOMAINS:
        if s_dom in domain:
            platform = s_dom.split(".")[0].title()
            base_result["website_status"] = "SOCIAL_ONLY"
            base_result["social_platform"] = platform
            base_result["has_valid_ssl"] = url.startswith("https://")
            base_result["issues"] = [f"Uses {platform} page instead of a standalone business website"]
            base_result["technical_issues_summary"] = (
                f"Uses {platform} directory/social profile rather than an owned website."
            )
            return base_result

    sess = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    t0 = time.time()
    try:
        # First check strict SSL verification, then fallback if cert invalid
        ssl_valid = False
        try:
            resp = sess.get(url, headers=headers, timeout=(4, 9), verify=True, allow_redirects=True)
            ssl_valid = str(resp.url).startswith("https://")
        except requests.exceptions.SSLError:
            resp = sess.get(url, headers=headers, timeout=(4, 9), verify=False, allow_redirects=True)
            ssl_valid = False

        elapsed_ms = int(round((time.time() - t0) * 1000))
        base_result["website_url"] = str(resp.url)
        base_result["http_status"] = resp.status_code
        base_result["response_time_ms"] = elapsed_ms
        base_result["has_valid_ssl"] = ssl_valid

        if resp.status_code >= 400:
            base_result["website_status"] = "BROKEN_OR_INACTIVE"
            base_result["issues"] = [f"Website returned HTTP {resp.status_code} error"]
            base_result["technical_issues_summary"] = f"Website returned HTTP {resp.status_code} (unreachable/error)."
            return base_result

        html_text = resp.text[:500000]
        html_lower = html_text.lower()
        soup = BeautifulSoup(html_text, "html.parser")

        base_result["website_status"] = "ACTIVE_OFFICIAL"
        viewport = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        mobile_ok = viewport is not None
        base_result["mobile_responsive"] = mobile_ok

        cms = _detect_cms(html_lower, soup, dict(resp.headers))
        base_result["cms_detected"] = cms

        # SEO metadata checks
        title_tag = soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        desc_text = (meta_desc.get("content") or "").strip() if meta_desc else ""
        h1_tag = soup.find("h1")
        canonical = soup.find("link", attrs={"rel": lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])]})

        seo_points = 0
        if title_text:
            seo_points += 30
        if desc_text:
            seo_points += 30
        if h1_tag and h1_tag.get_text(strip=True):
            seo_points += 20
        if canonical and canonical.get("href"):
            seo_points += 10
        if mobile_ok:
            seo_points += 10

        base_result["seo_checks"] = {
            "has_title": bool(title_text),
            "title_length": len(title_text),
            "has_meta_description": bool(desc_text),
            "has_h1": bool(h1_tag and h1_tag.get_text(strip=True)),
            "has_canonical": bool(canonical and canonical.get("href")),
            "seo_basic_score": seo_points,
        }
        base_result["seo_score"] = seo_points

        issues: List[str] = []
        positives: List[str] = []

        if ssl_valid:
            positives.append("Valid HTTPS / SSL certificate")
        else:
            issues.append("Missing or invalid HTTPS/SSL certificate")

        if mobile_ok:
            positives.append("Mobile viewport configured")
        else:
            issues.append("Missing mobile viewport meta tag")

        if not title_text:
            issues.append("Missing <title> tag")
        if not desc_text:
            issues.append("Missing meta description for SEO")
        if not (h1_tag and h1_tag.get_text(strip=True)):
            issues.append("Missing primary <h1> heading")
        if elapsed_ms > 3000:
            issues.append(f"Slow initial server response ({elapsed_ms} ms)")
        else:
            positives.append(f"Fast HTTP response ({elapsed_ms} ms)")

        if check_links:
            bl_info = _check_broken_links(str(resp.url), soup, sess, limit=5)
            base_result["broken_links"] = bl_info
            if bl_info["broken_count"] > 0:
                issues.append(f"{bl_info['broken_count']} broken internal link(s) detected")

        # Optional Google PageSpeed Insights v5 (mobile + desktop)
        if run_pagespeed:
            with ThreadPoolExecutor(max_workers=2) as ps_pool:
                f_mob = ps_pool.submit(fetch_pagespeed, str(resp.url), "mobile")
                f_desk = ps_pool.submit(fetch_pagespeed, str(resp.url), "desktop")
                mob = f_mob.result()
                desk = f_desk.result()

            base_result["mobile_pagespeed"] = mob
            base_result["desktop_pagespeed"] = desk
            if mob:
                base_result["performance_score"] = mob.get("performance_score")
                if mob.get("seo_score") is not None:
                    base_result["seo_score"] = mob["seo_score"]
                base_result["lcp_ms"] = mob.get("lcp_ms")
                base_result["cls"] = mob.get("cls")
                base_result["inp_ms"] = mob.get("inp_ms")

                perf = mob.get("performance_score")
                if perf is not None:
                    if perf < 50:
                        issues.append(f"Poor mobile PageSpeed score ({perf}/100)")
                    elif perf >= 80:
                        positives.append(f"Strong mobile PageSpeed score ({perf}/100)")
                lcp = mob.get("lcp_ms")
                if lcp is not None and lcp > 4000:
                    issues.append(f"Slow mobile LCP ({round(lcp / 1000, 1)}s > 4.0s threshold)")
                cls = mob.get("cls")
                if cls is not None and cls > 0.25:
                    issues.append(f"High layout instability CLS ({cls} > 0.25)")

        base_result["issues"] = issues
        base_result["positives"] = positives
        base_result["technical_issues_summary"] = (
            "; ".join(issues) if issues else "Website passes baseline SSL, mobile, and SEO checks."
        )
        return base_result

    except requests.exceptions.Timeout:
        base_result["website_status"] = "BROKEN_OR_INACTIVE"
        base_result["issues"] = ["Website request timed out"]
        base_result["technical_issues_summary"] = "Website timed out during audit."
        return base_result
    except Exception as exc:
        base_result["website_status"] = "BROKEN_OR_INACTIVE"
        base_result["issues"] = [f"Website unreachable: {str(exc)[:80]}"]
        base_result["technical_issues_summary"] = f"Connection failed: {str(exc)[:80]}"
        return base_result
    finally:
        try:
            sess.close()
        except Exception:
            pass
