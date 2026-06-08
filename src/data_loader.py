"""
data_loader.py
--------------
All raw data ingestion lives here.
Each function returns a raw, unmodified DataFrame — no business logic.

All fetched data lands in .cache/ — nothing writes to data/raw/.
"""

import io
import logging
import requests
import pandas as pd
from pathlib import Path
from typing import Optional

from cache_manager import CacheManager
import json

from utils import download_file, fetch_bytes
from config import (
    BCAD_ARCGIS_URL,
    CACHE_DIR, CACHE_TTL,
    CENSUS_API_KEY, CENSUS_BASE_URL, CENSUS_YEAR,
    CENSUS_TABLES, SA_CRIME_URL, SA_PERMITS_URL,
    TARGET_STATE_FIPS,
    FBI_CDE_API_KEY, FBI_CDE_YEAR, SUBURBAN_CITY_TO_ZIPS,
)

_cache = CacheManager(CACHE_DIR)

logger = logging.getLogger(__name__)

# Bump this key whenever CENSUS_TABLES changes — ensures stale caches auto-invalidate.
_CENSUS_CACHE_KEY = "census_acs_v3"

# Browser-like headers — SA Open Data portal (and many gov sites) return 403
# when they detect Python's default urllib user-agent string.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://data.sanantonio.gov/",
}

_ZILLOW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research/1.0)",
}

_ZHVI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)
_ZORI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "Zip_zori_uc_sfrcondomfr_sm_month.csv"
)
_ZHVF_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvf_growth/"
    "Zip_zhvf_growth_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)


# ── Zillow ────────────────────────────────────────────────────────────────────

def load_zhvi() -> pd.DataFrame:
    """
    Load Zillow Home Value Index (ZHVI) from Zillow's public research endpoint.
    Cached for 7 days — Zillow publishes monthly updates.
    """
    cached = _cache.get("zillow_zhvi", ttl_hours=CACHE_TTL["zillow_hours"])
    if cached is not None:
        return cached

    logger.info("Fetching ZHVI from Zillow research endpoint...")
    data = fetch_bytes(_ZHVI_URL, desc="ZHVI", headers=_ZILLOW_HEADERS)
    df = pd.read_csv(io.BytesIO(data), dtype={"RegionName": str})
    logger.info(f"ZHVI fetched: {len(df):,} rows")
    _cache.set("zillow_zhvi", df, source="load_zhvi")
    return df


def load_zori() -> pd.DataFrame:
    """
    Load Zillow Observed Rent Index (ZORI) from Zillow's public research endpoint.
    Cached for 7 days — Zillow publishes monthly updates.
    """
    cached = _cache.get("zillow_zori", ttl_hours=CACHE_TTL["zillow_hours"])
    if cached is not None:
        return cached

    logger.info("Fetching ZORI from Zillow research endpoint...")
    data = fetch_bytes(_ZORI_URL, desc="ZORI", headers=_ZILLOW_HEADERS)
    df = pd.read_csv(io.BytesIO(data), dtype={"RegionName": str})
    logger.info(f"ZORI fetched: {len(df):,} rows")
    _cache.set("zillow_zori", df, source="load_zori")
    return df


def load_zhvf() -> Optional[pd.DataFrame]:
    """
    Load Zillow Home Value Forecast (ZHVF) from Zillow's public research endpoint.
    Cached for 7 days. Returns None on failure — ZHVF is optional in the pipeline.
    """
    cached = _cache.get("zillow_zhvf", ttl_hours=CACHE_TTL["zhvf_hours"])
    if cached is not None:
        return cached

    logger.info("Fetching ZHVF from Zillow research endpoint...")
    try:
        data = fetch_bytes(_ZHVF_URL, desc="ZHVF", headers=_ZILLOW_HEADERS)
        df = pd.read_csv(io.BytesIO(data), dtype={"RegionName": str})
        logger.info(f"ZHVF fetched: {len(df):,} rows")
        _cache.set("zillow_zhvf", df, source="load_zhvf")
        return df
    except Exception as exc:
        logger.warning(f"ZHVF fetch failed (non-fatal): {exc}")
        return None


