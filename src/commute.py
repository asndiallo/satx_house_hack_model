"""
commute.py
----------
Calculate commute distance/time from each ZIP centroid to BAMC.
Uses Google Maps Distance Matrix API if key is set, else falls back
to geopy straight-line distance (Haversine formula).
"""

import hashlib
import logging
import time
import requests
import pandas as pd
import numpy as np

from cache_manager import CacheManager
from config import CACHE_DIR, CACHE_TTL, DUTY_STATION, GOOGLE_MAPS_API_KEY, MAX_COMMUTE_MILES

_cache = CacheManager(CACHE_DIR)

logger = logging.getLogger(__name__)

BAMC_LAT = DUTY_STATION["lat"]
BAMC_LON = DUTY_STATION["lon"]


# ── Haversine (free fallback) ─────────────────────────────────────────────────

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in miles between two lat/lon points."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))


def add_straight_line_distance(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add straight-line miles from each ZIP centroid to BAMC.
    Requires 'zip_lat' and 'zip_lon' columns.
    Use this when Google Maps API key is not available.
    """
    if "zip_lat" not in df.columns or "zip_lon" not in df.columns:
        raise ValueError(
            "DataFrame must have 'zip_lat' and 'zip_lon' columns.\n"
            "Get ZIP centroids from: https://simplemaps.com/data/us-zips (free tier)"
        )
    
    df = df.copy()
    df["commute_miles"] = df.apply(
        lambda r: haversine_miles(r["zip_lat"], r["zip_lon"], BAMC_LAT, BAMC_LON),
        axis=1
    )
    # Approximate minutes: assume 1.4x straight-line to road distance, 35 mph avg
    df["commute_minutes"] = (df["commute_miles"] * 1.4 / 35) * 60
    
    logger.info(
        f"Straight-line commute: {(df['commute_miles'] <= MAX_COMMUTE_MILES).sum()} "
        f"ZIPs within {MAX_COMMUTE_MILES} miles"
    )
    return df


# ── Google Maps (preferred) ───────────────────────────────────────────────────

def _commute_cache_key(zips: list[str]) -> str:
    zip_hash = hashlib.md5(",".join(sorted(zips)).encode()).hexdigest()[:8]
    return f"commute_to_bamc_{zip_hash}"


def add_drive_time_google(df: pd.DataFrame, departure_time: str = "morning_peak") -> pd.DataFrame:
    """
    Add real drive time via Google Maps Distance Matrix API.
    Batches requests (max 25 origins per call) to stay within rate limits.

    departure_time: 'morning_peak' targets 0600 Tuesday traffic
                    'offpeak' uses current time

    Results cached for 1 year — drive times to BAMC are effectively static.
    Cache is keyed by the sorted ZIP set so a changed input triggers a fresh fetch.
    """
    if not GOOGLE_MAPS_API_KEY:
        logger.warning("No GOOGLE_MAPS_API_KEY found. Falling back to straight-line.")
        return add_straight_line_distance(df)

    if "zip_lat" not in df.columns:
        raise ValueError("Need 'zip_lat' and 'zip_lon' columns for Google Maps calls.")

    cache_key = _commute_cache_key(df["zip"].tolist())
    cached = _cache.get(cache_key, ttl_hours=CACHE_TTL["commute_hours"])
    if cached is not None:
        return cached
    
    destination = f"{BAMC_LAT},{BAMC_LON}"
    results = []
    batch_size = 25
    
    origins = list(zip(df["zip_lat"], df["zip_lon"], df["zip"]))
    batches = [origins[i:i+batch_size] for i in range(0, len(origins), batch_size)]
    
    logger.info(f"Calling Google Maps API for {len(origins)} ZIPs in {len(batches)} batches")
    
    for i, batch in enumerate(batches):
        origin_str = "|".join(f"{lat},{lon}" for lat, lon, _ in batch)
        params = {
            "origins": origin_str,
            "destinations": destination,
            "mode": "driving",
            "key": GOOGLE_MAPS_API_KEY,
        }
        if departure_time == "morning_peak":
            # Next Tuesday at 0600 local
            import datetime
            now = datetime.datetime.now()
            days_ahead = (1 - now.weekday()) % 7 or 7  # next Tuesday
            next_tue = now + datetime.timedelta(days=days_ahead)
            depart = next_tue.replace(hour=6, minute=0, second=0, microsecond=0)
            params["departure_time"] = int(depart.timestamp())
        
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/distancematrix/json",
            params=params, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        
        for j, row in enumerate(data["rows"]):
            element = row["elements"][0]
            zip_code = batch[j][2]
            if element["status"] == "OK":
                minutes = element["duration"]["value"] / 60
                miles = element["distance"]["value"] / 1609.34
            else:
                minutes, miles = None, None
                logger.warning(f"ZIP {zip_code}: Google Maps returned {element['status']}")
            results.append({"zip": zip_code, "commute_minutes": minutes, "commute_miles": miles})
        
        # Respectful rate limiting
        if i < len(batches) - 1:
            time.sleep(0.1)
    
    commute_df = pd.DataFrame(results)
    df = df.merge(commute_df, on="zip", how="left")
    logger.info("Google Maps drive times added successfully")
    _cache.set(cache_key, df, source="add_drive_time_google")
    return df
