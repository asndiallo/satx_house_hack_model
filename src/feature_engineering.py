"""
feature_engineering.py
-----------------------
Compute derived features from the merged dataset.
All features should be interpretable — no black boxes.
"""

import logging
import pandas as pd
import numpy as np

from config import THRESHOLDS

logger = logging.getLogger(__name__)


def compute_rent_to_price(df: pd.DataFrame) -> pd.DataFrame:
    """Gross rent yield — annualized rent divided by home value."""
    df = df.copy()
    df["rent_to_price"] = (df["median_rent"] * 12) / df["median_home_value"]
    return df


def apply_hard_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove ZIPs that fail absolute thresholds BEFORE scoring.
    Hard filters are binary — a ZIP either passes or it doesn't.
    Log everything that gets cut so you can audit the funnel.
    """
    df = df.copy()
    initial = len(df)
    
    filters = {
        "min_rent_to_price":  df["rent_to_price"]    >= THRESHOLDS["min_rent_to_price"],
        "max_home_value":     df["median_home_value"] <= THRESHOLDS["max_home_value"],
        "min_owner_occ":      df["owner_occ_pct"]     >= THRESHOLDS["min_owner_occ_pct"],
        "max_owner_occ":      df["owner_occ_pct"]     <= THRESHOLDS["max_owner_occ_pct"],
        "max_crime":          df["crime_per_1k"]      <= THRESHOLDS["max_crime_per_1k"],
    }
    
    mask = pd.Series(True, index=df.index)
    for name, condition in filters.items():
        failed = (~condition).sum()
        if failed > 0:
            logger.info(f"Hard filter '{name}' removed {failed} ZIPs")
        mask &= condition
    
    result = df[mask].copy()
    logger.info(f"Hard filters: {initial} → {len(result)} ZIPs remaining")
    return result


def normalize_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Min-max normalize each feature to [0, 1] for scoring.
    Higher score = better in all cases (crime is inverted).
    
    Important: normalization is relative to your ZIP set.
    A score of 0.8 means "good vs other SA ZIPs", not "objectively good".
    """
    df = df.copy()
    
    def minmax(series: pd.Series, invert: bool = False) -> pd.Series:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.5, index=series.index)  # all same → neutral
        normalized = (series - mn) / (mx - mn)
        return 1 - normalized if invert else normalized
    
    df["score_rent_to_price"]   = minmax(df["rent_to_price"])
    df["score_crime"]           = minmax(df["crime_per_1k"],    invert=True)
    df["score_owner_occupancy"] = minmax(df["owner_occ_pct"])
    df["score_commute"]         = minmax(df["commute_minutes"], invert=True)
    
    return df
