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
from config import (
    CACHE_DIR, CACHE_TTL,
    CENSUS_BASE_URL, CENSUS_YEAR,
    CENSUS_TABLES, SA_CRIME_URL
)

_cache = CacheManager(CACHE_DIR)

logger = logging.getLogger(__name__)

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
    resp = requests.get(_ZHVI_URL, headers=_ZILLOW_HEADERS, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.BytesIO(resp.content), dtype={"RegionName": str})
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
    resp = requests.get(_ZORI_URL, headers=_ZILLOW_HEADERS, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.BytesIO(resp.content), dtype={"RegionName": str})
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
        resp = requests.get(_ZHVF_URL, headers=_ZILLOW_HEADERS, timeout=60)
        resp.raise_for_status()
        df = pd.read_csv(io.BytesIO(resp.content), dtype={"RegionName": str})
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
    cached = _cache.get("census_acs", ttl_hours=CACHE_TTL["census_hours"])
    if cached is not None:
        return cached

    variables = ",".join(CENSUS_TABLES.values())
    url = (
        f"{CENSUS_BASE_URL}/{CENSUS_YEAR}/acs/acs5"
        f"?get=NAME,{variables}"
        f"&for=zip+code+tabulation+area:*"
    )
    logger.info(f"Fetching Census ACS from API: {url}")
    logger.info("Pulling all ZCTAs nationally -- will filter to Texas ZIPs afterward")

    response = requests.get(url, timeout=60)
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

    _cache.set("census_acs", df, source="load_census_acs")
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

    logger.info("Downloading SAPD CFS data (~600MB, this will take 30-90s)...")
    logger.info(f"Source: {SA_CRIME_URL}")

    try:
        response = requests.get(
            SA_CRIME_URL,
            headers=_HEADERS,
            stream=True,
            timeout=120,
            allow_redirects=True,
        )
        response.raise_for_status()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        with open(cache_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                bytes_written += len(chunk)

        mb = bytes_written / (1024 * 1024)
        logger.info(f"Download complete: {mb:.1f} MB written to {cache_path}")

    except requests.HTTPError as e:
        raise RuntimeError(
            f"HTTP {e.response.status_code} downloading crime data.\n\n"
            "Manual fallback:\n"
            "  1. Open in browser: https://data.sanantonio.gov/dataset/sapd-calls-for-service\n"
            "  2. Click Download -> CSV\n"
            f"  3. Save file to: {cache_path}\n"
            "  4. Re-run the pipeline -- it will use the cached file."
        ) from e

    except requests.Timeout:
        raise RuntimeError(
            f"Download timed out after 120s. Try again on a faster connection,\n"
            f"or download manually and save to: {cache_path}"
        )

    df = pd.read_csv(cache_path, dtype=str)
    logger.info(f"Crime data loaded: {len(df):,} rows, columns: {df.columns.tolist()}")
    _cache.set("crime_raw_marker", True, source="load_crime_data")
    return df
