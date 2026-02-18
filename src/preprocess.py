"""
preprocess.py
-------------
Clean raw DataFrames and merge into a single ZIP-level master dataset.
No scoring logic here — just clean, typed, merged data.
"""

import logging
import pandas as pd
import numpy as np

from config import TARGET_METRO

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
    """
    df = df.copy()
    df["zip"] = df["zip"].astype(str).str.zfill(5)

    for col in ["owner_occ_count", "total_housing", "median_hh_income", "population"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["owner_occ_pct"] = df["owner_occ_count"] / df["total_housing"]
    df = df[df["total_housing"] > 0].dropna(subset=["owner_occ_pct"])

    # Filter out Census placeholder sentinel values (e.g. -666666666)
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

    Key design decision: filter by Problem type (criminal incidents only),
    NOT by Priority. Priority 1/2 includes medical emergencies, welfare checks,
    noise complaints — that's activity intensity, not crime severity.
    The VIOLENT_CRIME_PROBLEMS allowlist in config.py controls what counts.

    Pass census_df (output of process_census) for population normalization.
    Without it, raw counts are used and crime scoring is meaningless.
    """
    from config import VIOLENT_CRIME_PROBLEMS

    df = crime_df.copy()

    zip_col = next(
        (c for c in df.columns if c.lower() in ("postal_code", "zip", "zipcode", "zip_code")),
        None
    )
    if zip_col is None:
        raise ValueError(
            f"No ZIP column found in crime data. Got columns: {df.columns.tolist()}\n"
            "Expected 'Postal_Code' — check your SA Open Data CSV."
        )

    df["zip"] = df[zip_col].astype(str).str.strip().str.zfill(5)

    # Filter by Problem allowlist — criminal incidents only, no noise/medical/welfare
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
        logger.warning(
            "No 'Problem' column found — cannot filter by incident type. "
            "All calls counted. Inspect columns: crime_df.columns"
        )

    # Exclude JBSA ZIPs — not valid house-hack targets, distorts base population
    military_zips = {"78234", "78235", "78236", "78243"}
    df = df[~df["zip"].isin(military_zips)]

    crime_counts = df.groupby("zip").size().reset_index(name="crime_incidents")

    # Normalize by population — required for cross-ZIP comparisons to mean anything
    if census_df is not None and "population" in census_df.columns:
        pop = census_df[["zip", "population"]].copy()
        pop["population"] = pd.to_numeric(pop["population"], errors="coerce")
        crime_counts = crime_counts.merge(pop, on="zip", how="left")
        crime_counts = crime_counts[crime_counts["population"] > 0].copy()
        crime_counts["crime_per_1k"] = (
            crime_counts["crime_incidents"] / crime_counts["population"] * 1000
        )
        logger.info("Crime normalized per 1,000 residents using Census population data")
    else:
        logger.warning(
            "No population data — using raw crime counts. "
            "Pass census_df to process_crime() for proper normalization."
        )
        crime_counts["crime_per_1k"] = crime_counts["crime_incidents"]

    result = crime_counts[["zip", "crime_per_1k"]].dropna()
    logger.info(
        f"Crime: {len(result)} ZIPs | "
        f"range: {result['crime_per_1k'].min():.1f} - {result['crime_per_1k'].max():.1f} per 1k"
    )
    return result


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge_datasets(
    zhvi: pd.DataFrame,
    zori: pd.DataFrame,
    census: pd.DataFrame,
    crime: pd.DataFrame,
    commute: pd.DataFrame,
) -> pd.DataFrame:
    """
    Inner-join all processed DataFrames on ZIP.
    ZIPs missing from ANY source are dropped — logged explicitly.
    Population is dropped after merge (used only for crime normalization).
    """
    datasets = {
        "ZHVI":    zhvi,
        "ZORI":    zori,
        "Census":  census,
        "Crime":   crime,
        "Commute": commute,
    }

    base = zhvi.copy()
    for name, df in list(datasets.items())[1:]:
        before = len(base)
        base = base.merge(df, on="zip", how="inner")
        dropped = before - len(base)
        if dropped > 0:
            logger.warning(f"{name} merge dropped {dropped} ZIPs (no matching data)")

    # Drop population — only needed upstream for crime rate normalization
    if "population" in base.columns:
        base = base.drop(columns=["population"])

    logger.info(f"Merged dataset: {len(base)} ZIPs")
    return base