# ── Census ACS ────────────────────────────────────────────────────────────────

def load_census_acs() -> pd.DataFrame:
    """
    Pull owner-occupancy and income data from Census ACS 5-year API.
    Free, no API key required for basic access (<500 req/day).
    Returns ZIP-level DataFrame. Cached for 30 days.
    """
    cached = _cache.get(_CENSUS_CACHE_KEY, ttl_hours=CACHE_TTL["census_hours"])
    if cached is not None:
        return cached

    variables = ",".join(CENSUS_TABLES.values())
    url = (
        f"{CENSUS_BASE_URL}/{CENSUS_YEAR}/acs/acs5"
        f"?get=NAME,{variables}"
        f"&for=zip+code+tabulation+area:*"
    )
    if CENSUS_API_KEY:
        url += f"&key={CENSUS_API_KEY}"
    logger.info(f"Fetching Census ACS from API: {url}")
    logger.info("Pulling all ZCTAs nationally -- will filter to Texas ZIPs afterward")

    response = requests.get(url, timeout=60)
    if response.status_code == 302 or (response.headers.get("X-DataWebAPI-KeyError") == "1"):
        raise RuntimeError(
            "Census API rejected the request — API key required.\n\n"
            "Get a free key at: https://api.census.gov/data/key_signup.html\n"
            "Then add to your .env file:\n"
            "  CENSUS_API_KEY=your_key_here\n\n"
            "Keys are delivered instantly by email."
        )
    response.raise_for_status()

    data = response.json()
    headers, *rows = data
    df = pd.DataFrame(rows, columns=headers)

    reverse_map = {v: k for k, v in CENSUS_TABLES.items()}
    df = df.rename(columns=reverse_map)
    df = df.rename(columns={"zip code tabulation area": "zip"})

    df["zip"] = df["zip"].astype(str).str.zfill(5)
    texas_mask = df["zip"].between("73301", "79999")
    before = len(df)
    df = df[texas_mask].copy()
    logger.info(f"Filtered {before} national ZCTAs -> {len(df)} Texas ZIPs")

    _cache.set(_CENSUS_CACHE_KEY, df, source="load_census_acs")
    return df


# ── Crime Data ────────────────────────────────────────────────────────────────

def load_crime_data() -> pd.DataFrame:
    """
    Load San Antonio SAPD Calls for Service data.

    Root cause of 403: SA Open Data portal blocks Python's default urllib
    user-agent. Fix: use requests with browser-like headers and stream the
    response directly to disk (file is ~600MB -- don't load into RAM at once).

    Cache behavior: TTL-based — re-downloads after 7 days. The raw CSV lives
    in .cache/; a lightweight marker tracks freshness so we don't need to
    pickle the full file. Delete .cache/crime_raw_marker.* to force refresh.
    """
    cache_path = CACHE_DIR / "sa_crime_raw.csv"

    marker = _cache.get("crime_raw_marker", ttl_hours=CACHE_TTL["crime_hours"])
    if marker and cache_path.exists():
        logger.info(f"Using cached crime data (TTL fresh): {cache_path}")
        return pd.read_csv(cache_path, dtype=str)

    if cache_path.exists():
        logger.info("Crime cache TTL expired — re-downloading fresh data")

    logger.info(f"Downloading SAPD CFS data (~600MB): {SA_CRIME_URL}")

    try:
        mb = download_file(
            SA_CRIME_URL,
            cache_path,
            desc="SAPD crime data",
            headers=_HEADERS,
            timeout=(30, 600),
        ) / (1024 * 1024)
        logger.info(f"Download complete: {mb:.1f} MB → {cache_path}")
    except requests.HTTPError as e:
        raise RuntimeError(
            f"HTTP {e.response.status_code} downloading crime data.\n\n"
            "Manual fallback:\n"
            "  1. Open in browser: https://data.sanantonio.gov/dataset/sapd-calls-for-service\n"
            "  2. Click Download -> CSV\n"
            f"  3. Save file to: {cache_path}\n"
            "  4. Re-run the pipeline -- it will use the cached file."
        ) from e
    except (requests.ConnectionError, requests.Timeout) as e:
        raise RuntimeError(
            f"Crime data download failed ({type(e).__name__}). "
            "Check your connection and retry, or download manually:\n"
            "  1. Open: https://data.sanantonio.gov/dataset/sapd-calls-for-service\n"
            "  2. Click Download -> CSV\n"
            f"  3. Save to: {cache_path}"
        ) from e

    df = pd.read_csv(cache_path, dtype=str)
    logger.info(f"Crime data loaded: {len(df):,} rows, columns: {df.columns.tolist()}")
    _cache.set("crime_raw_marker", True, source="load_crime_data")
    return df


