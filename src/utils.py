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
from typing import Optional
import pandas as pd
import requests
from tqdm import tqdm

from cache_manager import CacheManager
from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)

# Census ZCTA Gazetteer — free, no auth, updated annually
_GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2024_Gazetteer/2024_Gaz_zcta_national.zip"
)


def download_file(
    url: str,
    dest: Path,
    desc: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout=(30, 600),
    chunk_size: int = 256 * 1024,
) -> int:
    """
    Stream a URL to disk with a tqdm progress bar. Atomic: writes to a .tmp
    file and renames on success so a failed download never corrupts the cache.
    Returns bytes written.
    """
    dest = Path(dest)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    resp = requests.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0)) or None
    dest.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    try:
        with (
            open(tmp, "wb") as fh,
            tqdm(
                total=total,
                desc=desc or dest.name,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                dynamic_ncols=True,
                miniters=1,
            ) as bar,
        ):
            for chunk in resp.iter_content(chunk_size=chunk_size):
                fh.write(chunk)
                bytes_written += len(chunk)
                bar.update(len(chunk))
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return bytes_written


def fetch_bytes(
    url: str,
    desc: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: int = 60,
) -> bytes:
    """
    Fetch a URL into memory with a tqdm progress bar. Use for smaller files
    (Zillow CSVs, ZIP centroid archives) where streaming to disk is overkill.
    """
    resp = requests.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0)) or None
    chunks: list[bytes] = []
    with tqdm(
        total=total,
        desc=desc or url.rsplit("/", 1)[-1],
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        dynamic_ncols=True,
        miniters=1,
    ) as bar:
        for chunk in resp.iter_content(chunk_size=256 * 1024):
            chunks.append(chunk)
            bar.update(len(chunk))
    return b"".join(chunks)


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
    raw_bytes = fetch_bytes(_GAZETTEER_URL, desc="ZIP centroids")

    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
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
