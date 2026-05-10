"""
main.py
-------
Full pipeline orchestrator.

Path B: military house hack, 3-year hold, BAMC duty station.
Logic: screen out unacceptable risk first, then optimize within safe candidates.

Usage:
    python main.py --no-google-maps
    python main.py --no-google-maps --diagnose
    python main.py --top 20
"""

import sys
import argparse
import logging
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils import setup_logging, save_csv, load_zip_centroids
from data_loader import load_zhvi, load_zori, load_census_acs, load_crime_data
from preprocess import (
    process_zhvi, compute_zhvi_stability, compute_zhvi_cagr,
    process_zori, process_census, process_crime, merge_datasets
)
from feature_engineering import (
    compute_rent_to_price,
    apply_hard_filters,
    flag_crime_risk,
    apply_yield_cap,
    apply_log_crime_transform,
    normalize_features,
)
from commute import add_drive_time_google, add_straight_line_distance
from scoring import compute_final_score, generate_summary_table
from config import (
    DATA_PROC,
    DATA_FINAL,
    OUTPUTS,
    THRESHOLDS,
    CRIME_PERCENTILE_CUTOFF,
    YIELD_CAP,
    MAX_COMMUTE_MINS,
    MAX_COMMUTE_MILES,
)


def parse_args():
    parser = argparse.ArgumentParser(description="SATX House Hack Scoring Model (Path B)")
    parser.add_argument("--no-google-maps", action="store_true")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--diagnose", action="store_true",
                        help="Print data snapshots and filter stats at every step")
    return parser.parse_args()


def diagnose(label: str, df: pd.DataFrame, numeric_cols: list = None) -> None:
    print(f"\n{'='*60}")
    print(f"  DIAGNOSE: {label}")
    print(f"  Rows: {len(df)} | Cols: {list(df.columns)}")
    if numeric_cols:
        for col in numeric_cols:
            if col in df.columns:
                s = pd.to_numeric(df[col], errors="coerce")
                print(f"  {col}: min={s.min():.4f}  max={s.max():.4f}  nulls={s.isna().sum()}")
    if len(df) > 0:
        print(df.head(3).to_string())
    print("="*60)


def check_filters(df: pd.DataFrame) -> None:
    """Print breakdown of how many ZIPs each filter removes."""
    print(f"\n{'='*60}")
    print("  FILTER BREAKDOWN (ZIPs failing each rule)")
    print(f"  Starting ZIPs: {len(df)}")
    print(f"  {'Filter':<35} {'Failing':>8}  Threshold/Rule")
    print(f"  {'-'*60}")

    checks = [
        ("rent_to_price >= min",    "rent_to_price",    ">=", THRESHOLDS["min_rent_to_price"]),
        ("median_home_value <= max","median_home_value", "<=", THRESHOLDS["max_home_value"]),
        ("owner_occ_pct >= min",    "owner_occ_pct",    ">=", THRESHOLDS["min_owner_occ_pct"]),
        ("owner_occ_pct <= max",    "owner_occ_pct",    "<=", THRESHOLDS["max_owner_occ_pct"]),
    ]
    if "median_hh_income" in df.columns:
        checks.append(("median_hh_income >= min", "median_hh_income", ">=", THRESHOLDS["min_median_income"]))
    if "commute_minutes" in df.columns:
        checks.append(("commute_minutes <= max", "commute_minutes", "<=", MAX_COMMUTE_MINS))
    elif "commute_miles" in df.columns:
        checks.append(("commute_miles <= max", "commute_miles", "<=", MAX_COMMUTE_MILES))

    surviving = pd.Series([True] * len(df), index=df.index)
    for label, col, op, threshold in checks:
        if col not in df.columns:
            print(f"  {label:<35} {'MISSING':>8}")
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        mask = (s >= threshold) if op == ">=" else (s <= threshold)
        failing = (~mask | s.isna()).sum()
        surviving &= (mask & s.notna())
        print(f"  {label:<35} {failing:>8}  ({threshold:,})")

    # Crime percentile display
    if "crime_per_1k" in df.columns:
        crime = pd.to_numeric(df["crime_per_1k"], errors="coerce")
        pct_threshold = crime.quantile(CRIME_PERCENTILE_CUTOFF)
        above = (crime > pct_threshold).sum()
        print(f"  {'crime_per_1k (percentile floor)':<35} {above:>8}  "
              f"(>{pct_threshold:.1f}/1k = top {1-CRIME_PERCENTILE_CUTOFF:.0%})")

    # Yield cap display
    if "rent_to_price" in df.columns:
        rtp = pd.to_numeric(df["rent_to_price"], errors="coerce")
        capped = (rtp > YIELD_CAP).sum()
        if capped > 0:
            print(f"  {'yield cap (scoring only)':<35} {capped:>8}  "
                  f"(>{YIELD_CAP:.0%} capped, not removed)")

    print(f"\n  ZIPs surviving hard filters: {surviving.sum()}")
    print("="*60)


