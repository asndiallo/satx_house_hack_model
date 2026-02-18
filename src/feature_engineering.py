"""
feature_engineering.py
-----------------------
Compute derived features from the merged dataset.
All features should be interpretable — no black boxes.
"""

import logging
import pandas as pd
import numpy as np

from config import THRESHOLDS, CRIME_PERCENTILE_CUTOFF

logger = logging.getLogger(__name__)


def compute_rent_to_price(df: pd.DataFrame) -> pd.DataFrame:
    """Gross rent yield — annualized rent divided by home value."""
    df = df.copy()
    df["rent_to_price"] = (df["median_rent"] * 12) / df["median_home_value"]
    return df


def apply_hard_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove ZIPs that fail absolute thresholds BEFORE scoring.

    Crime is intentionally excluded from hard filters.
    It enters the model as a soft scored penalty (log-transformed, then normalized).
    This lets all financially viable ZIPs compete on crime as a graded dimension,
    rather than being binarily eliminated by a threshold that depends on data quality.
    """
    df = df.copy()
    initial = len(df)

    filters = {
        "min_rent_to_price": df["rent_to_price"]    >= THRESHOLDS["min_rent_to_price"],
        "max_home_value":    df["median_home_value"] <= THRESHOLDS["max_home_value"],
        "min_owner_occ":     df["owner_occ_pct"]     >= THRESHOLDS["min_owner_occ_pct"],
        "max_owner_occ":     df["owner_occ_pct"]     <= THRESHOLDS["max_owner_occ_pct"],
    }

    mask = pd.Series(True, index=df.index)
    for name, condition in filters.items():
        failed = (~condition).sum()
        if failed > 0:
            logger.info(f"Hard filter '{name}' removed {failed} ZIPs")
        mask &= condition

    result = df[mask].copy()
    logger.info(f"Hard filters: {initial} -> {len(result)} ZIPs remaining")
    return result


def apply_log_crime_transform(df: pd.DataFrame) -> pd.DataFrame:
    """
    Log-transform crime_per_1k before normalization.

    Why this matters:
    Raw crime distributions are heavily right-skewed — a few high-crime ZIPs
    stretch the linear scale so that most ZIPs are compressed into a narrow band
    near zero. This makes the crime dimension nearly binary (extreme vs everything else).

    log(1 + x) compresses the tail while preserving rank order:
      - ZIP with crime=1   -> log(2)   = 0.69
      - ZIP with crime=25  -> log(26)  = 3.26
      - ZIP with crime=200 -> log(201) = 5.30
      - ZIP with crime=3000-> log(3001)= 8.01

    Without the transform, a ZIP with crime=3000 makes crime=200 look nearly safe.
    With the transform, the scoring scale is meaningful across the full range.

    The raw value is preserved in crime_per_1k for output/interpretation.
    The transformed value (crime_log) is what the scorer uses.
    """
    df = df.copy()
    df["crime_log"] = np.log1p(df["crime_per_1k"])
    logger.info(
        f"Crime log-transform: raw range [{df['crime_per_1k'].min():.1f}, "
        f"{df['crime_per_1k'].max():.1f}] -> "
        f"log range [{df['crime_log'].min():.2f}, {df['crime_log'].max():.2f}]"
    )
    return df


def normalize_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Min-max normalize each feature to [0, 1] for scoring.
    Higher normalized score = better in all cases (crime and commute are inverted).

    Crime is scored on the log-transformed value — run apply_log_crime_transform first.

    NOTE: scores are relative to your ZIP pool, not absolute.
    0.8 means "better than 80% of surviving ZIPs in this dataset."
    """
    df = df.copy()

    if "crime_log" not in df.columns:
        raise ValueError(
            "crime_log column missing. Run apply_log_crime_transform() before normalize_features()."
        )

    def minmax(series: pd.Series, invert: bool = False) -> pd.Series:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.5, index=series.index)
        normalized = (series - mn) / (mx - mn)
        return 1 - normalized if invert else normalized

    df["score_rent_to_price"]   = minmax(df["rent_to_price"])
    df["score_crime"]           = minmax(df["crime_log"],        invert=True)  # log-transformed
    df["score_owner_occupancy"] = minmax(df["owner_occ_pct"])
    df["score_commute"]         = minmax(df["commute_minutes"],  invert=True)

    return df