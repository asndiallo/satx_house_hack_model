"""
preprocess.py
-------------
Clean raw DataFrames and merge into a single ZIP-level master dataset.
No scoring logic here — just clean, typed, merged data.
"""

import logging

import numpy as np
import pandas as pd

from config import (
    MIN_POPULATION_FOR_CRIME,
    NON_SAPD_ZIPS,
    TARGET_BEDROOMS,
    TARGET_METRO,
    VIOLENT_CRIME_PROBLEMS,
    ZHVI_CAGR_WINDOWS,
    ZHVI_STABILITY_YEARS,
    ZORI_3BR_PREMIUM,
)

logger = logging.getLogger(__name__)


# ── Zillow ────────────────────────────────────────────────────────────────────


def process_zhvi(df: pd.DataFrame) -> pd.DataFrame:
    """Extract most recent home value per ZIP, filtered to San Antonio metro."""
    df = df.copy()
    df = df[df["Metro"].str.contains(TARGET_METRO, na=False)]
    df["zip"] = df["RegionName"].astype(str).str.zfill(5)
    date_cols = [c for c in df.columns if c[:4].isdigit()]
    df["median_home_value"] = pd.to_numeric(df[date_cols[-1]], errors="coerce")
    result = df[["zip", "median_home_value"]].dropna(subset=["median_home_value"])
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

    result = pd.DataFrame(
        {
            "zip": df["zip"].values,
            "zhvi_cov": cov.values,
        }
    ).dropna()

    result = result[result["zhvi_cov"] > 0]  # drop any zero-variance edge cases

    logger.info(
        f"ZHVI stability: {len(result)} ZIPs | "
        f"CoV range: {result['zhvi_cov'].min():.4f} – {result['zhvi_cov'].max():.4f} "
        f"(lower = more stable)"
    )
    return result


