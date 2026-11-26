import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

import re
import time
import json
import logging
import requests
import pandas as pd
import urllib3
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, parse_qs, unquote

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("crawler")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_THIS_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    try:
        _fh = logging.FileHandler(os.path.join(LOG_DIR, "crawler.log"), encoding="utf-8")
        _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(_fh)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Cookie injection — optional Google consent bypass (non-expired only)
# ---------------------------------------------------------------------------

COOKIE_SEARCH_PATHS = [
    os.environ.get("GOOGLE_COOKIES_PATH", ""),
    os.path.join(PROJECT_ROOT, "config", "google_cookies.json"),
    "/app/config/google_cookies.json",
]


def _load_cookies() -> list:
    """Load non-expired Google cookies from JSON file. Returns [] if not found."""
    now = time.time()
    for path in COOKIE_SEARCH_PATHS:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                valid = []
                for c in raw:
                    exp = c.get("expires") or c.get("expirationDate")
                    if exp and isinstance(exp, (int, float)) and exp > 0 and exp < now:
                        continue
                    valid.append(c)
                logger.info(
                    "Cookies loaded from %s — %d/%d non-expired cookies",
                    os.path.basename(path), len(valid), len(raw),
                )
                return valid
            except Exception as e:
                logger.warning("Cookie load failed from %s: %s", os.path.basename(path), e)
    logger.info("No google_cookies.json found — running clean browser context")
    return []


def _inject_cookies(context, cookies: list):
    """Inject cookies into a Playwright browser context."""
    if not cookies:
        return
    try:
        playwright_cookies = []
        for c in cookies:
            entry = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".google.com"),
                "path": c.get("path", "/"),
            }
            if "secure" in c:
                entry["secure"] = c["secure"]
            if "httpOnly" in c:
                entry["httpOnly"] = c["httpOnly"]
            if "sameSite" in c and c["sameSite"] in ("Strict", "Lax", "None"):
                entry["sameSite"] = c["sameSite"]
            playwright_cookies.append(entry)
        context.add_cookies(playwright_cookies)
    except Exception as e:
        logger.warning("Cookie injection error: %s", e)


logger.info("CRAWLER V3.1 LOADED (accurate selectors + resource blocking + concurrent enrichment)")


# ============================================
# PROGRESS CALLBACK (used by dashboard)
# ============================================

class ScrapeCancelled(Exception):
    """Raised by the progress callback to abort a running scrape."""
    pass

_progress_callback = None

def set_progress_callback(fn):
    """Set a callback fn(event_type: str, data: dict) for live progress."""
    global _progress_callback
    _progress_callback = fn

def clear_progress_callback():
    """Remove the progress callback (restores default CLI-only behaviour)."""
    global _progress_callback
    _progress_callback = None

def _notify(event_type, data=None):
    """Fire the callback if one is registered. Silently no-ops otherwise."""
    if _progress_callback is not None:
        _progress_callback(event_type, data or {})


# ============================================
# CITY DISCOVERY (COUNTRY MODE)
# ============================================

def fetch_cities_from_wikipedia(country, max_cities=30):
    """Dynamically fetch major cities for any country using Wikipedia's API."""
    headers = {"User-Agent": "LeadGenBot/1.0 (Educational lead generation tool)"}
    country_clean = country.strip().title().replace(" ", "_")

    candidate_titles = [
        f"List_of_cities_in_{country_clean}_by_population",
        f"List_of_cities_and_towns_in_{country_clean}",
        f"List_of_largest_cities_in_{country_clean}",
        f"List_of_cities_in_{country_clean}",
    ]

    for title in candidate_titles:
        try:
            html_response = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "parse", "page": title, "format": "json", "prop": "text"},
                headers=headers,
                timeout=12,
            )
            if html_response.status_code != 200:
                continue
            html_data = html_response.json()
            if "error" in html_data:
                continue
            html_content = html_data["parse"]["text"]["*"]
            soup = BeautifulSoup(html_content, "html.parser")
            tables = soup.find_all("table", {"class": "wikitable"})
            if not tables:
                continue

            cities = []
            blacklist_terms = [
                "census", "population", "metropolitan", "urban agglomeration",
                "state", "province", "territory", "district", "region",
                "wikipedia", "citation", "reference", "list of",
                "municipal corporation", "capital", "country"
            ]

            for table in tables:
                rows = table.find_all("tr")
                header_cells = rows[0].find_all(["th", "td"]) if rows else []
                header_texts = [h.get_text(strip=True).lower() for h in header_cells]
                city_col_index = None
                for idx, text in enumerate(header_texts):
                    if "city" in text or "name" in text or "town" in text:
                        city_col_index = idx
                        break

                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    if city_col_index is not None and city_col_index < len(cells):
                        target_cells = [cells[city_col_index]]
                    elif len(cells) > 1:
                        target_cells = [cells[1]]
                    else:
                        target_cells = [cells[0]]

                    for cell in target_cells:
                        link = cell.find("a")
                        if link and link.get_text(strip=True):
                            city_name = link.get_text(strip=True)
                            city_name_lower = city_name.lower()
                            is_blacklisted = any(term in city_name_lower for term in blacklist_terms)
                            if (2 < len(city_name) < 40 and not city_name.isdigit()
                                    and not is_blacklisted and city_name not in cities):
                                cities.append(city_name)

                if len(cities) >= 5:
                    break
                else:
                    cities = []

            if cities:
                logger.info("Found %d cities via Wikipedia page: %s", len(cities), title)
                return cities[:max_cities]

        except Exception as e:
            logger.warning("Wikipedia lookup failed for '%s': %s", title, str(e)[:80])
            continue

    return []


