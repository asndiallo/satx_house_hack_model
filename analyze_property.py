"""
analyze_property.py
-------------------
CLI for evaluating a specific property listing against ZIP-level market data.

Default mode: SFR room hack (units=1, specify --rooms-rented and --bedrooms).
The pipeline's est_room_rent (ZORI ÷ median rooms) is used automatically when
--rent-override is omitted. Use --rent-override when you have actual comps.

Usage:
    # SFR room hack — 3-bed home, rent 2 rooms, using pipeline est. room rent
    python analyze_property.py --zip 78239 --price 265000 --bedrooms 3 \\
        --rooms-rented 2 --bah 1900

    # SFR room hack — 4-bed home, rent 3 rooms, with actual comp rent override
    python analyze_property.py --zip 78239 --price 285000 --bedrooms 4 \\
        --rooms-rented 3 --rent-override 750 --bah 1900

    # Duplex — unit hack mode (you live in one unit, rent the other)
    python analyze_property.py --zip 78209 --price 285000 --units 2 --bah 1900

    # Triplex, specify hack fraction manually
    python analyze_property.py --zip 78209 --price 320000 --units 3 --hack-fraction 0.67

    # Conventional loan, 5% down
    python analyze_property.py --zip 78209 --price 285000 --units 2 \\
        --loan-type conventional --down-pct 5

    # Export as JSON
    python analyze_property.py --zip 78239 --price 265000 --bedrooms 3 \\
        --rooms-rented 2 --output json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from property_analyzer import (
    PropertyInput,
    analyze_property,
    format_report,
    print_report,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate a specific property listing against SA market data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required
    parser.add_argument("--zip", required=True, help="5-digit ZIP code")
    parser.add_argument(
        "--price", required=True, type=float, help="Asking price in dollars"
    )

    # Property details
    parser.add_argument(
        "--units",
        type=int,
        default=1,
        help="Number of units (1=SFH, 2=duplex, 3=triplex, 4=fourplex) [default: 1]",
    )
    parser.add_argument(
        "--bedrooms", type=int, default=3, help="Total bedrooms [default: 3]"
    )
    parser.add_argument(
        "--hack-fraction",
        type=float,
        default=None,
        help="Fraction of property rented (0–1). Auto-set from --units if omitted.",
    )
    parser.add_argument(
        "--rooms-rented",
        type=int,
        default=None,
        metavar="N",
        help="Room-hack mode: number of bedrooms to rent out (you keep 1). "
        "Pipeline est_room_rent is used automatically; override with --rent-override. "
        "E.g. 3-bed SFH, rent 2 rooms: --bedrooms 3 --rooms-rented 2",
    )

    # Financing
    parser.add_argument(
        "--loan-type",
        default="VA",
        choices=["VA", "va", "conventional", "conv"],
        help="Loan type [default: VA]",
    )
    parser.add_argument(
        "--down-pct",
        type=float,
        default=0.0,
        help="Down payment percent (e.g. 5 = 5%%) [default: 0]",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=6.875,
        help="Interest rate in percent (e.g. 6.875) [default: 6.875]",
    )
    parser.add_argument(
        "--term", type=int, default=30, help="Loan term in years [default: 30]"
    )
    parser.add_argument(
        "--va-second-use",
        action="store_true",
        help="Apply 3.30%% VA funding fee (subsequent use). Default is 2.15%% (first use).",
    )

    # Operating costs (override defaults)
    parser.add_argument(
        "--tax-pct",
        type=float,
        default=None,
        help="Annual property tax rate in percent (e.g. 2.2) [default: 2.2 Bexar County]",
    )
    parser.add_argument(
        "--hoa", type=float, default=0.0, help="Monthly HOA fee [default: 0]"
    )
    parser.add_argument(
        "--vacancy",
        type=float,
        default=None,
        help="Vacancy rate in percent (e.g. 5) [default: 5]",
    )
    parser.add_argument(
        "--maintenance",
        type=float,
        default=None,
        help="Maintenance reserve in percent of rent (e.g. 9) [default: 9]",
    )
    parser.add_argument(
        "--mgmt-phase2",
        type=float,
        default=None,
        help="Management fee Phase 2 in percent (e.g. 8) [default: 8]",
    )
    parser.add_argument(
        "--hold-years", type=int, default=3, help="Hold period in years [default: 3]"
    )
    parser.add_argument(
        "--selling-cost",
        type=float,
        default=None,
        help="Selling cost percent (e.g. 8) [default: 8]",
    )

    # Military
    parser.add_argument(
        "--bah",
        type=float,
        default=0.0,
        help="Monthly BAH (Basic Allowance for Housing) [default: 0]",
    )

    # Rent
    parser.add_argument(
        "--rent-override",
        type=float,
        default=None,
        help="Per-unit monthly rent (unit mode) or per-room rate (room-hack mode). "
        "Optional: pipeline est_room_rent is used as fallback for room-hack mode. "
        "Use when you have actual comparable listings to verify the estimate.",
    )

    # Output
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format [default: text]",
    )
    parser.add_argument(
        "--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )

    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(levelname)s | %(message)s",
    )

    # Normalize loan type
    loan_type = "VA" if args.loan_type.upper() in ("VA",) else "Conventional"
    down_pct = args.down_pct / 100.0
    rate = args.rate / 100.0

    prop = PropertyInput(
        zip_code=args.zip,
        asking_price=args.price,
        units=args.units,
        bedrooms=args.bedrooms,
        hack_fraction=args.hack_fraction,
        loan_type=loan_type,
        down_pct=down_pct,
        interest_rate=rate,
        loan_term_years=args.term,
        va_first_use=not args.va_second_use,
        property_tax_pct=args.tax_pct / 100.0 if args.tax_pct is not None else 0.022,
        hoa_monthly=args.hoa,
        vacancy_rate=args.vacancy / 100.0 if args.vacancy is not None else 0.05,
        maintenance_pct=(
            args.maintenance / 100.0 if args.maintenance is not None else 0.09
        ),
        mgmt_fee_phase2=(
            args.mgmt_phase2 / 100.0 if args.mgmt_phase2 is not None else 0.08
        ),
        hold_years=args.hold_years,
        selling_cost_pct=(
            args.selling_cost / 100.0 if args.selling_cost is not None else 0.08
        ),
        bah_monthly=args.bah,
        rent_override=args.rent_override,
        rooms_rented=args.rooms_rented,
    )

    try:
        results = analyze_property(prop)
    except (FileNotFoundError, ValueError) as e:
        print(f"\nError: {e}\n", file=sys.stderr)
        sys.exit(1)

    if args.output == "json":
        # Serialize key results to JSON (excluding non-serializable objects like pandas Series)
        row = results["row"]
        export = {
            "zip": prop.zip_code,
            "asking_price": prop.asking_price,
            "units": prop.units,
            "loan_type": prop.loan_type,
            "interest_rate": prop.interest_rate,
            "median_rent": results["median_rent"],
            "gross_yield": round(results["gross_yield"], 4),
            "home_value": results["home_value"],
            "zhvf_12mo": results["zhvf_12mo"],
            "rank": results["rank"],
            "score": results["score"],
            "commute_min": results["commute_min"],
            "cashflow_phase1_net": round(results["cf_p1"]["net"], 2),
            "cashflow_phase2_net": round(results["cf_p2"]["net"], 2),
            "breakeven_price": round(results["breakeven_price"], 0),
            "yield_targets": {
                f"{k:.1%}": round(v["max_price"], 0)
                for k, v in results["yield_targets"].items()
            },
            "pnl_scenarios": [
                {
                    "label": s["label"],
                    "exit_price": round(s["exit_price"], 0),
                    "net_proceeds": round(s["net_proceeds"], 0),
                    "total_return": round(s["total_return"], 0),
                }
                for s in results["pnl_scenarios"]
            ],
            "filters": {
                k: {"pass": v["pass"], "value": v["value"]}
                for k, v in results["filters"].items()
            },
            "scorecard": results["scorecard"],
        }
        print(json.dumps(export, indent=2))
    else:
        print_report(results)


if __name__ == "__main__":
    main()
