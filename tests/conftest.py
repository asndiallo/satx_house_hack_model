"""
conftest.py
-----------
Shared fixtures and path setup for the property_analyzer test suite.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure src/ is importable before any test module is loaded
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from property_analyzer import PropertyInput


# ── Property fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def base_prop():
    """Standard duplex, VA first-use, no BAH. The canonical test case."""
    return PropertyInput(
        zip_code="78239",
        asking_price=215_000,
        units=2,
    )


@pytest.fixture
def prop_with_bah():
    """Same as base_prop but with BAH offset."""
    return PropertyInput(
        zip_code="78239",
        asking_price=215_000,
        units=2,
        bah_monthly=1_900,
    )


@pytest.fixture
def sfh_prop():
    """Single-family home with explicit 50% hack fraction (room rental)."""
    return PropertyInput(
        zip_code="78209",
        asking_price=285_000,
        units=1,
        hack_fraction=0.5,
    )


@pytest.fixture
def triplex_prop():
    """Triplex — you occupy 1 unit, rent 2."""
    return PropertyInput(
        zip_code="78239",
        asking_price=320_000,
        units=3,
    )


@pytest.fixture
def fourplex_prop():
    """Fourplex — you occupy 1 unit, rent 3."""
    return PropertyInput(
        zip_code="78239",
        asking_price=400_000,
        units=4,
    )


@pytest.fixture
def conventional_prop():
    """Conventional loan, 20% down — no PMI."""
    return PropertyInput(
        zip_code="78239",
        asking_price=200_000,
        units=2,
        loan_type="Conventional",
        down_pct=0.20,
    )


@pytest.fixture
def conventional_low_down_prop():
    """Conventional loan, 5% down — PMI applies."""
    return PropertyInput(
        zip_code="78239",
        asking_price=200_000,
        units=2,
        loan_type="Conventional",
        down_pct=0.05,
    )


@pytest.fixture
def high_hoa_prop():
    """Property with significant HOA fees."""
    return PropertyInput(
        zip_code="78239",
        asking_price=215_000,
        units=2,
        hoa_monthly=250,
    )


# ── Data fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_ranked_row() -> dict:
    """Raw dict representing a single scored ZIP — mirrors ranked_zip_scores.csv schema."""
    return {
        "zip":               "78239",
        "median_home_value": 213_816.0,
        "median_rent":       1_446.0,
        "owner_occ_pct":     0.73,
        "median_hh_income":  71_721.0,
        "crime_per_1k":      51.7,
        "commute_minutes":   15.4,
        "commute_miles":     6.4,
        "zhvi_cov":          0.0606,
        "zhvi_cagr_5yr":     0.030,
        "zhvi_cagr_10yr":    0.051,
        "rent_to_price":     0.0811,
        "final_score":       0.714,
        "rank":              1,
    }


@pytest.fixture
def sample_ranked_df(sample_ranked_row) -> pd.DataFrame:
    """Single-row ranked DataFrame for the canonical ZIP 78239."""
    return pd.DataFrame([sample_ranked_row])


@pytest.fixture
def sample_merged_df(sample_ranked_row) -> pd.DataFrame:
    """
    Two-row merged DataFrame (pre-filter data).
    Includes the canonical ZIP and a high-crime filtered-out ZIP for
    percentile context tests.
    """
    second_row = {
        **sample_ranked_row,
        "zip":               "78209",
        "crime_per_1k":      291.3,
        "median_rent":       1_550.0,
        "median_home_value": 310_000.0,
        "owner_occ_pct":     0.48,   # fails owner-occ filter (< 50%)
        "final_score":       0.0,
        "rank":              99,
    }
    return pd.DataFrame([sample_ranked_row, second_row])


@pytest.fixture
def synthetic_crime_df() -> pd.DataFrame:
    """
    Small synthetic SAPD-format crime DataFrame for cache building tests.
    Covers multiple problem types, ZIPs, dates, and weekdays.
    """
    from property_analyzer import VIOLENT_CRIME_PROBLEMS  # noqa: E402 — deferred after sys.path

    problems = list(VIOLENT_CRIME_PROBLEMS)
    # Recent 12 months
    recent_rows = [
        {"Postal_Code": "78239", "Problem": problems[0],  "Response_Date": "2024-10-01", "Weekday": "Monday"},
        {"Postal_Code": "78239", "Problem": problems[0],  "Response_Date": "2024-11-15", "Weekday": "Friday"},
        {"Postal_Code": "78239", "Problem": problems[1],  "Response_Date": "2024-12-01", "Weekday": "Friday"},
        {"Postal_Code": "78239", "Problem": "THEFT",      "Response_Date": "2025-01-10", "Weekday": "Tuesday"},
        {"Postal_Code": "78209", "Problem": "ASSAULT",    "Response_Date": "2025-02-01", "Weekday": "Wednesday"},
        {"Postal_Code": "78209", "Problem": "ROBBERY",    "Response_Date": "2025-03-01", "Weekday": "Thursday"},
    ]
    # Prior 12 months (for trend computation)
    prior_rows = [
        {"Postal_Code": "78239", "Problem": problems[0],  "Response_Date": "2023-10-01", "Weekday": "Monday"},
        {"Postal_Code": "78239", "Problem": "THEFT",      "Response_Date": "2023-11-01", "Weekday": "Tuesday"},
        {"Postal_Code": "78239", "Problem": "THEFT",      "Response_Date": "2023-12-01", "Weekday": "Wednesday"},
        {"Postal_Code": "78239", "Problem": "THEFT",      "Response_Date": "2024-01-01", "Weekday": "Friday"},
        {"Postal_Code": "78239", "Problem": "THEFT",      "Response_Date": "2024-02-01", "Weekday": "Friday"},
        {"Postal_Code": "78209", "Problem": "ASSAULT",    "Response_Date": "2024-03-01", "Weekday": "Thursday"},
    ]
    return pd.DataFrame(recent_rows + prior_rows)
