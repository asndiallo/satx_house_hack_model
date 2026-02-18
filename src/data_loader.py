"""
data_loader.py
--------------
All raw data ingestion lives here.
Each function returns a raw, unmodified DataFrame — no business logic.
"""

import io
import logging
import requests
import pandas as pd
from pathlib import Path
from typing import Optional

from config import (
    DATA_RAW, CENSUS_BASE_URL, CENSUS_YEAR,
    CENSUS_TABLES, TARGET_STATE_FIPS, SA_CRIME_URL
)

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


# ── Zillow ────────────────────────────────────────────────────────────────────

def load_zhvi(filepath: Optional[Path] = None) -> pd.DataFrame:
    """
    Load Zillow Home Value Index (ZHVI) CSV.
    Download manually from:
    https://www.zillow.com/research/data/ -> 'ZHVI All Homes (SFR, Condo/Co-op)
    Time Series, Smoothed, Seasonally Adjusted' -> ZIP code level
    """
    path = filepath or DATA_RAW / "zillow_zhvi_zip.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"ZHVI file not found at {path}.\n"
            "Download from: https://www.zillow.com/research/data/"
        )
    logger.info(f"Loading ZHVI from {path}")
    df = pd.read_csv(path, dtype={"RegionName": str})
    return df


def load_zori(filepath: Optional[Path] = None) -> pd.DataFrame:
    """
    Load Zillow Observed Rent Index (ZORI) CSV.
    Download manually from:
    https://www.zillow.com/research/data/ -> 'ZORI (Smoothed): All Homes Plus
    Multifamily' -> ZIP code level
    """
    path = filepath or DATA_RAW / "zillow_zori_zip.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"ZORI file not found at {path}.\n"
            "Download from: https://www.zillow.com/research/data/"
        )
    logger.info(f"Loading ZORI from {path}")
    df = pd.read_csv(path, dtype={"RegionName": str})
    return df


# ── Census ACS ────────────────────────────────────────────────────────────────

def load_census_acs() -> pd.DataFrame:
    """
    Pull owner-occupancy and income data from Census ACS 5-year API.
    Free, no API key required for basic access (<500 req/day).
    Returns ZIP-level DataFrame.
    """
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

    out_path = DATA_RAW / "census_acs_raw.csv"
    df.to_csv(out_path, index=False)
    logger.info(f"Census data cached to {out_path}")

    return df


# ── Crime Data ────────────────────────────────────────────────────────────────

def load_crime_data(filepath: Optional[Path] = None) -> pd.DataFrame:
    """
    Load San Antonio SAPD Calls for Service data.

    Root cause of 403: SA Open Data portal blocks Python's default urllib
    user-agent. Fix: use requests with browser-like headers and stream the
    response directly to disk (file is ~600MB -- don't load into RAM at once).

    Cache behavior: if sa_crime_raw.csv already exists locally, skip download.
    Delete the cache file to force a fresh pull.
    """
    cache_path = filepath or DATA_RAW / "sa_crime_raw.csv"

    # Use cache if available
    if cache_path.exists():
        logger.info(f"Using cached crime data: {cache_path}")
        return pd.read_csv(cache_path, dtype=str)

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
            "Download timed out after 120s. Try again on a faster connection,\n"
            "or download manually and save to: {cache_path}"
        )

    df = pd.read_csv(cache_path, dtype=str)
    logger.info(f"Crime data loaded: {len(df):,} rows, columns: {df.columns.tolist()}")
    return df