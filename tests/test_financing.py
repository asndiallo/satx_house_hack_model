"""
test_financing.py
-----------------
Tests for mortgage/loan helpers and cost components:
  _loan_amount, _monthly_pi, _remaining_balance, _pmi_monthly,
  _fixed_costs, _variable_costs
"""

import pytest
from property_analyzer import (
    PropertyInput,
    _loan_amount,
    _monthly_pi,
    _remaining_balance,
    _pmi_monthly,
    _fixed_costs,
    _variable_costs,
    _VA_FEE_FIRST,
    _VA_FEE_SUBSEQ,
    _HOMESTEAD_EX,
    _PMI_ANNUAL,
)


# ── _loan_amount ───────────────────────────────────────────────────────────────

class TestLoanAmount:
    def test_va_first_use_zero_down_rolls_fee_into_loan(self, base_prop):
        expected = 215_000 * (1 + _VA_FEE_FIRST)
        assert _loan_amount(215_000, base_prop) == pytest.approx(expected)

    def test_va_subsequent_use_applies_higher_fee(self):
        prop = PropertyInput("78239", 200_000, units=2, va_first_use=False)
        expected = 200_000 * (1 + _VA_FEE_SUBSEQ)
        assert _loan_amount(200_000, prop) == pytest.approx(expected)

    def test_va_zero_down_loan_exceeds_purchase_price(self, base_prop):
        assert _loan_amount(215_000, base_prop) > 215_000

    def test_va_with_down_payment(self):
        prop = PropertyInput("78239", 200_000, units=2, down_pct=0.10)
        base = 200_000 * 0.90   # 10% down
        expected = base * (1 + _VA_FEE_FIRST)
        assert _loan_amount(200_000, prop) == pytest.approx(expected)

    def test_conventional_zero_down_equals_price(self):
        prop = PropertyInput("78239", 200_000, units=2, loan_type="Conventional", down_pct=0.0)
        assert _loan_amount(200_000, prop) == pytest.approx(200_000)

    def test_conventional_20pct_down(self, conventional_prop):
        assert _loan_amount(200_000, conventional_prop) == pytest.approx(160_000)

    def test_conventional_5pct_down(self, conventional_low_down_prop):
        assert _loan_amount(200_000, conventional_low_down_prop) == pytest.approx(190_000)

    @pytest.mark.parametrize("price", [100_000, 200_000, 300_000, 450_000])
    def test_loan_scales_linearly_with_price(self, price):
        """VA first-use 0% down: loan = price × (1 + fee)."""
        prop = PropertyInput("78239", price, units=2)
        assert _loan_amount(price, prop) == pytest.approx(price * (1 + _VA_FEE_FIRST))


# ── _monthly_pi ───────────────────────────────────────────────────────────────

class TestMonthlyPI:
    def test_zero_rate_equals_loan_divided_by_months(self):
        loan = 200_000
        pi = _monthly_pi(loan, rate=0.0, term_years=30)
        assert pi == pytest.approx(loan / 360)

    def test_positive_rate_increases_payment_vs_zero_rate(self):
        loan = 200_000
        assert _monthly_pi(loan, 0.06875, 30) > _monthly_pi(loan, 0.0, 30)

    def test_higher_rate_means_higher_payment(self):
        loan = 200_000
        assert _monthly_pi(loan, 0.08, 30) > _monthly_pi(loan, 0.05, 30)

    def test_longer_term_means_lower_payment(self):
        loan = 200_000
        assert _monthly_pi(loan, 0.06875, 15) > _monthly_pi(loan, 0.06875, 30)

    def test_payment_is_always_positive(self):
        assert _monthly_pi(200_000, 0.06875, 30) > 0

    def test_total_payments_exceed_principal_due_to_interest(self):
        loan = 200_000
        pi = _monthly_pi(loan, 0.06875, 30)
        assert pi * 360 > loan

    @pytest.mark.parametrize("rate", [0.04, 0.06, 0.07, 0.08, 0.09])
    def test_payment_monotone_in_rate(self, rate):
        """Monthly payment increases strictly with interest rate."""
        loan = 200_000
        pi_low  = _monthly_pi(loan, rate - 0.005, 30)
        pi_high = _monthly_pi(loan, rate + 0.005, 30)
        assert pi_high > pi_low

    def test_zero_loan_gives_zero_payment(self):
        assert _monthly_pi(0, 0.06875, 30) == pytest.approx(0.0)


