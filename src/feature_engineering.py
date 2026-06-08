"""
feature_engineering.py
-----------------------
Compute derived features and apply filters.

Path B principle: filters encode non-negotiables. Weights encode priorities.
If you're unwilling to compromise on something, it belongs here as a filter,
not in scoring.py as a weighted factor.
"""

import logging

import numpy as np
import pandas as pd

from config import (
    MAX_COMMUTE_MILES,
    MAX_COMMUTE_MINS,
    MAX_CRIME_PER_1K,
    TARGET_ROOMS_RENTED,
    THRESHOLDS,
    YIELD_CAP,
)

logger = logging.getLogger(__name__)


def compute_rent_to_price(df: pd.DataFrame) -> pd.DataFrame:
    """
    Room-hack gross yield: annualized room rental income ÷ home value.

    When est_room_rent is available (post-merge):
        rent_to_price = est_room_rent × TARGET_ROOMS_RENTED × 12 / median_home_value

    est_room_rent = ZORI / TARGET_BEDROOMS (3-bed SFR assumption, set in config).
    rooms_rented = TARGET_ROOMS_RENTED (2) — a model constant, not Census-derived.

    Using Census avg_renter_bedrooms (~2.3–2.8) as both the est_room_rent denominator
    and the rooms_rented multiplier caused them to partially cancel, collapsing yield
    to ZORI × (2/avg_bed) — a constant ~17% discount with cross-ZIP noise but no
    new signal. Fixed constants decouple yield from the Census bedroom distribution
    of renters (which is irrelevant for a 3-bed SFR purchase decision).

    Fallback (no est_room_rent): ZORI-based yield (median_rent × 12 / home_value).
    """
    df = df.copy()
    if "est_room_rent" in df.columns:
        room_hack_yield = (df["est_room_rent"] * TARGET_ROOMS_RENTED * 12) / df[
            "median_home_value"
        ]
        zori_yield = (df["median_rent"] * 12) / df["median_home_value"]
        # Use room-hack yield where data is present; ZORI fallback for sparse ZIPs
        has_room_data = df["est_room_rent"].notna()
        df["rent_to_price"] = room_hack_yield.where(has_room_data, other=zori_yield)
        n_room = has_room_data.sum()
        n_zori = (~has_room_data).sum()
        logger.info(
            f"rent_to_price: room-hack formula for {n_room} ZIPs, "
            f"ZORI fallback for {n_zori} ZIPs | "
            f"range: {df['rent_to_price'].min():.3f} – {df['rent_to_price'].max():.3f}"
        )
    else:
        df["rent_to_price"] = (df["median_rent"] * 12) / df["median_home_value"]
        logger.warning(
            "est_room_rent not found — rent_to_price using ZORI fallback. "
            "Re-run pipeline to generate est_room_rent from Census B25042 data."
        )
    return df


