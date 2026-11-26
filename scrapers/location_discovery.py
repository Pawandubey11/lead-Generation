"""
location_discovery.py
----------------------
Automatic city-wide locality discovery engine for LeadPulse.

Given a city + country, discovers localities/neighbourhoods/business-districts
inside that city so the scraper can search each one separately.

Discovery order:
  1. Manual localities (if provided) — instant, no network
  2. In-memory cache — instant for repeated searches
  3. Nominatim + Overpass API (OpenStreetMap, free, no API key, fast timeouts + mirror)
  4. Hardcoded fallback for major cities (used when OSM fails or returns < 3 results)
"""

from __future__ import annotations

import os
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# In-memory cache {(city_lower, country_lower): (source, list[str])}
_DISCOVERY_CACHE: dict[tuple[str, str], tuple[str, list[str]]] = {}

# ---------------------------------------------------------------------------
# Hardcoded fallback localities for major cities
# ---------------------------------------------------------------------------
FALLBACK_LOCALITIES: dict[str, list[str]] = {
    "delhi": [
        "Connaught Place", "Karol Bagh", "Rohini", "Dwarka", "Saket",
        "Lajpat Nagar", "Janakpuri", "Pitampura", "Nehru Place", "Rajouri Garden",
        "Vasant Kunj", "Greater Kailash", "Hauz Khas", "Preet Vihar", "Mayur Vihar",
        "Punjabi Bagh", "Paschim Vihar", "Uttam Nagar", "Shahdara", "Dilshad Garden",
    ],
    "noida": [
        "Sector 18", "Sector 62", "Sector 63", "Sector 15", "Sector 16",
        "Sector 50", "Sector 76", "Sector 104", "Sector 125", "Sector 132",
        "Sector 135", "Sector 142", "Film City", "Noida Extension", "Sector 44",
    ],
    "greater noida": [
        "Alpha 1", "Alpha 2", "Beta 1", "Beta 2", "Gamma 1", "Gamma 2",
        "Delta 1", "Knowledge Park I", "Knowledge Park II", "Knowledge Park III",
        "Pari Chowk", "Omega 1", "Techzone 4", "Surajpur", "Greater Noida West",
    ],
    "gurgaon": [
        "Cyber City", "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4",
        "Sohna Road", "Golf Course Road", "MG Road", "Udyog Vihar", "Sector 14",
        "Sector 29", "Sector 44", "Sector 45", "Sector 54", "Palam Vihar", "Sushant Lok",
    ],
    "gurugram": [
        "Cyber City", "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4",
        "Sohna Road", "Golf Course Road", "MG Road", "Udyog Vihar", "Sector 14",
        "Sector 29", "Sector 44", "Sector 45", "Sector 54", "Palam Vihar", "Sushant Lok",
    ],
    "ghaziabad": [
        "Indirapuram", "Vaishali", "Kaushambi", "Vasundhara", "Raj Nagar",
        "Raj Nagar Extension", "Crossings Republik", "Kavi Nagar", "Shastri Nagar", "Sahibabad",
    ],
    "faridabad": [
        "Sector 15", "Sector 16", "Sector 21C", "NIT Faridabad", "Neharpar",
        "Ballabgarh", "Surajkund", "Greenfields", "Sector 37", "Sector 79",
    ],
    "mumbai": [
        "Andheri", "Bandra", "Borivali", "Dadar", "Juhu", "Powai", "Thane",
        "Navi Mumbai", "Worli", "Lower Parel", "Malad", "Goregaon", "Kandivali",
        "Kurla", "Ghatkopar", "Vikhroli", "Mulund", "Chembur", "Vashi", "Colaba",
    ],
    "bangalore": [
        "Koramangala", "Indiranagar", "Whitefield", "HSR Layout", "Jayanagar",
        "Marathahalli", "Electronic City", "Bannerghatta Road", "JP Nagar",
        "Rajajinagar", "Malleshwaram", "Hebbal", "Yeshwanthpur", "BTM Layout",
        "Bellandur", "Sarjapur Road", "Yelahanka", "Banashankari", "Basavanagudi", "MG Road",
    ],
    "bengaluru": [
        "Koramangala", "Indiranagar", "Whitefield", "HSR Layout", "Jayanagar",
        "Marathahalli", "Electronic City", "Bannerghatta Road", "JP Nagar",
        "Rajajinagar", "Malleshwaram", "Hebbal", "Yeshwanthpur", "BTM Layout", "Bellandur",
    ],
    "hyderabad": [
        "Banjara Hills", "Jubilee Hills", "Hitech City", "Madhapur", "Gachibowli",
        "Kukatpally", "Secunderabad", "Ameerpet", "Begumpet", "LB Nagar",
        "Dilsukhnagar", "Uppal", "Miyapur", "Kompally", "Kondapur",
        "Mehdipatnam", "Tolichowki", "Manikonda", "Attapur", "Shamshabad",
    ],
    "chennai": [
        "Anna Nagar", "T Nagar", "Velachery", "Adyar", "Nungambakkam",
        "Mylapore", "Porur", "Ambattur", "Tambaram", "Chromepet",
        "Perambur", "Egmore", "Vadapalani", "Sholinganallur", "Perungudi",
        "Medavakkam", "Pallikaranai", "Nanganallur", "Saidapet", "Guindy",
    ],
    "kolkata": [
        "Salt Lake", "New Town", "Howrah", "Jadavpur", "Park Street",
        "Esplanade", "Ballygunge", "Behala", "Barasat", "Dum Dum",
        "Alipore", "Kasba", "Tollygunge", "Ultadanga", "Rajarhat",
        "Gariahat", "Dhakuria", "Golpark", "Rashbehari", "Bagmari",
    ],
    "pune": [
        "Koregaon Park", "Kothrud", "Hinjewadi", "Wakad", "Baner",
        "Viman Nagar", "Hadapsar", "Pimpri", "Chinchwad", "Aundh",
        "Shivajinagar", "Kharadi", "Kondhwa", "Pashan", "Magarpatta",
        "Warje", "Karve Nagar", "Deccan", "Camp", "Bibwewadi",
    ],
    "ahmedabad": [
        "CG Road", "SG Highway", "Navrangpura", "Bopal", "Satellite",
        "Vastrapur", "Thaltej", "Maninagar", "Naroda", "Odhav",
        "Chandkheda", "Gota", "Prahlad Nagar", "Ambawadi", "Paldi",
        "Memnagar", "Bodakdev", "Vejalpur", "Vastral", "Nikol",
    ],
    "jaipur": [
        "Malviya Nagar", "Vaishali Nagar", "Mansarovar", "C-Scheme", "MI Road",
        "Raja Park", "Tonk Road", "Jagatpura", "Bapu Nagar", "Sodala",
    ],
    "lucknow": [
        "Gomti Nagar", "Hazratganj", "Aliganj", "Indira Nagar", "Mahanagar",
        "Aminabad", "Alambagh", "Vikas Nagar", "Jankipuram", "Charbagh",
    ],
    "chandigarh": [
        "Sector 17", "Sector 22", "Sector 35", "Sector 8", "Sector 9",
        "Sector 34", "Sector 43", "Industrial Area Phase 1", "Manimajra", "Mohali Phase 7",
    ],
    "london": [
        "City of London", "Westminster", "Camden", "Shoreditch", "Canary Wharf",
        "Soho", "Mayfair", "Hackney", "Brixton", "Peckham",
        "Croydon", "Stratford", "Fulham", "Chelsea", "Islington",
        "Southwark", "Lambeth", "Lewisham", "Hammersmith", "Ealing",
    ],
    "berlin": [
        "Mitte", "Prenzlauer Berg", "Friedrichshain", "Kreuzberg", "Schoneberg",
        "Charlottenburg", "Neukolln", "Treptow", "Spandau", "Steglitz",
        "Pankow", "Lichtenberg", "Marzahn", "Reinickendorf", "Wedding",
        "Tempelhof", "Wilmersdorf", "Zehlendorf", "Koepenick", "Tiergarten",
    ],
    "new york": [
        "Manhattan", "Brooklyn", "Queens", "Bronx", "Midtown",
        "Downtown", "Upper East Side", "Upper West Side", "Harlem", "Astoria",
        "Flushing", "Williamsburg", "Long Island City", "Bushwick", "Park Slope",
        "Greenpoint", "Ridgewood", "Jackson Heights", "Jamaica", "Forest Hills",
    ],
    "paris": [
        "Montmartre", "Le Marais", "Saint-Germain-des-Pres", "Bastille", "Belleville",
        "Pigalle", "Oberkampf", "Republique", "Opera", "Chatelet",
        "Palais Royal", "Champs-Elysees", "Batignolles", "Nation", "Vincennes",
        "Neuilly-sur-Seine", "Levallois-Perret", "Boulogne-Billancourt", "Montrouge", "Ivry-sur-Seine",
    ],
    "dubai": [
        "Downtown Dubai", "Dubai Marina", "Jumeirah", "Deira", "Bur Dubai",
        "Business Bay", "JLT", "Silicon Oasis", "Al Quoz", "Mirdif",
        "Discovery Gardens", "International City", "Palm Jumeirah", "Karama", "Satwa",
        "Al Barsha", "Tecom", "DIFC", "JBR", "Oud Metha",
    ],
    "singapore": [
        "Orchard", "Marina Bay", "Bugis", "Chinatown", "Little India",
        "Tanjong Pagar", "Clementi", "Jurong", "Tampines", "Bedok",
        "Woodlands", "Yishun", "Ang Mo Kio", "Bishan", "Queenstown",
        "Punggol", "Sengkang", "Hougang", "Geylang", "Kallang",
    ],
    "sydney": [
        "CBD", "Surry Hills", "Newtown", "Bondi", "Parramatta",
        "Chatswood", "Manly", "Balmain", "Glebe", "Pyrmont",
        "Ultimo", "Darlinghurst", "Redfern", "Marrickville", "Randwick",
        "Leichhardt", "Strathfield", "Bankstown", "Liverpool", "Penrith",
    ],
    "toronto": [
        "Downtown", "Midtown", "Scarborough", "Etobicoke", "North York",
        "East York", "Yorkville", "Kensington Market", "Annex", "Queen West",
        "Liberty Village", "Distillery District", "Leslieville", "Roncesvalles", "Danforth",
        "Bloor West Village", "Junction", "Parkdale", "Cabbagetown", "Riverside",
    ],
    "bangkok": [
        "Silom", "Sukhumvit", "Chatuchak", "Lat Phrao", "Wang Thonglang",
        "Huai Khwang", "Ratchathewi", "Pathum Wan", "Bang Rak", "Khlong Toei",
        "Phra Nakhon", "Dusit", "Phaya Thai", "Sathon", "Yannawa",
        "Min Buri", "Nong Chok", "Saphan Sung", "Khan Na Yao", "Ladkrabang",
    ],
    "munich": [
        "Maxvorstadt", "Schwabing", "Haidhausen", "Neuhausen", "Pasing",
        "Sendling", "Au", "Bogenhausen", "Giesing", "Milbertshofen",
        "Riem", "Moosach", "Nymphenburg", "Trudering", "Laim",
        "Schwabing-West", "Berg am Laim", "Obergiesing", "Forstenried", "Hadern",
    ],
    "jakarta": [
        "Menteng", "Sudirman", "Kuningan", "Kebayoran Baru", "Pluit",
        "Kelapa Gading", "Cempaka Putih", "Tebet", "Pasar Minggu", "Cipete",
        "Fatmawati", "Cilandak", "Pondok Indah", "PIK", "BSD",
        "Tanah Abang", "Gambir", "Sawah Besar", "Johar Baru", "Kemayoran",
    ],
    "los angeles": [
        "Hollywood", "Downtown LA", "Santa Monica", "Venice", "Westwood",
        "Beverly Hills", "Culver City", "Burbank", "Pasadena", "Long Beach",
        "Koreatown", "Silver Lake", "Echo Park", "Eagle Rock", "Highland Park",
        "Glendale", "Torrance", "Inglewood", "Compton", "Pomona",
    ],
    "chicago": [
        "Loop", "River North", "Wicker Park", "Lincoln Park", "Lakeview",
        "Bucktown", "Logan Square", "Pilsen", "Bridgeport", "Hyde Park",
        "Evanston", "Oak Park", "Schaumburg", "Naperville", "Joliet",
        "Uptown", "Andersonville", "Rogers Park", "Ravenswood", "Avondale",
    ],
    "lagos": [
        "Victoria Island", "Lekki", "Ikeja", "Surulere", "Yaba",
        "Ikoyi", "Ajah", "Ogudu", "Festac", "Apapa",
        "Alimosho", "Agege", "Ojota", "Maryland", "Gbagada",
    ],
    "nairobi": [
        "Westlands", "Karen", "Kilimani", "Lavington", "Parklands",
        "CBD", "South B", "South C", "Eastleigh", "Kasarani",
        "Ruaka", "Runda", "Gigiri", "Spring Valley", "Muthaiga",
    ],
}

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LocalityDiscovery:
    """
    Discovers localities/neighbourhoods inside a given city.

    Args:
        city:              Target city name (e.g. "Delhi")
        country:           Country name (e.g. "India")
        manual_localities: Optional explicit list; bypasses all discovery.
    """

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    OVERPASS_URLS = [
        "https://overpass-api.de/api/interpreter",
    ]
    OVERPASS_URL = OVERPASS_URLS[0]
    USER_AGENT    = "LeadPulse/1.0 (locality-discovery; contact=local)"

    def __init__(
        self,
        city: str,
        country: str,
        manual_localities: Optional[list[str]] = None,
    ):
        self.city = city.strip()
        self.country = country.strip()
        self.manual_localities = [l.strip() for l in (manual_localities or []) if l.strip()]
        self.max_localities = int(os.environ.get("MAX_LOCALITIES", "30"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self) -> list[dict]:
        """
        Returns a list of locality dicts:
            [{"name": "Connaught Place", "city": "Delhi",
              "country": "India", "source": "nominatim|fallback|manual"}, ...]
        """
        # 1. Manual override — no network needed
        if self.manual_localities:
            return self._build_result(self.manual_localities, source="manual")

        cache_key = (self.city.lower(), self.country.lower())
        if cache_key in _DISCOVERY_CACHE:
            src, cached_names = _DISCOVERY_CACHE[cache_key]
            return self._build_result(cached_names, source=src)

        # 2. Try OSM Nominatim + Overpass (bounded fast timeouts)
        try:
            osm_localities = self._discover_via_osm()
        except Exception as exc:
            logger.warning("OSM locality discovery failed: %s", exc)
            osm_localities = []

        if len(osm_localities) >= 3:
            _DISCOVERY_CACHE[cache_key] = ("nominatim", osm_localities)
            return self._build_result(osm_localities, source="nominatim")

        # 3. Fallback — hardcoded dict
        fallback = self._discover_via_fallback()
        if fallback:
            logger.info("Using hardcoded fallback localities for %s", self.city)
            _DISCOVERY_CACHE[cache_key] = ("fallback", fallback)
            return self._build_result(fallback, source="fallback")

        # 4. Last resort — return the city itself so the scraper still works
        logger.warning(
            "No localities found for %s. Falling back to city-level search.", self.city
        )
        return self._build_result([self.city], source="fallback")

    def get_search_queries(self, business_type: str) -> list[dict]:
        """
        Returns a list of search query dicts:
            [{"locality": "Connaught Place",
              "query": "Restaurants in Connaught Place, Delhi",
              "search_area": "Connaught Place, Delhi",
              "source": "nominatim"}, ...]
        """
        localities = self.discover()
        queries = []
        for loc in localities:
            name = loc["name"]
            search_area = f"{name}, {self.city}" if name.lower() != self.city.lower() else name
            queries.append({
                "locality":    name,
                "query":       f"{business_type} in {search_area}",
                "search_area": search_area,
                "source":      loc.get("source", "unknown"),
                "city":        self.city,
                "country":     self.country,
            })
        return queries

    # ------------------------------------------------------------------
    # OSM discovery
    # ------------------------------------------------------------------

    def _discover_via_osm(self) -> list[str]:
        """Query Nominatim for city bbox, then Overpass (with mirror fallback) for neighbourhoods."""
        bbox = self._get_city_bbox()
        if not bbox:
            return []

        time.sleep(0.5)  # OSM courtesy pause

        south, west, north, east = bbox
        overpass_query = (
            f"[out:json][timeout:6];\n"
            f"node[\"place\"~\"suburb|neighbourhood|district|quarter\"]"
            f"({south},{west},{north},{east});\n"
            f"out;"
        )

        last_exc: Optional[Exception] = None
        elements: list = []
        for endpoint in self.OVERPASS_URLS:
            try:
                resp = requests.post(
                    endpoint,
                    data={"data": overpass_query},
                    timeout=7,
                    headers={"User-Agent": self.USER_AGENT},
                )
                resp.raise_for_status()
                elements = resp.json().get("elements", [])
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.debug("Overpass endpoint %s failed: %s", endpoint, exc)
                continue

        if last_exc is not None and not elements:
            raise last_exc

        names: list[str] = []
        for el in elements:
            name = el.get("tags", {}).get("name", "").strip()
            if name and self._is_valid_locality(name):
                names.append(name)

        return self._deduplicate(names)

    def _get_city_bbox(self) -> Optional[tuple[float, float, float, float]]:
        """Return (south, west, north, east) bounding box for the city via Nominatim."""
        q = f"{self.city}, {self.country}" if self.country else self.city
        params = {
            "q":              q,
            "format":         "json",
            "limit":          1,
            "addressdetails": 0,
        }
        resp = requests.get(
            self.NOMINATIM_URL,
            params=params,
            timeout=8,
            headers={"User-Agent": self.USER_AGENT},
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None

        bbox = results[0].get("boundingbox")
        if not bbox or len(bbox) < 4:
            return None

        south = float(bbox[0])
        north = float(bbox[1])
        west  = float(bbox[2])
        east  = float(bbox[3])
        return south, west, north, east

    # ------------------------------------------------------------------
    # Fallback discovery
    # ------------------------------------------------------------------

    def _discover_via_fallback(self) -> list[str]:
        """Return hardcoded localities for known cities (case-insensitive lookup)."""
        city_key = self.city.lower().strip()
        # Direct exact match first (prevents "greater noida" matching "noida" before its own entry)
        if city_key in FALLBACK_LOCALITIES:
            return FALLBACK_LOCALITIES[city_key]
        # Partial match longest key first
        for key in sorted(FALLBACK_LOCALITIES.keys(), key=len, reverse=True):
            if key in city_key or city_key in key:
                return FALLBACK_LOCALITIES[key]
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_valid_locality(self, name: str) -> bool:
        """Filter out noise from Overpass results."""
        if len(name) < 3:
            return False
        if name.lower() in (self.city.lower(), self.country.lower()):
            return False
        if name.isdigit():
            return False
        return True

    def _deduplicate(self, names: list[str]) -> list[str]:
        """Case-insensitive deduplication preserving first-seen casing."""
        seen: set[str] = set()
        result: list[str] = []
        for n in names:
            key = n.lower().strip()
            city_suffix = f", {self.city.lower()}"
            if key.endswith(city_suffix):
                n = n[:len(n) - len(city_suffix)].strip()
                key = n.lower().strip()
            if key and key not in seen:
                seen.add(key)
                result.append(n)
        return result[: self.max_localities]

    def _build_result(self, names: list[str], source: str) -> list[dict]:
        """Convert a list of names to the standard locality-dict format."""
        deduped = self._deduplicate(names)
        return [
            {
                "name":    n,
                "city":    self.city,
                "country": self.country,
                "source":  source,
            }
            for n in sorted(deduped)
        ]
