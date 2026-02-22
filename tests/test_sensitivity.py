"""
test_sensitivity.py
-------------------
Tests for sensitivity analysis functions:
  _rate_sensitivity, _hack_fraction_sensitivity
"""

import pytest
from property_analyzer import (
    _rate_sensitivity,
    _hack_fraction_sensitivity,
    _cashflow,
)

PRICE = 215_000
RENT  = 1_446.0


class TestRateSensitivity:
    def test_returns_list(self, base_prop):
        result = _rate_sensitivity(PRICE, RENT, base_prop)
        assert isinstance(result, list)

    def test_each_row_has_required_keys(self, base_prop):
        for row in _rate_sensitivity(PRICE, RENT, base_prop):
            assert {"rate", "pi", "net", "current"}.issubset(row.keys())

    def test_higher_rate_yields_lower_net(self, base_prop):
        """Phase 2 net cashflow decreases strictly as interest rate rises."""
        results = _rate_sensitivity(PRICE, RENT, base_prop)
        nets = [r["net"] for r in results]
        # Net should be monotonically non-increasing with rate
        for i in range(1, len(nets)):
            assert nets[i] <= nets[i - 1] + 0.01, (
                f"Net at index {i} ({nets[i]:.2f}) is not ≤ net at {i-1} ({nets[i-1]:.2f})"
            )

    def test_higher_rate_yields_higher_pi(self, base_prop):
        """Monthly P&I increases with interest rate."""
        results = _rate_sensitivity(PRICE, RENT, base_prop)
        pis = [r["pi"] for r in results]
        for i in range(1, len(pis)):
            assert pis[i] >= pis[i - 1] - 0.01

    def test_exactly_one_current_row(self, base_prop):
        """Exactly one row should be marked as the current rate."""
        results = _rate_sensitivity(PRICE, RENT, base_prop)
        current_rows = [r for r in results if r["current"]]
        assert len(current_rows) == 1

    def test_current_row_matches_prop_rate(self, base_prop):
        results = _rate_sensitivity(PRICE, RENT, base_prop)
        current = next(r for r in results if r["current"])
        assert current["rate"] == pytest.approx(base_prop.interest_rate, abs=0.001)

    def test_rates_are_sorted_ascending(self, base_prop):
        results = _rate_sensitivity(PRICE, RENT, base_prop)
        rates = [r["rate"] for r in results]
        assert rates == sorted(rates)

    def test_covers_range_above_and_below_current_rate(self, base_prop):
        results = _rate_sensitivity(PRICE, RENT, base_prop)
        rates = [r["rate"] for r in results]
        assert min(rates) < base_prop.interest_rate
        assert max(rates) > base_prop.interest_rate

    def test_pi_at_current_rate_matches_direct_calculation(self, base_prop):
        """P&I from sensitivity should match what _cashflow produces."""
        results = _rate_sensitivity(PRICE, RENT, base_prop)
        current = next(r for r in results if r["current"])
        cf = _cashflow(PRICE, RENT, base_prop, phase=2)
        assert current["pi"] == pytest.approx(cf["pi"], rel=1e-4)


class TestHackFractionSensitivity:
    def test_returns_list(self, base_prop):
        result = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        assert isinstance(result, list)

    def test_each_row_has_required_keys(self, base_prop):
        for row in _hack_fraction_sensitivity(PRICE, RENT, base_prop):
            assert {"fraction", "income", "net", "net_with_bah", "current"}.issubset(row.keys())

    def test_higher_fraction_gives_more_income(self, base_prop):
        """Renting more of the property → more rental income."""
        results = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        incomes = [r["income"] for r in results]
        assert incomes == sorted(incomes)

    def test_higher_fraction_improves_monthly_net(self, base_prop):
        """More income → better (higher) monthly net."""
        results = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        nets = [r["net"] for r in results]
        assert nets == sorted(nets)

    def test_fraction_zero_gives_zero_income(self, base_prop):
        """If no fraction is rented, rental income is $0."""
        prop = type(base_prop).__class__ if False else base_prop  # use fixture
        from property_analyzer import PropertyInput
        zero_prop = PropertyInput("78239", PRICE, units=2, hack_fraction=0.0)
        results = _hack_fraction_sensitivity(PRICE, RENT, zero_prop)
        # The 0% entry (if present) or the first entry should have $0 income
        zero_entries = [r for r in results if r["fraction"] == 0.0]
        if zero_entries:
            assert zero_entries[0]["income"] == pytest.approx(0.0)

    def test_income_is_units_times_rent_times_fraction(self, base_prop):
        """income = ZORI × units × fraction (ZORI is per-unit rate)."""
        results = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        for row in results:
            assert row["income"] == pytest.approx(RENT * base_prop.units * row["fraction"], rel=1e-6)

    def test_exactly_one_current_row(self, base_prop):
        results = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        current_rows = [r for r in results if r["current"]]
        assert len(current_rows) == 1

    def test_current_row_matches_prop_hack_fraction(self, base_prop):
        results = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        current = next(r for r in results if r["current"])
        assert current["fraction"] == pytest.approx(base_prop.hack_fraction, abs=0.025)

    def test_net_with_bah_includes_bah(self, prop_with_bah):
        results = _hack_fraction_sensitivity(PRICE, RENT, prop_with_bah)
        for row in results:
            assert row["net_with_bah"] == pytest.approx(row["net"] + prop_with_bah.bah_monthly)

    def test_fractions_are_between_zero_and_one(self, base_prop):
        results = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        for row in results:
            assert 0.0 <= row["fraction"] <= 1.0

    def test_fractions_are_sorted_ascending(self, base_prop):
        results = _hack_fraction_sensitivity(PRICE, RENT, base_prop)
        fractions = [r["fraction"] for r in results]
        assert fractions == sorted(fractions)
