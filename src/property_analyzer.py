"""
property_analyzer.py
--------------------
Evaluate a specific property listing against ZIP-level market data.

Inputs:  ZIP code, asking price, units, financing params
Outputs: crime breakdown, negotiation range, cashflow (Phase 1/2), 3-yr P&L,
         sensitivity analysis, filter status, decision scorecard
"""

import sys
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    DATA_FINAL, DATA_PROC, DATA_RAW,
    THRESHOLDS, CRIME_PERCENTILE_CUTOFF, MAX_COMMUTE_MINS, MAX_COMMUTE_MILES,
    VIOLENT_CRIME_PROBLEMS, YIELD_CAP, DUTY_STATION, MIN_POPULATION_FOR_CRIME,
)

logger = logging.getLogger(__name__)

# ── File paths ────────────────────────────────────────────────────────────────
_RANKED_PATH         = DATA_FINAL / "ranked_zip_scores.csv"
_MERGED_PATH         = DATA_PROC  / "merged_zip_dataset.csv"
_ZHVF_PATH           = DATA_RAW   / "zhvf_growth_zip.csv"
_CRIME_RAW_PATH      = DATA_RAW   / "sa_crime_raw.csv"
_CRIME_TYPE_CACHE    = DATA_PROC  / "crime_type_by_zip.csv"
_CRIME_WEEKDAY_CACHE = DATA_PROC  / "crime_weekday_by_zip.csv"

# ── Financing defaults ────────────────────────────────────────────────────────
_VA_FEE_FIRST  = 0.0215   # VA funding fee, first use
_VA_FEE_SUBSEQ = 0.0330   # VA funding fee, subsequent use
_PMI_ANNUAL    = 0.0085   # Conventional PMI when LTV > 80%
_PROP_TAX      = 0.022    # Bexar County effective rate
_INS_PER_1K    = 1.50     # Annual insurance per $1,000 of value
_VACANCY       = 0.05
_MAINT         = 0.09
_MGMT_P1       = 0.00     # Self-manage while living there
_MGMT_P2       = 0.08     # Hired manager post-PCS
_HOLD_YRS      = 3
_SELL_COST     = 0.08     # Realtor + closing costs
_HOMESTEAD_EX  = 100_000  # Texas homestead exemption
_RATE          = 0.06875  # Feb 2026 VA 30yr average
_TERM          = 30

# ── Appreciation scenarios for 3-yr P&L ──────────────────────────────────────
# ZHVF scenario is filled at runtime from actual ZHVF data for the ZIP
_APPRECIATION_SCENARIOS = [0.00, 0.03, 0.05, 0.08]

# ── Crime display categories ──────────────────────────────────────────────────
_CRIME_CATEGORIES: Dict[str, set] = {
    "Assault & Violence": {
        "ASSAULT", "ASSAULT IN PROGRESS", "FAMILY VIOLENCE",
        "FAMILY VIOLENCE GUN INV", "FAMILY VIOLENCE KNIFE INV",
        "CUTTING", "CUTTING IN PROGRESS",
        "DISTURBANCE (GUN INVOLVED)", "DISTURBANCE (KNIFE INVOLVED)",
        "DISTURBANCE FAMILY GUN INV", "DISTURBANCE FAMILY KNIFE INV",
        "DISTURBANCE NEIGHBOR GUN INV", "DISTURBANCE NEIGHBOR KNIFE IN",
        "FIGHT", "FIGHT GUN INVOLVED", "FIGHT KNIFE INVOLVED",
    },
    "Theft & Burglary": {
        "BURGLARY", "BURGLARY (IN PROGRESS)", "BURGLARY VEHICLE",
        "BURGLARY VEHICLE IN PROGRESS", "THEFT", "THEFT IN PROGRESS",
        "THEFT OF VEHICLE", "THEFT OF VEHICLE IN PROGRESS",
    },
    "Robbery": {
        "ROBBERY", "ROBBERY IN PROGRESS", "ROBBERY OF INDIVIDUAL",
        "ROBBERY OF INDIVIDUAL PROGRES", "HOLDUP ALARM IN PROGRESS",
        "HOLDUP ALARM RES IN PROGRESS",
    },
    "Weapons & Shooting": {
        "SHOOTING", "SHOOTING IN PROGRESS", "SHOTS FIRED JUST OCCURRED",
        "SHOT FIRED/HEARD", "SHOTSPOTTER SINGLE ALERT",
        "SHOTSPOTTER MULTIPLE ALERT", "WEAPONS",
    },
    "Narcotics & Vice": {"NARCOTIC LAWS", "VICE"},
    "Sexual Violence": {
        "RAPE", "RAPE IN PROGRESS", "SEXUAL OFFENSE-CHILD",
        "INTERNET PREDATOR", "LEWD CONDUCT",
    },
    "Threats & Arson": {
        "VIOLATION OF PROTECTIVE ORDER", "VIOLATION SEX OFF REG",
        "THREATS BOMB", "THREATS BOMB IN PROGRESS",
        "THREAT - BOMB WITH DEVICE", "ARSON RESPONSE",
    },
}


def _categorize(problem_upper: str) -> str:
    for cat, codes in _CRIME_CATEGORIES.items():
        if problem_upper in codes:
            return cat
    return "Other"


# ── Input ─────────────────────────────────────────────────────────────────────

@dataclass
class PropertyInput:
    zip_code: str
    asking_price: float
    units: int = 2                        # 1=SFH/condo, 2=duplex, 3=triplex, 4=fourplex
    bedrooms: int = 3
    hack_fraction: Optional[float] = None # fraction of property rented; auto-set from units
    loan_type: str = "VA"
    down_pct: float = 0.0
    interest_rate: float = _RATE
    loan_term_years: int = _TERM
    va_first_use: bool = True
    property_tax_pct: float = _PROP_TAX
    insurance_per_1k: float = _INS_PER_1K
    hoa_monthly: float = 0.0
    vacancy_rate: float = _VACANCY
    maintenance_pct: float = _MAINT
    mgmt_fee_phase1: float = _MGMT_P1
    mgmt_fee_phase2: float = _MGMT_P2
    hold_years: int = _HOLD_YRS
    selling_cost_pct: float = _SELL_COST
    bah_monthly: float = 0.0
    rent_override: Optional[float] = None  # override ZORI median if you know actual rent

    def __post_init__(self):
        self.zip_code = str(self.zip_code).zfill(5)
        if self.hack_fraction is None:
            # Rent everything except the one unit you occupy
            self.hack_fraction = max(0.0, (self.units - 1) / max(self.units, 1))


# ── Mortgage helpers ──────────────────────────────────────────────────────────

def _loan_amount(price: float, prop: PropertyInput) -> float:
    base = price * (1.0 - prop.down_pct)
    if prop.loan_type.upper() == "VA":
        fee = _VA_FEE_FIRST if prop.va_first_use else _VA_FEE_SUBSEQ
        return base * (1.0 + fee)
    return base


