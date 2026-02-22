"""
test_analyzer.py
----------------
Integration tests for analyze_property(), _evaluate_filters(), display helpers,
and format_report(). Uses monkeypatched file paths so no real data is required.
"""

import pytest
import pandas as pd

import property_analyzer as pa
from property_analyzer import (
    PropertyInput,
    analyze_property,
    format_report,
    _evaluate_filters,
    _sign,
    _check,
    _bar,
    THRESHOLDS,
)

PRICE = 215_000
RENT  = 1_446.0


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _write_data_files(tmp_path, ranked_df, merged_df):
    """Write ranked and merged DataFrames to temp CSV files; return paths."""
    ranked_path = tmp_path / "ranked_zip_scores.csv"
    merged_path = tmp_path / "merged_zip_dataset.csv"
    ranked_df.to_csv(ranked_path, index=False)
    merged_df.to_csv(merged_path, index=False)
    return ranked_path, merged_path


def _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path):
    """Patch all data file path constants in the property_analyzer module."""
    monkeypatch.setattr(pa, "_RANKED_PATH",         ranked_path)
    monkeypatch.setattr(pa, "_MERGED_PATH",          merged_path)
    monkeypatch.setattr(pa, "_ZHVF_PATH",            tmp_path / "no_zhvf.csv")
    monkeypatch.setattr(pa, "_CRIME_TYPE_CACHE",     tmp_path / "no_type.csv")
    monkeypatch.setattr(pa, "_CRIME_WEEKDAY_CACHE",  tmp_path / "no_weekday.csv")
    monkeypatch.setattr(pa, "_CRIME_RAW_PATH",       tmp_path / "no_raw.csv")


# ── _evaluate_filters ─────────────────────────────────────────────────────────

ANNUAL_RENT = RENT * 12  # per-unit annual rent passed to _evaluate_filters


class TestEvaluateFilters:
    def test_price_ceiling_pass(self, sample_ranked_row):
        row = pd.Series(sample_ranked_row)
        filters = _evaluate_filters(row, asking_price=200_000, annual_rent=ANNUAL_RENT)
        assert filters["price_ceiling"]["pass"] is True

    def test_price_ceiling_fail(self, sample_ranked_row):
        row = pd.Series(sample_ranked_row)
        filters = _evaluate_filters(row, asking_price=500_000, annual_rent=ANNUAL_RENT)
        assert filters["price_ceiling"]["pass"] is False

    def test_yield_floor_pass(self, sample_ranked_row):
        """At $215k with $17,352/yr annual rent → 8.07% > 6.5% → pass."""
        row = pd.Series(sample_ranked_row)
        filters = _evaluate_filters(row, asking_price=215_000, annual_rent=ANNUAL_RENT)
        assert filters["yield_floor"]["pass"] is True

    def test_yield_floor_fail_at_high_price(self, sample_ranked_row):
        """At $400k with $17,352/yr annual rent → 4.34% < 6.5% → fail."""
        row = pd.Series(sample_ranked_row)
        filters = _evaluate_filters(row, asking_price=400_000, annual_rent=ANNUAL_RENT)
        assert filters["yield_floor"]["pass"] is False

    def test_yield_floor_fix_price_is_correct(self, sample_ranked_row):
        """fix_price should be exactly annual_rent / min_yield."""
        row = pd.Series(sample_ranked_row)
        filters = _evaluate_filters(row, asking_price=400_000, annual_rent=ANNUAL_RENT)
        expected = ANNUAL_RENT / THRESHOLDS["min_rent_to_price"]
        assert filters["yield_floor"]["fix_price"] == pytest.approx(expected)

    def test_owner_occ_min_pass(self, sample_ranked_row):
        row = pd.Series(sample_ranked_row)  # owner_occ_pct = 0.73
        filters = _evaluate_filters(row, asking_price=PRICE, annual_rent=ANNUAL_RENT)
        assert filters["owner_occ_min"]["pass"] is True

    def test_owner_occ_min_fail(self, sample_ranked_row):
        row = pd.Series({**sample_ranked_row, "owner_occ_pct": 0.40})
        filters = _evaluate_filters(row, asking_price=PRICE, annual_rent=ANNUAL_RENT)
        assert filters["owner_occ_min"]["pass"] is False

    def test_owner_occ_max_fail(self, sample_ranked_row):
        row = pd.Series({**sample_ranked_row, "owner_occ_pct": 0.90})
        filters = _evaluate_filters(row, asking_price=PRICE, annual_rent=ANNUAL_RENT)
        assert filters["owner_occ_max"]["pass"] is False

    def test_commute_pass(self, sample_ranked_row):
        row = pd.Series(sample_ranked_row)  # commute_minutes = 15.4
        filters = _evaluate_filters(row, asking_price=PRICE, annual_rent=ANNUAL_RENT)
        assert filters["commute"]["pass"] is True

    def test_commute_fail(self, sample_ranked_row):
        row = pd.Series({**sample_ranked_row, "commute_minutes": 45.0})
        filters = _evaluate_filters(row, asking_price=PRICE, annual_rent=ANNUAL_RENT)
        assert filters["commute"]["pass"] is False

    def test_income_pass(self, sample_ranked_row):
        row = pd.Series(sample_ranked_row)  # income = $71,721
        filters = _evaluate_filters(row, asking_price=PRICE, annual_rent=ANNUAL_RENT)
        assert filters["income"]["pass"] is True

    def test_income_fail(self, sample_ranked_row):
        row = pd.Series({**sample_ranked_row, "median_hh_income": 30_000})
        filters = _evaluate_filters(row, asking_price=PRICE, annual_rent=ANNUAL_RENT)
        assert filters["income"]["pass"] is False


