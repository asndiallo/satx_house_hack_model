"""
test_crime.py
-------------
Tests for crime categorization and cache I/O:
  _categorize, _build_crime_cache, _load_crime_breakdown
"""

from pathlib import Path

import pytest
import pandas as pd

import property_analyzer as pa
from property_analyzer import _categorize, VIOLENT_CRIME_PROBLEMS


# ── _categorize ───────────────────────────────────────────────────────────────

class TestCategorize:
    def test_assault_maps_to_assault_category(self):
        assert _categorize("ASSAULT") == "Assault & Violence"

    def test_assault_in_progress_maps_to_assault_category(self):
        assert _categorize("ASSAULT IN PROGRESS") == "Assault & Violence"

    def test_family_violence_maps_to_assault_category(self):
        assert _categorize("FAMILY VIOLENCE") == "Assault & Violence"

    def test_robbery_maps_to_robbery_category(self):
        assert _categorize("ROBBERY") == "Robbery"

    def test_robbery_in_progress_maps_to_robbery_category(self):
        assert _categorize("ROBBERY IN PROGRESS") == "Robbery"

    def test_theft_maps_to_theft_category(self):
        assert _categorize("THEFT") == "Theft & Burglary"

    def test_burglary_maps_to_theft_category(self):
        assert _categorize("BURGLARY") == "Theft & Burglary"

    def test_burglary_vehicle_maps_to_theft_category(self):
        assert _categorize("BURGLARY VEHICLE") == "Theft & Burglary"

    def test_theft_of_vehicle_maps_to_theft_category(self):
        assert _categorize("THEFT OF VEHICLE") == "Theft & Burglary"

    def test_shooting_maps_to_weapons_category(self):
        assert _categorize("SHOOTING") == "Weapons & Shooting"

    def test_shots_fired_maps_to_weapons_category(self):
        assert _categorize("SHOTS FIRED JUST OCCURRED") == "Weapons & Shooting"

    def test_shotspotter_maps_to_weapons_category(self):
        assert _categorize("SHOTSPOTTER SINGLE ALERT") == "Weapons & Shooting"

    def test_narcotics_maps_to_narcotics_category(self):
        assert _categorize("NARCOTIC LAWS") == "Narcotics & Vice"

    def test_vice_maps_to_narcotics_category(self):
        assert _categorize("VICE") == "Narcotics & Vice"

    def test_rape_maps_to_sexual_violence_category(self):
        assert _categorize("RAPE") == "Sexual Violence"

    def test_arson_maps_to_threats_arson_category(self):
        assert _categorize("ARSON RESPONSE") == "Threats & Arson"

    def test_bomb_threat_maps_to_threats_arson_category(self):
        assert _categorize("THREATS BOMB") == "Threats & Arson"

    def test_unknown_code_returns_other(self):
        assert _categorize("COMPLETELY UNKNOWN PROBLEM") == "Other"

    def test_empty_string_returns_other(self):
        assert _categorize("") == "Other"

    def test_all_violent_crime_problems_are_categorized(self):
        """Every code in the allowlist must map to a named category (not 'Other')."""
        uncategorized = [
            p for p in VIOLENT_CRIME_PROBLEMS
            if _categorize(p.upper()) == "Other"
        ]
        assert uncategorized == [], (
            f"These VIOLENT_CRIME_PROBLEMS are missing from _CRIME_CATEGORIES: {uncategorized}"
        )


# ── _build_crime_cache ────────────────────────────────────────────────────────