def fetch_cities_via_wikipedia_search(country, max_cities=30):
    """Fallback: uses Wikipedia's search API to find cities pages."""
    headers = {"User-Agent": "LeadGenBot/1.0 (Educational lead generation tool)"}
    try:
        search_response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "list": "search",
                "srsearch": f"list of cities in {country} by population",
                "format": "json", "srlimit": 5,
            },
            headers=headers,
            timeout=12,
        )
        if search_response.status_code != 200:
            return []

        results = search_response.json().get("query", {}).get("search", [])
        for result in results:
            page_title = result.get("title", "")
            if not page_title:
                continue
            html_response = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "parse", "page": page_title, "format": "json", "prop": "text"},
                headers=headers,
                timeout=12,
            )
            if html_response.status_code != 200:
                continue
            html_data = html_response.json()
            if "error" in html_data:
                continue
            html_content = html_data["parse"]["text"]["*"]
            soup = BeautifulSoup(html_content, "html.parser")
            tables = soup.find_all("table", {"class": "wikitable"})
            if not tables:
                continue

            cities = []
            blacklist_terms = [
                "census", "population", "metropolitan", "urban agglomeration",
                "state", "province", "territory", "district", "region",
                "wikipedia", "citation", "reference", "list of",
                "municipal corporation", "capital", "country"
            ]
            for table in tables:
                rows = table.find_all("tr")
                header_cells = rows[0].find_all(["th", "td"]) if rows else []
                header_texts = [h.get_text(strip=True).lower() for h in header_cells]
                city_col_index = None
                for idx, text in enumerate(header_texts):
                    if "city" in text or "name" in text or "town" in text:
                        city_col_index = idx
                        break
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    if city_col_index is not None and city_col_index < len(cells):
                        target_cells = [cells[city_col_index]]
                    elif len(cells) > 1:
                        target_cells = [cells[1]]
                    else:
                        target_cells = [cells[0]]
                    for cell in target_cells:
                        link = cell.find("a")
                        if link and link.get_text(strip=True):
                            city_name = link.get_text(strip=True)
                            city_name_lower = city_name.lower()
                            is_blacklisted = any(term in city_name_lower for term in blacklist_terms)
                            if (2 < len(city_name) < 40 and not city_name.isdigit()
                                    and not is_blacklisted and city_name not in cities):
                                cities.append(city_name)
                if len(cities) >= 5:
                    break
                else:
                    cities = []
            if cities:
                logger.info("Found %d cities via Wikipedia search: %s", len(cities), page_title)
                return cities[:max_cities]

    except Exception as e:
        logger.warning("Wikipedia search fallback failed: %s", str(e)[:80])

    return []


def get_cities(country, max_cities=30):
    if not country or not str(country).strip():
        logger.info("No country specified. Skipping city lookup.")
        return []
    logger.info("Looking up major cities for '%s'...", country)
    cities = fetch_cities_from_wikipedia(country, max_cities=max_cities)
    if cities:
        return cities
    logger.info("Direct lookup failed — trying Wikipedia search...")
    cities = fetch_cities_via_wikipedia_search(country, max_cities=max_cities)
    if cities:
        return cities
    logger.warning("Could not find city list for '%s'. Using country name as single location.", country)
    return [country]


# ============================================
# BROWSER HELPERS (with resource blocking)
# ============================================

_CONSENT_TITLES = [
    "before you continue", "sign in", "consent", "google accounts",
    "verify it's you", "choose an account", "we use cookies",
]

_LOADED_COOKIES: list = None


def _get_cookies() -> list:
    global _LOADED_COOKIES
    if _LOADED_COOKIES is None:
        _LOADED_COOKIES = _load_cookies()
    return _LOADED_COOKIES


def launch_browser(p):
    return p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            "--memory-pressure-off",
            "--js-flags=--max-old-space-size=256",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run",
            "--mute-audio",
            "--blink-settings=imagesEnabled=false",
            "--lang=en-IN",
        ]
    )


def _route_block_heavy(route):
    """Block heavy non-DOM assets (images, fonts, map tiles) so Google Maps loads 5-10x faster."""
    try:
        rtype = route.request.resource_type
        if rtype in ("image", "media", "font"):
            return route.abort()
        url = route.request.url
        if "maps/vt" in url or "khms" in url or "streetviewpixels" in url or "ggpht.com" in url:
            return route.abort()
        return route.continue_()
    except Exception:
        return route.continue_()


def new_context(browser, inject_cookies: bool = True, block_heavy: bool = False):
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    if block_heavy:
        context.route("**/*", _route_block_heavy)
    # Inject EU Google Consent bypass cookies so cloud servers in EU (e.g. Frankfurt) never stall on consent.google.com
    try:
        context.add_cookies([
            {"name": "CONSENT", "value": "YES+cb.20210328-17-p0.en+FX+417", "domain": ".google.com", "path": "/"},
            {"name": "SOCS", "value": "CAISHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiA_LyaBg", "domain": ".google.com", "path": "/"},
        ])
    except Exception:
        pass
    if inject_cookies:
        _inject_cookies(context, _get_cookies())
    return context


def new_page(browser, inject_cookies: bool = True, block_heavy: bool = False):
    """Create a context+page with resource blocking and optional cookies."""
    ctx = new_context(browser, inject_cookies=inject_cookies, block_heavy=block_heavy)
    return ctx.new_page()


