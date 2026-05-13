"""
config.py
---------
Single source of truth for ALL model parameters.
Change weights, thresholds, and paths HERE only — never hardcode elsewhere.

This model is tuned for Path B: military house hack, 3-year hold, BAMC duty station.
Path B logic: screen out unacceptable risk first, then optimize within safe candidates.
Some things are NOT tradeable — those are filters, not weights.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ── Project Paths ─────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_PROC = ROOT_DIR / "data" / "processed"
DATA_FINAL = ROOT_DIR / "data" / "final"
OUTPUTS = ROOT_DIR / "outputs"
CACHE_DIR = ROOT_DIR / ".cache"

# ── Cache TTLs ────────────────────────────────────────────────────────────────
CACHE_TTL = {
    "census_hours": 720,    # 30 days — ACS is annual data, no point re-fetching
    "crime_hours": 168,     # 7 days — SA Open Data portal updates frequently
    "commute_hours": 8760,  # 1 year — drive times to BAMC are effectively static
    "zillow_hours": 168,    # 7 days — Zillow publishes monthly updates
    "zhvf_hours": 168,      # 7 days — ZHVF forecast refreshes monthly
    "uszips_hours": 8760,   # 1 year — ZIP centroids never change
    "bcad_hours": 720,      # 30 days — BCAD assessed values update annually
}

# ── Duty Station ──────────────────────────────────────────────────────────────
DUTY_STATION = {
    "name": "BAMC - Fort Sam Houston",
    "lat": 29.4563,
    "lon": -98.4436,
}

# ── Geographic Scope ──────────────────────────────────────────────────────────
TARGET_STATE_FIPS = "48"
TARGET_METRO = "San Antonio"
MAX_COMMUTE_MILES = 25
MAX_COMMUTE_MINS = 35

# ── Target Property Assumptions (room-hack yield formula) ────────────────────
# These drive est_room_rent (preprocess.py) and rooms_rented (feature_engineering.py).
# Using fixed model constants rather than Census avg_renter_bedrooms because:
#   - avg_renter_bedrooms (2.3–2.8) reflects all rental units, not 3-bed SFRs
#   - Using it as both est_room_rent denominator and rooms_rented multiplier causes
#     them to partially cancel, reducing yield to ZORI × (2/avg_bed) with cross-ZIP noise
#   - A 3-bed SFR is the actual target; that's the right denominator for per-room rate
TARGET_BEDROOMS = 3  # bedrooms in target SFR (denominator for per-room rate)
TARGET_ROOMS_RENTED = 2  # rooms rented while occupying 1

# ZORI measures the median across all unit sizes (~70% are 1–2BR in SA).
# For a 3BR purchase, the relevant rent is the 3BR market rate, which commands
# a premium over the blended median. Calibration from 78239 (Feb 2026):
#   ZORI = $1,446  |  3BR market rent = $2,168  |  ratio = 1.50
# Room-for-rent listings in SA cluster at $650–$800/room.
# Without the multiplier: est_room_rent = $1,446 / 3 = $482  (too low)
# With 1.40×:             est_room_rent = $1,446 × 1.40 / 3 = $675  (in range)
# 1.40 is conservative (lower bound of observed room rents). Tune with real comps.
ZORI_3BR_PREMIUM = 1.40

# ── Scoring Weights (must sum to 1.0) ─────────────────────────────────────────
# These encode your priorities AS A MILITARY HOUSE HACKER, not a pure investor.
# Key shifts vs Path A investor logic:
#   - Crime weight increased (you live there — it is not negotiable)
#   - Yield weight decreased (viability matters more than maximization)
#   - Stability added (3-year hold = price volatility is real risk)
#   - Commute reduced slightly (still important, but safety/stability outrank it)
#
# SFR room-hack shift (2026 update):
#   - Owner-occupancy raised to 0.25 — when tenants share your home, neighborhood
#     character matters even more than in a standard duplex setup.
#   - Yield lowered to 0.20 — per-room yield signal; SFR data coverage is wider.
#
# Run: python sensitivity.py to verify rankings hold across weight perturbations.
WEIGHTS = {
    "rent_to_price": 0.20,  # per-room yield signal; viability, not maximization
    "crime": 0.30,  # non-negotiable — you live there
    "owner_occupancy": 0.25,  # raised: tenants share your home, neighbors matter more
    "commute": 0.15,  # important but not override-level
    "stability": 0.10,  # 3-year price stability (ZHVI CoV)
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# ── Hard Filters (non-negotiable disqualifiers) ───────────────────────────────
# Anything here is a SCREEN, not a scored dimension.
# Path B principle: if you won't compromise on it, make it a filter.
THRESHOLDS = {
    # Lowered from 0.045 to 0.035 to include multifamily house hack candidates.
    # SFH room hack at median ZORI/price yields ~6% (passes 4.5% easily).
    # Duplex house hack yields ~4.3% in Phase 1 (one rented unit, higher asset price)
    # and ~8.6% in Phase 2 (full rental) — a sound investment that 4.5% would reject.
    # 3.5% still screens out ZIPs with genuinely weak rental fundamentals.
    "min_rent_to_price": 0.035,
    # SA 2026 conforming VA loan limit — adjust if your COE differs
    "max_home_value": 450_000,
    # Lowered to 0.35 for multifamily house hack strategy (live in one unit, rent
    # others, then fully vacate after ~1 year). Rental-dense neighborhoods (35–50%
    # owner-occ) often have the strongest multifamily inventory and tenant demand —
    # exactly what you need for the property to self-fund after you PCS/move on.
    "min_owner_occ_pct": 0.35,
    # Above 85% = low rental demand; finding tenants will be hard.
    # Raised from 0.80: highly owner-occupied suburban ZIPs near BAMC were being
    # excluded even though they offer strong appreciation and low crime.
    "max_owner_occ_pct": 0.85,
    # Tenant base quality screen — low income correlates with:
    # higher delinquency risk, slower resale, weaker neighborhood trajectory
    # $42k = roughly E-5/E-6 BAH + base pay range in SA — your target tenant
    "min_median_income": 42_000,
}

# ── Crime Filtering ───────────────────────────────────────────────────────────
# Path B: crime is a hard screen, not a soft negotiable.
# 0.45 = keep only the safest 45% of ZIPs by crime rate, where "safe" means "lower crime than 45% of other ZIPs".
# You live in this property. This is not tradeable against yield.
CRIME_PERCENTILE_CUTOFF = 0.45

# Minimum population for a ZIP to get a crime per-1k rate.
# Without this floor, commercial corridors and fringe ZIPs with low Census-enumerated
# residents produce absurd rates (8,540/1k → 2,110/1k after 2k floor).
# 5,000 is the right floor: below this, a ZIP is either non-residential or so sparse
# that its crime rate has no predictive value for where you'll actually live.
MIN_POPULATION_FOR_CRIME = 5_000

# DATA_SUSPECT threshold for crime_flag (informational — does not remove ZIPs).
# ZIPs above this threshold get flagged as DATA_SUSPECT rather than LOW/ELEVATED/HIGH.
#
# SA CFS methodology context: SAPD data counts dispatch calls (not incidents) divided
# by residential population. Commercial corridors and mixed-use ZIPs inflate rates
# because their denominator (Census residential population) is far smaller than their
# actual daytime/activity footprint. The median SA ZIP is ~370/1k; the 90th percentile
# is ~750/1k. Values above 700 are likely artifacts of this denominator mismatch, not
# genuinely unlivable neighborhoods. Ground-truth: 78227 (~580/1k) is a normal
# residential neighborhood per direct observation.
MAX_CRIME_PER_1K = 700

# ZIPs excluded from crime normalization because they are NOT primarily served
# by SAPD. The SAPD Calls for Service dataset only contains San Antonio PD
# dispatches — ZIPs policed by other departments will show artificially low
# crime rates, which corrupts the percentile distribution and misleads the model.
#
# Known non-SAPD coverage ZIPs (verify before adding more):
#   78154 — Schertz/Selma area. Straddles the Bexar/Guadalupe county line.
#            Served by Schertz PD, Cibolo PD, and Guadalupe County SO — none
#            of which appear in SAPD data. Crime rate of 6.6/1k is a SAPD artifact,
#            not a true measure of public safety in this ZIP.
#
# These ZIPs are dropped from crime processing (same mechanism as military ZIPs).
# Without crime data they are dropped by the inner join in merge_datasets and
# do not appear in ranked output — which is the correct behavior since their
# crime signal is unreliable.
NON_SAPD_ZIPS = {
    "78154",  # Schertz/Selma — Schertz PD / Guadalupe County SO jurisdiction
}

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

# ── Home Value Appreciation (ZHVI CAGR) ───────────────────────────────────────
# Annualized CAGR windows computed from ZHVI history for display in the output.
# NOT used in scoring — pass-through context for equity-building decisions.
# CoV answers "how bumpy is the ride?"; CAGR answers "where do you end up?"
# Both matter for holds beyond 3 years.
ZHVI_CAGR_WINDOWS = [5, 10]  # years

# ── Investment Decision Scorecard Thresholds ──────────────────────────────────
# Used by the 8-condition investment scorecard in property_analyzer.py.
# Each condition produces GREEN / YELLOW / RED.
# Final verdict: any RED = SKIP; 3+ YELLOW = SKIP; 1–2 YELLOW = CAUTION; all clear = BUY.

# Condition 1 & 3 — Phase 2 monthly cashflow (current and stress-tested)
PHASE2_SURVIVAL_FLOOR = -150  # ≥ -$150/mo = GREEN: manageable from W-2 income
PHASE2_CAUTION_FLOOR = -300  # -$150 to -$300 = YELLOW; < -$300 = RED (pure speculation)

# Condition 2 — 3-yr exit neutrality
# Computed as: net_proceeds (0% appr) + cumulative Phase1 net_with_bah - down_payment
# Includes BAH because that's real cash you received while holding.
EXIT_NEUTRAL_YELLOW = -10_000  # -$10k floor for YELLOW; more negative = RED

# Condition 3 — Interest rate stress test parameters
STRESS_RATE_DELTA = 0.01  # +1% above your locked rate
STRESS_RENT_GROWTH = 0.02  # 2%/yr rent growth compounded over hold period

# Condition 4 — Purchase price relative to ZIP median home value
PRICE_PREMIUM_GREEN = 0.10  # ≤ 10% above median = GREEN
PRICE_PREMIUM_YELLOW = 0.20  # 10–20% above = YELLOW; > 20% = RED (bad risk asymmetry)

# Condition 5 — Phase 1 cash-on-cash yield (net_with_bah × 12 / asking_price)
# For VA 0%-down loans, denominator is asset value (no meaningful cash investment).
# For conventional loans with down payment, denominator is down_payment.
# Skipped (N/A) for VA 0%-down — Phase 2 survival and exit neutrality cover it.
COC_GREEN = 0.10  # ≥ 10% = GREEN
COC_YELLOW = 0.08  # 8–10% = YELLOW; < 8% = RED

# ZIP Quality — Crime tier thresholds (severity-weighted incidents per 1,000 residents)
# Tier A (GREEN):  < 50/1k — quiet suburban
# Tier B (YELLOW): 50–100/1k — moderate, acceptable for investment
# Tier C/D (RED):  > 100/1k — too high for a leveraged primary residence
CRIME_TIER_THRESHOLDS = {"A": 50, "B": 100}

# ZIP Quality — 5-yr ZHVI CAGR appreciation
CAGR_5YR_GREEN = 0.03  # ≥ 3%/yr = GREEN
CAGR_5YR_YELLOW = 0.01  # 1–3%/yr = YELLOW; < 1% = RED

# ── Census API ────────────────────────────────────────────────────────────────
# Free key: https://api.census.gov/data/key_signup.html  (instant email delivery)
# Without a key, anonymous requests are capped at 500/day per IP.
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY", None)
CENSUS_YEAR = 2022
CENSUS_TABLES = {
    "owner_occ_count": "B25003_002E",
    "total_housing": "B25003_001E",
    "median_hh_income": "B19013_001E",
    "population": "B01003_001E",
    # B25042: Tenure by bedrooms — renter-occupied units by bedroom count.
    # Used to compute avg_renter_bedrooms per ZIP, which is the correct denominator
    # for est_room_rent = ZORI / avg_renter_bedrooms.
    # B25018 (median rooms) was incorrect: total rooms (~5.5) ≠ bedrooms (~2.5).
    "renter_total": "B25042_001E",  # total renter-occupied units
    "renter_0bed": "B25042_002E",  # no bedroom (studio)
    "renter_1bed": "B25042_003E",
    "renter_2bed": "B25042_004E",
    "renter_3bed": "B25042_005E",
    "renter_4bed": "B25042_006E",
    "renter_5bed": "B25042_007E",  # 5+ bedrooms
    # B25024: Units in structure — housing stock composition by building type.
    # Used to compute pct_sfr, pct_duplex, pct_small_mf per ZIP.
    # Tells you where duplexes / small MF properties actually exist —
    # critical for comparing room-hack (SFR) vs unit-hack (duplex/triplex) viability.
    "units_total":  "B25024_001E",  # all housing units
    "units_1det":   "B25024_002E",  # 1-unit, detached (SFR)
    "units_1att":   "B25024_003E",  # 1-unit, attached (townhouse/rowhouse)
    "units_2":      "B25024_004E",  # 2-unit buildings (duplex)
    "units_3_4":    "B25024_005E",  # 3–4 unit buildings
    "units_5_9":    "B25024_006E",  # 5–9 unit buildings
    "units_10_19":  "B25024_007E",  # 10–19 unit buildings
    "units_20_49":  "B25024_008E",  # 20–49 unit buildings
    "units_50plus": "B25024_009E",  # 50+ unit buildings (large apartment complex)
}
CENSUS_BASE_URL = "https://api.census.gov/data"

# ── Google Maps ───────────────────────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", None)

# ── Bexar CAD (BCAD) ─────────────────────────────────────────────────────────
# ArcGIS REST service — Bexar County GIS, no auth required.
# Supports statistics queries (GROUP BY ZIP + State_cd) in a single request.
# State_cd reference: A1=SFR, B1=Small MF (duplex/triplex/quad), B2=Large MF.
BCAD_ARCGIS_URL = (
    "https://maps.bexar.org/arcgis/rest/services/Parcels/MapServer/0/query"
)

# ── San Antonio Open Data ─────────────────────────────────────────────────────
SA_CRIME_URL = (
    "https://data.sanantonio.gov/dataset/111a6b75-a125-410c-b483-8470e9bf9324"
    "/resource/9cb17985-ac16-49a6-ad69-6fe5ad8f2bf5/download/pubsafedash_cfs.csv"
)
# Schema (verified Feb 2026):
# Master_Incident_Number, Response_Date, Priority, Problem, Service_Area,
# Type, Seconds, Weekday, Disposition_Groups, Disposition_Type, Postal_Code