def compute_zhvi_cagr(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute annualized home value growth rates (CAGR) from ZHVI history.

    Complements zhvi_cov (stability) with directional signal:
    - CoV answers "how volatile is the price path?"
    - CAGR answers "where is the price actually going long-term?"

    Both matter for equity-building over multi-year holds. CAGR is a
    display-only column — it does not feed into scoring weights.
    Windows are defined in config.ZHVI_CAGR_WINDOWS.
    """
    df = df.copy()
    df = df[df["Metro"].str.contains(TARGET_METRO, na=False)]
    df["zip"] = df["RegionName"].astype(str).str.zfill(5)

    date_cols = sorted([c for c in df.columns if c[:4].isdigit()])
    result = df[["zip"]].copy().reset_index(drop=True)

    cagr_cols = []
    for years in ZHVI_CAGR_WINDOWS:
        col_name = f"zhvi_cagr_{years}yr"
        n_months = years * 12
        if len(date_cols) < n_months + 1:
            logger.warning(
                f"Insufficient ZHVI history for {years}yr CAGR "
                f"({len(date_cols)} months available, need {n_months + 1}) — skipping"
            )
            continue
        start_vals = pd.to_numeric(df[date_cols[-(n_months + 1)]], errors="coerce")
        end_vals = pd.to_numeric(df[date_cols[-1]], errors="coerce")
        result[col_name] = (end_vals.values / start_vals.values) ** (1 / years) - 1
        cagr_cols.append(col_name)

    result = result.dropna(subset=cagr_cols, how="all") if cagr_cols else result

    if cagr_cols:
        logger.info(
            f"ZHVI CAGR: {len(result)} ZIPs | "
            + " | ".join(
                f"{c}: {result[c].min():.2%} – {result[c].max():.2%}"
                for c in cagr_cols
                if c in result.columns
            )
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

    avg_renter_bedrooms: weighted average bedrooms per renter-occupied unit,
    computed from B25042 bedroom distribution. Used to derive est_room_rent
    in merge_datasets(). Typical SA range: 2.2–2.8 bedrooms/unit.
    """
    df = df.copy()
    df["zip"] = df["zip"].astype(str).str.zfill(5)

    for col in [
        "owner_occ_count",
        "total_housing",
        "median_hh_income",
        "population",
        "renter_total",
        "renter_0bed",
        "renter_1bed",
        "renter_2bed",
        "renter_3bed",
        "renter_4bed",
        "renter_5bed",
        "units_total",
        "units_1det",
        "units_1att",
        "units_2",
        "units_3_4",
        "units_5_9",
        "units_10_19",
        "units_20_49",
        "units_50plus",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["owner_occ_pct"] = df["owner_occ_count"] / df["total_housing"]
    df = df[df["total_housing"] > 0].dropna(subset=["owner_occ_pct"])

    # Filter Census income sentinel values (e.g. -666666666)
    if "median_hh_income" in df.columns:
        df.loc[df["median_hh_income"] < 0, "median_hh_income"] = None

    # Compute avg_renter_bedrooms from B25042 bedroom distribution.
    # Studios (0-bed) count as 0; 5+ bed capped at 5 (conservative for SA).
    renter_cols = [
        "renter_0bed",
        "renter_1bed",
        "renter_2bed",
        "renter_3bed",
        "renter_4bed",
        "renter_5bed",
    ]
    if all(c in df.columns for c in renter_cols + ["renter_total"]):
        weighted_sum = (
            df["renter_0bed"] * 0
            + df["renter_1bed"] * 1
            + df["renter_2bed"] * 2
            + df["renter_3bed"] * 3
            + df["renter_4bed"] * 4
            + df["renter_5bed"] * 5
        )
        valid = df["renter_total"] > 0
        df["avg_renter_bedrooms"] = np.nan
        df.loc[valid, "avg_renter_bedrooms"] = (
            weighted_sum[valid] / df.loc[valid, "renter_total"]
        )
        # Clip to [1.0, 5.0] — guard against Census data anomalies
        df["avg_renter_bedrooms"] = df["avg_renter_bedrooms"].clip(lower=1.0, upper=5.0)
        n_valid = df["avg_renter_bedrooms"].notna().sum()
        logger.info(
            f"avg_renter_bedrooms computed for {n_valid} ZIPs | "
            f"range: {df['avg_renter_bedrooms'].min():.2f} – "
            f"{df['avg_renter_bedrooms'].max():.2f}"
        )

    # Compute housing type percentages from B25024 (Units in Structure).
    # pct_sfr      = SFR (detached + attached) share — room-hack candidate density
    # pct_duplex   = 2-unit share — most common unit-hack target
    # pct_small_mf = 2–4 unit share — all small MF house-hack targets combined
    b25024_required = ["units_total", "units_1det", "units_1att", "units_2", "units_3_4"]
    if all(c in df.columns for c in b25024_required):
        valid = df["units_total"] > 0
        df["pct_sfr"] = np.nan
        df["pct_duplex"] = np.nan
        df["pct_small_mf"] = np.nan
        df.loc[valid, "pct_sfr"] = (
            (df.loc[valid, "units_1det"] + df.loc[valid, "units_1att"])
            / df.loc[valid, "units_total"]
        )
        df.loc[valid, "pct_duplex"] = (
            df.loc[valid, "units_2"] / df.loc[valid, "units_total"]
        )
        df.loc[valid, "pct_small_mf"] = (
            (df.loc[valid, "units_2"] + df.loc[valid, "units_3_4"])
            / df.loc[valid, "units_total"]
        )
        n = valid.sum()
        logger.info(
            f"Housing mix (B25024): {n} ZIPs | "
            f"sfr median: {df['pct_sfr'].median():.1%} | "
            f"duplex median: {df['pct_duplex'].median():.1%} | "
            f"small-MF median: {df['pct_small_mf'].median():.1%}"
        )

    keep = ["zip", "owner_occ_pct", "median_hh_income"]
    if "population" in df.columns:
        keep.append("population")
    if "avg_renter_bedrooms" in df.columns:
        keep.append("avg_renter_bedrooms")
    for col in ["pct_sfr", "pct_duplex", "pct_small_mf"]:
        if col in df.columns:
            keep.append(col)

    result = df[keep]
    logger.info(f"Census: {len(result)} ZIPs after processing")
    return result


# ── Crime ─────────────────────────────────────────────────────────────────────


def process_crime(
    crime_df: pd.DataFrame, census_df: pd.DataFrame = None
) -> pd.DataFrame:
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
        (
            c
            for c in df.columns
            if c.lower() in ("postal_code", "zip", "zipcode", "zip_code")
        ),
        None,
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
        logger.warning(
            "No 'Problem' column — cannot filter by type. All calls counted."
        )

    # Exclude JBSA ZIPs — military base population distorts crime normalization
    military_zips = {"78234", "78235", "78236", "78243"}
    df = df[~df["zip"].isin(military_zips)]

    # Exclude ZIPs policed by non-SAPD agencies (Schertz PD, county SO, etc.)
    # Their SAPD call counts are near-zero by definition, producing artificially
    # safe crime rates that corrupt the percentile distribution.
    # See NON_SAPD_ZIPS in config.py for rationale and verification notes.
    if NON_SAPD_ZIPS:
        before_non_sapd = len(df)
        df = df[~df["zip"].isin(NON_SAPD_ZIPS)]
        removed = before_non_sapd - len(df)
        if removed > 0:
            logger.info(
                f"Excluded {removed} non-SAPD ZIP(s) from crime data: {sorted(NON_SAPD_ZIPS)}"
            )

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


# ── BCAD ─────────────────────────────────────────────────────────────────────


def process_bcad(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot BCAD parcel stats (one row per ZIP × State_cd) into ZIP-level columns.

    Texas property type codes used here:
      A1 = Single Family Residential — room-hack target
      B1 = Multifamily Residential (duplexes, triplexes, fourplexes, small apts) — unit-hack target
      B2 = Large Multifamily (5+ unit complexes) — not a house-hack target

    Output columns per ZIP:
      bcad_sfr_count      — A1 parcel count
      bcad_sfr_assessed   — A1 average assessed value (land + structure)
      bcad_mf_count       — B1 parcel count (small MF, primary unit-hack candidates)
      bcad_mf_assessed    — B1 average assessed value
      bcad_large_mf_count — B2 parcel count (apartment complexes, for context)
    """
    df = df.copy()
    df["State_cd"] = df["State_cd"].astype(str).str.strip().str.upper()

    def _agg(state_code: str, count_col: str, val_col: str) -> pd.DataFrame:
        sub = df[df["State_cd"] == state_code].copy()
        if sub.empty:
            return pd.DataFrame(columns=["zip", count_col, val_col])
        sub["avg_tot_val"] = pd.to_numeric(sub["avg_tot_val"], errors="coerce")
        counts = sub[["zip", "prop_count"]].rename(columns={"prop_count": count_col})
        vals   = sub[["zip", "avg_tot_val"]].rename(columns={"avg_tot_val": val_col})
        return counts.merge(vals, on="zip", how="left")

    sfr   = _agg("A1", "bcad_sfr_count",      "bcad_sfr_assessed")
    mf    = _agg("B1", "bcad_mf_count",        "bcad_mf_assessed")
    large = df[df["State_cd"] == "B2"][["zip", "prop_count"]].rename(
        columns={"prop_count": "bcad_large_mf_count"}
    )

    result = sfr.merge(mf, on="zip", how="outer").merge(large, on="zip", how="outer")

    for col in ["bcad_sfr_count", "bcad_mf_count", "bcad_large_mf_count"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0).astype(int)

    logger.info(
        f"BCAD processed: {len(result)} ZIPs | "
        f"total SFR parcels: {result['bcad_sfr_count'].sum():,.0f} | "
        f"total small-MF parcels: {result['bcad_mf_count'].sum():,.0f}"
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
    cagr: pd.DataFrame = None,
    bcad: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Inner-join all processed DataFrames on ZIP.
    ZIPs missing from any required source are dropped with explicit logging.

    stability is optional — if not provided, stability scoring is skipped.
    cagr is optional — left-joined so ZIPs with insufficient ZHVI history
    are not dropped; they simply get NaN CAGR columns.
    Population is dropped after merge (only needed for crime normalization).
    """
    datasets = {
        "ZHVI": zhvi,
        "ZORI": zori,
        "Census": census,
        "Crime": crime,
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

    # CAGR is display-only — left join so no ZIPs are dropped for missing history
    if cagr is not None:
        base = base.merge(cagr, on="zip", how="left")
        cagr_cols = [c for c in cagr.columns if c != "zip"]
        n_filled = base[cagr_cols[0]].notna().sum() if cagr_cols else 0
        logger.info(
            f"CAGR merged (left join): {n_filled}/{len(base)} ZIPs have CAGR data"
        )

    # BCAD is display-only — left join so pipeline runs even without parcel data
    if bcad is not None:
        base = base.merge(bcad, on="zip", how="left")
        n_filled = base["bcad_sfr_count"].notna().sum() if "bcad_sfr_count" in base.columns else 0
        logger.info(f"BCAD merged (left join): {n_filled}/{len(base)} ZIPs have parcel data")

    # Population was only needed for crime normalization — drop from final dataset
    if "population" in base.columns:
        base = base.drop(columns=["population"])

    # Per-room rent estimate: (ZORI × ZORI_3BR_PREMIUM) ÷ TARGET_BEDROOMS.
    # ZORI is the median across all unit sizes — mostly 1–2BR in SA. A 3BR room hack
    # operates in the 3BR market, which commands a premium over the blended median.
    # Calibration (78239, Feb 2026): ZORI=$1,446, 3BR market=$2,168, ratio=1.50.
    # ZORI_3BR_PREMIUM=1.40 (conservative) → est_room_rent ≈ $675, matching
    # observed SA room-for-rent listings ($650–$800). Tune in config as comps change.
    # Use --rent-override with actual listings for specific property analysis.
    if "median_rent" in base.columns:
        valid = base["median_rent"].notna() & base["median_rent"].gt(0)
        base["est_room_rent"] = None
        base.loc[valid, "est_room_rent"] = (
            base.loc[valid, "median_rent"] * ZORI_3BR_PREMIUM / TARGET_BEDROOMS
        )
        n_filled = base["est_room_rent"].notna().sum()
        if n_filled > 0:
            rr = base.loc[base["est_room_rent"].notna(), "est_room_rent"]
            logger.info(
                f"est_room_rent computed for {n_filled}/{len(base)} ZIPs | "
                f"range: ${rr.min():.0f} – ${rr.max():.0f} | median: ${rr.median():.0f}"
            )
    else:
        logger.warning("Cannot compute est_room_rent — median_rent missing")

    logger.info(f"Merged dataset: {len(base)} ZIPs")
    return base
