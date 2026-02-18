"""
main.py
-------
Pipeline orchestrator. Runs the full model end-to-end.

Usage:
    python main.py --no-google-maps
    python main.py --no-google-maps --diagnose   # prints data snapshots at each step
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
from preprocess import process_zhvi, process_zori, process_census, process_crime, merge_datasets
from feature_engineering import compute_rent_to_price, apply_hard_filters, apply_log_crime_transform, normalize_features
from commute import add_drive_time_google, add_straight_line_distance
from scoring import compute_final_score, generate_summary_table
from config import DATA_PROC, DATA_FINAL, OUTPUTS, THRESHOLDS


def parse_args():
    parser = argparse.ArgumentParser(description="SATX House Hack Scoring Model")
    parser.add_argument("--no-google-maps", action="store_true")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--diagnose", action="store_true",
                        help="Print data snapshots and filter stats at every step")
    return parser.parse_args()


def diagnose(label: str, df: pd.DataFrame, numeric_cols: list = None) -> None:
    """Print a concise snapshot of a DataFrame at any pipeline stage."""
    print(f"\n{'='*60}")
    print(f"  DIAGNOSE: {label}")
    print(f"  Rows: {len(df)} | Cols: {list(df.columns)}")
    if numeric_cols:
        for col in numeric_cols:
            if col in df.columns:
                s = pd.to_numeric(df[col], errors="coerce")
                print(f"  {col}: min={s.min():.4f}  max={s.max():.4f}  "
                      f"nulls={s.isna().sum()}")
    if len(df) > 0:
        print(df.head(3).to_string())
    print("="*60)


def check_hard_filters(df: pd.DataFrame) -> None:
    """Show exactly how many ZIPs each threshold kills — before applying them."""
    print(f"\n{'='*60}")
    print("  HARD FILTER BREAKDOWN (ZIPs failing each rule)")
    print(f"  Starting ZIPs: {len(df)}")
    print(f"  {'Filter':<30} {'Failing':>8}  {'Threshold'}")
    print(f"  {'-'*55}")

    checks = [
        ("rent_to_price >= min",    "rent_to_price",    ">=", THRESHOLDS["min_rent_to_price"]),
        ("median_home_value <= max", "median_home_value","<=", THRESHOLDS["max_home_value"]),
        ("owner_occ_pct >= min",    "owner_occ_pct",    ">=", THRESHOLDS["min_owner_occ_pct"]),
        ("owner_occ_pct <= max",    "owner_occ_pct",    "<=", THRESHOLDS["max_owner_occ_pct"]),
        # Crime uses percentile filter — no hard threshold here
    ]
    # Show crime distribution separately
    if "crime_per_1k" in df.columns:
        crime = pd.to_numeric(df["crime_per_1k"], errors="coerce")
        from config import CRIME_PERCENTILE_CUTOFF
        pct_threshold = crime.quantile(CRIME_PERCENTILE_CUTOFF)
        above = (crime > pct_threshold).sum()
        print(f"  {'crime_per_1k (percentile)':<30} {above:>8}  (>{pct_threshold:.1f} = top {1-CRIME_PERCENTILE_CUTOFF:.0%})")

    surviving = pd.Series([True] * len(df), index=df.index)
    for label, col, op, threshold in checks:
        if col not in df.columns:
            print(f"  {label:<30} {'MISSING COL':>8}")
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if op == ">=":
            mask = series >= threshold
        elif op == "<=":
            mask = series <= threshold
        failing = (~mask | series.isna()).sum()
        surviving &= (mask & series.notna())
        print(f"  {label:<30} {failing:>8}  ({threshold})")

    print(f"\n  ZIPs surviving ALL filters: {surviving.sum()}")

    if surviving.sum() == 0:
        print("\n  >>> DIAGNOSIS: All ZIPs filtered out. Suggested actions:")
        print("  1. Check that crime data ZIPs overlap with Zillow ZIPs (run --diagnose)")
        print("  2. Consider loosening thresholds in src/config.py")
        print("     - min_rent_to_price: try 0.05 instead of 0.07")
        print("     - max_home_value: try 500_000 instead of 400_000")
        print("     - max_crime_per_1k: try 60.0 instead of 35.0")
        print("  3. Check crime_per_1k values — if no pop data, raw counts are used")
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

    zhvi   = process_zhvi(zhvi_raw)
    zori   = process_zori(zori_raw)
    census = process_census(census_raw)
    crime  = process_crime(crime_raw, census_df=census)  # pass census for population normalization

    if diagnose_mode:
        diagnose("ZHVI processed", zhvi, ["median_home_value"])
        diagnose("ZORI processed", zori, ["median_rent"])
        diagnose("Census processed", census, ["owner_occ_pct", "median_hh_income"])
        diagnose("Crime processed", crime, ["crime_per_1k"])

        # ZIP overlap check — the most common silent failure point
        sets = {
            "ZHVI":   set(zhvi["zip"]),
            "ZORI":   set(zori["zip"]),
            "Census": set(census["zip"]),
            "Crime":  set(crime["zip"]),
        }
        print(f"\n{'='*60}")
        print("  ZIP OVERLAP ANALYSIS")
        for name, s in sets.items():
            print(f"  {name:<10}: {len(s)} ZIPs")
        common = set.intersection(*sets.values())
        print(f"  ALL four overlap: {len(common)} ZIPs")
        if len(common) == 0:
            print("  >>> WARNING: Zero ZIP overlap across sources!")
            print("       Check that ZIP formats match (5-digit zero-padded strings).")
            for name, s in sets.items():
                sample = list(s)[:5]
                print(f"       {name} sample ZIPs: {sample}")
        print("="*60)

    # ── Step 3: Commute ───────────────────────────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 3: Computing commute times")
    logger.info("="*60)

    base_zips = zhvi[["zip"]].merge(zip_coords, on="zip", how="left")
    missing_coords = base_zips["zip_lat"].isna().sum()
    if missing_coords > 0:
        logger.warning(f"{missing_coords} ZIPs have no lat/lon — will be dropped from commute")

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

    merged = merge_datasets(zhvi, zori, census, crime, commute)
    save_csv(merged, DATA_PROC / "merged_zip_dataset.csv", "merged")

    if merged.empty:
        logger.error("Merge produced 0 rows. Run with --diagnose to identify the gap.")
        return

    if diagnose_mode:
        diagnose("Merged dataset", merged,
                 ["median_home_value", "median_rent", "owner_occ_pct", "crime_per_1k", "commute_minutes"])

    # ── Step 5: Features & Filters ────────────────────────────────────────────
    logger.info("="*60)
    logger.info("STEP 5: Feature engineering & hard filters")
    logger.info("="*60)

    features = compute_rent_to_price(merged)

    if diagnose_mode:
        check_hard_filters(features)

    features = apply_hard_filters(features)
    features = apply_log_crime_transform(features)

    if features.empty:
        logger.error(
            "All ZIPs removed by hard filters.\n"
            "Run with --diagnose to see exactly which thresholds are too tight.\n"
            "Then loosen them in src/config.py (THRESHOLDS dict)."
        )
        return

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
    pd.set_option("display.width", 120)
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