def dismiss_consent_wall(page):
    """Detect and click Google's cookie consent dialog ONLY when actually on a consent page."""
    try:
        current_url = page.url or ""
        title = (page.title() or "").lower()
    except Exception:
        return False

    if "consent.google" not in current_url and "before you continue" not in title:
        return False

    consent_selectors = [
        'button:has-text("Accept all")',
        'button:has-text("I agree")',
        'form[action*="consent"] button >> nth=-1',
        'button[aria-label="Accept all"]',
        '#L2AGLb',
    ]

    for attempt in range(2):
        try:
            logger.info("Consent wall detected at: %s", current_url[:80])
            for sel in consent_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click(timeout=4000)
                        logger.info("Dismissed Google consent wall (attempt %d)", attempt + 1)
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                        page.wait_for_timeout(1000)
                        if "consent.google" not in (page.url or ""):
                            return True
                        break
                except Exception:
                    continue
        except Exception:
            pass

    return False


def _save_debug_artifacts(page, city):
    """Saves a screenshot + HTML snapshot for failure diagnosis."""
    try:
        debug_dir = os.path.join(OUTPUT_DIR, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        safe_city = re.sub(r"[^a-zA-Z0-9_-]", "_", city)
        png_path = os.path.join(debug_dir, f"{safe_city}.png")
        html_path = os.path.join(debug_dir, f"{safe_city}.html")
        page.screenshot(path=png_path, timeout=10000)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        logger.info("Saved debug artifacts: %s, %s", png_path, html_path)
    except Exception as debug_err:
        logger.warning("Could not save debug artifacts: %s", str(debug_err)[:80])


# ============================================
# EXTRACT EMAILS + SOCIALS FROM WEBSITE (POOLED + CONCURRENT)
# ============================================

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}")
_EMAIL_FULL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}$")

_EMAIL_BLACKLIST_DOMAINS = {
    "example.com", "domain.com", "email.com", "company.com", "yourdomain.com",
    "yourmail.com", "sentry.io", "wixpress.com", "squarespace.com", "shopify.com",
    "wordpress.org", "elementor.com", "webflow.com", "amazonaws.com",
    "cloudflare.com", "jsdelivr.net", "fontawesome.com", "ueni.com",
}
_EMAIL_BLACKLIST_SUBSTRINGS = (
    "example.", "wixpress", "sentry", "yourmail", "yourdomain",
)
_EMAIL_BLACKLIST_PREFIXES = {
    "noreply", "no-reply", "donotreply", "bounce", "mailer-daemon",
    "postmaster", "daemon", "void", "you", "yourname", "your-name",
    "name", "username", "user", "johndoe", "john.doe", "janedoe",
    "jane.doe", "test", "example", "sample", "demo",
}

_INSTAGRAM_RE = re.compile(r'instagram\.com/(?!explore|p/|reel/|stories/|tv/|accounts/)([^/?#\s"\']+)', re.IGNORECASE)
_FACEBOOK_RE  = re.compile(r'facebook\.com/(?!sharer|share\.php|share/|login|dialog|tr\?|events/|groups/pages/|photo|video|watch|hashtag)([^/?#\s"\']+)', re.IGNORECASE)
_LINKEDIN_RE  = re.compile(r'linkedin\.com/(?:company|in|school)/([^/?#\s"\']+)', re.IGNORECASE)


def _is_valid_scraped_email(email: str) -> bool:
    """Validate candidate email and reject placeholder/asset strings."""
    if not email:
        return False
    em = unquote(str(email)).strip().strip(".,;:<>\"'")
    if len(em) > 100 or not _EMAIL_FULL_RE.match(em):
        return False
    el = em.lower()
    if re.search(r'\.(png|jpg|jpeg|gif|svg|webp|woff|woff2|ttf|js|css)$', el):
        return False
    local_part, domain = el.rsplit("@", 1)
    if local_part in _EMAIL_BLACKLIST_PREFIXES:
        return False
    if domain in _EMAIL_BLACKLIST_DOMAINS:
        return False
    if any(sub in domain for sub in _EMAIL_BLACKLIST_SUBSTRINGS):
        return False
    return True


