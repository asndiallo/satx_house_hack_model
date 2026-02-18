"""
sensitivity.py
--------------
Two robustness tests for the scoring model.

TEST 1 — Weight Stability
Perturbs weights ±delta and checks whether top ZIP rankings hold.
Proves: results aren't just artifacts of your weight choices.

TEST 2 — Hard Filter Dependency
Rescores all ZIPs without hard filters applied (crime as pure soft penalty).
Proves: your top ZIPs win on merit, not because hard filters eliminated competition.
If rankings shift dramatically in Test 2 → hard filters were doing heavy lifting.

Usage:
    python sensitivity.py                  # both tests, top 5, delta=10%
    python sensitivity.py --test weights   # weight stability only
    python sensitivity.py --test filters   # filter dependency only
    python sensitivity.py --top 8 --delta 0.15
"""

import sys
import argparse
import logging
import pandas as pd
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import WEIGHTS, DATA_FINAL, OUTPUTS
from utils import setup_logging

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--delta", type=float, default=0.10)
    parser.add_argument("--test", choices=["weights", "filters", "both"], default="both")
    parser.add_argument("--scored-csv", type=Path, default=DATA_FINAL / "ranked_zip_scores.csv",
                        help="Output of main.py (with hard filters applied)")
    parser.add_argument("--merged-csv", type=Path, default=None,
                        help="Merged dataset before hard filters (data/processed/merged_zip_dataset.csv)")
    return parser.parse_args()


# ── Shared Scoring Logic ──────────────────────────────────────────────────────

