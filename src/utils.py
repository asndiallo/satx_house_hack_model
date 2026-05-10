"""
utils.py
--------
Shared utilities: logging setup, file I/O helpers, validation.
"""

import io
import logging
import sys
import zipfile
from pathlib import Path
import pandas as pd
import requests

from cache_manager import CacheManager
from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)

# Census ZCTA Gazetteer — free, no auth, updated annually
_GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2024_Gazetteer/2024_Gaz_zcta_national.zip"
)


def setup_logging(level: str = "INFO") -> None:
    log_format = "%(asctime)s | %(levelname)-8s | %(module)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("model_run.log", mode="w"),
        ]
    )


def save_csv(df: pd.DataFrame, path: Path, description: str = "") -> None:
    """Save DataFrame with logging. Creates parent dirs if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    rows, cols = df.shape
    label = f" ({description})" if description else ""
    logger.info(f"Saved{label}: {path.name} — {rows} rows × {cols} cols")


def validate_dataframe(df: pd.DataFrame, required_cols: list, name: str = "DataFrame") -> None:
    """Raise informative error if required columns are missing."""
    missing = set(required_cols) - set(df.columns)
    if missing:
        raise ValueError(
            f"{name} is missing required columns: {sorted(missing)}\n"
            f"Available: {sorted(df.columns.tolist())}"
        )


def load_zip_centroids(filepath: Path = None) -> pd.DataFrame:
    """
    Load ZIP code latitude/longitude centroids.

    Fetches from the Census ZCTA Gazetteer on first run (or after TTL expiry)
    and caches the result. No manual download required.
    Cached for 1 year — ZIP centroids are effectively static.
    """
    if filepath is not None:
        df = pd.read_csv(filepath, dtype={"zip": str})
        df["zip"] = df["zip"].str.zfill(5)
        return df[["zip", "lat", "lng"]].rename(columns={"lat": "zip_lat", "lng": "zip_lon"})

    _cache = CacheManager(CACHE_DIR)
    cached = _cache.get("uszips", ttl_hours=CACHE_TTL["uszips_hours"])
    if cached is not None:
        return cached

    logger.info("Fetching ZIP centroids from Census ZCTA Gazetteer...")
    resp = requests.get(_GAZETTEER_URL, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        txt_name = next(n for n in zf.namelist() if n.endswith(".txt"))
        with zf.open(txt_name) as f:
            raw = pd.read_csv(f, sep="\t", dtype={"GEOID": str})
    raw.columns = raw.columns.str.strip()

    raw["GEOID"] = raw["GEOID"].astype(str).str.zfill(5)
    df = raw[["GEOID", "INTPTLAT", "INTPTLONG"]].rename(columns={
        "GEOID": "zip",
        "INTPTLAT": "zip_lat",
        "INTPTLONG": "zip_lon",
    })
    df = df.dropna(subset=["zip_lat", "zip_lon"])
    logger.info(f"ZIP centroids loaded: {len(df):,} ZCTAs")

    _cache.set("uszips", df, source="load_zip_centroids")
    return df
