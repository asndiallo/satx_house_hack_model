"""
test_cashflow.py
----------------
Tests for _cashflow (Phase 1 & Phase 2) and net-with-BAH calculations.
"""

import pytest
from property_analyzer import PropertyInput, _cashflow, _loan_amount, _monthly_pi


PRICE  = 215_000
RENT   = 1_446.0


class TestPhase1Cashflow:
    def test_gross_rent_is_rent_times_units_times_hack_fraction(self, base_prop):
        """ZORI is per-unit: Phase 1 income = ZORI × units × hack_fraction."""
        cf = _cashflow(PRICE, RENT, base_prop, phase=1)
        assert cf["gross_rent"] == pytest.approx(RENT * base_prop.units * base_prop.hack_fraction)

    def test_net_equals_income_minus_expense(self, base_prop):
        cf = _cashflow(PRICE, RENT, base_prop, phase=1)
        assert cf["net"] == pytest.approx(cf["gross_rent"] - cf["total_expense"])

    def test_homestead_exemption_applied_in_phase1(self, base_prop):
        """Phase 1 tax should be less than Phase 2 (homestead reduces taxable base)."""
        cf1 = _cashflow(PRICE, RENT, base_prop, phase=1)
        cf2 = _cashflow(PRICE, RENT, base_prop, phase=2)
        assert cf1["fixed"]["property_tax"] < cf2["fixed"]["property_tax"]

    def test_management_fee_is_zero_in_phase1(self, base_prop):
        """Phase 1 uses mgmt_fee_phase1 which defaults to 0%."""
        cf = _cashflow(PRICE, RENT, base_prop, phase=1)
        assert cf["variable"]["management"] == pytest.approx(0.0)

    def test_loan_amount_in_output(self, base_prop):
        cf = _cashflow(PRICE, RENT, base_prop, phase=1)
        expected_loan = _loan_amount(PRICE, base_prop)
        assert cf["loan_amount"] == pytest.approx(expected_loan)

    def test_pi_in_output(self, base_prop):
        cf = _cashflow(PRICE, RENT, base_prop, phase=1)
        loan = _loan_amount(PRICE, base_prop)
        expected_pi = _monthly_pi(loan, base_prop.interest_rate, base_prop.loan_term_years)
        assert cf["pi"] == pytest.approx(expected_pi)

    def test_net_with_bah_includes_bah(self, prop_with_bah):
        cf = _cashflow(PRICE, RENT, prop_with_bah, phase=1)
        assert cf["net_with_bah"] == pytest.approx(cf["net"] + prop_with_bah.bah_monthly)

    def test_bah_zero_means_net_with_bah_equals_net(self, base_prop):
        cf = _cashflow(PRICE, RENT, base_prop, phase=1)
        assert cf["net_with_bah"] == pytest.approx(cf["net"])

    def test_zero_hack_fraction_gives_zero_income(self):
        """SFH with no rental → Phase 1 income is $0."""
        prop = PropertyInput("78239", PRICE, units=1, hack_fraction=0.0)
        cf = _cashflow(PRICE, RENT, prop, phase=1)
        assert cf["gross_rent"] == pytest.approx(0.0)

    def test_full_hack_fraction_on_duplex_gives_two_units_rent(self):
        """Renting 100% of a duplex → 2 × ZORI (both units at market rate)."""
        prop = PropertyInput("78239", PRICE, units=2, hack_fraction=1.0)
        cf = _cashflow(PRICE, RENT, prop, phase=1)
        assert cf["gross_rent"] == pytest.approx(RENT * 2)

    def test_hoa_included_in_total_expense(self, high_hoa_prop):
        cf = _cashflow(PRICE, RENT, high_hoa_prop, phase=1)
        assert cf["fixed"]["hoa"] == pytest.approx(high_hoa_prop.hoa_monthly)
        assert high_hoa_prop.hoa_monthly in [cf["fixed"]["hoa"]]

    def test_higher_price_produces_lower_net(self, base_prop):
        """As price increases, net decreases monotonically (costs increase)."""
        cf_low  = _cashflow(150_000, RENT, base_prop, phase=1)
        cf_high = _cashflow(350_000, RENT, base_prop, phase=1)
        assert cf_low["net"] > cf_high["net"]

    def test_higher_rent_produces_higher_net(self, base_prop):
        """As rent increases, net increases (income increases)."""
        cf_low  = _cashflow(PRICE, 1_000, base_prop, phase=1)
        cf_high = _cashflow(PRICE, 2_000, base_prop, phase=1)
        assert cf_high["net"] > cf_low["net"]


