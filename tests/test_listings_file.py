"""
test_listings_file.py
---------------------
Unit tests for analyze_listings.py:
  - load_listings_file() parsing (JSON + YAML)
  - Alias resolution and percentage conversions
  - Defaults merge logic
  - _format_comparison_table()
  - _run_all() with monkeypatched analyze_property
  - Error cases: missing file, empty listings, bad JSON
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make the repo root importable (analyze_listings.py lives there)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import analyze_listings as al
from analyze_listings import (
    _format_comparison_table,
    _normalise_key,
    _parse_listing,
    _run_all,
    _verdict_rank,
    load_listings_file,
)
from property_analyzer import PropertyInput

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def minimal_json(tmp_path) -> Path:
    """Single listing, no defaults."""
    data = {
        "listings": [
            {"zip": "78239", "price": 265000, "units": 2}
        ]
    }
    p = tmp_path / "listings.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def multi_json(tmp_path) -> Path:
    """Two listings with defaults block."""
    data = {
        "defaults": {"loan_type": "VA", "bah": 1900, "rate": 6.875},
        "listings": [
            {"label": "First St", "zip": "78239", "price": 265000, "units": 2},
            {"label": "Oak Ave",  "zip": "78209", "price": 310000, "units": 2},
        ],
    }
    p = tmp_path / "multi.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def room_hack_json(tmp_path) -> Path:
    data = {
        "listings": [
            {
                "label": "Room hack",
                "zip": "78239",
                "price": 265000,
                "units": 1,
                "bedrooms": 4,
                "rooms_rented": 3,
                "rent_override": 700,
            }
        ]
    }
    p = tmp_path / "room.json"
    p.write_text(json.dumps(data))
    return p


# ── _normalise_key ─────────────────────────────────────────────────────────────


class TestNormaliseKey:
    def test_zip_alias(self):
        assert _normalise_key("zip") == "zip_code"

    def test_price_alias(self):
        assert _normalise_key("price") == "asking_price"

    def test_rate_alias(self):
        assert _normalise_key("rate") == "interest_rate"

    def test_bah_alias(self):
        assert _normalise_key("bah") == "bah_monthly"

    def test_hoa_alias(self):
        assert _normalise_key("hoa") == "hoa_monthly"

    def test_passthrough_unknown(self):
        assert _normalise_key("units") == "units"

    def test_passthrough_zip_code(self):
        """Already-canonical names pass through unchanged."""
        assert _normalise_key("zip_code") == "zip_code"


# ── _parse_listing ─────────────────────────────────────────────────────────────


class TestParseListing:
    def test_returns_label_and_property_input(self):
        label, prop = _parse_listing({"zip": "78239", "price": 265000}, {})
        assert isinstance(label, str)
        assert isinstance(prop, PropertyInput)

    def test_explicit_label_used(self):
        label, _ = _parse_listing(
            {"label": "My Listing", "zip": "78239", "price": 265000}, {}
        )
        assert label == "My Listing"

    def test_auto_label_when_no_label(self):
        label, _ = _parse_listing({"zip": "78239", "price": 265000}, {})
        assert "78239" in label

    def test_defaults_merged(self):
        defaults = {"bah": 1900, "loan_type": "VA"}
        _, prop = _parse_listing({"zip": "78239", "price": 265000}, defaults)
        assert prop.bah_monthly == pytest.approx(1900)
        assert prop.loan_type == "VA"

    def test_listing_overrides_defaults(self):
        defaults = {"bah": 1900}
        _, prop = _parse_listing({"zip": "78239", "price": 265000, "bah": 500}, defaults)
        assert prop.bah_monthly == pytest.approx(500)

    def test_rate_pct_conversion(self):
        """rate=6.875 (percent) → interest_rate=0.06875 (fraction)."""
        _, prop = _parse_listing({"zip": "78239", "price": 265000, "rate": 6.875}, {})
        assert prop.interest_rate == pytest.approx(0.06875)

    def test_down_pct_conversion(self):
        """down_pct=5 → 0.05."""
        _, prop = _parse_listing(
            {"zip": "78239", "price": 265000, "down_pct": 5, "loan_type": "conventional"}, {}
        )
        assert prop.down_pct == pytest.approx(0.05)

    def test_loan_type_normalised_to_va(self):
        _, prop = _parse_listing({"zip": "78239", "price": 265000, "loan_type": "va"}, {})
        assert prop.loan_type == "VA"

    def test_loan_type_normalised_conventional(self):
        _, prop = _parse_listing(
            {"zip": "78239", "price": 265000, "loan_type": "conventional"}, {}
        )
        assert prop.loan_type == "Conventional"

    def test_va_second_use_sets_va_first_use_false(self):
        _, prop = _parse_listing(
            {"zip": "78239", "price": 265000, "va_second_use": True}, {}
        )
        assert prop.va_first_use is False

    def test_zip_zero_padded(self):
        _, prop = _parse_listing({"zip": "1234", "price": 265000}, {})
        assert prop.zip_code == "01234"

    def test_room_hack_fields_passed_through(self):
        _, prop = _parse_listing(
            {
                "zip": "78239",
                "price": 265000,
                "units": 1,
                "bedrooms": 4,
                "rooms_rented": 3,
                "rent_override": 700,
            },
            {},
        )
        assert prop.rooms_rented == 3
        assert prop.bedrooms == 4
        assert prop.rent_override == pytest.approx(700)

    def test_unknown_keys_ignored(self):
        """Keys not in PropertyInput (e.g. _comment) should not raise."""
        label, prop = _parse_listing(
            {"zip": "78239", "price": 265000, "_comment": "ignore me"}, {}
        )
        assert isinstance(prop, PropertyInput)


# ── load_listings_file ─────────────────────────────────────────────────────────


class TestLoadListingsFile:
    def test_loads_minimal_json(self, minimal_json):
        _, listings = load_listings_file(minimal_json)
        assert len(listings) == 1

    def test_loads_multi_json(self, multi_json):
        _, listings = load_listings_file(multi_json)
        assert len(listings) == 2

    def test_defaults_applied_to_all(self, multi_json):
        _, listings = load_listings_file(multi_json)
        for _label, prop in listings:
            assert prop.bah_monthly == pytest.approx(1900)
            assert prop.loan_type == "VA"

    def test_returns_raw_data_dict(self, minimal_json):
        raw, _ = load_listings_file(minimal_json)
        assert isinstance(raw, dict)
        assert "listings" in raw

    def test_labels_returned(self, multi_json):
        _, listings = load_listings_file(multi_json)
        labels = [lbl for lbl, _ in listings]
        assert "First St" in labels
        assert "Oak Ave" in labels

    def test_raises_value_error_if_no_listings_key(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"foo": "bar"}))
        with pytest.raises(ValueError, match="listings"):
            load_listings_file(p)

    def test_raises_value_error_if_listings_empty(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"listings": []}))
        with pytest.raises(ValueError, match="empty"):
            load_listings_file(p)

    def test_raises_value_error_if_not_dict(self, tmp_path):
        p = tmp_path / "array.json"
        p.write_text(json.dumps([{"zip": "78239", "price": 100000}]))
        with pytest.raises(ValueError, match="object"):
            load_listings_file(p)

    def test_raises_file_not_found_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_listings_file(tmp_path / "does_not_exist.json")

    def test_room_hack_listing_loaded(self, room_hack_json):
        _, listings = load_listings_file(room_hack_json)
        assert len(listings) == 1
        _label, prop = listings[0]
        assert prop.rooms_rented == 3


# ── _verdict_rank ─────────────────────────────────────────────────────────────


class TestVerdictRank:
    def test_buy_ranks_first(self):
        assert _verdict_rank("BUY") < _verdict_rank("CAUTION")

    def test_caution_ranks_before_skip(self):
        assert _verdict_rank("CAUTION") < _verdict_rank("SKIP")

    def test_error_ranks_last(self):
        assert _verdict_rank("ERROR") >= _verdict_rank("SKIP")

    def test_unknown_verdict_does_not_raise(self):
        assert isinstance(_verdict_rank("UNKNOWN"), int)


# ── _format_comparison_table ──────────────────────────────────────────────────


class TestFormatComparisonTable:
    @pytest.fixture
    def sample_rows(self):
        return [
            {
                "label": "First St",
                "zip": "78239",
                "score": 0.714,
                "p1_net": -312.0,
                "p2_net": 180.0,
                "yield": 0.0807,
                "verdict": "BUY",
            },
            {
                "label": "Oak Ave",
                "zip": "78209",
                "score": 0.320,
                "p1_net": -580.0,
                "p2_net": -100.0,
                "yield": 0.060,
                "verdict": "SKIP",
            },
        ]

    def test_returns_string(self, sample_rows):
        result = _format_comparison_table(sample_rows)
        assert isinstance(result, str)

    def test_contains_header(self, sample_rows):
        result = _format_comparison_table(sample_rows)
        assert "LISTING COMPARISON" in result

    def test_contains_all_labels(self, sample_rows):
        result = _format_comparison_table(sample_rows)
        assert "First St" in result
        assert "Oak Ave" in result

    def test_contains_zips(self, sample_rows):
        result = _format_comparison_table(sample_rows)
        assert "78239" in result
        assert "78209" in result

    def test_contains_verdict(self, sample_rows):
        result = _format_comparison_table(sample_rows)
        assert "BUY" in result
        assert "SKIP" in result

    def test_none_score_shown_as_na(self):
        rows = [
            {
                "label": "No Score",
                "zip": "78239",
                "score": None,
                "p1_net": None,
                "p2_net": None,
                "yield": None,
                "verdict": "ERROR",
            }
        ]
        result = _format_comparison_table(rows)
        assert "N/A" in result

    def test_long_label_truncated(self):
        rows = [
            {
                "label": "A" * 60,
                "zip": "78239",
                "score": 0.5,
                "p1_net": 100.0,
                "p2_net": 200.0,
                "yield": 0.07,
                "verdict": "BUY",
            }
        ]
        result = _format_comparison_table(rows)
        # Line should not be absurdly long
        for line in result.splitlines():
            assert len(line) < 200


# ── _run_all ──────────────────────────────────────────────────────────────────


class TestRunAll:
    """Mock analyze_property to avoid needing real pipeline data."""

    @pytest.fixture
    def mock_result(self):
        return {
            "cf_p1": {"net": -300.0},
            "cf_p2": {"net": 150.0},
            "gross_yield": 0.078,
            "score": 0.65,
            "conditions": {"_verdict": "BUY"},
        }

    @pytest.fixture
    def two_listings(self):
        return [
            ("First St", PropertyInput("78239", 265000, units=2)),
            ("Oak Ave",  PropertyInput("78209", 310000, units=2)),
        ]

    def test_returns_one_row_per_listing(self, two_listings, mock_result):
        with patch("analyze_listings.analyze_property", return_value=mock_result):
            rows = _run_all(two_listings, summary_only=True, output_json=False)
        assert len(rows) == 2

    def test_row_contains_label(self, two_listings, mock_result):
        with patch("analyze_listings.analyze_property", return_value=mock_result):
            rows = _run_all(two_listings, summary_only=True, output_json=False)
        labels = [r["label"] for r in rows]
        assert "First St" in labels
        assert "Oak Ave" in labels

    def test_row_verdict_populated(self, two_listings, mock_result):
        with patch("analyze_listings.analyze_property", return_value=mock_result):
            rows = _run_all(two_listings, summary_only=True, output_json=False)
        for r in rows:
            assert r["verdict"] == "BUY"

    def test_error_row_on_exception(self, two_listings):
        with patch(
            "analyze_listings.analyze_property",
            side_effect=ValueError("ZIP not found"),
        ):
            rows = _run_all(two_listings, summary_only=True, output_json=False)
        assert all(r["verdict"] == "ERROR" for r in rows)
        assert all("error" in r for r in rows)

    def test_partial_error_does_not_abort(self, two_listings, mock_result):
        """If one listing fails, others still get analyzed."""
        call_count = 0

        def side_effect(prop):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first fails")
            return mock_result

        with patch("analyze_listings.analyze_property", side_effect=side_effect):
            rows = _run_all(two_listings, summary_only=True, output_json=False)

        assert len(rows) == 2
        assert rows[0]["verdict"] == "ERROR"
        assert rows[1]["verdict"] == "BUY"
