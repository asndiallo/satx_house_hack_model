"""
preprocess.py
-------------
Clean raw DataFrames and merge into a single ZIP-level master dataset.
No scoring logic here — just clean, typed, merged data.
"""

import logging
import pandas as pd
import numpy as np

from config import TARGET_METRO, ZHVI_STABILITY_YEARS, VIOLENT_CRIME_PROBLEMS, MIN_POPULATION_FOR_CRIME

logger = logging.getLogger(__name__)


# ── Zillow ────────────────────────────────────────────────────────────────────

def process_zhvi(df: pd.DataFrame) -> pd.DataFrame:
    """Extract most recent home value per ZIP, filtered to San Antonio metro."""
    df = df.copy()
    df = df[df["Metro"].str.contains(TARGET_METRO, na=False)]
    df["zip"] = df["RegionName"].astype(str).str.zfill(5)
    date_cols = [c for c in df.columns if c[:4].isdigit()]
    df["median_home_value"] = pd.to_numeric(df[date_cols[-1]], errors="coerce")
    result = df[["zip", "median_home_value"]].dropna()
    logger.info(f"ZHVI: {len(result)} ZIPs after processing")
    return result


def compute_zhvi_stability(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute price stability from ZHVI monthly time series.

    Uses Coefficient of Variation (std / mean) over the last N years of monthly
    home values. Lower CoV = more stable price history = better for a 3-year hold.

    Why CoV instead of raw std dev:
    A $300k ZIP with std=$30k (CoV=0.10) is more stable than a $150k ZIP
    with std=$20k (CoV=0.13), even though the raw deviation is larger.
    CoV normalizes for price level, making ZIPs comparable.

    This replaces the "buy in a lottery-ticket ZIP and hope" approach.
    For military house hacking, boring and stable beats exciting and volatile.
    """
    df = df.copy()
    df = df[df["Metro"].str.contains(TARGET_METRO, na=False)]
    df["zip"] = df["RegionName"].astype(str).str.zfill(5)

    # Get all monthly date columns, sorted chronologically
    date_cols = sorted([c for c in df.columns if c[:4].isdigit()])
    n_months = ZHVI_STABILITY_YEARS * 12

    if len(date_cols) < n_months:
        logger.warning(
            f"Only {len(date_cols)} months of ZHVI data available — "
            f"using all available instead of {n_months} ({ZHVI_STABILITY_YEARS} years)"
        )
        analysis_cols = date_cols
    else:
        analysis_cols = date_cols[-n_months:]

    # Convert to numeric
    price_data = df[analysis_cols].apply(pd.to_numeric, errors="coerce")

    # CoV per ZIP — ignore ZIPs with too many missing months (>20%)
    valid_threshold = len(analysis_cols) * 0.80
    row_valid = price_data.notna().sum(axis=1) >= valid_threshold

    cov = price_data.std(axis=1) / price_data.mean(axis=1)
    cov[~row_valid] = np.nan

    result = pd.DataFrame({
        "zip": df["zip"].values,
        "zhvi_cov": cov.values,
    }).dropna()

    result = result[result["zhvi_cov"] > 0]  # drop any zero-variance edge cases

    logger.info(
        f"ZHVI stability: {len(result)} ZIPs | "
        f"CoV range: {result['zhvi_cov'].min():.4f} – {result['zhvi_cov'].max():.4f} "
        f"(lower = more stable)"
    )
    return result


def process_zori(df: pd.DataFrame) -> pd.DataFrame:
    """Extract most recent rent estimate per ZIP, filtered to San Antonio metro."""
    df = df.copy()
    df = df[df["Metro"].str.contains(TARGET_METRO, na=False)]
    df["zip"] = df["RegionName"].astype(str).str.zfill(5)
    date_cols = [c for c in df.columns if c[:4].isdigit()]
    df["median_rent"] = pd.to_numeric(df[date_cols[-1]], errors="coerce")
    result = df[["zip", "median_rent"]].dropna()
    logger.info(f"ZORI: {len(result)} ZIPs after processing")
    return result


# ── Census ────────────────────────────────────────────────────────────────────

def process_census(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate owner-occupancy rate and clean income/population data.
    Population is passed through for crime rate normalization downstream.
    median_hh_income is passed through for the income hard filter.
    """
    df = df.copy()
    df["zip"] = df["zip"].astype(str).str.zfill(5)

    for col in ["owner_occ_count", "total_housing", "median_hh_income", "population"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["owner_occ_pct"] = df["owner_occ_count"] / df["total_housing"]
    df = df[df["total_housing"] > 0].dropna(subset=["owner_occ_pct"])

    # Filter Census income sentinel values (e.g. -666666666)
    if "median_hh_income" in df.columns:
        df.loc[df["median_hh_income"] < 0, "median_hh_income"] = None

    keep = ["zip", "owner_occ_pct", "median_hh_income"]
    if "population" in df.columns:
        keep.append("population")

    result = df[keep]
    logger.info(f"Census: {len(result)} ZIPs after processing")
    return result


# ── Crime ─────────────────────────────────────────────────────────────────────

def process_crime(crime_df: pd.DataFrame, census_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Aggregate SAPD CFS incidents to ZIP level, normalized per 1,000 residents.

    Filter strategy: Problem-type allowlist (criminal incidents only).
    NOT Priority — Priority 1/2 includes medical calls, welfare checks, noise.
    Activity intensity != crime severity.

    Pass census_df for population normalization. Without it, cross-ZIP
    comparison is meaningless and thresholds break.
    """
    df = crime_df.copy()

    zip_col = next(
        (c for c in df.columns if c.lower() in ("postal_code", "zip", "zipcode", "zip_code")),
        None
    )
    if zip_col is None:
        raise ValueError(
            f"No ZIP column found in crime data. Got: {df.columns.tolist()}\n"
            "Expected 'Postal_Code' — check SA Open Data CSV schema."
        )

    df["zip"] = df[zip_col].astype(str).str.strip().str.zfill(5)

    if "Problem" in df.columns:
        before = len(df)
        df["_problem_upper"] = df["Problem"].astype(str).str.upper().str.strip()
        df = df[df["_problem_upper"].isin({p.upper() for p in VIOLENT_CRIME_PROBLEMS})]
        df = df.drop(columns=["_problem_upper"])
        logger.info(
            f"Crime Problem filter: {before:,} total CFS -> {len(df):,} criminal incidents "
            f"({len(df) / before * 100:.1f}% of all calls)"
        )
    else:
        logger.warning("No 'Problem' column — cannot filter by type. All calls counted.")

    # Exclude JBSA ZIPs — military base population distorts crime normalization
    military_zips = {"78234", "78235", "78236", "78243"}
    df = df[~df["zip"].isin(military_zips)]

    crime_counts = df.groupby("zip").size().reset_index(name="crime_incidents")

    if census_df is not None and "population" in census_df.columns:
        pop = census_df[["zip", "population"]].copy()
        pop["population"] = pd.to_numeric(pop["population"], errors="coerce")
        crime_counts = crime_counts.merge(pop, on="zip", how="left")
        crime_counts = crime_counts[crime_counts["population"] > 0].copy()

        # Drop ZIPs with population too small to produce a valid per-1k rate.
        # Commercial corridors and fringe areas have near-zero Census residents
        # but large incident counts — producing rates like 8,540/1k which corrupt
        # the crime distribution and make the percentile floor meaningless.
        thin = crime_counts["population"] < MIN_POPULATION_FOR_CRIME
        if thin.sum() > 0:
            logger.warning(
                f"Dropping {thin.sum()} ZIP(s) with population < {MIN_POPULATION_FOR_CRIME:,} "
                f"(unreliable per-1k rate). ZIPs: {sorted(crime_counts.loc[thin, 'zip'].tolist())}"
            )
            crime_counts = crime_counts[~thin].copy()

        crime_counts["crime_per_1k"] = (
            crime_counts["crime_incidents"] / crime_counts["population"] * 1000
        )
        logger.info("Crime normalized per 1,000 residents using Census population")
    else:
        logger.warning(
            "No population data — raw crime counts used. "
            "Pass census_df to process_crime() for proper normalization."
        )
        crime_counts["crime_per_1k"] = crime_counts["crime_incidents"]

    result = crime_counts[["zip", "crime_per_1k"]].dropna()
    logger.info(
        f"Crime: {len(result)} ZIPs | "
        f"range: {result['crime_per_1k'].min():.1f} – {result['crime_per_1k'].max():.1f} per 1k"
    )
    return result


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge_datasets(
    zhvi: pd.DataFrame,
    zori: pd.DataFrame,
    census: pd.DataFrame,
    crime: pd.DataFrame,
    commute: pd.DataFrame,
    stability: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Inner-join all processed DataFrames on ZIP.
    ZIPs missing from any required source are dropped with explicit logging.

    stability is optional — if not provided, stability scoring is skipped.
    Population is dropped after merge (only needed for crime normalization).
    """
    datasets = {
        "ZHVI":    zhvi,
        "ZORI":    zori,
        "Census":  census,
        "Crime":   crime,
        "Commute": commute,
    }
    if stability is not None:
        datasets["Stability"] = stability

    base = zhvi.copy()
    for name, df in list(datasets.items())[1:]:
        before = len(base)
        base = base.merge(df, on="zip", how="inner")
        dropped = before - len(base)
        if dropped > 0:
            logger.warning(f"{name} merge dropped {dropped} ZIPs (no matching data)")

    # Population was only needed for crime normalization — drop from final dataset
    if "population" in base.columns:
        base = base.drop(columns=["population"])

    logger.info(f"Merged dataset: {len(base)} ZIPs")
    return base