# ── analyze_property ──────────────────────────────────────────────────────────

class TestAnalyzeProperty:
    def test_raises_file_not_found_when_no_data(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pa, "_RANKED_PATH", tmp_path / "no_ranked.csv")
        monkeypatch.setattr(pa, "_MERGED_PATH", tmp_path / "no_merged.csv")
        with pytest.raises(FileNotFoundError, match="pipeline data"):
            analyze_property(PropertyInput("78239", PRICE, units=2))

    def test_raises_value_error_for_unknown_zip(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        with pytest.raises(ValueError, match="not found"):
            analyze_property(PropertyInput("99999", PRICE, units=2))

    def test_returns_dict_with_required_top_level_keys(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        required = {
            "prop", "row", "in_ranked", "median_rent", "annual_rent", "gross_yield",
            "home_value", "price_delta", "price_delta_pct", "cf_p1", "cf_p2",
            "yield_targets", "breakeven_price", "pnl_scenarios", "rate_sensitivity",
            "hack_sensitivity", "filters", "scorecard", "crime_breakdown",
            "rank", "score", "total_qualifying",
        }
        assert required.issubset(result.keys())

    def test_gross_yield_calculated_correctly(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        """gross_yield = ZORI × units × 12 / asking_price (ZORI is per-unit)."""
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        expected = (result["median_rent"] * result["prop"].units * 12) / PRICE
        assert result["gross_yield"] == pytest.approx(expected)

    def test_rent_override_used_when_provided(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        override_rent = 1_800.0
        result = analyze_property(
            PropertyInput("78239", PRICE, units=2, rent_override=override_rent)
        )
        assert result["median_rent"] == pytest.approx(override_rent)

    def test_in_ranked_true_for_qualifying_zip(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        assert result["in_ranked"] is True

    def test_in_ranked_false_for_filtered_out_zip(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        """ZIP 78209 is in merged but not ranked (owner-occ fails)."""
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78209", 310_000, units=2))
        assert result["in_ranked"] is False

    def test_rank_returned_for_qualifying_zip(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        assert result["rank"] == 1

    def test_price_delta_correct(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        assert result["price_delta"] == pytest.approx(PRICE - result["home_value"])

    def test_yield_targets_cover_four_levels(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        assert set(result["yield_targets"].keys()) == {0.065, 0.070, 0.075, 0.080}

    def test_filters_dict_contains_all_expected_checks(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        expected_keys = {"price_ceiling", "yield_floor", "owner_occ_min", "owner_occ_max",
                         "commute", "income"}
        assert expected_keys.issubset(result["filters"].keys())

    def test_scorecard_contains_expected_keys(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        expected = {"filters_at_asking", "phase1_neutral", "phase1_with_bah",
                    "phase2_positive", "return_flat_pos", "return_5pct_pos", "top_ranked"}
        assert expected.issubset(result["scorecard"].keys())

    def test_crime_breakdown_none_when_no_crime_data(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        """Without crime data files, crime_breakdown should be None (graceful)."""
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        # With no crime raw/cache files, breakdown should be None
        assert result["crime_breakdown"] is None

    def test_pnl_has_flat_scenario(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        result = analyze_property(PropertyInput("78239", PRICE, units=2))
        labels = [s["label"] for s in result["pnl_scenarios"]]
        assert "Flat (0%)" in labels

    def test_room_hack_raises_without_rent_override(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        """Room-hack mode without --rent-override must raise ValueError."""
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        prop = PropertyInput("78239", PRICE, units=1, bedrooms=4, rooms_rented=3)
        with pytest.raises(ValueError, match="rooms-rented"):
            analyze_property(prop)

    def test_room_hack_succeeds_with_rent_override(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        """Room-hack mode with rent_override should complete without error."""
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        prop = PropertyInput(
            "78239", PRICE, units=1, bedrooms=4,
            rooms_rented=3, rent_override=650.0,
        )
        result = analyze_property(prop)
        assert result is not None

    def test_room_hack_annual_rent_uses_bedrooms(
        self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df
    ):
        """annual_rent = per_room × bedrooms × 12 in room-hack mode."""
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        per_room = 650.0
        bedrooms = 4
        prop = PropertyInput(
            "78239", PRICE, units=1, bedrooms=bedrooms,
            rooms_rented=3, rent_override=per_room,
        )
        result = analyze_property(prop)
        assert result["annual_rent"] == pytest.approx(per_room * bedrooms * 12)


# ── Display helpers ───────────────────────────────────────────────────────────

class TestSignHelper:
    def test_negative_value_returns_minus(self):
        assert _sign(-1.0) == "-"

    def test_positive_value_returns_plus(self):
        assert _sign(1.0) == "+"

    def test_zero_returns_plus(self):
        assert _sign(0.0) == "+"

    def test_large_negative(self):
        assert _sign(-99_999) == "-"

    def test_small_positive(self):
        assert _sign(0.001) == "+"


class TestCheckHelper:
    def test_true_returns_checkmark(self):
        assert _check(True) == "✓"

    def test_false_returns_cross(self):
        assert _check(False) == "✗"

    def test_none_returns_question(self):
        assert _check(None) == "?"


class TestBarHelper:
    def test_zero_pct_is_all_spaces(self):
        result = _bar(0, width=10)
        assert result == " " * 10

    def test_100_pct_is_all_blocks(self):
        result = _bar(100, width=10)
        assert result == "█" * 10

    def test_50_pct_is_half_blocks(self):
        result = _bar(50, width=10)
        assert result == "█" * 5 + " " * 5

    def test_output_length_always_equals_width(self):
        for pct in [0, 10, 33, 50, 75, 99, 100]:
            assert len(_bar(pct, width=20)) == 20

    def test_custom_width_respected(self):
        assert len(_bar(50, width=30)) == 30

    def test_out_of_range_pct_clamped(self):
        """Values outside 0–100 should not cause errors or wrong lengths."""
        assert len(_bar(-10, width=10)) == 10
        assert len(_bar(150, width=10)) == 10


# ── format_report ─────────────────────────────────────────────────────────────

class TestFormatReport:
    @pytest.fixture
    def analysis_result(self, monkeypatch, tmp_path, sample_ranked_df, sample_merged_df):
        ranked_path, merged_path = _write_data_files(tmp_path, sample_ranked_df, sample_merged_df)
        _patch_data_paths(monkeypatch, tmp_path, ranked_path, merged_path)
        return analyze_property(PropertyInput("78239", PRICE, units=2, bah_monthly=1_900))

    def test_returns_non_empty_string(self, analysis_result):
        report = format_report(analysis_result)
        assert isinstance(report, str)
        assert len(report) > 100

    def test_contains_all_section_headers(self, analysis_result):
        report = format_report(analysis_result)
        sections = [
            "ZIP MARKET OVERVIEW",
            "CRIME INTELLIGENCE",
            "NEGOTIATION RANGE",
            "CASHFLOW ANALYSIS",
            "3-YEAR HOLD P&L",
            "SENSITIVITY ANALYSIS",
            "FILTER STATUS",
            "DECISION SCORECARD",
        ]
        for section in sections:
            assert section in report, f"Missing section: {section}"

    def test_contains_zip_code(self, analysis_result):
        assert "78239" in format_report(analysis_result)

    def test_contains_asking_price(self, analysis_result):
        assert "215,000" in format_report(analysis_result)

    def test_negative_cashflow_shows_minus_sign(self, analysis_result):
        """The sign fix: negative monthly net should display as -$XXX not $XXX."""
        report = format_report(analysis_result)
        # Phase 1 net is negative; it should appear with a '-' sign
        assert "-$" in report

    def test_positive_cashflow_shows_plus_sign(self, analysis_result):
        """Positive values (e.g. with BAH) should show +$XXX."""
        report = format_report(analysis_result)
        assert "+$" in report

    def test_phase1_label_present(self, analysis_result):
        assert "PHASE 1" in format_report(analysis_result)

    def test_phase2_label_present(self, analysis_result):
        assert "PHASE 2" in format_report(analysis_result)

    def test_verdict_present(self, analysis_result):
        assert "VERDICT" in format_report(analysis_result)

    def test_filter_pass_present(self, analysis_result):
        assert "PASS" in format_report(analysis_result)