def _monthly_pi(loan: float, rate: float, term_years: int) -> float:
    r = rate / 12.0
    n = term_years * 12
    if r == 0:
        return loan / n
    return loan * (r * (1.0 + r) ** n) / ((1.0 + r) ** n - 1.0)


def _remaining_balance(loan: float, rate: float, term_years: int, years_paid: int) -> float:
    r = rate / 12.0
    n = term_years * 12
    p = years_paid * 12
    if r == 0:
        return loan * (1.0 - p / n)
    return loan * ((1.0 + r) ** n - (1.0 + r) ** p) / ((1.0 + r) ** n - 1.0)


def _pmi_monthly(price: float, loan: float, prop: PropertyInput) -> float:
    if prop.loan_type.upper() == "VA":
        return 0.0
    if loan / price <= 0.80:
        return 0.0
    return loan * _PMI_ANNUAL / 12.0


# ── Cost components ───────────────────────────────────────────────────────────

def _fixed_costs(price: float, prop: PropertyInput, homestead: bool = False) -> Dict[str, float]:
    """Property-value-based costs: tax, insurance, HOA."""
    taxable = max(0.0, price - _HOMESTEAD_EX) if homestead else price
    return {
        "property_tax": taxable * prop.property_tax_pct / 12.0,
        "insurance":    price / 1000.0 * prop.insurance_per_1k / 12.0,
        "hoa":          prop.hoa_monthly,
    }


def _variable_costs(gross_rent: float, mgmt_fee: float, prop: PropertyInput) -> Dict[str, float]:
    """Rent-based costs: vacancy, maintenance, management."""
    return {
        "vacancy":     gross_rent * prop.vacancy_rate,
        "maintenance": gross_rent * prop.maintenance_pct,
        "management":  gross_rent * mgmt_fee,
    }


# ── Cashflow ──────────────────────────────────────────────────────────────────

def _cashflow(price: float, median_rent: float, prop: PropertyInput, phase: int) -> Dict[str, Any]:
    """
    phase=1: house hack — you live in one unit, rent prop.hack_fraction of property
    phase=2: full rental post-PCS — entire property rented

    Note on median_rent: follows the existing pipeline convention where
    median_rent is the full-property ZORI estimate. Phase 1 income =
    median_rent × hack_fraction. Use rent_override to correct for
    specific property types if ZORI doesn't reflect your unit size.
    """
    loan = _loan_amount(price, prop)
    pi   = _monthly_pi(loan, prop.interest_rate, prop.loan_term_years)
    pmi  = _pmi_monthly(price, loan, prop)

    if phase == 1:
        gross_rent = median_rent * prop.hack_fraction
        homestead  = True
        mgmt_fee   = prop.mgmt_fee_phase1
    else:
        gross_rent = median_rent
        homestead  = False
        mgmt_fee   = prop.mgmt_fee_phase2

    fixed    = _fixed_costs(price, prop, homestead=homestead)
    variable = _variable_costs(gross_rent, mgmt_fee, prop)

    total_expense = pi + pmi + sum(fixed.values()) + sum(variable.values())
    net           = gross_rent - total_expense

    return {
        "gross_rent":    gross_rent,
        "pi":            pi,
        "pmi":           pmi,
        "loan_amount":   loan,
        "fixed":         fixed,
        "variable":      variable,
        "total_expense": total_expense,
        "net":           net,
        "net_with_bah":  net + prop.bah_monthly if phase == 1 else net,
    }


# ── Negotiation helpers ───────────────────────────────────────────────────────

def _max_price_for_yield(target_yield: float, annual_rent: float) -> float:
    """Gross yield = annual_rent / price → max_price = annual_rent / target_yield."""
    return annual_rent / target_yield


def _breakeven_price_phase1(median_rent: float, prop: PropertyInput) -> float:
    """
    Binary search for the price where Phase 1 net monthly = 0.
    (Tenant rental income exactly covers all monthly costs.)
    Returns a large value if breakeven is unreachable (e.g. hack_fraction=0).
    """
    if prop.hack_fraction <= 0:
        return 0.0

    lo, hi = 10_000.0, 3_000_000.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        net = _cashflow(mid, median_rent, prop, phase=1)["net"]
        if net > 0:
            lo = mid   # still profitable — can afford higher price
        else:
            hi = mid   # costs exceed income — need lower price
    return (lo + hi) / 2.0


# ── 3-Year P&L ────────────────────────────────────────────────────────────────

def _three_year_pnl(
    price: float,
    median_rent: float,
    prop: PropertyInput,
    zhvf_12mo: Optional[float] = None,
) -> List[Dict]:
    """3-year hold P&L under multiple appreciation scenarios."""
    loan        = _loan_amount(price, prop)
    down_paid   = price * prop.down_pct
    cf          = _cashflow(price, median_rent, prop, phase=1)
    net_monthly = cf["net"]
    cum_cf      = net_monthly * prop.hold_years * 12
    principal   = loan - _remaining_balance(loan, prop.interest_rate, prop.loan_term_years, prop.hold_years)

    # Build scenarios: ZHVF first (if available), then fixed rates
    apprecations = []
    if zhvf_12mo is not None:
        apprecations.append(("ZHVF fcst", zhvf_12mo))
    for pct in _APPRECIATION_SCENARIOS:
        label = f"+{pct:.0%}/yr" if pct > 0 else ("Flat (0%)" if pct == 0 else f"{pct:.1%}/yr")
        apprecations.append((label, pct))

    results = []
    for label, ann_pct in apprecations:
        exit_price    = price * (1.0 + ann_pct) ** prop.hold_years
        selling_costs = exit_price * prop.selling_cost_pct
        rem_balance   = _remaining_balance(loan, prop.interest_rate, prop.loan_term_years, prop.hold_years)
        net_proceeds  = exit_price - selling_costs - rem_balance
        total_return  = net_proceeds + cum_cf - down_paid
        results.append({
            "label":         label,
            "ann_pct":       ann_pct,
            "exit_price":    exit_price,
            "selling_costs": selling_costs,
            "rem_balance":   rem_balance,
            "net_proceeds":  net_proceeds,
            "total_return":  total_return,
            "principal":     principal,
            "cum_cf":        cum_cf,
            "down_paid":     down_paid,
        })
    return results


# ── Sensitivity ───────────────────────────────────────────────────────────────