# ── _remaining_balance ────────────────────────────────────────────────────────

class TestRemainingBalance:
    def test_zero_years_equals_original_loan(self):
        loan = 200_000
        assert _remaining_balance(loan, 0.06875, 30, years_paid=0) == pytest.approx(loan)

    def test_full_term_balance_is_effectively_zero(self):
        loan = 200_000
        rem = _remaining_balance(loan, 0.06875, 30, years_paid=30)
        assert abs(rem) < 1.0   # floating-point near-zero

    def test_balance_decreases_monotonically(self):
        loan = 200_000
        balances = [_remaining_balance(loan, 0.06875, 30, y) for y in [0, 3, 5, 10, 20, 30]]
        assert balances == sorted(balances, reverse=True)

    def test_zero_rate_amortizes_linearly(self):
        """At 0% interest, half the loan is gone after half the term."""
        loan = 120_000
        rem = _remaining_balance(loan, 0.0, 10, years_paid=5)
        assert rem == pytest.approx(60_000)

    def test_early_years_mostly_interest_little_principal(self):
        """VA 0% down at 6.875% — very little principal paid in first 3 years."""
        loan = 200_000
        principal_paid = loan - _remaining_balance(loan, 0.06875, 30, years_paid=3)
        assert principal_paid < loan * 0.05   # < 5% paid down in 3 years

    @pytest.mark.parametrize("years", [1, 5, 10, 15])
    def test_balance_is_always_non_negative(self, years):
        rem = _remaining_balance(200_000, 0.06875, 30, years)
        assert rem >= 0


# ── _pmi_monthly ──────────────────────────────────────────────────────────────

class TestPMIMonthly:
    def test_va_loan_never_has_pmi(self, base_prop):
        # Regardless of LTV
        assert _pmi_monthly(215_000, 215_000, base_prop) == 0.0

    def test_va_loan_pmi_zero_even_at_100pct_ltv(self, base_prop):
        price = 200_000
        loan  = 210_000   # > price (VA fee rolled in)
        assert _pmi_monthly(price, loan, base_prop) == 0.0

    def test_conventional_high_ltv_triggers_pmi(self, conventional_low_down_prop):
        price = 200_000
        loan  = price * 0.95   # 95% LTV
        pmi = _pmi_monthly(price, loan, conventional_low_down_prop)
        assert pmi > 0

    def test_conventional_80pct_ltv_no_pmi(self, conventional_prop):
        price = 200_000
        loan  = price * 0.80
        assert _pmi_monthly(price, loan, conventional_prop) == 0.0

    def test_conventional_pmi_amount_is_reasonable(self, conventional_low_down_prop):
        """PMI should be ~ loan × PMI_rate / 12."""
        price = 200_000
        loan  = 190_000
        expected = loan * _PMI_ANNUAL / 12
        assert _pmi_monthly(price, loan, conventional_low_down_prop) == pytest.approx(expected)

    def test_conventional_pmi_drops_at_80pct_ltv_boundary(self):
        """Just below and just above 80% LTV."""
        prop  = PropertyInput("78239", 200_000, units=2, loan_type="Conventional")
        price = 200_000
        assert _pmi_monthly(price, price * 0.800, prop) == 0.0
        assert _pmi_monthly(price, price * 0.801, prop) > 0


# ── _fixed_costs ──────────────────────────────────────────────────────────────

