"""
test_negotiation.py
-------------------
Tests for negotiation helpers and 3-year P&L scenarios:
  _max_price_for_yield, _breakeven_price_phase1, _three_year_pnl
"""

import pytest
from property_analyzer import (
    PropertyInput,
    _max_price_for_yield,
    _breakeven_price_phase1,
    _cashflow,
    _three_year_pnl,
    _APPRECIATION_SCENARIOS,
)

PRICE  = 215_000
RENT   = 1_446.0


# ── _max_price_for_yield ──────────────────────────────────────────────────────

class TestMaxPriceForYield:
    def test_basic_formula(self):
        """price = annual_rent / target_yield."""
        annual_rent = 17_400
        assert _max_price_for_yield(0.065, annual_rent) == pytest.approx(annual_rent / 0.065)

    def test_higher_yield_target_means_lower_max_price(self):
        annual_rent = 17_400
        p_low  = _max_price_for_yield(0.065, annual_rent)
        p_high = _max_price_for_yield(0.080, annual_rent)
        assert p_low > p_high

    def test_higher_rent_means_higher_max_price(self):
        p_low  = _max_price_for_yield(0.065, 12_000)
        p_high = _max_price_for_yield(0.065, 18_000)
        assert p_high > p_low

    @pytest.mark.parametrize("target_yield", [0.065, 0.070, 0.075, 0.080])
    def test_implied_yield_at_max_price_equals_target(self, target_yield):
        """gross_yield at max_price must equal target_yield."""
        annual_rent = 17_400
        max_price = _max_price_for_yield(target_yield, annual_rent)
        implied_yield = annual_rent / max_price
        assert implied_yield == pytest.approx(target_yield, rel=1e-6)

    def test_known_value_6_5pct(self):
        """$1,446/mo rent → annual $17,352 → max at 6.5% = $266,954 (approx)."""
        annual_rent = RENT * 12
        result = _max_price_for_yield(0.065, annual_rent)
        assert result == pytest.approx(annual_rent / 0.065, rel=1e-6)


# ── _breakeven_price_phase1 ───────────────────────────────────────────────────

class TestBreakevenPrice:
    def test_at_breakeven_price_net_is_near_zero(self, base_prop):
        """Core invariant: net monthly cashflow at breakeven price ≈ $0."""
        bp = _breakeven_price_phase1(RENT, base_prop)
        cf = _cashflow(bp, RENT, base_prop, phase=1)
        assert abs(cf["net"]) < 1.0   # within $1

    def test_below_breakeven_is_cash_positive(self, base_prop):
        bp = _breakeven_price_phase1(RENT, base_prop)
        cf_below = _cashflow(bp * 0.9, RENT, base_prop, phase=1)
        assert cf_below["net"] > 0

    def test_above_breakeven_is_cash_negative(self, base_prop):
        bp = _breakeven_price_phase1(RENT, base_prop)
        cf_above = _cashflow(bp * 1.1, RENT, base_prop, phase=1)
        assert cf_above["net"] < 0

    def test_higher_rent_raises_breakeven_price(self, base_prop):
        """Higher rent → tenants can cover a higher-priced property."""
        bp_low  = _breakeven_price_phase1(1_000, base_prop)
        bp_high = _breakeven_price_phase1(2_000, base_prop)
        assert bp_high > bp_low

    def test_higher_rate_lowers_breakeven_price(self):
        """Higher rate → more expensive mortgage → need lower price to break even."""
        prop_low  = PropertyInput("78239", PRICE, units=2, interest_rate=0.05)
        prop_high = PropertyInput("78239", PRICE, units=2, interest_rate=0.08)
        bp_low  = _breakeven_price_phase1(RENT, prop_low)
        bp_high = _breakeven_price_phase1(RENT, prop_high)
        assert bp_low > bp_high

    def test_zero_hack_fraction_returns_zero(self):
        """No rental income → can't break even at any price via rental income."""
        prop = PropertyInput("78239", PRICE, units=1, hack_fraction=0.0)
        assert _breakeven_price_phase1(RENT, prop) == 0.0

    def test_full_hack_fraction_raises_breakeven(self, base_prop):
        """100% rented → more income → can support higher price."""
        prop_full = PropertyInput("78239", PRICE, units=2, hack_fraction=1.0)
        bp_half = _breakeven_price_phase1(RENT, base_prop)
        bp_full = _breakeven_price_phase1(RENT, prop_full)
        assert bp_full > bp_half

    def test_convergence_is_tight(self, base_prop):
        """Binary search should converge to within $1 in 60 iterations."""
        bp = _breakeven_price_phase1(RENT, base_prop)
        cf = _cashflow(bp, RENT, base_prop, phase=1)
        assert abs(cf["net"]) < 0.5   # within 50 cents