def _rate_sensitivity(price: float, median_rent: float, prop: PropertyInput) -> List[Dict]:
    """Vary interest rate; show Phase 2 monthly net cashflow."""
    rates = [0.050, 0.055, 0.060, 0.065, 0.06875, 0.070, 0.075, 0.080, 0.085]
    results = []
    loan = _loan_amount(price, prop)
    pmi  = _pmi_monthly(price, loan, prop)
    fixed    = _fixed_costs(price, prop, homestead=False)
    variable = _variable_costs(median_rent, prop.mgmt_fee_phase2, prop)
    base_non_pi = pmi + sum(fixed.values()) + sum(variable.values())

    for r in rates:
        pi  = _monthly_pi(loan, r, prop.loan_term_years)
        net = median_rent - (pi + base_non_pi)
        results.append({
            "rate":    r,
            "pi":      pi,
            "net":     net,
            "current": abs(r - prop.interest_rate) < 0.0005,
        })
    return results


def _hack_fraction_sensitivity(price: float, median_rent: float, prop: PropertyInput) -> List[Dict]:
    """Vary hack fraction; show Phase 1 monthly net and net+BAH."""
    fractions = [0.25, 0.33, 0.50, 0.67, 0.75, 1.00]
    results = []
    loan = _loan_amount(price, prop)
    pi   = _monthly_pi(loan, prop.interest_rate, prop.loan_term_years)
    pmi  = _pmi_monthly(price, loan, prop)
    fixed = _fixed_costs(price, prop, homestead=True)  # Phase 1 = homestead

    for f in fractions:
        gross_rent = median_rent * f
        variable   = _variable_costs(gross_rent, prop.mgmt_fee_phase1, prop)
        total_exp  = pi + pmi + sum(fixed.values()) + sum(variable.values())
        net        = gross_rent - total_exp
        results.append({
            "fraction":    f,
            "income":      gross_rent,
            "net":         net,
            "net_with_bah": net + prop.bah_monthly,
            "current":     abs(f - prop.hack_fraction) < 0.02,
        })
    return results


# ── Crime data ────────────────────────────────────────────────────────────────

def _build_crime_cache() -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Load raw SAPD data, compute per-ZIP crime type and weekday breakdowns,
    and save to cache CSVs. This runs once (~30-60s) and caches the result.
    """
    if not _CRIME_RAW_PATH.exists():
        logger.warning(f"Crime raw data not found at {_CRIME_RAW_PATH}")
        return None, None

    print(f"  Building crime breakdown cache (one-time, ~30-60s)...")
    needed_cols = ["Postal_Code", "Problem", "Response_Date", "Weekday"]
    df = pd.read_csv(
        _CRIME_RAW_PATH, low_memory=False,
        usecols=lambda c: c in needed_cols,
    )

    # Filter to criminal problems only
    upper_problems = {p.upper() for p in VIOLENT_CRIME_PROBLEMS}
    df["_prob"] = df["Problem"].astype(str).str.upper().str.strip()
    df = df[df["_prob"].isin(upper_problems)].copy()

    # Clean ZIPs, exclude military
    df["zip"] = df["Postal_Code"].astype(str).str.strip().str.zfill(5)
    military_zips = {"78234", "78235", "78236", "78243"}
    df = df[~df["zip"].isin(military_zips)]

    # Parse dates for trend analysis
    df["date"] = pd.to_datetime(df.get("Response_Date"), errors="coerce")
    df = df.dropna(subset=["date"])

    latest = df["date"].max()
    cutoff_recent = latest - pd.DateOffset(months=12)
    cutoff_prior  = latest - pd.DateOffset(months=24)

    recent = df[df["date"] >= cutoff_recent].copy()
    prior  = df[(df["date"] >= cutoff_prior) & (df["date"] < cutoff_recent)].copy()

    # Crime type breakdown: categorize problems
    for frame in (recent, prior):
        frame["category"] = frame["_prob"].apply(_categorize)

    type_recent = recent.groupby(["zip", "category"]).size().reset_index(name="count_recent")
    type_prior  = prior.groupby(["zip",  "category"]).size().reset_index(name="count_prior")
    type_df = type_recent.merge(type_prior, on=["zip", "category"], how="outer").fillna(0)
    type_df["count_recent"] = type_df["count_recent"].astype(int)
    type_df["count_prior"]  = type_df["count_prior"].astype(int)

    # Weekday breakdown (recent only)
    weekday_df = recent.groupby(["zip", "Weekday"]).size().reset_index(name="count")

    DATA_PROC.mkdir(parents=True, exist_ok=True)
    type_df.to_csv(_CRIME_TYPE_CACHE, index=False)
    weekday_df.to_csv(_CRIME_WEEKDAY_CACHE, index=False)
    print(f"  Crime cache saved → {_CRIME_TYPE_CACHE.name}, {_CRIME_WEEKDAY_CACHE.name}")
    return type_df, weekday_df


def _load_crime_breakdown(zip_code: str) -> Optional[Dict]:
    """
    Return crime type and weekday breakdown for a specific ZIP.
    Builds and caches the breakdown on first call.
    Returns None if crime data is unavailable.
    """
    # Try to load from cache first
    if _CRIME_TYPE_CACHE.exists() and _CRIME_WEEKDAY_CACHE.exists():
        type_df    = pd.read_csv(_CRIME_TYPE_CACHE,    dtype={"zip": str})
        weekday_df = pd.read_csv(_CRIME_WEEKDAY_CACHE, dtype={"zip": str})
    else:
        type_df, weekday_df = _build_crime_cache()
        if type_df is None:
            return None

    # Filter to this ZIP
    t = type_df[type_df["zip"] == zip_code].copy()
    w = weekday_df[weekday_df["zip"] == zip_code].copy() if weekday_df is not None else pd.DataFrame()

    if t.empty:
        return None

    total_recent = int(t["count_recent"].sum())
    total_prior  = int(t["count_prior"].sum())
    trend_pct    = ((total_recent - total_prior) / total_prior * 100.0) if total_prior > 0 else None

    # Sort categories by recent count
    t = t.sort_values("count_recent", ascending=False)
    categories = []
    for _, row in t.iterrows():
        cnt   = int(row["count_recent"])
        prior = int(row["count_prior"])
        pct   = cnt / total_recent * 100.0 if total_recent > 0 else 0.0
        categories.append({
            "name":  row["category"],
            "count": cnt,
            "pct":   pct,
            "prior": prior,
        })

    peak_day = None
    if not w.empty:
        peak_day = w.loc[w["count"].idxmax(), "Weekday"] if len(w) > 0 else None

    return {
        "total_recent": total_recent,
        "total_prior":  total_prior,
        "trend_pct":    trend_pct,
        "categories":   categories,
        "peak_day":     peak_day,
    }


# ── Pipeline data loading ─────────────────────────────────────────────────────

def _load_pipeline_data() -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """Load ranked scores, merged (pre-filter) data, and ZHVF forecast."""
    ranked = None
    merged = None
    zhvf   = None

    if _RANKED_PATH.exists():
        ranked = pd.read_csv(_RANKED_PATH, dtype={"zip": str})
        ranked["zip"] = ranked["zip"].str.zfill(5)

    if _MERGED_PATH.exists():
        merged = pd.read_csv(_MERGED_PATH, dtype={"zip": str})
        merged["zip"] = merged["zip"].str.zfill(5)

    if _ZHVF_PATH.exists():
        try:
            zhvf = pd.read_csv(_ZHVF_PATH)
            # Normalize ZIP column
            zip_col = next(
                (c for c in zhvf.columns if c.lower() in ("regionname", "zip", "zipcode")),
                None
            )
            if zip_col:
                zhvf["zip"] = zhvf[zip_col].astype(str).str.strip().str.zfill(5)
        except Exception as e:
            logger.warning(f"Could not load ZHVF data: {e}")
            zhvf = None

    return ranked, merged, zhvf


def _get_zip_row(zip_code: str, ranked: Optional[pd.DataFrame], merged: Optional[pd.DataFrame]) -> Tuple[Optional[pd.Series], bool]:
    """
    Return (row, in_ranked).
    Prefers ranked (has score/rank), falls back to merged (pre-filter data).
    """
    if ranked is not None and zip_code in ranked["zip"].values:
        return ranked[ranked["zip"] == zip_code].iloc[0], True
    if merged is not None and zip_code in merged["zip"].values:
        return merged[merged["zip"] == zip_code].iloc[0], False
    return None, False


def _get_zhvf_forecast(zip_code: str, zhvf: Optional[pd.DataFrame]) -> Optional[float]:
    """Extract 12-month price forecast for a ZIP from ZHVF data."""
    if zhvf is None or "zip" not in zhvf.columns:
        return None
    row = zhvf[zhvf["zip"] == zip_code]
    if row.empty:
        return None
    # Look for a column named with "12" (12-month forecast)
    forecast_col = next(
        (c for c in zhvf.columns if "12" in str(c) and c != "zip"), None
    )
    if forecast_col is None:
        # Fall back: use the last non-zip numeric column
        num_cols = [c for c in zhvf.columns if c != "zip" and pd.api.types.is_numeric_dtype(zhvf[c])]
        forecast_col = num_cols[-1] if num_cols else None
    if forecast_col is None:
        return None
    val = pd.to_numeric(row.iloc[0][forecast_col], errors="coerce")
    if pd.isna(val):
        return None
    # Normalize: Zillow ZHVF can be expressed as decimal (0.03) or percent (3.0)
    return float(val) if abs(val) < 1 else float(val) / 100.0


def _compute_commute_fallback(zip_code: str) -> Optional[Tuple[float, float]]:
    """Haversine fallback for commute when ZIP isn't in pipeline data."""
    from commute import haversine_miles
    from utils import load_zip_centroids
    try:
        centroids = load_zip_centroids()
        row = centroids[centroids["zip"] == zip_code]
        if row.empty:
            return None
        lat, lon = float(row.iloc[0]["zip_lat"]), float(row.iloc[0]["zip_lon"])
        miles   = haversine_miles(lat, lon, DUTY_STATION["lat"], DUTY_STATION["lon"])
        minutes = (miles * 1.4 / 35.0) * 60.0
        return round(minutes, 1), round(miles, 1)
    except Exception:
        return None