def run_pipeline(use_google_maps: bool = True, top_n: int = 15, diagnose_mode: bool = False) -> None:
    logger = logging.getLogger(__name__)

    # ── Step 1: Load ──────────────────────────────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 1: Loading raw data")
    logger.info("="*60)

    zhvi_raw   = load_zhvi()
    zori_raw   = load_zori()
    census_raw = load_census_acs()
    crime_raw  = load_crime_data()
    zip_coords = load_zip_centroids()

    # ── Step 2: Process ───────────────────────────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 2: Processing raw data")
    logger.info("="*60)

    zhvi      = process_zhvi(zhvi_raw)
    stability = compute_zhvi_stability(zhvi_raw)    # from same ZHVI file, free
    cagr      = compute_zhvi_cagr(zhvi_raw)         # from same ZHVI file, free
    zori      = process_zori(zori_raw)
    census    = process_census(census_raw)
    crime     = process_crime(crime_raw, census_df=census)

    if diagnose_mode:
        diagnose("ZHVI processed",      zhvi,      ["median_home_value"])
        diagnose("ZHVI stability (CoV)", stability, ["zhvi_cov"])
        diagnose("ZHVI CAGR",           cagr,      ["zhvi_cagr_5yr", "zhvi_cagr_10yr"])
        diagnose("ZORI processed",      zori,      ["median_rent"])
        diagnose("Census processed",    census,    ["owner_occ_pct", "median_hh_income"])
        diagnose("Crime processed",     crime,     ["crime_per_1k"])

        sets = {
            "ZHVI":      set(zhvi["zip"]),
            "Stability": set(stability["zip"]),
            "ZORI":      set(zori["zip"]),
            "Census":    set(census["zip"]),
            "Crime":     set(crime["zip"]),
        }
        print(f"\n{'='*60}")
        print("  ZIP OVERLAP ANALYSIS")
        for name, s in sets.items():
            print(f"  {name:<12}: {len(s)} ZIPs")
        common = set.intersection(*sets.values())
        print(f"  ALL five overlap: {len(common)} ZIPs")
        print("="*60)

    # ── Step 3: Commute ───────────────────────────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 3: Computing commute times")
    logger.info("="*60)

    base_zips = zhvi[["zip"]].merge(zip_coords, on="zip", how="left")
    if base_zips["zip_lat"].isna().sum() > 0:
        logger.warning(f"{base_zips['zip_lat'].isna().sum()} ZIPs missing coordinates")

    if use_google_maps:
        commute = add_drive_time_google(base_zips)
    else:
        commute = add_straight_line_distance(base_zips)

    commute = commute[["zip", "commute_minutes", "commute_miles"]].dropna()

    if diagnose_mode:
        diagnose("Commute", commute, ["commute_minutes", "commute_miles"])

    # ── Step 4: Merge ─────────────────────────────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 4: Merging datasets")
    logger.info("="*60)

    merged = merge_datasets(zhvi, zori, census, crime, commute, stability=stability, cagr=cagr)
    save_csv(merged, DATA_PROC / "merged_zip_dataset.csv", "merged")

    if merged.empty:
        logger.error("Merge produced 0 rows. Run with --diagnose to identify the gap.")
        return

    if diagnose_mode:
        diagnose("Merged dataset", merged,
                 ["median_home_value", "median_rent", "owner_occ_pct",
                  "crime_per_1k", "commute_minutes", "zhvi_cov", "median_hh_income"])

    # ── Step 5: Feature engineering & filters ─────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 5: Feature engineering & filters (Path B)")
    logger.info("="*60)

    features = compute_rent_to_price(merged)

    if diagnose_mode:
        check_filters(features)

    # Hard filters first — remove unacceptable ZIPs entirely
    features = apply_hard_filters(features)

    if features.empty:
        logger.error(
            "All ZIPs removed by hard filters. "
            "Loosen THRESHOLDS in src/config.py and re-run."
        )
        return

    # Flag crime risk — keeps all ZIPs, adds crime_flag column for transparency
    features = flag_crime_risk(features)

    # Transform for scoring
    features = apply_yield_cap(features)
    features = apply_log_crime_transform(features)
    features = normalize_features(features)

    # ── Step 6: Score ─────────────────────────────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 6: Scoring and ranking")
    logger.info("="*60)

    scored = compute_final_score(features)
    save_csv(scored, DATA_FINAL / "ranked_zip_scores.csv", "final scored")

    summary = generate_summary_table(scored, top_n=top_n)
    save_csv(summary, OUTPUTS / "top_zips_summary.csv", "human-readable summary")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 140)
    print("\n" + summary.to_string(index=False))
    logger.info("Pipeline complete. Check outputs/ for results.")


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)
    run_pipeline(
        use_google_maps=not args.no_google_maps,
        top_n=args.top,
        diagnose_mode=args.diagnose,
    )