class TestPhase2Cashflow:
    def test_gross_rent_is_all_units(self, base_prop):
        """Phase 2 rents all units — ZORI × units (duplex = 2 × ZORI)."""
        cf = _cashflow(PRICE, RENT, base_prop, phase=2)
        assert cf["gross_rent"] == pytest.approx(RENT * base_prop.units)

    def test_no_homestead_in_phase2(self, base_prop):
        """Phase 2 taxes on full price (you're not living there)."""
        cf = _cashflow(PRICE, RENT, base_prop, phase=2)
        expected_tax = PRICE * base_prop.property_tax_pct / 12
        assert cf["fixed"]["property_tax"] == pytest.approx(expected_tax)

    def test_management_fee_applied_in_phase2(self, base_prop):
        """Phase 2 uses mgmt_fee_phase2 (default 8%) on full multi-unit rent."""
        cf = _cashflow(PRICE, RENT, base_prop, phase=2)
        assert cf["variable"]["management"] == pytest.approx(RENT * base_prop.units * base_prop.mgmt_fee_phase2)

    def test_phase2_net_with_bah_equals_net(self, prop_with_bah):
        """BAH is not included in Phase 2 (you're not living there)."""
        cf = _cashflow(PRICE, RENT, prop_with_bah, phase=2)
        assert cf["net_with_bah"] == pytest.approx(cf["net"])

    def test_phase2_more_expensive_than_phase1(self, base_prop):
        """Phase 2 has higher total expenses (full tax, full rent-based costs, mgmt fee)."""
        cf1 = _cashflow(PRICE, RENT, base_prop, phase=1)
        cf2 = _cashflow(PRICE, RENT, base_prop, phase=2)
        assert cf2["total_expense"] > cf1["total_expense"]


class TestRoomHackCashflow:
    """Room-hack mode: SFH, rent individual bedrooms at per-room rate."""

    ROOM_RATE = 650.0   # per-room monthly rent (passed as rent_override / median_rent)
    BEDROOMS  = 4
    ROOMS_OUT = 3       # renting 3, keeping 1

    def _prop(self):
        return PropertyInput(
            "78239", PRICE,
            units=1, bedrooms=self.BEDROOMS, rooms_rented=self.ROOMS_OUT,
            rent_override=self.ROOM_RATE,
        )

    def test_phase1_income_equals_room_rate_times_rooms_rented(self):
        """Phase 1 income = per_room × bedrooms × hack_fraction = per_room × rooms_rented."""
        prop = self._prop()
        cf   = _cashflow(PRICE, self.ROOM_RATE, prop, phase=1)
        expected = self.ROOM_RATE * self.ROOMS_OUT   # $650 × 3 = $1,950
        assert cf["gross_rent"] == pytest.approx(expected)

    def test_phase2_income_equals_room_rate_times_all_bedrooms(self):
        """Phase 2 income = per_room × all bedrooms (all rented post-PCS)."""
        prop = self._prop()
        cf   = _cashflow(PRICE, self.ROOM_RATE, prop, phase=2)
        expected = self.ROOM_RATE * self.BEDROOMS    # $650 × 4 = $2,600
        assert cf["gross_rent"] == pytest.approx(expected)

    def test_phase1_income_less_than_phase2(self):
        """Keeping one bedroom → Phase 1 income < Phase 2 income."""
        prop = self._prop()
        cf1  = _cashflow(PRICE, self.ROOM_RATE, prop, phase=1)
        cf2  = _cashflow(PRICE, self.ROOM_RATE, prop, phase=2)
        assert cf1["gross_rent"] < cf2["gross_rent"]

    def test_rent_multiplier_is_bedrooms(self):
        prop = self._prop()
        assert prop.rent_multiplier == self.BEDROOMS


class TestCashflowOutputStructure:
    @pytest.mark.parametrize("phase", [1, 2])
    def test_required_keys_present(self, base_prop, phase):
        cf = _cashflow(PRICE, RENT, base_prop, phase=phase)
        required = {"gross_rent", "pi", "pmi", "loan_amount", "fixed", "variable",
                    "total_expense", "net", "net_with_bah"}
        assert required.issubset(cf.keys())

    @pytest.mark.parametrize("phase", [1, 2])
    def test_fixed_costs_sub_keys(self, base_prop, phase):
        cf = _cashflow(PRICE, RENT, base_prop, phase=phase)
        assert {"property_tax", "insurance", "hoa"}.issubset(cf["fixed"].keys())

    @pytest.mark.parametrize("phase", [1, 2])
    def test_variable_costs_sub_keys(self, base_prop, phase):
        cf = _cashflow(PRICE, RENT, base_prop, phase=phase)
        assert {"vacancy", "maintenance", "management"}.issubset(cf["variable"].keys())

    @pytest.mark.parametrize("phase", [1, 2])
    def test_pi_is_positive(self, base_prop, phase):
        cf = _cashflow(PRICE, RENT, base_prop, phase=phase)
        assert cf["pi"] > 0

    @pytest.mark.parametrize("phase", [1, 2])
    def test_total_expense_is_positive(self, base_prop, phase):
        cf = _cashflow(PRICE, RENT, base_prop, phase=phase)
        assert cf["total_expense"] > 0

    @pytest.mark.parametrize("phase", [1, 2])
    def test_total_expense_is_sum_of_parts(self, base_prop, phase):
        cf = _cashflow(PRICE, RENT, base_prop, phase=phase)
        component_sum = (
            cf["pi"]
            + cf["pmi"]
            + sum(cf["fixed"].values())
            + sum(cf["variable"].values())
        )
        assert cf["total_expense"] == pytest.approx(component_sum)

    def test_va_loan_has_no_pmi(self, base_prop):
        cf = _cashflow(PRICE, RENT, base_prop, phase=1)
        assert cf["pmi"] == 0.0