# ── Hard filter evaluation ────────────────────────────────────────────────────

def _evaluate_filters(row: pd.Series, asking_price: float, median_rent: float) -> Dict:
    """Check each hard filter against the asking price (and against the yield-target price)."""
    annual_rent = median_rent * 12.0
    yield_at_ask = annual_rent / asking_price if asking_price > 0 else 0.0
    yield_target_price = _max_price_for_yield(THRESHOLDS["min_rent_to_price"], annual_rent)

    crime_cutoff = None
    crime_value  = float(row["crime_per_1k"]) if "crime_per_1k" in row.index else None

    results = {
        "price_ceiling": {
            "label":     f"Price ≤ ${THRESHOLDS['max_home_value']:,}",
            "pass":      asking_price <= THRESHOLDS["max_home_value"],
            "value":     f"${asking_price:,.0f}",
            "threshold": f"≤ ${THRESHOLDS['max_home_value']:,}",
        },
        "yield_floor": {
            "label":     f"Yield ≥ {THRESHOLDS['min_rent_to_price']:.1%}",
            "pass":      yield_at_ask >= THRESHOLDS["min_rent_to_price"],
            "value":     f"{yield_at_ask:.2%}",
            "threshold": f"≥ {THRESHOLDS['min_rent_to_price']:.1%}",
            "fix_price": yield_target_price,
        },
        "owner_occ_min": {
            "label":     f"Owner-occ ≥ {THRESHOLDS['min_owner_occ_pct']:.0%}",
            "pass":      float(row.get("owner_occ_pct", 1)) >= THRESHOLDS["min_owner_occ_pct"]
                         if "owner_occ_pct" in row.index else None,
            "value":     f"{row.get('owner_occ_pct', 'N/A'):.0%}" if "owner_occ_pct" in row.index else "N/A",
            "threshold": f"≥ {THRESHOLDS['min_owner_occ_pct']:.0%}",
        },
        "owner_occ_max": {
            "label":     f"Owner-occ ≤ {THRESHOLDS['max_owner_occ_pct']:.0%}",
            "pass":      float(row.get("owner_occ_pct", 0)) <= THRESHOLDS["max_owner_occ_pct"]
                         if "owner_occ_pct" in row.index else None,
            "value":     f"{row.get('owner_occ_pct', 'N/A'):.0%}" if "owner_occ_pct" in row.index else "N/A",
            "threshold": f"≤ {THRESHOLDS['max_owner_occ_pct']:.0%}",
        },
        "commute": {
            "label":     f"Commute ≤ {MAX_COMMUTE_MINS} min",
            "pass":      float(row.get("commute_minutes", 0)) <= MAX_COMMUTE_MINS
                         if "commute_minutes" in row.index else None,
            "value":     f"{row.get('commute_minutes', 'N/A'):.0f} min" if "commute_minutes" in row.index else "N/A",
            "threshold": f"≤ {MAX_COMMUTE_MINS} min",
        },
        "income": {
            "label":     f"Income ≥ ${THRESHOLDS['min_median_income']:,}",
            "pass":      float(row.get("median_hh_income", 0)) >= THRESHOLDS["min_median_income"]
                         if "median_hh_income" in row.index else None,
            "value":     f"${row.get('median_hh_income', 'N/A'):,.0f}" if "median_hh_income" in row.index else "N/A",
            "threshold": f"≥ ${THRESHOLDS['min_median_income']:,}",
        },
    }

    # Crime filter — percentile-based, so we need the full merged dataset to compute cutoff
    if crime_value is not None:
        results["crime"] = {
            "label":     f"Crime ≤ {CRIME_PERCENTILE_CUTOFF:.0%} percentile",
            "pass":      None,   # filled in analyze_property once we have the full dataset
            "value":     f"{crime_value:.1f}/1k",
            "threshold": f"top {1-CRIME_PERCENTILE_CUTOFF:.0%} safest",
        }

    return results


