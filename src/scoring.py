"""
scoring.py
----------
Apply weighted scoring model to normalized features.
This is the core of your decision model — keep it transparent.
"""

import logging
import pandas as pd

from config import WEIGHTS

logger = logging.getLogger(__name__)

SCORE_COLS = {
    "rent_to_price":   "score_rent_to_price",
    "crime":           "score_crime",
    "owner_occupancy": "score_owner_occupancy",
    "commute":         "score_commute",
}


def compute_final_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Weighted linear combination of normalized feature scores.
    
    Each score is [0, 1]. Final score is [0, 1].
    Higher = better candidate ZIP for house-hacking near BAMC.
    
    To change priorities, update WEIGHTS in config.py — not here.
    """
    df = df.copy()
    
    # Validate all score columns exist
    missing = [col for col in SCORE_COLS.values() if col not in df.columns]
    if missing:
        raise ValueError(f"Missing score columns: {missing}. Run feature_engineering first.")
    
    df["final_score"] = sum(
        WEIGHTS[factor] * df[score_col]
        for factor, score_col in SCORE_COLS.items()
    )
    
    df["rank"] = df["final_score"].rank(ascending=False, method="min").astype(int)
    df = df.sort_values("rank")
    
    # Score breakdown for interpretability — don't hide the math
    for factor, score_col in SCORE_COLS.items():
        df[f"weighted_{factor}"] = WEIGHTS[factor] * df[score_col]
    
    if df.empty:
        logger.warning("Scoring complete, but no ZIPs remained after filtering. Returning empty results.")
        return df

    logger.info(
        f"Scoring complete. Top ZIP: {df.iloc[0]['zip']} "
        f"(score: {df.iloc[0]['final_score']:.3f})"
    )
    return df


def generate_summary_table(df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    """
    Human-readable output table for the top N ZIPs.
    This is what you actually use to make decisions.
    """
    cols = [
        "rank", "zip",
        "median_home_value", "median_rent", "rent_to_price",
        "commute_minutes", "crime_per_1k", "owner_occ_pct",
        "final_score",
        "weighted_rent_to_price", "weighted_crime",
        "weighted_owner_occupancy", "weighted_commute",
    ]
    available_cols = [c for c in cols if c in df.columns]
    
    summary = df[available_cols].head(top_n).copy()
    
    # Format for readability
    if "median_home_value" in summary:
        summary["median_home_value"] = summary["median_home_value"].map("${:,.0f}".format)
    if "median_rent" in summary:
        summary["median_rent"] = summary["median_rent"].map("${:,.0f}".format)
    if "rent_to_price" in summary:
        summary["rent_to_price"] = summary["rent_to_price"].map("{:.3f}".format)
    if "owner_occ_pct" in summary:
        summary["owner_occ_pct"] = summary["owner_occ_pct"].map("{:.1%}".format)
    if "commute_minutes" in summary:
        summary["commute_minutes"] = summary["commute_minutes"].map("{:.0f} min".format)
    if "final_score" in summary:
        summary["final_score"] = summary["final_score"].map("{:.3f}".format)
    
    return summary