# ── Suburban Crime (FBI CDE / UCR) ───────────────────────────────────────────

_FBI_CDE_BASE = "https://api.usa.gov/crime/fbi/cde"


def load_suburban_crime() -> Optional[pd.DataFrame]:
    """
    Fetch UCR Part I offense data for suburban TX agencies from FBI Crime Data Explorer.

    Covers cities outside SAPD jurisdiction (Cibolo, Schertz, New Braunfels, etc.)
    so their ZIPs can be scored instead of receiving a NO_DATA flag.

    Requires FBI_CDE_API_KEY in .env — free key at https://api.data.gov/signup/
    Returns None gracefully if key not set or API unavailable.

    API response format: {COUNTY_NAME: [agency_records]} — one request, no pagination.
    Agency records have no city_name field; matched by substring in agency_name.

    Methodology note: UCR counts 8 reported offense types (Part I violent + property).
    SAPD data counts all dispatched criminal calls — a broader definition that produces
    rates 3–5× higher for equivalent areas. Both are log-transformed and relative-ranked,
    so the directional ordering (suburbs safer than dense SA ZIPs) is preserved even
    without a perfect methodological match.
    """
    if not FBI_CDE_API_KEY:
        logger.info(
            "FBI_CDE_API_KEY not set — suburban crime data skipped. "
            "Add to .env to score suburbs like Cibolo, Schertz, New Braunfels. "
            "Free key: https://api.data.gov/signup/"
        )
        return None

    cache_key = f"suburban_crime_{FBI_CDE_YEAR}"
    cached = _cache.get(cache_key, ttl_hours=CACHE_TTL.get("suburban_crime_hours", 8760))
    if cached is not None:
        return cached

    # Step 1: fetch all TX agencies — response is {COUNTY_NAME: [agencies]}, one call
    try:
        resp = requests.get(
            f"{_FBI_CDE_BASE}/agency/byStateAbbr/TX",
            params={"API_KEY": FBI_CDE_API_KEY},
            timeout=30,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"FBI CDE agency list fetch failed: {exc}")
        return None

    # Flatten {COUNTY: [agencies]} into a single list
    all_agencies = []
    if isinstance(data, dict):
        for county, agency_list in data.items():
            if isinstance(agency_list, list):
                for a in agency_list:
                    a["_county"] = county
                    all_agencies.append(a)
    elif isinstance(data, list):
        all_agencies = data

    if not all_agencies:
        logger.warning("FBI CDE: no TX agencies in response — check API key or endpoint")
        return None

    logger.info(f"FBI CDE: {len(all_agencies)} TX agencies fetched")

    # Step 2: match agencies to target cities by substring in agency_name.
    # Agency records have no city_name field — "Cibolo Police Department" → "Cibolo".
    # Prefer city PDs (agency_type_name="City") over county SOs.
    city_to_ori: dict[str, str] = {}
    city_to_name: dict[str, str] = {}

    for city_name, _zips in SUBURBAN_CITY_TO_ZIPS.items():
        city_upper = city_name.upper()
        candidates = [
            a for a in all_agencies
            if city_upper in a.get("agency_name", "").upper()
        ]
        if not candidates:
            logger.warning(
                f"FBI CDE: no agency found for '{city_name}' — "
                f"ZIP(s) {_zips} will remain NO_DATA"
            )
            continue

        # City PD preferred; fall back to county SO or first match
        pds = [a for a in candidates if a.get("agency_type_name", "").lower() == "city"]
        chosen = (pds or candidates)[0]
        city_to_ori[city_upper] = chosen["ori"]
        city_to_name[city_upper] = chosen["agency_name"]

    if not city_to_ori:
        logger.warning("FBI CDE: no agencies matched any target city")
        return None

    # Step 3: fetch offense totals per agency.
    # api.usa.gov/crime/fbi/cde only proxies the agency LIST — per-agency offense
    # data is on cde.fbi.gov (the CDE website's own public API, no key needed).
    # We try two endpoint shapes; whichever returns 200 is used.
    _CDE_BASE = "https://cde.fbi.gov/api"

    def _fetch_offenses(ori: str) -> tuple[int, int]:
        """Return (total_offenses, population) for the agency, or (0, 0) on failure."""
        # NIBRS annual offense counts by subcategory
        attempts = [
            (
                f"{_CDE_BASE}/nibrs/offense/agencies/{ori}/count/annual",
                {"variable": "offense_subcat_name", "from": FBI_CDE_YEAR, "to": FBI_CDE_YEAR},
            ),
            # Fallback: try without the variable filter
            (
                f"{_CDE_BASE}/nibrs/offense/agencies/{ori}/count/annual",
                {"from": FBI_CDE_YEAR, "to": FBI_CDE_YEAR},
            ),
            # Fallback: prior year in case current year isn't published yet
            (
                f"{_CDE_BASE}/nibrs/offense/agencies/{ori}/count/annual",
                {"variable": "offense_subcat_name", "from": FBI_CDE_YEAR - 1, "to": FBI_CDE_YEAR - 1},
            ),
        ]
        for url, params in attempts:
            try:
                r = requests.get(url, params=params, timeout=15, headers=_HEADERS)
                logger.debug(f"FBI CDE offense probe [{r.status_code}]: {r.url}")
                if r.status_code != 200:
                    continue
                body = r.json()
                # Response: {"data": [{"data_year": Y, "key": "Burglary", "value": N}, ...]}
                # or a plain list
                items = body.get("data", body) if isinstance(body, dict) else body
                if not isinstance(items, list) or not items:
                    continue
                # Sum "value" field across all offense subcategories
                total = sum(int(item.get("value", 0) or 0) for item in items)
                # Population comes from a separate agency detail endpoint; use 0 here —
                # process_suburban_crime() will fill in Census population instead.
                return total, 0
            except Exception as exc:
                logger.debug(f"FBI CDE offense attempt failed ({url}): {exc}")
        return 0, 0

    rows = []
    city_zip_map = {c.upper(): zips for c, zips in SUBURBAN_CITY_TO_ZIPS.items()}

    for city_upper, ori in city_to_ori.items():
        total, pop = _fetch_offenses(ori)
        if total == 0:
            logger.warning(
                f"FBI CDE: no offense data for {city_upper} "
                f"({ori} — {city_to_name[city_upper]}) — ZIP(s) "
                f"{city_zip_map.get(city_upper, [])} will remain NO_DATA"
            )
            continue

        logger.info(
            f"FBI CDE {city_upper} — {city_to_name[city_upper]} ({ori}): "
            f"{total:,} Part I offenses ({FBI_CDE_YEAR})"
        )
        for zip_code in city_zip_map.get(city_upper, []):
            rows.append({
                "zip": str(zip_code).zfill(5),
                "crime_incidents": total,
                "ucr_population": pop,
            })

    if not rows:
        logger.warning(
            "FBI CDE: no suburban crime rows assembled. "
            "All agency offense lookups failed — check logs above for details."
        )
        return None

    df = pd.DataFrame(rows)
    logger.info(f"Suburban crime (UCR): {len(df)} ZIP records assembled")
    _cache.set(cache_key, df, source="load_suburban_crime")
    return df


