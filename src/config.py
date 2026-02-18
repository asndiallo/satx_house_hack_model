"""
config.py
---------
Single source of truth for all model parameters.
Change weights, thresholds, and paths HERE only — never hardcode elsewhere.
"""

from pathlib import Path
import os

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
# Challenge these before going live — they encode YOUR priorities.
# Run: python sensitivity.py to see how rankings shift when weights change.
WEIGHTS = {
    "rent_to_price":   0.35,
    "crime":           0.25,
    "owner_occupancy": 0.20,
    "commute":         0.20,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# ── Hard Filters (absolute disqualifiers) ────────────────────────────────────
# These remove ZIPs before scoring. Crime is handled separately via percentile.
THRESHOLDS = {
    # SA is a C+/B- yield market. Observed range: 0.04-0.09.
    "min_rent_to_price":  0.055,

    # Adjust to your VA loan limit / purchase budget ceiling.
    "max_home_value":     500_000,

    # Balanced range: too low = transient/unstable, too high = low rental demand
    "min_owner_occ_pct":  0.40,
    "max_owner_occ_pct":  0.85,
}

# ── Crime Filtering ───────────────────────────────────────────────────────────
# Percentile-based cutoff: keeps bottom N% of ZIPs by crime rate.
# More robust than a hard threshold because it's immune to CFS data distortion.
# 0.60 = keep the 60% least-criminal ZIPs in your scoring pool.
CRIME_PERCENTILE_CUTOFF = 0.60

# Allowlist of SA CFS Problem values that map to actual criminal incidents.
# Filters out: medical emergencies, welfare checks, noise complaints, traffic.
# If crime_per_1k still looks distorted, inspect with:
#   crime_raw["Problem"].value_counts().head(30)
# Then add or remove values here.
VIOLENT_CRIME_PROBLEMS = {
    "ASSAULT",
    "ASSAULT - FAMILY VIOLENCE",
    "ASSAULT WITH INJURY",
    "AGGRAVATED ASSAULT",
    "ROBBERY",
    "ROBBERY - CARJACKING",
    "BURGLARY",
    "BURGLARY - VEHICLE",
    "BURGLARY - RESIDENCE",
    "BURGLARY - BUSINESS",
    "SHOOTING",
    "SHOTS FIRED",
    "HOMICIDE",
    "RAPE",
    "SEXUAL ASSAULT",
    "KIDNAPPING",
    "ARSON",
    "THEFT",
    "THEFT - AUTO",
    "THEFT FROM VEHICLE",
    "THEFT - SHOPLIFTING",
    "NARCOTICS",
    "NARCOTICS - SELL/DELIVER",
}

# ── Census API ────────────────────────────────────────────────────────────────
CENSUS_YEAR = 2022
CENSUS_TABLES = {
    "owner_occ_count":  "B25003_002E",
    "total_housing":    "B25003_001E",
    "median_hh_income": "B19013_001E",
    "population":       "B01003_001E",  # required for crime per-1k normalization
}
CENSUS_BASE_URL = "https://api.census.gov/data"

# ── Google Maps (optional — falls back to geopy if None) ─────────────────────
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", None)

# ── San Antonio Open Data ─────────────────────────────────────────────────────
SA_CRIME_URL = (
    "https://data.sanantonio.gov/dataset/111a6b75-a125-410c-b483-8470e9bf9324"
    "/resource/9cb17985-ac16-49a6-ad69-6fe5ad8f2bf5/download/pubsafedash_cfs.csv"
)
# Schema (verified Feb 2026):
# Master_Incident_Number, Response_Date, Priority, Problem, Service_Area,
# Type, Seconds, Weekday, Disposition_Groups, Disposition_Type, Postal_Code