def apply_hard_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove ZIPs that fail non-negotiable thresholds BEFORE scoring.

    Each filter here represents something you are unwilling to trade away:
    - yield floor: if it doesn't cashflow, it doesn't qualify
    - home value ceiling: budget reality, not preference
    - owner-occ range: neighborhood character screen
    - income floor: tenant base quality — this is structural risk, not bias

    Crime is handled separately by flag_crime_risk() — it labels ZIPs LOW/ELEVATED/HIGH/DATA_SUSPECT
    rather than removing them, since SA CFS data quality is unreliable for hard cutoffs.
    """
    df = df.copy()
    initial = len(df)

    filters = {
        "min_rent_to_price": df["rent_to_price"] >= THRESHOLDS["min_rent_to_price"],
        "max_home_value": df["median_home_value"] <= THRESHOLDS["max_home_value"],
        "min_owner_occ": df["owner_occ_pct"] >= THRESHOLDS["min_owner_occ_pct"],
        "max_owner_occ": df["owner_occ_pct"] <= THRESHOLDS["max_owner_occ_pct"],
    }

    # Commute hard filter — 66-minute commute ZIPs should not appear in results at all.
    # Unlike most filters this has a tolerance: straight-line estimates undercount by ~30%
    # so the threshold is set loose (MAX_COMMUTE_MINS) and the score handles refinement.
    # If commute data is missing, the filter is skipped with a warning — not ideal, but better than dropping ZIPs with data gaps.
    if "commute_minutes" in df.columns:
        filters["max_commute_mins"] = df["commute_minutes"] <= MAX_COMMUTE_MINS
    elif "commute_miles" in df.columns:
        filters["max_commute_miles"] = df["commute_miles"] <= MAX_COMMUTE_MILES
    else:
        logger.warning(
            "No commute data found — commute filter skipped. "
            "Check that commute_minutes or commute_miles is in the dataset."
        )

    # Income filter — only apply if data is available (some ZIPs have Census gaps)
    if "median_hh_income" in df.columns:
        income_series = pd.to_numeric(df["median_hh_income"], errors="coerce")
        filters["min_median_income"] = (
            income_series >= THRESHOLDS["min_median_income"]
        ) | income_series.isna()  # don't drop ZIPs just because Census has a gap
    else:
        logger.warning("median_hh_income not in dataset — income filter skipped")

    # SFR inventory filter — ZIPs below the floor are dominated by apartments/condos
    # where sourcing a 3BR SFR at target price is structurally difficult.
    if "pct_sfr" in df.columns and "min_pct_sfr" in THRESHOLDS:
        sfr_series = pd.to_numeric(df["pct_sfr"], errors="coerce")
        filters["min_pct_sfr"] = (
            sfr_series >= THRESHOLDS["min_pct_sfr"]
        ) | sfr_series.isna()  # skip filter if Census data gap
    elif "min_pct_sfr" in THRESHOLDS:
        logger.warning("pct_sfr not in dataset — SFR inventory filter skipped")

    mask = pd.Series(True, index=df.index)
    for name, condition in filters.items():
        failed = (~condition).sum()
        if failed > 0:
            logger.info(f"Hard filter '{name}' removed {failed} ZIPs")
        mask &= condition

    result = df[mask].copy()
    logger.info(f"Hard filters: {initial} -> {len(result)} ZIPs remaining")
    return result


def flag_crime_risk(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a crime_flag column instead of removing ZIPs.

    CFS data quality varies across ZIPs (population denominator issues, non-SAPD
    jurisdictions, commercial corridors with few residents). Hard-removing ZIPs on
    relative crime rank throws away neighborhoods that may be perfectly livable.

    Instead: flag and let the 30% crime weight push high-crime ZIPs to the bottom.
    The user sees all candidates with explicit risk labels.

    Flags (based on crime_per_1k within the candidate pool):
      LOW          — bottom tercile (safest)
      ELEVATED     — middle tercile
      HIGH         — top tercile
      DATA_SUSPECT — above MAX_CRIME_PER_1K absolute ceiling (data quality concern)
      NO_DATA      — ZIP outside SAPD jurisdiction; no crime rate available
    """
    df = df.copy()
    crime = df["crime_per_1k"]

    crime_known = crime.dropna()
    t33 = crime_known.quantile(0.33)
    t67 = crime_known.quantile(0.67)

    def _flag(v) -> str:
        if pd.isna(v):
            return "NO_DATA"
        if v > MAX_CRIME_PER_1K:
            return "DATA_SUSPECT"
        if v <= t33:
            return "LOW"
        if v <= t67:
            return "ELEVATED"
        return "HIGH"

    df["crime_flag"] = crime.apply(_flag)

    counts = df["crime_flag"].value_counts().to_dict()
    logger.info(
        f"Crime flags: {counts} "
        f"(DATA_SUSPECT threshold: {MAX_CRIME_PER_1K}/1k, "
        f"LOW ≤ {t33:.0f}, ELEVATED ≤ {t67:.0f}, HIGH > {t67:.0f})"
    )
    return df