# ── BCAD Parcel Data ──────────────────────────────────────────────────────────

_SA_AREA_ZIPS_BCAD = (
    [str(z) for z in range(78201, 78270)]
    + ["78109", "78148", "78150", "78154", "78266"]
)


def load_bcad_data() -> Optional[pd.DataFrame]:
    """
    Fetch BCAD parcel counts and assessed values from the Bexar County ArcGIS
    REST service — no auth required, single statistics query, cached 30 days.

    Returns a raw DataFrame with one row per (ZIP, State_cd) combination:
      Zip          — 5-digit ZIP code
      State_cd     — Texas property type code (A1=SFR, B1=Small MF, B2=Large MF)
      prop_count   — number of parcels in this ZIP × State_cd group
      avg_tot_val  — average total assessed value (land + improvements)
      avg_impr_val — average improvement (structure) value only

    Uses a single ArcGIS GROUP BY statistics query — no pagination needed.
    """
    cached = _cache.get("bcad_parcels", ttl_hours=CACHE_TTL["bcad_hours"])
    if cached is not None:
        return cached

    logger.info("Fetching BCAD parcel stats from Bexar County ArcGIS REST service...")

    zip_list = "','".join(_SA_AREA_ZIPS_BCAD)
    out_stats = json.dumps([
        {"statisticType": "count", "onStatisticField": "OBJECTID",  "outStatisticFieldName": "prop_count"},
        {"statisticType": "avg",   "onStatisticField": "TotVal",    "outStatisticFieldName": "avg_tot_val"},
        {"statisticType": "avg",   "onStatisticField": "ImprVal",   "outStatisticFieldName": "avg_impr_val"},
    ])
    params = {
        "where": f"Zip IN ('{zip_list}')",
        "groupByFieldsForStatistics": "Zip,State_cd",
        "outStatistics": out_stats,
        "f": "json",
    }

    try:
        resp = requests.get(BCAD_ARCGIS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"BCAD fetch failed (non-fatal — pipeline continues without it): {exc}")
        return None

    if "error" in data:
        logger.warning(f"BCAD ArcGIS error: {data['error']} — skipping")
        return None

    features = data.get("features", [])
    if not features:
        logger.warning("BCAD returned 0 features — skipping")
        return None

    rows = [f["attributes"] for f in features]
    df = pd.DataFrame(rows)
    df = df.rename(columns={"Zip": "zip"})
    df["zip"] = df["zip"].astype(str).str.zfill(5)

    logger.info(
        f"BCAD: {len(df)} ZIP×State_cd groups | "
        f"{df['prop_count'].sum():,.0f} total parcels across {df['zip'].nunique()} ZIPs"
    )
    _cache.set("bcad_parcels", df, source="load_bcad_data")
    return df


