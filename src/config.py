"""
config.py
---------
Single source of truth for all model parameters.
Change weights, thresholds, and paths HERE only — never hardcode elsewhere.
"""

from pathlib import Path

# ── Project Paths ─────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).resolve().parents[1]
DATA_RAW   = ROOT_DIR / "data" / "raw"
DATA_PROC  = ROOT_DIR / "data" / "processed"
DATA_FINAL = ROOT_DIR / "data" / "final"
OUTPUTS    = ROOT_DIR / "outputs"

# ── Duty Station ──────────────────────────────────────────────────────────────
DUTY_STATION = {
    "name": "BAMC - Fort Sam Houston",
    "lat": 29.4563,
    "lon": -98.4436,
}

# ── Geographic Scope ──────────────────────────────────────────────────────────
TARGET_STATE_FIPS = "48"        # Texas
TARGET_METRO      = "San Antonio"
MAX_COMMUTE_MILES = 25          # straight-line cutoff before scoring
MAX_COMMUTE_MINS  = 35          # drive-time cutoff (Google Maps)

# ── Scoring Weights (must sum to 1.0) ─────────────────────────────────────────
# Challenge these before going live — they encode YOUR priorities
WEIGHTS = {
    "rent_to_price":   0.35,
    "crime":           0.25,
    "owner_occupancy": 0.20,
    "commute":         0.20,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# ── Scoring Thresholds ────────────────────────────────────────────────────────
THRESHOLDS = {
    # SA is a C+/B- yield market — 0.07 is too aggressive here.
    # Observed range in data: 0.04–0.09. Use 0.055 to keep competitive ZIPs.
    "min_rent_to_price":      0.055,

    # Observed max home value in SA ZIPs: ~$905k. $400k cut too much.
    # House-hack budget ceiling — adjust to your VA loan limit if needed.
    "max_home_value":         500_000,

    "min_owner_occ_pct":      0.40,   # loosened slightly — 0.45 killed 11 ZIPs
    "max_owner_occ_pct":      0.85,   # loosened slightly — 0.80 killed 8 ZIPs

    # IMPORTANT: this threshold only applies AFTER proper per-1k normalization.
    # Raw counts (before population data) made every ZIP fail this.
    # 50 per 1k = ~5% of population involved in a call — reasonable upper bound.
    "max_crime_per_1k":       50.0,
}

# ── Census API ────────────────────────────────────────────────────────────────
CENSUS_YEAR = 2022
CENSUS_TABLES = {
    "owner_occ_count":    "B25003_002E",
    "total_housing":      "B25003_001E",
    "median_hh_income":   "B19013_001E",
    "population":         "B01003_001E",   # total population — needed for crime rate normalization
}
CENSUS_BASE_URL = "https://api.census.gov/data"

# ── Google Maps (optional — falls back to geopy if None) ─────────────────────
# Set via environment variable, never hardcode keys in source
import os
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", None)

# ── San Antonio Open Data ─────────────────────────────────────────────────────
SA_CRIME_URL = (
    "https://data.sanantonio.gov/dataset/111a6b75-a125-410c-b483-8470e9bf9324"
    "/resource/9cb17985-ac16-49a6-ad69-6fe5ad8f2bf5/download/pubsafedash_cfs.csv"
)
# Data dictionary (as of Feb 2026):
# Columns: Master_Incident_Number, Response_Date, Priority, Problem,
#          Service_Area, Type, Seconds, Weekday, Disposition_Groups,
#          Disposition_Type, Postal_Code