# ── Main analysis entry point ─────────────────────────────────────────────────

def analyze_property(prop: PropertyInput) -> Dict[str, Any]:
    """
    Run full analysis for a property listing. Returns a structured dict
    suitable for formatting or JSON export.
    """
    ranked, merged, zhvf_df = _load_pipeline_data()

    if ranked is None and merged is None:
        raise FileNotFoundError(
            "No pipeline data found. Run `python main.py --no-google-maps` first to generate "
            "data/processed/merged_zip_dataset.csv and data/final/ranked_zip_scores.csv"
        )

    row, in_ranked = _get_zip_row(prop.zip_code, ranked, merged)

    if row is None:
        raise ValueError(
            f"ZIP {prop.zip_code} not found in pipeline data. "
            "It may be outside the San Antonio metro area or missing from source data."
        )

    # Use rent_override if provided, else ZORI median
    median_rent = prop.rent_override if prop.rent_override else float(row.get("median_rent", 0))
    if median_rent <= 0:
        raise ValueError(f"No rent data for ZIP {prop.zip_code}. Use --rent-override to specify expected rent.")

    annual_rent  = median_rent * 12.0
    gross_yield  = annual_rent / prop.asking_price

    # Market context
    home_value   = float(row.get("median_home_value", prop.asking_price))
    price_delta  = prop.asking_price - home_value
    price_delta_pct = price_delta / home_value * 100.0 if home_value > 0 else 0.0

    # ZHVF forecast
    zhvf_12mo = _get_zhvf_forecast(prop.zip_code, zhvf_df)

    # Compute commute if missing from data
    commute_min  = float(row["commute_minutes"]) if "commute_minutes" in row.index else None
    commute_mi   = float(row["commute_miles"])   if "commute_miles"   in row.index else None
    if commute_min is None:
        fallback = _compute_commute_fallback(prop.zip_code)
        if fallback:
            commute_min, commute_mi = fallback

    # Crime percentile cutoff from full dataset
    crime_cutoff = None
    if merged is not None and "crime_per_1k" in merged.columns:
        crime_cutoff = float(merged["crime_per_1k"].quantile(CRIME_PERCENTILE_CUTOFF))
    elif ranked is not None and "crime_per_1k" in ranked.columns:
        crime_cutoff = float(ranked["crime_per_1k"].quantile(CRIME_PERCENTILE_CUTOFF))

    # Cashflow
    cf_p1 = _cashflow(prop.asking_price, median_rent, prop, phase=1)
    cf_p2 = _cashflow(prop.asking_price, median_rent, prop, phase=2)

    # Negotiation
    yield_targets = {}
    for y in [0.065, 0.070, 0.075, 0.080]:
        mp = _max_price_for_yield(y, annual_rent)
        yield_targets[y] = {
            "max_price":  mp,
            "gap":        prop.asking_price - mp,
            "gap_pct":    (prop.asking_price - mp) / prop.asking_price * 100.0,
        }
    breakeven_price = _breakeven_price_phase1(median_rent, prop)

    # 3-year P&L scenarios
    pnl_scenarios = _three_year_pnl(prop.asking_price, median_rent, prop, zhvf_12mo=zhvf_12mo)

    # Sensitivity
    rate_sens  = _rate_sensitivity(prop.asking_price, median_rent, prop)
    hack_sens  = _hack_fraction_sensitivity(prop.asking_price, median_rent, prop)

    # Filter status
    filters = _evaluate_filters(row, prop.asking_price, median_rent)
    if "crime" in filters and crime_cutoff is not None:
        crime_val = float(row.get("crime_per_1k", 0))
        filters["crime"]["pass"] = crime_val <= crime_cutoff
        filters["crime"]["cutoff"] = crime_cutoff

    # City-wide stats for context
    city_avg_crime = None
    city_avg_rent  = None
    city_avg_value = None
    src_df = merged if merged is not None else ranked
    if src_df is not None:
        if "crime_per_1k" in src_df.columns:
            city_avg_crime = float(src_df["crime_per_1k"].median())
        if "median_rent" in src_df.columns:
            city_avg_rent = float(src_df["median_rent"].median())
        if "median_home_value" in src_df.columns:
            city_avg_value = float(src_df["median_home_value"].median())

    # Percentile context for key metrics
    def _pct_rank(col, val, ascending=True):
        if src_df is None or col not in src_df.columns or val is None:
            return None
        s = pd.to_numeric(src_df[col], errors="coerce").dropna()
        if ascending:
            return int((s <= val).sum() / len(s) * 100)
        else:
            return int((s >= val).sum() / len(s) * 100)

    # Crime breakdown
    crime_breakdown = _load_crime_breakdown(prop.zip_code)

    # Rank info
    rank      = int(row["rank"])        if in_ranked and "rank"        in row.index else None
    score     = float(row["final_score"]) if in_ranked and "final_score" in row.index else None
    total_qualifying = len(ranked) if ranked is not None and in_ranked else None

    # Scorecard checks
    filters_pass_asking = all(v["pass"] for v in filters.values() if v["pass"] is not None)
    yield_fix_price = yield_targets[0.065]["max_price"]
    # "negotiated price" check: non-price filters all pass AND negotiated price ≤ ceiling
    non_price_ok = all(
        v["pass"] for k, v in filters.items()
        if k not in ("price_ceiling", "yield_floor") and v["pass"] is not None
    )
    filters_pass_negot = non_price_ok and (yield_fix_price <= THRESHOLDS["max_home_value"])

    sc = {
        "filters_at_asking":    filters_pass_asking,
        "filters_at_negot":     yield_fix_price,
        "filters_at_negot_pass": filters_pass_negot,
        "phase1_neutral":     cf_p1["net"] >= 0,
        "phase1_with_bah":    cf_p1["net_with_bah"] >= 0,
        "phase2_positive":    cf_p2["net"] >= 0,
        "return_flat_pos":    next((s["total_return"] >= 0 for s in pnl_scenarios if s["ann_pct"] == 0.0), False),
        "return_5pct_pos":    next((s["total_return"] >= 0 for s in pnl_scenarios if abs(s["ann_pct"] - 0.05) < 0.001), False),
        "crime_improving":    (crime_breakdown["trend_pct"] is not None and
                               crime_breakdown["trend_pct"] < 0) if crime_breakdown else None,
        "top_ranked":         rank is not None and rank <= max(5, (total_qualifying or 0) // 3),
    }

    return {
        "prop":              prop,
        "row":               row,
        "in_ranked":         in_ranked,
        "median_rent":       median_rent,
        "annual_rent":       annual_rent,
        "gross_yield":       gross_yield,
        "home_value":        home_value,
        "price_delta":       price_delta,
        "price_delta_pct":   price_delta_pct,
        "commute_min":       commute_min,
        "commute_mi":        commute_mi,
        "zhvf_12mo":         zhvf_12mo,
        "cf_p1":             cf_p1,
        "cf_p2":             cf_p2,
        "yield_targets":     yield_targets,
        "breakeven_price":   breakeven_price,
        "pnl_scenarios":     pnl_scenarios,
        "rate_sensitivity":  rate_sens,
        "hack_sensitivity":  hack_sens,
        "filters":           filters,
        "crime_breakdown":   crime_breakdown,
        "crime_cutoff":      crime_cutoff,
        "city_avg_crime":    city_avg_crime,
        "city_avg_rent":     city_avg_rent,
        "city_avg_value":    city_avg_value,
        "rank":              rank,
        "score":             score,
        "total_qualifying":  total_qualifying,
        "scorecard":         sc,
        "pct_price":         _pct_rank("median_home_value", prop.asking_price),
        "pct_yield":         _pct_rank("rent_to_price", gross_yield),
        "pct_crime":         _pct_rank("crime_per_1k", row.get("crime_per_1k"), ascending=False),
        "pct_commute":       _pct_rank("commute_minutes", commute_min, ascending=False),
    }


# ── Report formatting ─────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 22) -> str:
    filled = max(0, min(width, round(pct / 100.0 * width)))
    return "█" * filled + " " * (width - filled)


def _check(v: Optional[bool]) -> str:
    if v is True:   return "✓"
    if v is False:  return "✗"
    return "?"


def _sign(v: float) -> str:
    return "+" if v >= 0 else "-"


def _fmt_money(v: float) -> str:
    return f"${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def format_report(r: Dict[str, Any]) -> str:
    prop = r["prop"]
    row  = r["row"]
    cf1  = r["cf_p1"]
    cf2  = r["cf_p2"]
    W    = 68

    lines = []
    sep  = "═" * W
    thin = "─" * W

    def section(title: str):
        lines.append(f"\n── {title} {'─' * max(0, W - len(title) - 4)}")

    lines.append(sep)
    lines.append("  PROPERTY ANALYSIS REPORT")
    unit_label = {1: "SFH/Condo", 2: "Duplex", 3: "Triplex", 4: "Fourplex"}.get(prop.units, f"{prop.units}-unit")
    lines.append(f"  ZIP {prop.zip_code}  |  ${prop.asking_price:,.0f} asking  |  {unit_label}  |  {prop.loan_type} {prop.interest_rate:.3%} {prop.loan_term_years}yr")
    lines.append(sep)

    # ── 1. ZIP OVERVIEW ───────────────────────────────────────────────────────
    section("1. ZIP MARKET OVERVIEW")
    if r["rank"]:
        lines.append(f"  Rank: #{r['rank']} of {r['total_qualifying']} qualifying ZIPs  |  Score: {r['score']:.3f}")
    else:
        lines.append(f"  This ZIP did NOT pass all hard filters (not in ranked output)")

    delta_sign = "+" if r["price_delta"] >= 0 else ""
    lines.append(f"  Median home value:  ${r['home_value']:>10,.0f}   Asking: ${prop.asking_price:,.0f} ({delta_sign}{r['price_delta_pct']:.1f}% vs median)")
    lines.append(f"  Median rent (ZORI): ${r['median_rent']:>10,.0f}/mo  Gross yield: {r['gross_yield']:.2%}  {'⚠ below 6.5% floor' if r['gross_yield'] < THRESHOLDS['min_rent_to_price'] else '✓ above floor'}")

    if r["commute_min"] is not None:
        lines.append(f"  Commute to BAMC:   {r['commute_min']:>10.0f} min  ({r['commute_mi']:.1f} mi)")

    if "owner_occ_pct" in row.index:
        lines.append(f"  Owner-occupancy:   {float(row['owner_occ_pct']):>10.0%}   Median HH income: ${float(row.get('median_hh_income', 0)):,.0f}")

    if "zhvi_cagr_5yr" in row.index:
        cagr5  = float(row["zhvi_cagr_5yr"])
        cagr10 = float(row.get("zhvi_cagr_10yr", 0)) if "zhvi_cagr_10yr" in row.index else None
        cagr_str = f"5yr CAGR {cagr5:+.1%}"
        if cagr10:
            cagr_str += f"  |  10yr CAGR {cagr10:+.1%}"
        lines.append(f"  {cagr_str}")

    if r["zhvf_12mo"] is not None:
        lines.append(f"  ZHVF 12mo forecast: {r['zhvf_12mo']:+.2%}  ({'price expected to decline' if r['zhvf_12mo'] < 0 else 'price expected to rise'})")

    if "zhvi_cov" in row.index:
        cov = float(row["zhvi_cov"])
        lines.append(f"  Price stability:   CoV {cov:.4f}  (lower = more stable)")

    # City comparison
    if r["city_avg_crime"] and "crime_per_1k" in row.index:
        crime_val = float(row["crime_per_1k"])
        vs_avg = (crime_val - r["city_avg_crime"]) / r["city_avg_crime"] * 100.0
        lines.append(f"  Crime/1k:          {crime_val:>10.1f}    (city median: {r['city_avg_crime']:.1f}/1k, {vs_avg:+.1f}% vs avg)")

    # ── 2. CRIME INTELLIGENCE ─────────────────────────────────────────────────
    section("2. CRIME INTELLIGENCE")
    crime_val = float(row.get("crime_per_1k", 0)) if "crime_per_1k" in row.index else None

    if crime_val is not None:
        cutoff_str = f"  (cutoff {r['crime_cutoff']:.1f}/1k)" if r["crime_cutoff"] else ""
        filt = r["filters"].get("crime", {})
        pass_str = "PASS" if filt.get("pass") else "FAIL" if filt.get("pass") is False else "N/A"
        lines.append(f"  Crime rate: {crime_val:.1f} / 1,000 residents  |  Filter: {pass_str}{cutoff_str}")

    cb = r["crime_breakdown"]
    if cb:
        lines.append(f"\n  Crime type breakdown — last 12 months ({cb['total_recent']:,} incidents):")
        for cat in cb["categories"]:
            bar_str = _bar(cat["pct"], 20)
            lines.append(f"  {cat['name']:<22}  {bar_str}  {cat['pct']:>4.0f}%  ({cat['count']:,})")

        if cb["trend_pct"] is not None:
            arrow   = "▼" if cb["trend_pct"] < 0 else "▲"
            quality = "improving" if cb["trend_pct"] < 0 else "worsening"
            lines.append(f"\n  Trend vs prior 12 months: {arrow} {abs(cb['trend_pct']):.1f}%  {quality}")

        if cb["peak_day"]:
            lines.append(f"  Peak day: {cb['peak_day']}")
    else:
        lines.append("  Crime breakdown unavailable (run pipeline to download SAPD data)")

    # ── 3. NEGOTIATION RANGE ──────────────────────────────────────────────────
    section("3. NEGOTIATION RANGE")
    hack_pct = prop.hack_fraction * 100
    lines.append(f"  ZORI median rent: ${r['median_rent']:,.0f}/mo  |  Annual potential: ${r['annual_rent']:,.0f}/yr")
    unit_label2 = f"{prop.units}-unit" if prop.units > 1 else "SFH"
    lines.append(f"  Hack setup: {unit_label2}, {hack_pct:.0f}% rented while you occupy the rest")
    lines.append("")
    lines.append(f"  Max price by gross yield target:")
    lines.append(f"  {'Target':<10} {'Max Price':>12}  {'vs Asking':>12}  Note")
    lines.append(f"  {'─'*52}")
    notes = {0.065: "hard filter floor", 0.070: "recommended target", 0.075: "strong buyer position", 0.080: "best case"}
    for y, info in r["yield_targets"].items():
        gap_str = f"-${abs(info['gap']):,.0f}"
        above = prop.asking_price <= info["max_price"]
        marker = "✓ ask already below" if above else f"  {gap_str}"
        lines.append(f"  {y:.1%}       ${info['max_price']:>12,.0f}  {gap_str:>12}  {notes[y]}")

    lines.append("")
    bp = r["breakeven_price"]
    if bp > 0:
        gap_be = prop.asking_price - bp
        lines.append(f"  Phase 1 break-even price: ${bp:,.0f}  (costs = tenant rental income)")
        if gap_be > 0:
            lines.append(f"  → Need to negotiate ${gap_be:,.0f} ({gap_be/prop.asking_price*100:.1f}%) below asking to break even")
            lines.append(f"  → At asking: out-of-pocket ${abs(cf1['net']):,.0f}/mo (before BAH)")
        else:
            lines.append(f"  → Asking price is already BELOW break-even — Phase 1 cash-positive!")

    # ── 4. CASHFLOW ANALYSIS ──────────────────────────────────────────────────
    section("4. CASHFLOW ANALYSIS")
    va_fee = _VA_FEE_FIRST if prop.va_first_use else _VA_FEE_SUBSEQ
    down_amt = prop.asking_price * prop.down_pct
    lines.append(f"  Loan amount (w/ {va_fee:.2%} VA fee rolled in): ${cf1['loan_amount']:,.0f}")
    lines.append(f"  Monthly P&I: ${cf1['pi']:,.0f}   Down payment: ${down_amt:,.0f}")

    for phase, cf, label in [
        (1, cf1, f"PHASE 1 — House Hack ({hack_pct:.0f}% rented)"),
        (2, cf2, "PHASE 2 — Full Rental (post-PCS)"),
    ]:
        lines.append(f"\n  {label}")
        lines.append(f"  {'─'*50}")
        lines.append(f"  {'Rental income':<32}  {_sign(cf['gross_rent'])}${cf['gross_rent']:>8,.0f}")
        lines.append(f"  {'Mortgage (P&I)':<32}  -${cf['pi']:>8,.0f}")
        if cf["pmi"] > 0:
            lines.append(f"  {'PMI':<32}  -${cf['pmi']:>8,.0f}")
        homestead_note = " (homestead exempt $100k)" if phase == 1 else ""
        lines.append(f"  {'Property tax' + homestead_note:<32}  -${cf['fixed']['property_tax']:>8,.0f}")
        lines.append(f"  {'Insurance':<32}  -${cf['fixed']['insurance']:>8,.0f}")
        if cf["fixed"]["hoa"] > 0:
            lines.append(f"  {'HOA':<32}  -${cf['fixed']['hoa']:>8,.0f}")
        lines.append(f"  {'Vacancy':<32}  -${cf['variable']['vacancy']:>8,.0f}")
        lines.append(f"  {'Maintenance':<32}  -${cf['variable']['maintenance']:>8,.0f}")
        if cf["variable"]["management"] > 0:
            lines.append(f"  {'Management':<32}  -${cf['variable']['management']:>8,.0f}")
        lines.append(f"  {'─'*50}")
        net_str = f"{_sign(cf['net'])}${abs(cf['net']):,.0f}"
        verdict = "✓ cash-positive" if cf["net"] >= 0 else "✗ out-of-pocket"
        lines.append(f"  {'Monthly net':<32}  {net_str:>10}  {verdict}")
        if phase == 1 and prop.bah_monthly > 0:
            bah_str = f"{_sign(cf['net_with_bah'])}${abs(cf['net_with_bah']):,.0f}"
            bah_v   = "✓ positive with BAH" if cf["net_with_bah"] >= 0 else "✗ still negative with BAH"
            lines.append(f"  {'With BAH (${:,.0f}/mo)'.format(prop.bah_monthly):<32}  {bah_str:>10}  {bah_v}")

    # ── 5. 3-YEAR HOLD P&L ────────────────────────────────────────────────────
    section("5. 3-YEAR HOLD P&L")
    s0 = r["pnl_scenarios"][0]
    cum_cf_monthly = cf1["net"]
    lines.append(f"  Down payment: ${s0['down_paid']:,.0f}  |  Loan at entry: ${s0['rem_balance'] + s0['principal']:,.0f}")
    lines.append(f"  Principal paid down after {prop.hold_years} yrs: ${s0['principal']:,.0f}")
    lines.append(f"  Cumulative Phase 1 cashflow ({prop.hold_years*12} mo × {_sign(cum_cf_monthly)}${abs(cum_cf_monthly):,.0f}):  {_sign(s0['cum_cf'])}${abs(s0['cum_cf']):,.0f}")
    if prop.bah_monthly > 0:
        bah_total = prop.bah_monthly * prop.hold_years * 12
        lines.append(f"  Total BAH received over {prop.hold_years} yrs: ${bah_total:,.0f}")
    lines.append(f"\n  Exit scenarios ({prop.selling_cost_pct:.0%} selling costs):")
    lines.append(f"  {'Scenario':<16}  {'Exit Price':>12}  {'Net Proceeds':>13}  {'Total Return':>13}")
    lines.append(f"  {'─'*58}")
    for s in r["pnl_scenarios"]:
        v = _check(s["total_return"] >= 0)
        lines.append(
            f"  {s['label']:<16}  ${s['exit_price']:>11,.0f}"
            f"  {_sign(s['net_proceeds'])}${abs(s['net_proceeds']):>11,.0f}"
            f"  {_sign(s['total_return'])}${abs(s['total_return']):>11,.0f}  {v}"
        )
    if down_amt == 0:
        lines.append(f"\n  Note: 0% down VA loan = no equity buffer to absorb {prop.selling_cost_pct:.0%} selling costs.")

    # ── 6. SENSITIVITY ────────────────────────────────────────────────────────
    section("6. SENSITIVITY ANALYSIS")
    lines.append("  Phase 2 monthly cashflow vs. interest rate:")
    max_abs_net = max(abs(s["net"]) for s in r["rate_sensitivity"]) or 1
    for s in r["rate_sensitivity"]:
        marker  = "  ← current" if s["current"] else ""
        v       = _check(s["net"] >= 0)
        bar_len = max(1, round(abs(s["net"]) / max_abs_net * 20))
        bar_str = "█" * bar_len
        lines.append(f"  {s['rate']:.1%}   {_sign(s['net'])}${abs(s['net']):>5,.0f}  {v}  {bar_str}{marker}")

    lines.append(f"\n  Phase 1 monthly cost vs. hack fraction:")
    lines.append(f"  {'Fraction':>8}   {'Rent Income':>12}   {'Monthly Net':>12}   {'With BAH':>10}")
    lines.append(f"  {'─'*52}")
    for s in r["hack_sensitivity"]:
        marker = "  ← current" if s["current"] else ""
        lines.append(
            f"  {s['fraction']:>7.0%}"
            f"   ${s['income']:>10,.0f}"
            f"   {_sign(s['net'])}${abs(s['net']):>10,.0f}"
            f"   {_sign(s['net_with_bah'])}${abs(s['net_with_bah']):>8,.0f}{marker}"
        )

    # ── 7. FILTER STATUS ──────────────────────────────────────────────────────
    section("7. FILTER STATUS")
    fail_count = 0
    for key, f in r["filters"].items():
        if f["pass"] is None:
            status = "N/A   "
        elif f["pass"]:
            status = "PASS  "
        else:
            status = "FAIL  "
            fail_count += 1
        fix = ""
        if not f.get("pass") and "fix_price" in f:
            fix = f"  → negotiate to ${f['fix_price']:,.0f}"
        lines.append(f"  {f['label']:<36}  {status}  {f['value']}{fix}")

    lines.append("")
    if fail_count == 0:
        lines.append("  All filters PASS at asking price. ✓")
    else:
        lines.append(f"  {fail_count} filter(s) FAIL at asking price.")
        yp = r["yield_targets"][0.065]["max_price"]
        if yp < prop.asking_price:
            lines.append(f"  Negotiate to ≤ ${yp:,.0f} to meet the 6.5% yield floor.")

    # ── 8. DECISION SCORECARD ─────────────────────────────────────────────────
    section("8. DECISION SCORECARD")
    sc = r["scorecard"]
    yp = r["yield_targets"][0.065]["max_price"]
    scorecard_items = [
        (sc["filters_at_asking"],  "All hard filters pass at asking price"),
        (sc.get("filters_at_negot_pass", False), f"All hard filters pass at ${yp:,.0f} (6.5% yield target)"),
        (sc["phase1_neutral"],     "Phase 1 cash-neutral without BAH"),
        (sc["phase1_with_bah"] if prop.bah_monthly > 0 else None,
                                   f"Phase 1 cash-neutral with ${prop.bah_monthly:,.0f}/mo BAH"),
        (sc["phase2_positive"],    "Phase 2 cash-positive post-PCS"),
        (sc["return_flat_pos"],    "3-yr total return positive at 0% appreciation"),
        (sc["return_5pct_pos"],    "3-yr total return positive at +5%/yr appreciation"),
        (sc["crime_improving"],    "Crime trend improving YoY"),
        (sc["top_ranked"],         f"ZIP is top-ranked (#{r['rank']} of {r['total_qualifying']})" if r["rank"] else "ZIP is in ranked output"),
    ]
    passes = 0
    for val, label in scorecard_items:
        if val is None:
            continue
        marker = _check(val)
        if val:
            passes += 1
        lines.append(f"  [{marker}] {label}")

    # Verdict
    lines.append("")
    verdict = _generate_verdict(r)
    # Word-wrap verdict at ~65 chars
    words  = verdict.split()
    line_  = "  VERDICT: "
    wrapped = []
    for w in words:
        if len(line_) + len(w) + 1 > W - 2:
            wrapped.append(line_)
            line_ = "           " + w + " "
        else:
            line_ += w + " "
    if line_.strip():
        wrapped.append(line_)
    lines.extend(wrapped)

    lines.append("\n" + thin)
    return "\n".join(lines)


def _generate_verdict(r: Dict[str, Any]) -> str:
    prop = r["prop"]
    sc   = r["scorecard"]
    cf1  = r["cf_p1"]
    cf2  = r["cf_p2"]
    yp   = r["yield_targets"][0.065]["max_price"]

    issues    = []
    positives = []
    actions   = []

    # Filter issues
    if not sc["filters_at_asking"]:
        gap = prop.asking_price - yp
        issues.append(f"fails yield filter at asking")
        actions.append(f"negotiate down ≥ ${gap:,.0f} to ${yp:,.0f} to pass all filters")

    # Phase 2 post-PCS cashflow
    if cf2["net"] < -600:
        issues.append(f"Phase 2 costs ${abs(cf2['net']):,.0f}/mo more than it earns post-PCS")
        actions.append("plan for property management costs and potential negative cashflow when deployed")
    elif cf2["net"] < 0:
        issues.append(f"Phase 2 slightly underwater (${abs(cf2['net']):,.0f}/mo)")

    # Price forecast headwind
    if r.get("zhvf_12mo") is not None and r["zhvf_12mo"] < -0.02:
        issues.append(f"Zillow forecasts {r['zhvf_12mo']:.1%} price decline next 12 months")
        actions.append("consider waiting or negotiating harder given downward price forecast")

    # Positives
    if sc.get("crime_improving"):
        positives.append("crime trend improving YoY")
    if r["rank"] and r["rank"] <= 5:
        positives.append(f"top #{r['rank']} ranked ZIP")
    if cf1["net_with_bah"] >= 0 and prop.bah_monthly > 0:
        positives.append("cash-neutral with BAH")
    if sc["filters_at_asking"]:
        positives.append("passes all hard filters at asking price")

    # Build verdict
    if not issues:
        if sc["phase2_positive"]:
            return ("Strong buy. Passes all filters, Phase 2 cash-positive. "
                    f"Strong ZIP score (#{r['rank']} of {r['total_qualifying']}). " if r["rank"] else "") + \
                   "Verify rent estimates against current listings before closing."
        else:
            tail = f"#{r['rank']} ranked ZIP" if r["rank"] else "solid ZIP fundamentals"
            return (f"Solid candidate with {tail}. "
                    "Passes all filters. Phase 2 cashflow is tight but survivable — "
                    "confirm property management cost assumptions.")

    verdict_parts = []
    if positives:
        verdict_parts.append(f"Positives: {', '.join(positives)}.")
    verdict_parts.append(f"Watch out for: {'; '.join(issues)}.")
    if actions:
        verdict_parts.append(f"Recommended: {'; '.join(actions)}.")
    return " ".join(verdict_parts)


def print_report(r: Dict[str, Any]) -> None:
    print(format_report(r))