def _clean_social_url(href: str) -> str:
    """Normalise a social URL and strip tracking query params."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    elif not href.startswith("http"):
        return ""
    href = re.sub(r'[?&](utm_[^&]*|fbclid=[^&]*|ref=[^&]*|source=[^&]*)(&|$)', '', href)
    href = re.sub(r'[?&]$', '', href)
    return href.split("?")[0].rstrip("/")


def _unwrap_website_url(href: str) -> str:
    """Unwrap Google /url?q=... redirects and strip UTM params if present."""
    if not href:
        return ""
    href = href.strip()
    if "google.com/url?" in href or href.startswith("/url?"):
        try:
            qs = parse_qs(urlparse(href).query)
            if "q" in qs and qs["q"]:
                href = qs["q"][0]
            elif "url" in qs and qs["url"]:
                href = qs["url"][0]
        except Exception:
            pass
    return href


def extract_socials_and_email(url: str, session: requests.Session = None) -> dict:
    """
    Fetch a business website (+ up to 1 /contact page if needed) and extract:
    - email (mailto: preferred first, then text/HTML with placeholder filtering)
    - instagram, facebook, linkedin profile URLs
    Never fabricates data.
    """
    socials = {"instagram": "", "facebook": "", "linkedin": "", "email": ""}

    if not url or not str(url).strip():
        return socials

    url = _unwrap_website_url(str(url).strip())
    if not url.startswith("http"):
        url = "https://" + url

    sess = session or requests
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def _parse_html(html_text: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html_text, "html.parser")
        candidates: list[str] = []

        # 1. Prefer explicit mailto: anchors first (highest accuracy)
        for a in soup.find_all("a", href=True):
            href_raw = a["href"].strip()
            if href_raw.lower().startswith("mailto:"):
                raw_addr = unquote(href_raw[7:].split("?")[0]).strip()
                if raw_addr and raw_addr not in candidates:
                    candidates.append(raw_addr)

        # 2. Fallback regex on visible text and raw HTML
        visible = soup.get_text(" ", strip=True)
        for cand in _EMAIL_RE.findall(visible + "\n" + html_text):
            cleaned = unquote(cand).strip()
            if cleaned not in candidates:
                candidates.append(cleaned)

        for cand in candidates:
            if not socials["email"] and _is_valid_scraped_email(cand):
                socials["email"] = unquote(cand).strip().strip(".,;:<>\"'")
                break

        # Social links + potential contact page links
        contact_links: list[str] = []
        base_netloc = urlparse(base_url).netloc.lower()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href:
                continue
            hl = href.lower()

            if not socials["instagram"] and "instagram.com" in hl:
                m = _INSTAGRAM_RE.search(href)
                if m and m.group(1).lower() not in ("", "instagram", "p", "explore"):
                    socials["instagram"] = _clean_social_url(href)

            elif not socials["facebook"] and "facebook.com" in hl:
                m = _FACEBOOK_RE.search(href)
                if m and m.group(1).lower() not in ("", "facebook", "sharer", "share"):
                    socials["facebook"] = _clean_social_url(href)

            elif not socials["linkedin"] and "linkedin.com" in hl:
                if _LINKEDIN_RE.search(href):
                    socials["linkedin"] = _clean_social_url(href)

            elif not socials["email"]:
                lbl = (a.get_text() or "").lower()
                if any(k in hl or k in lbl for k in ("contact", "about", "reach-us", "reachus")):
                    full = urljoin(base_url, href)
                    parsed_full = urlparse(full)
                    if (parsed_full.scheme in ("http", "https")
                            and parsed_full.netloc.lower() == base_netloc
                            and full not in contact_links):
                        contact_links.append(full)

        return contact_links

    t0 = time.time()
    try:
        response = sess.get(
            url,
            headers=headers,
            timeout=(4, 7),
            verify=False,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            logger.debug("Website HTTP %d for %s", response.status_code, url)
            return socials
        contact_links = _parse_html(response.text[:600000], response.url)

        # Follow up to 1 contact page if email still missing on homepage
        if not socials["email"] and contact_links:
            for cl in contact_links[:1]:
                try:
                    rc = sess.get(cl, headers=headers, timeout=(3, 5), verify=False, allow_redirects=True)
                    if rc.status_code < 400:
                        _parse_html(rc.text[:400000], rc.url)
                except Exception:
                    pass
    except requests.exceptions.Timeout:
        logger.debug("Website timeout for %s (%.1fs)", url, time.time() - t0)
    except requests.exceptions.ConnectionError:
        logger.debug("Website connection error for %s", url)
    except Exception as e:
        logger.debug("Website fetch error for %s: %s", url, str(e)[:60])

    return socials


def enrich_leads_websites(leads: list[dict], max_workers: int = 6) -> float:
    """
    Concurrently scrape websites for email + social links across a batch of leads.
    Mutates leads in-place and returns elapsed seconds.
    """
    t0 = time.time()
    targets = [(i, ld["website"]) for i, ld in enumerate(leads) if ld.get("website")]
    if not targets:
        return 0.0

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_to_idx = {
            pool.submit(extract_socials_and_email, url, session): idx
            for idx, url in targets
        }
        for fut in as_completed(fut_to_idx):
            idx = fut_to_idx[fut]
            try:
                socials = fut.result()
                leads[idx]["instagram"] = socials.get("instagram", "")
                leads[idx]["facebook"] = socials.get("facebook", "")
                leads[idx]["linkedin"] = socials.get("linkedin", "")
                leads[idx]["email"] = socials.get("email", "")
            except Exception as exc:
                logger.debug("Concurrent website enrich error: %s", exc)

    try:
        session.close()
    except Exception:
        pass
    return time.time() - t0


# ============================================
# CLEAN TEXT & GOOGLE MAPS ATOMIC EXTRACTION
# ============================================

def clean_text(text):
    if not text:
        return ""
    text = text.replace("\ue0b0", "").replace("\ue0c8", "").replace("\n", " ")
    return text.strip()


_CONSENT_TITLES = [
    "before you continue", "sign in", "consent", "google accounts",
    "verify it's you", "choose an account", "we use cookies",
]


def _is_consent_page(title: str, url: str) -> bool:
    """Return True if the page is a Google consent/error page, not a real business."""
    title_lower = (title or "").lower()
    url_lower = (url or "").lower()
    if "consent.google" in url_lower:
        return True
    return any(t in title_lower for t in _CONSENT_TITLES)


def _extract_listing_dom(page) -> dict:
    """
    Extract all Google Maps business details in ONE browser JS round-trip (<10ms)
    instead of 20+ sequential Playwright locator timeouts.
    """
    return page.evaluate("""() => {
        const clean = (s) => (s || '').replace(/[\\ue0b0\\ue0c8\\n]/g, ' ').replace(/\\s+/g, ' ').trim();
        const txt = (s) => {
            const el = document.querySelector(s);
            return el ? clean(el.innerText) : '';
        };
        const attr = (s, a) => {
            const el = document.querySelector(s);
            return el ? (el.getAttribute(a) || '').trim() : '';
        };

        const name = txt('h1.DUwDvf') || txt('h1[class*="fontHeadlineLarge"]') || txt('h1');

        let phone = txt('button[data-item-id*="phone"] .fontBodyMedium') || txt('button[data-item-id*="phone"]');
        if (!phone) {
            const pbtn = document.querySelector('button[aria-label*="Phone:"], a[data-item-id*="phone"], a[href^="tel:"]');
            if (pbtn) {
                const lbl = pbtn.getAttribute('aria-label') || pbtn.getAttribute('href') || pbtn.innerText || '';
                phone = clean(lbl.replace(/^Phone:\\s*/i, '').replace(/^tel:/i, '').replace(/^Call\\s+/i, ''));
            }
        }
        if (phone.toLowerCase().startsWith('call ')) {
            phone = phone.slice(5).trim();
        }

        let address = txt('button[data-item-id="address"] .fontBodyMedium') || txt('button[data-item-id="address"]') || txt('[data-item-id="address"]');
        if (!address) {
            const abtn = document.querySelector('button[aria-label*="Address:"]');
            if (abtn) address = clean((abtn.getAttribute('aria-label') || '').replace(/^Address:\\s*/i, ''));
        }

        const website = attr('a[data-item-id="authority"]', 'href')
                     || attr('a[aria-label*="Website:"]', 'href')
                     || attr('a[jsaction*="website"]', 'href');

        const category = txt('button[jsaction*="category"]')
                      || txt('span[jsaction*="category"]')
                      || txt('button.DkEaL')
                      || txt('span.DkEaL');

        let rating = '';
        let reviews = '';
        const rEl = document.querySelector('div.F7nice span[aria-hidden="true"], div[jsaction*="pane.rating"] span[aria-hidden="true"], span.MW4etd');
        if (rEl) {
            const rCand = (rEl.innerText || '').trim().replace(',', '.');
            if (/^\\d(\\.\\d)?$/.test(rCand)) rating = rCand;
        }
        if (!rating) {
            const rAria = document.querySelector('span[aria-label*="stars"], div.F7nice span[aria-label]');
            if (rAria) {
                const m = (rAria.getAttribute('aria-label') || '').match(/([\\d.]+)\\s*(?:stars?|out of)/i);
                if (m) rating = m[1];
            }
        }

        const revEl = document.querySelector('div.F7nice span[aria-label*="review"], span.UY7F9, button[jsaction*="moreReviews"], span[aria-label*="reviews"]');
        if (revEl) {
            const raw = revEl.getAttribute('aria-label') || revEl.innerText || '';
            const m = raw.replace(/,/g, '').match(/(\\d+)/);
            if (m) reviews = m[1];
        }

        return { name, phone, address, website, category, rating, reviews };
    }""")


def scrape_business(link, p, browser, page, business_type: str = "", fetch_website_inline: bool = True):
    """
    Scrape a single Google Maps business listing.

    Returns (lead_dict | None, browser, page).
    """
    for attempt in range(2):
        try:
            if not browser.is_connected() or page.is_closed():
                logger.info("Browser/page disconnected — recreating page...")
                if not browser.is_connected():
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser = launch_browser(p)
                page = new_page(browser, inject_cookies=(attempt == 0))

            page.goto(link, wait_until="domcontentloaded", timeout=20000)

            dismiss_consent_wall(page)

            try:
                page.wait_for_selector("h1", timeout=5000)
            except Exception:
                pass

            # Brief wait for contact buttons if panel is still hydrating
            try:
                page.wait_for_selector(
                    'button[data-item-id="address"], button[data-item-id*="phone"], a[data-item-id="authority"]',
                    timeout=1800,
                )
            except Exception:
                pass

            page_title = ""
            try:
                page_title = page.title()
            except Exception:
                pass

            if _is_consent_page(page_title, page.url):
                logger.warning("Skipped consent/error page: '%s'", page_title[:60])
                return None, browser, page

            dom_data = _extract_listing_dom(page)
            business_name = dom_data.get("name", "")

            if not business_name and page_title:
                clean_title = page_title.split(" - Google")[0].strip()
                if not _is_consent_page(clean_title, page.url):
                    business_name = clean_title

            if _is_consent_page(business_name, page.url):
                logger.warning("Skipped consent page masquerading as lead: '%s'", business_name[:60])
                return None, browser, page

            website = _unwrap_website_url(dom_data.get("website", ""))
            category = dom_data.get("category", "")
            effective_biz_type = category if category else business_type

            if fetch_website_inline and website:
                socials = extract_socials_and_email(website)
            else:
                socials = {"instagram": "", "facebook": "", "linkedin": "", "email": ""}

            lead = {
                "business_name": business_name,
                "phone": dom_data.get("phone", ""),
                "website": website,
                "address": dom_data.get("address", ""),
                "instagram": socials["instagram"],
                "facebook": socials["facebook"],
                "linkedin": socials["linkedin"],
                "email": socials["email"],
                "rating": dom_data.get("rating", ""),
                "reviews": dom_data.get("reviews", ""),
                "business_type": effective_biz_type,
                "source_name": "Google Maps",
                "source_url": link,
            }

            return lead, browser, page

        except ScrapeCancelled:
            raise
        except Exception as e:
            err_str = str(e)
            logger.warning("scrape_business attempt %d failed for %s: %s", attempt + 1, link[:70], err_str[:90])
            # Recreate context WITHOUT cookies if connection was closed/reset, without killing Chromium unless disconnected
            try:
                if not page.is_closed():
                    ctx = page.context
                    page.close()
                    ctx.close()
            except Exception:
                pass
            if not browser.is_connected():
                try:
                    browser.close()
                except Exception:
                    pass
                browser = launch_browser(p)
            page = new_page(browser, inject_cookies=False)
            time.sleep(0.5)

    return None, browser, page


# ============================================
# SCRAPE ONE CITY / LOCALITY
# ============================================

def scrape_city(business_type, city, p, browser, page, partial_save_callback=None, max_leads_per_city=20):
    city_leads = []
    search_query = f"{business_type} in {city}"

    logger.info("=" * 50)
    logger.info("Scraping: %s", search_query)
    logger.info("=" * 50)

    t_city_start = time.time()
    timeouts_count = 0

    search_url = (
        "https://www.google.com/maps/search/"
        + search_query.strip().replace(" ", "+")
        + "?hl=en"
    )

    try:
        if not browser.is_connected() or page.is_closed():
            if not browser.is_connected():
                try:
                    browser.close()
                except Exception:
                    pass
                browser = launch_browser(p)
            page = new_page(browser, inject_cookies=False)

        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
        except Exception as nav_err:
            # Retry once cleanly without cookies if connection closed/timed out
            if "ERR_CONNECTION_CLOSED" in str(nav_err) or "Timeout" in str(nav_err):
                timeouts_count += 1
                logger.warning("Search load retry without cookies for %s: %s", city, str(nav_err)[:80])
                try:
                    ctx = page.context
                    page.close()
                    ctx.close()
                except Exception:
                    pass
                page = new_page(browser, inject_cookies=False)
                page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
            else:
                raise

        dismiss_consent_wall(page)

        try:
            page.wait_for_selector('div[role="feed"], a[href*="/maps/place/"], h1', timeout=10000)
        except Exception:
            pass

        scrollable_div = None
        for feed_sel in [
            'div[role="feed"]',
            'div[aria-label*="Results for"]',
            'div.m6QErb[aria-label]',
            'div.m6QErb',
        ]:
            try:
                if page.locator(feed_sel).count() > 0:
                    scrollable_div = page.locator(feed_sel).first
                    break
            except Exception:
                continue

        if not scrollable_div:
            scrollable_div = page.locator("body")

    except Exception as e:
        logger.error("Failed to load Maps for %s: %s", city, e)
        _save_debug_artifacts(page, city)
        return city_leads, browser, page

    # ---- Improved scrolling strategy ----
    is_quick = os.environ.get("QUICK_SCRAPE") == "true"
    max_scrolls = 3 if is_quick else 25
    scroll_interval = 1.0 if is_quick else 1.5
    max_unchanged = 3 if is_quick else 4

    max_biz_env = os.environ.get("MAX_BIZ_PER_CITY")
    if max_biz_env and max_biz_env.isdigit():
        selected_limit = int(max_biz_env)
    elif is_quick and max_leads_per_city <= 20:
        selected_limit = 3
    else:
        selected_limit = max_leads_per_city
    selected_limit = max(1, min(selected_limit, 200))

    previous_count = 0
    same_count = 0
    t_scroll_start = time.time()

    for i in range(max_scrolls):
        try:
            scrollable_div.evaluate("(el) => el.scrollTop = el.scrollHeight")
            time.sleep(scroll_interval)

            cards = scrollable_div.locator('a[href*="/maps/place/"]').all()
            current_count = len(cards)
            logger.debug("  Scroll %d | Businesses: %d", i + 1, current_count)

            # Stop early if we already collected more than enough candidates for selected_limit
            if current_count >= selected_limit + 5:
                logger.info("  Reached target depth (%d >= %d) at scroll %d", current_count, selected_limit, i + 1)
                break

            # Detect Google Maps end-of-list marker
            try:
                if page.locator('span.HlvSq, p:has-text("end of the list")').count() > 0:
                    logger.info("  End of results reached at scroll %d (%d businesses)", i + 1, current_count)
                    break
            except Exception:
                pass

            if current_count == previous_count:
                same_count += 1
            else:
                same_count = 0

            previous_count = current_count
            if same_count >= max_unchanged:
                logger.info("  No new results after %d scrolls — stopping at %d businesses", max_unchanged, current_count)
                break
        except Exception as scroll_err:
            logger.warning("  Scroll error: %s", str(scroll_err)[:60])
            break

    t_scroll_elapsed = time.time() - t_scroll_start

    # ---- Collect unique /maps/place/ business links (EXCLUDE /maps/reserve/ booking widgets) ----
    business_links = []
    seen_links: set = set()
    try:
        cards = scrollable_div.locator('a[href*="/maps/place/"]').all()
        for card in cards:
            try:
                href = card.get_attribute("href")
                if href and "/maps/place/" in href and "/maps/reserve/" not in href:
                    clean_link = href.split("?")[0]
                    if clean_link not in seen_links:
                        seen_links.add(clean_link)
                        business_links.append(clean_link)
            except Exception:
                pass
    except Exception as e:
        logger.warning("Link collection error: %s", str(e)[:60])

    # Fallback: if search landed directly on a single business page (h1 present, no feed links)
    if not business_links:
        try:
            cur_url = page.url or ""
            if "/maps/place/" in cur_url and "/maps/reserve/" not in cur_url:
                business_links.append(cur_url.split("?")[0])
        except Exception:
            pass

    business_links = business_links[:selected_limit]
    logger.info("Found %d valid place links in %s (scroll %.1fs, limit %d)", len(business_links), city, t_scroll_elapsed, selected_limit)
    _notify("businesses_found", {"city": city, "total_businesses": len(business_links)})

    # ---- Extract Google Maps details quickly (defer website fetch to concurrent batch!) ----
    t_details_start = time.time()
    skipped = 0
    failed = 0

    for idx, link in enumerate(business_links):
        _notify("business_progress", {
            "city": city,
            "business_index": idx + 1,
            "total_businesses": len(business_links),
        })

        lead, browser, page = scrape_business(
            link, p, browser, page,
            business_type=business_type,
            fetch_website_inline=False,  # batched concurrently right below!
        )

        if lead and any([lead["business_name"], lead["phone"], lead["website"], lead["address"]]):
            lead["city"] = city
            city_leads.append(lead)
            if len(city_leads) % 3 == 0 and partial_save_callback:
                partial_save_callback(city_leads, idx + 1, len(business_links))
        else:
            if lead is None:
                failed += 1
            else:
                skipped += 1

        # Recycle browser context every 10 businesses to prevent Chromium OOM on 512MB cloud containers
        if (idx + 1) % 10 == 0:
            try:
                old_ctx = page.context
                page = new_page(browser, inject_cookies=True, block_heavy=False)
                old_ctx.close()
            except Exception:
                pass

    t_details_elapsed = time.time() - t_details_start

    # Save extracted city leads immediately before website enrichment
    if city_leads and partial_save_callback:
        partial_save_callback(city_leads, len(business_links), len(business_links))

    # Release Chromium context memory before website enrichment (prevents 512MB container OOM)
    try:
        page.context.close()
    except Exception:
        pass
    import gc
    gc.collect()

    # ---- Concurrent Website Enrichment (emails + socials) ----
    t_web_elapsed = enrich_leads_websites(city_leads, max_workers=3)

    if city_leads and partial_save_callback:
        partial_save_callback(city_leads, len(business_links), len(business_links))

    t_city_elapsed = time.time() - t_city_start
    avg_per_lead = round(t_city_elapsed / max(len(city_leads), 1), 2)
    logger.info(
        "City %s done: %d leads | %d failed | %d skipped | scroll=%.1fs maps=%.1fs web=%.1fs total=%.1fs (%.2fs/lead)",
        city, len(city_leads), failed, skipped,
        t_scroll_elapsed, t_details_elapsed, t_web_elapsed, t_city_elapsed, avg_per_lead,
    )
    _notify("city_summary", {
        "city": city,
        "leads": len(city_leads),
        "discovered": len(business_links),
        "failed": failed,
        "skipped": skipped,
        "timeouts": timeouts_count,
        "scroll_seconds": round(t_scroll_elapsed, 2),
        "maps_detail_seconds": round(t_details_elapsed, 2),
        "website_enrich_seconds": round(t_web_elapsed, 2),
        "elapsed_seconds": round(t_city_elapsed, 2),
        "avg_seconds_per_lead": avg_per_lead,
    })
    return city_leads, browser, page


# ============================================
# DEDUPLICATION HELPER
# ============================================

def _deduplicate_df(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Deduplicate leads carefully:
    - Same source_url + spin -> duplicate (exact same Maps listing)
    - Same normalized (business_name, address, spin) when address exists -> duplicate
      (preserves legitimate branches of chains at different addresses!)
    - Same normalized (business_name, spin) when address is empty -> duplicate
    - Same normalized (phone>=7digits, business_name, spin) -> duplicate
    Returns (deduped_df, duplicates_removed_count).
    """
    if df is None or df.empty:
        return df, 0
    before = len(df)
    w = df.copy()
    w["_name_norm"] = w["business_name"].fillna("").astype(str).str.lower().str.strip()
    w["_addr_norm"] = w["address"].fillna("").astype(str).str.lower().str.strip() if "address" in w.columns else ""
    w["_phone_norm"] = w["phone"].fillna("").astype(str).str.replace(r"[^\d+]", "", regex=True) if "phone" in w.columns else ""

    if "source_url" in w.columns:
        has_url = w["source_url"].fillna("").astype(str).str.strip() != ""
        w = w[~(has_url & w.duplicated(subset=["source_url", "spin"], keep="first"))]

    has_addr = w["_addr_norm"] != ""
    w = w[~(has_addr & w.duplicated(subset=["_name_norm", "_addr_norm", "spin"], keep="first"))]
    w = w[~((~has_addr) & w.duplicated(subset=["_name_norm", "spin"], keep="first"))]

    has_ph = w["_phone_norm"].str.len() >= 7
    w = w[~(has_ph & w.duplicated(subset=["_phone_norm", "_name_norm", "spin"], keep="first"))]

    w.drop(columns=["_name_norm", "_addr_norm", "_phone_norm"], inplace=True, errors="ignore")
    removed = before - len(w)
    return w, removed