class TestFixedCosts:
    def test_homestead_reduces_tax_base(self, base_prop):
        price  = 215_000
        no_hs  = _fixed_costs(price, base_prop, homestead=False)
        with_hs = _fixed_costs(price, base_prop, homestead=True)
        assert with_hs["property_tax"] < no_hs["property_tax"]

    def test_homestead_exempts_first_100k(self, base_prop):
        price = 215_000
        costs = _fixed_costs(price, base_prop, homestead=True)
        taxable = max(0, price - _HOMESTEAD_EX)
        expected_tax = taxable * base_prop.property_tax_pct / 12
        assert costs["property_tax"] == pytest.approx(expected_tax)

    def test_no_homestead_taxes_full_price(self, base_prop):
        price = 215_000
        costs = _fixed_costs(price, base_prop, homestead=False)
        expected_tax = price * base_prop.property_tax_pct / 12
        assert costs["property_tax"] == pytest.approx(expected_tax)

    def test_price_below_homestead_exemption_gives_zero_tax(self, base_prop):
        """Property worth less than $100k → fully exempt → $0 tax."""
        price = 80_000
        costs = _fixed_costs(price, base_prop, homestead=True)
        assert costs["property_tax"] == pytest.approx(0.0)

    def test_insurance_scales_with_price(self, base_prop):
        costs_low  = _fixed_costs(100_000, base_prop)
        costs_high = _fixed_costs(300_000, base_prop)
        assert costs_high["insurance"] > costs_low["insurance"]

    def test_hoa_included_in_fixed_costs(self, high_hoa_prop):
        costs = _fixed_costs(215_000, high_hoa_prop)
        assert costs["hoa"] == pytest.approx(high_hoa_prop.hoa_monthly)

    def test_no_hoa_is_zero(self, base_prop):
        costs = _fixed_costs(215_000, base_prop)
        assert costs["hoa"] == 0.0

    def test_all_components_are_non_negative(self, base_prop):
        costs = _fixed_costs(215_000, base_prop, homestead=True)
        for key, val in costs.items():
            assert val >= 0, f"{key} is negative"


# ── _variable_costs ───────────────────────────────────────────────────────────

class TestVariableCosts:
    def test_vacancy_is_pct_of_gross_rent(self, base_prop):
        gross_rent = 1_000.0
        costs = _variable_costs(gross_rent, mgmt_fee=0.0, prop=base_prop)
        assert costs["vacancy"] == pytest.approx(gross_rent * base_prop.vacancy_rate)

    def test_maintenance_is_pct_of_gross_rent(self, base_prop):
        gross_rent = 1_000.0
        costs = _variable_costs(gross_rent, mgmt_fee=0.0, prop=base_prop)
        assert costs["maintenance"] == pytest.approx(gross_rent * base_prop.maintenance_pct)

    def test_management_fee_zero_when_self_managing(self, base_prop):
        gross_rent = 1_000.0
        costs = _variable_costs(gross_rent, mgmt_fee=0.0, prop=base_prop)
        assert costs["management"] == pytest.approx(0.0)

    def test_management_fee_applied_correctly(self, base_prop):
        gross_rent = 1_000.0
        mgmt = 0.08
        costs = _variable_costs(gross_rent, mgmt_fee=mgmt, prop=base_prop)
        assert costs["management"] == pytest.approx(gross_rent * mgmt)

    def test_zero_rent_gives_zero_variable_costs(self, base_prop):
        costs = _variable_costs(0.0, mgmt_fee=0.08, prop=base_prop)
        for val in costs.values():
            assert val == pytest.approx(0.0)

    def test_all_components_scale_linearly_with_rent(self, base_prop):
        """Doubling rent should double all variable costs."""
        costs_base   = _variable_costs(1_000, mgmt_fee=0.08, prop=base_prop)
        costs_double = _variable_costs(2_000, mgmt_fee=0.08, prop=base_prop)
        for key in costs_base:
            assert costs_double[key] == pytest.approx(costs_base[key] * 2)