def rescore(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """Recompute final_score using pre-existing normalized score columns."""
    score_map = {
        "rent_to_price":   "score_rent_to_price",
        "crime":           "score_crime",
        "owner_occupancy": "score_owner_occupancy",
        "commute":         "score_commute",
    }
    missing = [col for col in score_map.values() if col not in df.columns]
    if missing:
        raise ValueError(f"Score columns missing: {missing}. Run main.py first.")
    df = df.copy()
    df["final_score"] = sum(weights[f] * df[c] for f, c in score_map.items())
    df["rank"] = df["final_score"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("rank")


def score_from_raw(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """
    Score a raw merged DataFrame from scratch (no pre-existing score columns).
    Used for Test 2 to score all ZIPs without hard filters.
    """
    df = df.copy()

    # Compute rent-to-price
    df["rent_to_price"] = (df["median_rent"] * 12) / df["median_home_value"]

    # Log-transform crime (same as production pipeline)
    df["crime_log"] = np.log1p(df["crime_per_1k"])

    def minmax(series, invert=False):
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.5, index=series.index)
        n = (series - mn) / (mx - mn)
        return 1 - n if invert else n

    df["score_rent_to_price"]   = minmax(df["rent_to_price"])
    df["score_crime"]           = minmax(df["crime_log"],       invert=True)
    df["score_owner_occupancy"] = minmax(df["owner_occ_pct"])
    df["score_commute"]         = minmax(df["commute_minutes"], invert=True)

    df["final_score"] = sum(weights[f] * df[c] for f, c in {
        "rent_to_price":   "score_rent_to_price",
        "crime":           "score_crime",
        "owner_occupancy": "score_owner_occupancy",
        "commute":         "score_commute",
    }.items())
    df["rank"] = df["final_score"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("rank")


def generate_weight_scenarios(base: dict, delta: float) -> list:
    factors = list(base.keys())
    scenarios = [("baseline", base.copy())]
    for i, up in enumerate(factors):
        for j, down in enumerate(factors):
            if i == j:
                continue
            w = base.copy()
            w[up]   = round(w[up]   + delta, 3)
            w[down] = round(w[down] - delta, 3)
            if any(v < 0 for v in w.values()):
                continue
            if abs(sum(w.values()) - 1.0) > 1e-6:
                continue
            scenarios.append((f"{up}+{delta:.0%} / {down}-{delta:.0%}", w))
    return scenarios


# ── Test 1: Weight Stability ──────────────────────────────────────────────────

def test_weight_stability(df: pd.DataFrame, top_n: int, delta: float) -> None:
    scenarios = generate_weight_scenarios(WEIGHTS, delta)
    baseline_top = rescore(df, WEIGHTS).head(top_n)["zip"].tolist()

    print(f"\n{'='*70}")
    print(f"  TEST 1 — WEIGHT STABILITY")
    print(f"  Top {top_n} ZIPs across {len(scenarios)} scenarios (delta=±{delta:.0%})")
    print(f"  Baseline top {top_n}: {baseline_top}")
    print(f"{'='*70}")
    print(f"  {'Scenario':<43} {'Overlap':>8}  Top ZIPs")
    print(f"  {'-'*68}")

    stable = 0
    records = []
    for label, weights in scenarios:
        rescored = rescore(df, weights)
        top_zips = rescored.head(top_n)["zip"].tolist()
        overlap = len(set(top_zips) & set(baseline_top))
        pct = overlap / top_n
        marker = "✓" if pct >= 0.6 else "⚠"
        if pct >= 0.6:
            stable += 1
        print(f"  {marker} {label:<43} {overlap}/{top_n}     {', '.join(top_zips)}")
        for rank_pos, z in enumerate(top_zips, 1):
            records.append({"test": "weight_stability", "scenario": label, "rank": rank_pos,
                            "zip": z, **{f"w_{k}": v for k, v in weights.items()}})

    pct_stable = stable / len(scenarios) * 100
    verdict = ("✓ STABLE" if pct_stable >= 80
               else "⚠ MODERATE" if pct_stable >= 50
               else "✗ UNSTABLE")
    print(f"\n  {verdict}: {stable}/{len(scenarios)} scenarios ({pct_stable:.0f}%) have ≥60% overlap")
    return pd.DataFrame(records)


# ── Test 2: Hard Filter Dependency ────────────────────────────────────────────

def test_filter_dependency(filtered_df: pd.DataFrame, merged_df: pd.DataFrame, top_n: int) -> None:
    """
    Score all ZIPs (no hard filters) and compare to filtered results.
    If top ZIPs shift significantly → hard filters were doing the heavy lifting.
    If top ZIPs hold → your winners earn their rank on merit.
    """
    filtered_top = rescore(filtered_df, WEIGHTS).head(top_n)["zip"].tolist()
    all_zips_scored = score_from_raw(merged_df, WEIGHTS)
    all_zips_top = all_zips_scored.head(top_n)["zip"].tolist()
    overlap = len(set(filtered_top) & set(all_zips_top))

    print(f"\n{'='*70}")
    print(f"  TEST 2 — HARD FILTER DEPENDENCY")
    print(f"  Do your top ZIPs win on merit, or just by surviving filters?")
    print(f"{'='*70}")
    print(f"  With hard filters applied:  {len(filtered_df)} ZIPs -> top {top_n}: {filtered_top}")
    print(f"  All {len(merged_df)} ZIPs scored (no filters):       top {top_n}: {all_zips_top}")
    print(f"\n  Overlap: {overlap}/{top_n} ZIPs appear in both top-{top_n} lists")

    if overlap == top_n:
        print("  ✓ STRONG: Top ZIPs are top-ranked even without filters.")
        print("    Hard filters are convenience, not crutches.")
    elif overlap >= top_n * 0.6:
        print("  ✓ MODERATE: Core ZIPs hold up. Some ranking shift from filter removal.")
        print("    Your top 1-2 picks are likely robust; lower picks less certain.")
    else:
        print("  ⚠ WARNING: Rankings change significantly without hard filters.")
        print("    Hard filters are determining your winners more than the score.")
        print("    Consider: are your filters encoding domain knowledge,")
        print("    or are they artifacts of uncertain thresholds?")

    # Show where the previously-filtered ZIPs ranked in the all-ZIP scoring
    print(f"\n  How filtered-out ZIPs rank when scored on merit:")
    filtered_zips = set(merged_df["zip"]) - set(filtered_df["zip"])
    filtered_rankings = all_zips_scored[all_zips_scored["zip"].isin(filtered_zips)]
    print(f"  {filtered_rankings[['zip','rank','final_score','rent_to_price','crime_per_1k']].head(10).to_string(index=False)}")

    records = []
    for _, row in all_zips_scored.iterrows():
        records.append({"test": "filter_dependency", "zip": row["zip"],
                        "rank_no_filters": row["rank"], "final_score": round(row["final_score"], 4),
                        "was_filtered_out": row["zip"] not in set(filtered_df["zip"])})
    return pd.DataFrame(records)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()
    setup_logging("INFO")

    # Load scored output (post-filter)
    if not args.scored_csv.exists():
        print(f"ERROR: {args.scored_csv} not found. Run main.py first.")
        sys.exit(1)
    scored_df = pd.read_csv(args.scored_csv, dtype={"zip": str})

    # Load merged dataset (pre-filter) for Test 2
    merged_path = args.merged_csv or Path("data/processed/merged_zip_dataset.csv")

    all_results = []

    if args.test in ("weights", "both"):
        r = test_weight_stability(scored_df, args.top, args.delta)
        all_results.append(r)

    if args.test in ("filters", "both"):
        if not merged_path.exists():
            print(f"\n⚠ Test 2 skipped: {merged_path} not found.")
            print("  Run main.py first — it saves merged_zip_dataset.csv to data/processed/")
        else:
            merged_df = pd.read_csv(merged_path, dtype={"zip": str})
            r = test_filter_dependency(scored_df, merged_df, args.top)
            all_results.append(r)

    if all_results:
        out_path = OUTPUTS / "sensitivity_results.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(all_results, ignore_index=True).to_csv(out_path, index=False)
        print(f"\n  Full results: {out_path}\n")