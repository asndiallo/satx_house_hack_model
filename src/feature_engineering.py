"""
feature_engineering.py
-----------------------
Compute derived features and apply filters.

Path B principle: filters encode non-negotiables. Weights encode priorities.
If you're unwilling to compromise on something, it belongs here as a filter,
not in scoring.py as a weighted factor.
"""

import logging
import pandas as pd
import numpy as np

from config import (
    THRESHOLDS,
    CRIME_PERCENTILE_CUTOFF,
    YIELD_CAP,
    MAX_COMMUTE_MINS,
    MAX_COMMUTE_MILES,
)

logger = logging.getLogger(__name__)


def compute_rent_to_price(df: pd.DataFrame) -> pd.DataFrame:
    """Gross rent yield — annualized rent divided by home value."""
    df = df.copy()
    df["rent_to_price"] = (df["median_rent"] * 12) / df["median_home_value"]
    return df


def apply_hard_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove ZIPs that fail non-negotiable thresholds BEFORE scoring.

    Each filter here represents something you are unwilling to trade away:
    - yield floor: if it doesn't cashflow, it doesn't qualify
    - home value ceiling: budget reality, not preference
    - owner-occ range: neighborhood character screen
    - income floor: tenant base quality — this is structural risk, not bias

    Crime is handled separately by apply_crime_floor() — it uses a percentile
    cutoff so it adapts to the actual distribution rather than an absolute number.
    """
    df = df.copy()
    initial = len(df)
    rent_to_price = pd.to_numeric(df["rent_to_price"], errors="coerce")
    home_value = pd.to_numeric(df["median_home_value"], errors="coerce")
    owner_occ = pd.to_numeric(df["owner_occ_pct"], errors="coerce")

    filters = {
        "min_rent_to_price": rent_to_price >= THRESHOLDS["min_rent_to_price"],
        "max_home_value": home_value <= THRESHOLDS["max_home_value"],
        "min_owner_occ": owner_occ >= THRESHOLDS["min_owner_occ_pct"],
        "max_owner_occ": owner_occ <= THRESHOLDS["max_owner_occ_pct"],
    }

    # Income filter — only apply if data is available (some ZIPs have Census gaps)
    if "median_hh_income" in df.columns:
        income_series = pd.to_numeric(df["median_hh_income"], errors="coerce")
        filters["min_median_income"] = (
            income_series >= THRESHOLDS["min_median_income"]
        ) | income_series.isna()  # don't drop ZIPs just because Census has a gap
    else:
        logger.warning("median_hh_income not in dataset — income filter skipped")

    # Commute filter — use minutes when available, otherwise miles fallback.
    if "commute_minutes" in df.columns:
        commute_minutes = pd.to_numeric(df["commute_minutes"], errors="coerce")
        filters["max_commute_mins"] = commute_minutes <= MAX_COMMUTE_MINS
    elif "commute_miles" in df.columns:
        commute_miles = pd.to_numeric(df["commute_miles"], errors="coerce")
        filters["max_commute_miles"] = commute_miles <= MAX_COMMUTE_MILES
    else:
        logger.warning("No commute column found — commute hard filter skipped")

    mask = pd.Series(True, index=df.index)
    for name, condition in filters.items():
        failed = (~condition).sum()
        if failed > 0:
            logger.info(f"Hard filter '{name}' removed {failed} ZIPs")
        mask &= condition

    result = df[mask].copy()
    logger.info(f"Hard filters: {initial} -> {len(result)} ZIPs remaining")
    return result


def apply_crime_floor(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove ZIPs in the upper half of the crime distribution.

    Path B treats safety as a non-negotiable screen, not a scored tradeoff.
    You live in this property — crime is not negotiable against yield.

    Uses a percentile cutoff (not an absolute number) because:
    - CFS data quality varies — an absolute threshold depends on data accuracy
    - Relative ranking within SA is what matters for your decision
    - 0.50 = keep only the safer half of candidate ZIPs

    The cutoff is set in config.py as CRIME_PERCENTILE_CUTOFF.
    """
    df = df.copy()
    threshold = df["crime_per_1k"].quantile(CRIME_PERCENTILE_CUTOFF)
    before = len(df)
    df = df[df["crime_per_1k"] <= threshold].copy()
    removed = before - len(df)
    logger.info(
        f"Crime floor ({CRIME_PERCENTILE_CUTOFF:.0%} percentile): "
        f"threshold={threshold:.1f}/1k — removed {removed} ZIPs, {len(df)} remaining"
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

    NOTE: all scores are relative to your current ZIP pool, not absolute.
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

    df["score_rent_to_price"]   = minmax(df["rent_to_price_capped"])
    df["score_crime"]           = minmax(df["crime_log"],       invert=True)
    df["score_owner_occupancy"] = minmax(df["owner_occ_pct"])
    df["score_commute"]         = minmax(df["commute_minutes"], invert=True)

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