def apply_yield_cap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cap rent_to_price at YIELD_CAP before normalization.

    Path B treats abnormally high yield as a warning sign, not a bonus.
    In SA, gross yield > 12% almost always signals distress pricing or data issues,
    not a hidden gem. Capping prevents these ZIPs from scoring artificially high
    on the yield dimension and drowning out safety/stability signals.

    The raw rent_to_price value is preserved in the output for transparency.
    score_rent_to_price is computed from rent_to_price_capped.
    """
    df = df.copy()
    df["rent_to_price_capped"] = df["rent_to_price"].clip(upper=YIELD_CAP)
    n_capped = (df["rent_to_price"] > YIELD_CAP).sum()
    if n_capped > 0:
        logger.info(
            f"Yield cap ({YIELD_CAP:.0%}): {n_capped} ZIPs had yield capped "
            f"(raw range was {df['rent_to_price'].max():.3f})"
        )
    return df


def apply_log_crime_transform(df: pd.DataFrame) -> pd.DataFrame:
    """
    Log-transform crime_per_1k before normalization.

    Crime distributions are heavily right-skewed. Without transformation,
    extreme ZIPs stretch the scale so all other ZIPs look equally safe.

    log(1 + x) compresses the tail while preserving rank order:
      crime=1   -> log(2)   = 0.69
      crime=25  -> log(26)  = 3.26
      crime=100 -> log(101) = 4.62
      crime=500 -> log(501) = 6.22

    Raw value preserved in crime_per_1k. crime_log is what the scorer uses.
    """
    df = df.copy()
    df["crime_log"] = np.log1p(df["crime_per_1k"])
    logger.info(
        f"Crime log-transform: raw [{df['crime_per_1k'].min():.1f}, "
        f"{df['crime_per_1k'].max():.1f}] -> "
        f"log [{df['crime_log'].min():.2f}, {df['crime_log'].max():.2f}]"
    )
    return df


def normalize_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Min-max normalize each feature to [0, 1] for scoring.
    Higher normalized score = better in all cases (inverted where lower = better).

    Yield is scored from rent_to_price_capped (not raw) — run apply_yield_cap first.
    Crime is scored from crime_log — run apply_log_crime_transform first.
    Stability (zhvi_cov) is inverted — lower CoV = more stable = better score.

    NOTE: crime/owner-occ/commute/stability are relative to the surviving ZIP pool.
    Yield is anchored to config floor/cap (absolute) — stable across pipeline runs.
    """
    df = df.copy()

    required = ["crime_log", "rent_to_price_capped"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing columns: {missing}. "
            "Run apply_yield_cap() and apply_log_crime_transform() first."
        )

    def minmax(series: pd.Series, invert: bool = False) -> pd.Series:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.5, index=series.index)
        normalized = (series - mn) / (mx - mn)
        return 1 - normalized if invert else normalized

    # Yield is normalized against config floor/cap, not pool min/max.
    # Pool min-max causes ZIPs near the floor to score ~0 (floor ≈ pool min → near-zero
    # numerator). Anchoring to config constants gives the same score regardless of which
    # other ZIPs survive the filter, and preserves meaningful differentiation:
    #   floor (0.045) → 0.0   |   8% yield → 0.40   |   cap (0.12) → 1.0
    _yield_floor = THRESHOLDS["min_rent_to_price"]
    _yield_range = YIELD_CAP - _yield_floor
    df["score_rent_to_price"] = (
        (df["rent_to_price_capped"] - _yield_floor) / _yield_range
    ).clip(0, 1)
    # ZIPs outside SAPD jurisdiction have crime_log=NaN — assign neutral 0.5 so
    # they aren't penalized for missing data while still not scoring well on safety.
    df["score_crime"] = minmax(df["crime_log"], invert=True).fillna(0.5)
    df["score_owner_occupancy"] = minmax(df["owner_occ_pct"])
    df["score_commute"] = minmax(df["commute_minutes"], invert=True)

    # Stability score — only if ZHVI CoV data was merged in
    if "zhvi_cov" in df.columns:
        df["score_stability"] = minmax(df["zhvi_cov"], invert=True)
        logger.info("Stability score computed from ZHVI CoV")
    else:
        # Fallback: neutral stability score so scoring still works
        df["score_stability"] = 0.5
        logger.warning(
            "zhvi_cov not in dataset — stability score set to neutral (0.5). "
            "Check that compute_zhvi_stability() ran and merged correctly."
        )

    return df
