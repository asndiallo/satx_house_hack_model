"""
scoring.py
----------
Apply weighted scoring model to normalized features.
Weights and their rationale live in config.py — not here.
"""

import logging

import pandas as pd

from config import WEIGHTS

logger = logging.getLogger(__name__)

SCORE_COLS = {
    "rent_to_price": "score_rent_to_price",
    "crime": "score_crime",
    "owner_occupancy": "score_owner_occupancy",
    "commute": "score_commute",
    "stability": "score_stability",
}


def compute_final_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Weighted linear combination of normalized feature scores.
    Each score is [0, 1]. Final score is [0, 1]. Higher = better.
    To change priorities, update WEIGHTS in config.py.
    """
    df = df.copy()

    missing = [col for col in SCORE_COLS.values() if col not in df.columns]
    if missing:
        raise ValueError(
            f"Missing score columns: {missing}. Run feature_engineering first."
        )

    df["final_score"] = sum(
        WEIGHTS[factor] * df[score_col] for factor, score_col in SCORE_COLS.items()
    )

    df["rank"] = df["final_score"].rank(ascending=False, method="min").astype(int)
    df = df.sort_values("rank")

    for factor, score_col in SCORE_COLS.items():
        df[f"weighted_{factor}"] = WEIGHTS[factor] * df[score_col]

    logger.info(
        f"Scoring complete. Top ZIP: {df.iloc[0]['zip']} "
        f"(score: {df.iloc[0]['final_score']:.3f})"
    )
    return df


def generate_summary_table(df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    """Human-readable output table for the top N ZIPs."""
    cols = [
        "rank",
        "zip",
        "median_home_value",
        "median_rent",
        "est_room_rent",
        "rent_to_price",
        "commute_minutes",
        "crime_per_1k",
        "crime_flag",
        "owner_occ_pct",
        "pct_sfr",
        "bcad_sfr_count",
        "permit_sfr_12mo",
        "permit_large_mf_12mo",
        "zhvi_cov",
        "zhvi_cagr_5yr",
        "zhvi_cagr_10yr",
        "median_hh_income",
        "final_score",
        "weighted_rent_to_price",
        "weighted_crime",
        "weighted_owner_occupancy",
        "weighted_commute",
        "weighted_stability",
    ]
    available_cols = [c for c in cols if c in df.columns]
    summary = df[available_cols].head(top_n).copy()

    fmt = {
        "median_home_value": "${:,.0f}".format,
        "median_rent": "${:,.0f}".format,
        "median_hh_income": "${:,.0f}".format,
        "rent_to_price": "{:.3f}".format,
        "owner_occ_pct": "{:.1%}".format,
        "pct_sfr": "{:.1%}".format,
        "commute_minutes": "{:.0f} min".format,
        "final_score": "{:.3f}".format,
        "zhvi_cov": "{:.4f}".format,
        "zhvi_cagr_5yr": "{:+.2%}".format,
        "zhvi_cagr_10yr": "{:+.2%}".format,
    }
    for col, fn in fmt.items():
        if col in summary.columns:
            summary[col] = summary[col].map(fn)

    return summary
