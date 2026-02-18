"""
utils.py
--------
Shared utilities: logging setup, file I/O helpers, validation.
"""

import logging
import sys
from pathlib import Path
import pandas as pd


def setup_logging(level: str = "INFO") -> None:
    """
    Configure logging to both console and file.
    Call once at the top of main.py.
    """
    log_format = "%(asctime)s | %(levelname)-8s | %(module)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("model_run.log", mode="w"),
        ]
    )


def save_csv(df: pd.DataFrame, path: Path, description: str = "") -> None:
    """Save DataFrame with logging. Creates parent dirs if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    rows, cols = df.shape
    label = f" ({description})" if description else ""
    logging.getLogger(__name__).info(
        f"Saved{label}: {path.name} — {rows} rows × {cols} cols"
    )


def validate_dataframe(df: pd.DataFrame, required_cols: list, name: str = "DataFrame") -> None:
    """Raise informative error if required columns are missing."""
    missing = set(required_cols) - set(df.columns)
    if missing:
        raise ValueError(
            f"{name} is missing required columns: {sorted(missing)}\n"
            f"Available: {sorted(df.columns.tolist())}"
        )


def load_zip_centroids(filepath: Path = None) -> pd.DataFrame:
    """
    Load ZIP code latitude/longitude centroids.
    
    Download the free tier from: https://simplemaps.com/data/us-zips
    File: uszips.csv — contains zip, lat, lng columns.
    This is required for commute calculations.
    """
    from config import DATA_RAW
    path = filepath or DATA_RAW / "uszips.csv"
    
    if not path.exists():
        raise FileNotFoundError(
            f"ZIP centroids file not found at {path}.\n"
            "Download free from: https://simplemaps.com/data/us-zips\n"
            "Rename to 'uszips.csv' and place in data/raw/"
        )
    
    df = pd.read_csv(path, dtype={"zip": str})
    df["zip"] = df["zip"].str.zfill(5)
    return df[["zip", "lat", "lng"]].rename(columns={"lat": "zip_lat", "lng": "zip_lon"})