# ── SA Building Permits ───────────────────────────────────────────────────────

_PERMITS_CACHE_PATH = CACHE_DIR / "sa_permits_issued.csv"


def load_permit_data() -> Optional[pd.DataFrame]:
    """
    Load SA building permits from the SA Open Data portal.

    Cached as a flat CSV file (same pattern as crime data) with a 7-day TTL
    marker. The file covers current + recent months; we filter to the trailing
    12 months in process_permits().

    Uses browser-like headers — the SA Open Data portal blocks default
    Python user-agents (same issue as the crime data endpoint).
    """
    marker = _cache.get("permits_marker", ttl_hours=CACHE_TTL["permits_hours"])
    if marker and _PERMITS_CACHE_PATH.exists():
        logger.info(f"Using cached permits data: {_PERMITS_CACHE_PATH}")
        return pd.read_csv(_PERMITS_CACHE_PATH, dtype=str, low_memory=False)

    logger.info("Downloading SA building permits (~20 MB)...")
    try:
        mb = download_file(
            SA_PERMITS_URL,
            _PERMITS_CACHE_PATH,
            desc="SA permits",
            headers=_HEADERS,
            timeout=(30, 120),
        ) / (1024 * 1024)
        logger.info(f"Permits download complete: {mb:.1f} MB → {_PERMITS_CACHE_PATH}")
    except Exception as exc:
        if _PERMITS_CACHE_PATH.exists():
            logger.warning(f"Permits download failed ({exc}) — using stale cache")
        else:
            logger.warning(f"Permits download failed (non-fatal): {exc}")
            return None

    _cache.set("permits_marker", True, source="load_permit_data")
    _cache.invalidate("permits_processed")  # force reprocessing on next pipeline run
    df = pd.read_csv(_PERMITS_CACHE_PATH, dtype=str, low_memory=False)
    logger.info(f"Permits loaded: {len(df):,} rows")
    return df