# ============================================
# MAIN GENERATE LEADS — COUNTRY / LOCALITY MODE
# ============================================

def generate_leads(business_type, country, max_cities=30, custom_cities=None, max_leads_per_city=20, is_locality_mode=False):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generate_leads._locality_mode = is_locality_mode

    t_discovery_start = time.time()
    if custom_cities:
        cities = custom_cities
    else:
        cities = get_cities(country, max_cities=max_cities)
    t_discovery_elapsed = time.time() - t_discovery_start

    all_leads = []

    progress_file = os.path.join(OUTPUT_DIR, "progress.txt")
    completed_cities = set()

    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            completed_cities = set(line.strip() for line in f.readlines() if line.strip())
        logger.info("Resuming — %d locations already done.", len(completed_cities))

    remaining_cities = [c for c in cities if c not in completed_cities]

    raw_output = os.path.join(OUTPUT_DIR, "local_business_leads.csv")
    if os.path.exists(raw_output) and completed_cities:
        try:
            existing_df = pd.read_csv(raw_output)
            all_leads = existing_df.to_dict("records")
            logger.info("Loaded %d existing leads.", len(all_leads))
        except Exception:
            pass

    mode_label = "localities" if is_locality_mode else "cities"
    logger.info("Target: %s across %d %s in %s", business_type, len(cities), mode_label, country)
    logger.info("Remaining %s: %d", mode_label, len(remaining_cities))

    scraped_time = time.strftime("%Y-%m-%d %H:%M:%S")
    friendly_spin = f"{business_type} in {country} ({scraped_time[:16]})"
    _master_city = country or ""

    # Read historical CSV ONCE instead of re-reading on every partial save!
    historical_df = pd.DataFrame()
    if os.path.exists(raw_output):
        try:
            hist = pd.read_csv(raw_output)
            if "spin" in hist.columns:
                historical_df = hist[hist["spin"] != friendly_spin].copy()
            else:
                historical_df = hist.copy()
        except Exception as e:
            logger.warning("Could not load existing CSV history: %s", e)

    def _atomic_save_leads(rows: list[dict]) -> tuple[pd.DataFrame, int]:
        current_run_df = pd.DataFrame(rows)
        if not historical_df.empty and not current_run_df.empty:
            df_temp = pd.concat([historical_df, current_run_df], ignore_index=True)
        elif not historical_df.empty:
            df_temp = historical_df.copy()
        else:
            df_temp = current_run_df
        df_temp, dup_removed = _deduplicate_df(df_temp)
        _tmp = raw_output + ".tmp"
        df_temp.to_csv(_tmp, index=False)
        os.replace(_tmp, raw_output)
        return df_temp, dup_removed

    import asyncio
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    t_total_start = time.time()
    t_save_total = 0.0
    total_dups_removed = 0

    with sync_playwright() as p:
        t_init0 = time.time()
        browser = launch_browser(p)
        page = new_page(browser, inject_cookies=False)
        t_browser_init = time.time() - t_init0
        logger.info("Browser initialized in %.2fs", t_browser_init)

        try:
            for city_idx, city in enumerate(remaining_cities):
                _notify("city_start", {
                    "city": city,
                    "city_index": city_idx + 1,
                    "total_cities": len(remaining_cities),
                })
                if is_locality_mode:
                    _notify("locality_start", {
                        "locality": city,
                        "locality_index": city_idx + 1,
                        "total_localities": len(remaining_cities),
                        "parent_city": _master_city,
                    })
                logger.info("[%s %d/%d] %s", "Locality" if is_locality_mode else "City", city_idx + 1, len(remaining_cities), city)

                query_target = (
                    f"{city}, {_master_city}"
                    if (is_locality_mode and _master_city and city.lower() != _master_city.lower() and _master_city.lower() not in city.lower())
                    else city
                )

                def save_partial_city(city_leads, business_index=None, total_businesses=None):
                    nonlocal t_save_total
                    ts0 = time.time()
                    scrape_time = time.strftime("%Y-%m-%d %H:%M:%S")
                    partial_rows = []
                    for lead in city_leads:
                        row = lead.copy()
                        row["spin"] = friendly_spin
                        row["scraped_at"] = scrape_time
                        row["city"] = _master_city if is_locality_mode and _master_city else city
                        row["locality"] = city if is_locality_mode else ""
                        row["search_area"] = query_target
                        row["country"] = country if not is_locality_mode else ""
                        partial_rows.append(row)

                    df_temp, _ = _atomic_save_leads(all_leads + partial_rows)
                    t_save_total += time.time() - ts0
                    _notify("lead_extracted", {
                        "city": city,
                        "business_index": business_index or len(partial_rows),
                        "total_businesses": total_businesses or len(partial_rows),
                        "total_leads": len(df_temp),
                    })
                    _notify("log", {"message": f"💾 Saved {len(partial_rows)} leads in {city}"})

                city_leads, browser, page = scrape_city(
                    business_type, query_target, p, browser, page,
                    save_partial_city, max_leads_per_city,
                )

                scrape_time = time.strftime("%Y-%m-%d %H:%M:%S")
                for lead in city_leads:
                    lead["spin"] = friendly_spin
                    lead["scraped_at"] = scrape_time
                    lead["city"] = _master_city if is_locality_mode and _master_city else city
                    lead["locality"] = city if is_locality_mode else ""
                    lead["search_area"] = query_target

                all_leads.extend(city_leads)

                with open(progress_file, "a", encoding="utf-8") as f:
                    f.write(city + "\n")

                ts0 = time.time()
                df_temp, dup_removed = _atomic_save_leads(all_leads)
                t_save_total += time.time() - ts0
                total_dups_removed = dup_removed

                logger.info("Progress saved — Total leads so far: %d (deduped: %d)", len(df_temp), dup_removed)
                _notify("city_done", {
                    "city": city,
                    "city_index": city_idx + 1,
                    "total_cities": len(remaining_cities),
                    "city_leads_count": len(city_leads),
                    "total_leads": len(df_temp),
                })
                if is_locality_mode:
                    _notify("locality_done", {
                        "locality": city,
                        "locality_index": city_idx + 1,
                        "total_localities": len(remaining_cities),
                        "locality_leads_count": len(city_leads),
                        "total_leads": len(df_temp),
                    })
                time.sleep(0.5)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    ts0 = time.time()
    df, total_dups_removed = _atomic_save_leads(all_leads)
    t_save_total += time.time() - ts0

    if os.path.exists(progress_file):
        os.remove(progress_file)

    t_total_elapsed = time.time() - t_total_start
    extracted_count = len(all_leads)
    metrics = {
        "discovery_seconds": round(t_discovery_elapsed, 2),
        "browser_init_seconds": round(t_browser_init, 2),
        "save_seconds": round(t_save_total, 2),
        "total_seconds": round(t_total_elapsed, 2),
        "locations_scraped": len(remaining_cities),
        "leads_extracted_run": extracted_count,
        "duplicates_removed": int(total_dups_removed),
        "avg_seconds_per_lead": round(t_total_elapsed / max(extracted_count, 1), 2),
    }
    _notify("run_metrics", metrics)

    logger.info("=" * 50)
    logger.info("ALL LOCATIONS DONE")
    logger.info("Run Leads: %d | Total CSV Rows: %d | Dups Removed: %d", extracted_count, len(df), total_dups_removed)
    logger.info("Total Time: %.1fs (%.1f min) | Avg/lead: %.2fs | Save I/O: %.2fs",
                t_total_elapsed, t_total_elapsed / 60, metrics["avg_seconds_per_lead"], t_save_total)
    logger.info("Saved to: %s", raw_output)
    logger.info("=" * 50)

    return df