class TestBuildCrimeCache:
    def test_returns_none_when_raw_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pa, "_CRIME_RAW_PATH", tmp_path / "nonexistent.csv")
        type_df, weekday_df = pa._build_crime_cache()
        assert type_df is None
        assert weekday_df is None

    def test_creates_type_cache_file(self, monkeypatch, tmp_path, synthetic_crime_df):
        raw_path     = tmp_path / "crime_raw.csv"
        type_cache   = tmp_path / "type_cache.csv"
        weekday_cache = tmp_path / "weekday_cache.csv"
        synthetic_crime_df.to_csv(raw_path, index=False)

        monkeypatch.setattr(pa, "_CRIME_RAW_PATH",      raw_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_cache)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_cache)

        pa._build_crime_cache()
        assert type_cache.exists()

    def test_creates_weekday_cache_file(self, monkeypatch, tmp_path, synthetic_crime_df):
        raw_path     = tmp_path / "crime_raw.csv"
        type_cache   = tmp_path / "type_cache.csv"
        weekday_cache = tmp_path / "weekday_cache.csv"
        synthetic_crime_df.to_csv(raw_path, index=False)

        monkeypatch.setattr(pa, "_CRIME_RAW_PATH",      raw_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_cache)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_cache)

        pa._build_crime_cache()
        assert weekday_cache.exists()

    def test_type_cache_has_expected_columns(self, monkeypatch, tmp_path, synthetic_crime_df):
        raw_path      = tmp_path / "crime_raw.csv"
        type_cache    = tmp_path / "type_cache.csv"
        weekday_cache = tmp_path / "weekday_cache.csv"
        synthetic_crime_df.to_csv(raw_path, index=False)

        monkeypatch.setattr(pa, "_CRIME_RAW_PATH",      raw_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_cache)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_cache)

        type_df, _ = pa._build_crime_cache()
        assert type_df is not None
        assert {"zip", "category", "count_recent", "count_prior"}.issubset(type_df.columns)

    def test_military_zips_excluded(self, monkeypatch, tmp_path, synthetic_crime_df):
        # Add a military ZIP row to the synthetic data
        military_row = pd.DataFrame([{
            "Postal_Code": "78234",
            "Problem": "THEFT",
            "Response_Date": "2025-01-01",
            "Weekday": "Monday",
        }])
        df_with_military = pd.concat([synthetic_crime_df, military_row], ignore_index=True)

        raw_path      = tmp_path / "crime_raw.csv"
        type_cache    = tmp_path / "type_cache.csv"
        weekday_cache = tmp_path / "weekday_cache.csv"
        df_with_military.to_csv(raw_path, index=False)

        monkeypatch.setattr(pa, "_CRIME_RAW_PATH",      raw_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_cache)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_cache)

        type_df, _ = pa._build_crime_cache()
        assert type_df is not None
        assert "78234" not in type_df["zip"].values

    def test_count_recent_and_prior_are_integers(self, monkeypatch, tmp_path, synthetic_crime_df):
        raw_path      = tmp_path / "crime_raw.csv"
        type_cache    = tmp_path / "type_cache.csv"
        weekday_cache = tmp_path / "weekday_cache.csv"
        synthetic_crime_df.to_csv(raw_path, index=False)

        monkeypatch.setattr(pa, "_CRIME_RAW_PATH",      raw_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_cache)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_cache)

        type_df, _ = pa._build_crime_cache()
        assert type_df["count_recent"].dtype in (int, "int64", "int32")
        assert type_df["count_prior"].dtype  in (int, "int64", "int32")


# ── _load_crime_breakdown ─────────────────────────────────────────────────────

class TestLoadCrimeBreakdown:
    def _make_type_cache(self, tmp_path: "Path") -> "Path":
        df = pd.DataFrame([
            {"zip": "78239", "category": "Theft & Burglary", "count_recent": 50, "count_prior": 60},
            {"zip": "78239", "category": "Assault & Violence", "count_recent": 30, "count_prior": 25},
            {"zip": "78239", "category": "Robbery",            "count_recent": 10, "count_prior": 8},
            {"zip": "78209", "category": "Theft & Burglary",   "count_recent": 80, "count_prior": 70},
        ])
        path = tmp_path / "crime_type.csv"
        df.to_csv(path, index=False)
        return path

    def _make_weekday_cache(self, tmp_path: "Path") -> "Path":
        df = pd.DataFrame([
            {"zip": "78239", "Weekday": "Monday",    "count": 10},
            {"zip": "78239", "Weekday": "Friday",    "count": 25},
            {"zip": "78239", "Weekday": "Wednesday", "count": 5},
        ])
        path = tmp_path / "crime_weekday.csv"
        df.to_csv(path, index=False)
        return path

    def test_returns_none_when_both_caches_missing_and_no_raw(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    tmp_path / "missing_type.csv")
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", tmp_path / "missing_weekday.csv")
        monkeypatch.setattr(pa, "_CRIME_RAW_PATH",      tmp_path / "missing_raw.csv")
        result = pa._load_crime_breakdown("78239")
        assert result is None

    def test_returns_none_for_zip_not_in_cache(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("99999")
        assert result is None

    def test_returns_dict_for_known_zip(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        assert result is not None
        assert isinstance(result, dict)

    def test_total_recent_is_sum_of_categories(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        assert result["total_recent"] == 50 + 30 + 10

    def test_total_prior_is_sum_of_prior_counts(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        assert result["total_prior"] == 60 + 25 + 8

    def test_categories_sorted_by_count_descending(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        counts = [c["count"] for c in result["categories"]]
        assert counts == sorted(counts, reverse=True)

    def test_category_pct_sums_to_100(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        total_pct = sum(c["pct"] for c in result["categories"])
        assert total_pct == pytest.approx(100.0, abs=0.1)

    def test_trend_pct_computed_correctly(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        # total_recent = 90, total_prior = 93
        # trend = (90 - 93) / 93 * 100 ≈ -3.23%
        expected = (90 - 93) / 93 * 100.0
        assert result["trend_pct"] == pytest.approx(expected, rel=1e-4)

    def test_trend_negative_means_improving(self, monkeypatch, tmp_path):
        """Fewer incidents this year than last year = improving (negative trend)."""
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        assert result["trend_pct"] < 0   # recent (90) < prior (93)

    def test_peak_day_is_highest_count_weekday(self, monkeypatch, tmp_path):
        type_path    = self._make_type_cache(tmp_path)
        weekday_path = self._make_weekday_cache(tmp_path)
        monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",    type_path)
        monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE", weekday_path)
        result = pa._load_crime_breakdown("78239")
        assert result["peak_day"] == "Friday"   # count=25 > Monday=10 > Wednesday=5