# ── _three_year_pnl ───────────────────────────────────────────────────────────

class TestThreeYearPnl:
    def test_returns_list_of_dicts(self, base_prop):
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        assert isinstance(scenarios, list)
        assert len(scenarios) >= len(_APPRECIATION_SCENARIOS)

    def test_required_keys_in_each_scenario(self, base_prop):
        required = {"label", "ann_pct", "exit_price", "selling_costs",
                    "rem_balance", "net_proceeds", "total_return",
                    "principal", "cum_cf", "down_paid"}
        for scenario in _three_year_pnl(PRICE, RENT, base_prop):
            assert required.issubset(scenario.keys())

    def test_exit_price_increases_with_appreciation(self, base_prop):
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        # Ignore ZHVF scenario if present; sort the fixed scenarios by ann_pct
        fixed = [s for s in scenarios if s["label"] != "ZHVF fcst"]
        exit_prices = [s["exit_price"] for s in fixed]
        assert exit_prices == sorted(exit_prices)

    def test_total_return_increases_with_appreciation(self, base_prop):
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        fixed = [s for s in scenarios if s["label"] != "ZHVF fcst"]
        returns = [s["total_return"] for s in fixed]
        assert returns == sorted(returns)

    def test_zero_down_means_zero_down_paid(self, base_prop):
        """VA 0% down: down_paid should be $0."""
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        for s in scenarios:
            assert s["down_paid"] == pytest.approx(0.0)

    def test_down_payment_correct_for_conventional(self, conventional_prop):
        """20% down on $200k → down_paid = $40k."""
        scenarios = _three_year_pnl(200_000, RENT, conventional_prop)
        for s in scenarios:
            assert s["down_paid"] == pytest.approx(40_000)

    def test_flat_exit_price_equals_purchase_price(self, base_prop):
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        flat = next(s for s in scenarios if s["ann_pct"] == 0.0)
        assert flat["exit_price"] == pytest.approx(PRICE)

    def test_selling_costs_are_pct_of_exit_price(self, base_prop):
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        for s in scenarios:
            expected_selling = s["exit_price"] * base_prop.selling_cost_pct
            assert s["selling_costs"] == pytest.approx(expected_selling, rel=1e-6)

    def test_cumulative_cashflow_equals_monthly_times_months(self, base_prop):
        """cum_cf = monthly_net × hold_years × 12."""
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        cf1 = _cashflow(PRICE, RENT, base_prop, phase=1)
        expected_cum = cf1["net"] * base_prop.hold_years * 12
        for s in scenarios:
            assert s["cum_cf"] == pytest.approx(expected_cum)

    def test_zhvf_scenario_added_when_provided(self, base_prop):
        """When zhvf_12mo is provided, the first scenario should be ZHVF."""
        scenarios = _three_year_pnl(PRICE, RENT, base_prop, zhvf_12mo=-0.019)
        assert scenarios[0]["label"] == "ZHVF fcst"

    def test_no_zhvf_scenario_when_not_provided(self, base_prop):
        scenarios = _three_year_pnl(PRICE, RENT, base_prop, zhvf_12mo=None)
        labels = [s["label"] for s in scenarios]
        assert "ZHVF fcst" not in labels

    def test_principal_paid_is_positive_non_zero(self, base_prop):
        """Some principal is always paid in 3 years (even tiny amount)."""
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        for s in scenarios:
            assert s["principal"] > 0

    def test_net_proceeds_is_exit_minus_selling_costs_minus_loan(self, base_prop):
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        for s in scenarios:
            expected = s["exit_price"] - s["selling_costs"] - s["rem_balance"]
            assert s["net_proceeds"] == pytest.approx(expected)

    def test_total_return_formula(self, base_prop):
        """total_return = net_proceeds + cum_cf - down_paid."""
        scenarios = _three_year_pnl(PRICE, RENT, base_prop)
        for s in scenarios:
            expected = s["net_proceeds"] + s["cum_cf"] - s["down_paid"]
            assert s["total_return"] == pytest.approx(expected)
