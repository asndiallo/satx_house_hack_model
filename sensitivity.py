"""
sensitivity.py
--------------
Tests how stable your ZIP rankings are when weights shift.

If your top ZIPs change dramatically with small weight changes,
the model is reflecting your priors, not real signal.

Usage:
    python sensitivity.py                     # uses data/final/ranked_zip_scores.csv
    python sensitivity.py --top 5             # check top 5 stability
    python sensitivity.py --delta 0.15        # shift weights by ±15% instead of ±10%
"""

import sys
import argparse
import logging
import pandas as pd
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import WEIGHTS, DATA_FINAL, OUTPUTS
from utils import setup_logging


def parse_args():
    parser = argparse.ArgumentParser(description="Sensitivity analysis for scoring weights")
    parser.add_argument("--top", type=int, default=5, help="Top N ZIPs to track")
    parser.add_argument("--delta", type=float, default=0.10, help="Weight shift amount")
    parser.add_argument("--input", type=Path, default=DATA_FINAL / "ranked_zip_scores.csv")
    return parser.parse_args()


def rescore(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """Recompute final_score with new weights using pre-normalized score columns."""
    score_map = {
        "rent_to_price":   "score_rent_to_price",
        "crime":           "score_crime",
        "owner_occupancy": "score_owner_occupancy",
        "commute":         "score_commute",
    }
    missing = [col for col in score_map.values() if col not in df.columns]
    if missing:
        raise ValueError(
            f"Score columns not found: {missing}\n"
            "Run main.py first to generate ranked_zip_scores.csv"
        )
    df = df.copy()
    df["final_score"] = sum(
        weights[factor] * df[score_col]
        for factor, score_col in score_map.items()
    )
    df["rank"] = df["final_score"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("rank")


def generate_weight_scenarios(base: dict, delta: float) -> list[tuple[str, dict]]:
    """
    Generate weight scenarios by shifting pairs of weights ±delta.
    Only creates scenarios where all weights remain positive and sum to 1.0.
    """
    factors = list(base.keys())
    scenarios = [("baseline", base.copy())]

    for i, factor_up in enumerate(factors):
        for j, factor_down in enumerate(factors):
            if i == j:
                continue
            w = base.copy()
            w[factor_up]   = round(w[factor_up]   + delta, 3)
            w[factor_down] = round(w[factor_down] - delta, 3)
            if any(v < 0 for v in w.values()):
                continue
            if abs(sum(w.values()) - 1.0) > 1e-6:
                continue
            label = f"{factor_up}+{delta:.0%} / {factor_down}-{delta:.0%}"
            scenarios.append((label, w))

    return scenarios


def run_sensitivity(input_path: Path, top_n: int, delta: float) -> None:
    logger = logging.getLogger(__name__)

    if not input_path.exists():
        print(f"ERROR: {input_path} not found. Run main.py first.")
        sys.exit(1)

    df = pd.read_csv(input_path, dtype={"zip": str})
    logger.info(f"Loaded {len(df)} scored ZIPs from {input_path.name}")

    scenarios = generate_weight_scenarios(WEIGHTS, delta)
    logger.info(f"Running {len(scenarios)} weight scenarios (delta={delta:.0%})")

    # Track top-N ZIPs across all scenarios
    results = {}
    for label, weights in scenarios:
        rescored = rescore(df, weights)
        top_zips = rescored.head(top_n)["zip"].tolist()
        results[label] = top_zips

    # Build comparison table
    baseline_top = results["baseline"]
    print(f"\n{'='*70}")
    print(f"  SENSITIVITY ANALYSIS — Top {top_n} ZIPs across {len(scenarios)} weight scenarios")
    print(f"  Base weights: {WEIGHTS}")
    print(f"  Shift delta: ±{delta:.0%}")
    print(f"{'='*70}")
    print(f"\n  {'Scenario':<45} {'Top ZIPs'}")
    print(f"  {'-'*65}")

    stable_count = 0
    for label, top_zips in results.items():
        overlap = len(set(top_zips) & set(baseline_top))
        stability = overlap / top_n
        marker = "✓" if stability >= 0.6 else "⚠"
        if stability >= 0.6:
            stable_count += 1
        print(f"  {marker} {label:<43} {', '.join(top_zips)}  ({overlap}/{top_n} overlap)")

    # Summary verdict
    total = len(scenarios)
    pct_stable = stable_count / total * 100
    print(f"\n{'='*70}")
    print(f"  VERDICT: {stable_count}/{total} scenarios ({pct_stable:.0f}%) have ≥60% top-ZIP overlap")

    if pct_stable >= 80:
        print("  ✓ Rankings are STABLE. Top ZIPs have real signal, not just weight artifacts.")
    elif pct_stable >= 50:
        print("  ⚠ Rankings are MODERATELY STABLE. Core top 2-3 ZIPs are likely reliable.")
        print("    Lower-ranked ZIPs are sensitive to weight assumptions.")
    else:
        print("  ✗ Rankings are UNSTABLE. Model is reflecting your weight choices,")
        print("    not meaningful differences between ZIPs.")
        print("    Consider: are your data sources reliable enough to score this finely?")

    # Save full results to CSV for inspection
    records = []
    for label, weights in scenarios:
        rescored = rescore(df, weights)
        for _, row in rescored.head(top_n).iterrows():
            records.append({
                "scenario": label,
                "rank": row["rank"],
                "zip": row["zip"],
                "final_score": round(row["final_score"], 4),
                **{f"w_{k}": v for k, v in weights.items()}
            })

    out_path = OUTPUTS / "sensitivity_results.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(out_path, index=False)
    print(f"\n  Full results saved to: {out_path}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    args = parse_args()
    setup_logging("INFO")
    run_sensitivity(args.input, args.top, args.delta)