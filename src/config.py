"""
config.py
---------
Single source of truth for ALL model parameters.
Change weights, thresholds, and paths HERE only — never hardcode elsewhere.

This model is tuned for Path B: military house hack, 3-year hold, BAMC duty station.
Path B logic: screen out unacceptable risk first, then optimize within safe candidates.
Some things are NOT tradeable — those are filters, not weights.
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
TARGET_STATE_FIPS = "48"
TARGET_METRO      = "San Antonio"
MAX_COMMUTE_MILES = 25
MAX_COMMUTE_MINS  = 35

# ── Scoring Weights (must sum to 1.0) ─────────────────────────────────────────
# These encode your priorities AS A MILITARY HOUSE HACKER, not a pure investor.
# Key shifts vs Path A investor logic:
#   - Crime weight increased (you live there — it is not negotiable)
#   - Yield weight decreased (viability matters more than maximization)
#   - Stability added (3-year hold = price volatility is real risk)
#   - Commute reduced slightly (still important, but safety/stability outrank it)
#
# Run: python sensitivity.py to verify rankings hold across weight perturbations.
WEIGHTS = {
    "rent_to_price":   0.25,   # viability, not maximization
    "crime":           0.30,   # non-negotiable — you live there
    "owner_occupancy": 0.20,   # neighborhood stability proxy
    "commute":         0.15,   # important but not override-level
    "stability":       0.10,   # 3-year price stability (ZHVI CoV)
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# ── Hard Filters (non-negotiable disqualifiers) ───────────────────────────────
# Anything here is a SCREEN, not a scored dimension.
# Path B principle: if you won't compromise on it, make it a filter.
THRESHOLDS = {
    # Derived from SA cashflow math — revised for 2026 market conditions:
    # VA loan 0% down, 6.5% rate, $250k home ~ $1,580/month PITI
    # Need ~$1,800/month rent to cover PITI + 5% vacancy + 8% maintenance reserve
    # BUT: SA median home values have risen ~30% since 2022 without proportional rent growth.
    # At $300k (more realistic 2026 SA median), break-even is ~$2,160/month rent —
    # which most SA ZIPs cannot support. 0.065 reflects current market reality
    # while still excluding ZIPs that genuinely don't cashflow on a VA loan.
    # Revisit this annually as rates and prices shift.
    "min_rent_to_price":  0.065,

    # SA 2026 conforming VA loan limit — adjust if your COE differs
    "max_home_value":     450_000,

    # Tightened from 0.40: below 50% = neighborhood is primarily transient renters
    # That's not who you want living next to you or renting from you
    "min_owner_occ_pct":  0.50,

    # Above 80% = low rental demand; finding tenants will be hard
    "max_owner_occ_pct":  0.80,

    # Tenant base quality screen — low income correlates with:
    # higher delinquency risk, slower resale, weaker neighborhood trajectory
    # $42k = roughly E-5/E-6 BAH + base pay range in SA — your target tenant
    "min_median_income":  42_000,
}

# ── Crime Filtering ───────────────────────────────────────────────────────────
# Path B: crime is a hard screen, not a soft negotiable.
# 0.45 = keep only the safest 45% of ZIPs by crime rate, where "safe" means "lower crime than 45% of other ZIPs".
# You live in this property. This is not tradeable against yield.
CRIME_PERCENTILE_CUTOFF = 0.45

# Minimum population for a ZIP to get a crime per-1k rate.
# Without this floor, commercial corridors and fringe ZIPs with ~100 Census residents
# but thousands of daily workers produce absurd rates (e.g. 8,540/1k).
# Those ZIPs are not residential neighborhoods — they have no place in this model.
# 2,000 is conservative; raise to 5,000 if you want to exclude thin-data ZIPs entirely.
MIN_POPULATION_FOR_CRIME = 2_000

# Allowlist of SA CFS Problem types that represent actual criminal incidents.
# Excludes medical emergencies, welfare checks, noise, traffic — activity, not crime.
# To inspect actual values in your data: crime_raw["Problem"].value_counts().head(40)
VIOLENT_CRIME_PROBLEMS = {
    # ASSAULT / ACTIVE VIOLENCE
    "ASSAULT",
    "ASSAULT IN PROGRESS",
    "FAMILY VIOLENCE",
    "FAMILY VIOLENCE GUN INV",
    "FAMILY VIOLENCE KNIFE INV",
    "CUTTING",
    "CUTTING IN PROGRESS",
    "DISTURBANCE (GUN INVOLVED)",
    "DISTURBANCE (KNIFE INVOLVED)",
    "DISTURBANCE FAMILY GUN INV",
    "DISTURBANCE FAMILY KNIFE INV",
    "DISTURBANCE NEIGHBOR GUN INV",
    "DISTURBANCE NEIGHBOR KNIFE IN",
    "FIGHT",
    "FIGHT GUN INVOLVED",
    "FIGHT KNIFE INVOLVED",

    # ROBBERY
    "ROBBERY",
    "ROBBERY IN PROGRESS",
    "ROBBERY OF INDIVIDUAL",
    "ROBBERY OF INDIVIDUAL PROGRES",
    "HOLDUP ALARM IN PROGRESS",
    "HOLDUP ALARM RES IN PROGRESS",

    # SEXUAL VIOLENCE
    "RAPE",
    "RAPE IN PROGRESS",
    "SEXUAL OFFENSE-CHILD",
    "INTERNET PREDATOR",
    "LEWD CONDUCT",

    # SHOOTINGS / WEAPONS
    "SHOOTING",
    "SHOOTING IN PROGRESS",
    "SHOTS FIRED JUST OCCURRED",
    "SHOT FIRED/HEARD",
    "SHOTSPOTTER SINGLE ALERT",
    "SHOTSPOTTER MULTIPLE ALERT",
    "WEAPONS",

    # ARSON
    "ARSON RESPONSE",

    # BURGLARY
    "BURGLARY",
    "BURGLARY (IN PROGRESS)",
    "BURGLARY VEHICLE",
    "BURGLARY VEHICLE IN PROGRESS",

    # THEFT
    "THEFT",
    "THEFT IN PROGRESS",
    "THEFT OF VEHICLE",
    "THEFT OF VEHICLE IN PROGRESS",

    # CRIMINAL THREATS & ORDERS
    "VIOLATION OF PROTECTIVE ORDER",
    "VIOLATION SEX OFF REG",
    "THREATS BOMB",
    "THREATS BOMB IN PROGRESS",
    "THREAT - BOMB WITH DEVICE",

    # NARCOTICS / VICE
    "NARCOTIC LAWS",
    "VICE",
}

# ── Yield Cap ─────────────────────────────────────────────────────────────────
# Path B treats abnormal yield as a warning sign, not a bonus.
# In SA, gross yield > 12% almost always means:
#   - Distressed area, deferred maintenance, or data quality issue
#   - NOT a hidden gem
# Cap rent_to_price at this value before normalization so extreme outliers
# don't dominate the yield score and pull up high-crime/unstable ZIPs.
YIELD_CAP = 0.12

# ── Price Stability (ZHVI CoV) ────────────────────────────────────────────────
# Number of years of ZHVI monthly data to use for stability calculation.
# Coefficient of Variation (std/mean) over this period — lower = more stable.
# For a 3-year hold, you want stable appreciation, not lottery-ticket volatility.
ZHVI_STABILITY_YEARS = 5

# ── Census API ────────────────────────────────────────────────────────────────
CENSUS_YEAR = 2022
CENSUS_TABLES = {
    "owner_occ_count":  "B25003_002E",
    "total_housing":    "B25003_001E",
    "median_hh_income": "B19013_001E",
    "population":       "B01003_001E",
}
CENSUS_BASE_URL = "https://api.census.gov/data"

# ── Google Maps ───────────────────────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", None)

# ── San Antonio Open Data ─────────────────────────────────────────────────────
SA_CRIME_URL = (
    "https://data.sanantonio.gov/dataset/111a6b75-a125-410c-b483-8470e9bf9324"
    "/resource/9cb17985-ac16-49a6-ad69-6fe5ad8f2bf5/download/pubsafedash_cfs.csv"
)
# Schema (verified Feb 2026):
# Master_Incident_Number, Response_Date, Priority, Problem, Service_Area,
# Type, Seconds, Weekday, Disposition_Groups, Disposition_Type, Postal_Code