"""
analyze_listings.py
-------------------
Analyze one or more property listings defined in a JSON or YAML file.

Designed for users who collect listings from Zillow, Realtor.com, etc. into a
structured file and want to evaluate them all against the pipeline's ZIP-level
market data in a single run.

Single listing → full property report (same as analyze_property.py).
Multiple listings → per-listing reports + a ranked comparison table at the end.

Usage:
    # Analyze listings defined in a JSON file
    python analyze_listings.py --file examples/listings_template.json

    # YAML is also supported
    python analyze_listings.py --file my_listings.yaml

    # Export comparison as JSON (only the summary table, not full reports)
    python analyze_listings.py --file examples/listings_template.json --output json

    # Suppress per-listing full reports; show only comparison table
    python analyze_listings.py --file examples/listings_template.json --summary-only

File format (JSON):
    {
      "defaults": {           <- optional; applied to every listing unless overridden
        "loan_type": "VA",
        "bah_monthly": 1900,
        "rate": 6.875,
        "term": 30
      },
      "listings": [
        {
          "label": "123 Oak Ave",   <- optional display name
          "zip": "78239",
          "price": 265000,
          "bedrooms": 3,
          "rooms_rented": 2,
          "rent_override": 700
        },
        {
          "label": "456 Elm St",
          "zip": "78209",
          "price": 285000,
          "units": 2,
          "hoa": 120
        }
      ]
    }

See examples/listings_template.json for a fully documented template.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent / "src"))

from property_analyzer import (
    PropertyInput,
    analyze_property,
    format_report,
    print_report,
)

# ── YAML is optional ──────────────────────────────────────────────────────────
try:
    import yaml as _yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── Field name aliases: JSON key → PropertyInput field ───────────────────────
# Allows concise JSON keys ("zip", "price") alongside the full Python names.
_ALIASES: Dict[str, str] = {
    "zip": "zip_code",
    "price": "asking_price",
    "rate": "interest_rate",
    "term": "loan_term_years",
    "tax_pct": "property_tax_pct",
    "hoa": "hoa_monthly",
    "vacancy": "vacancy_rate",
    "maintenance": "maintenance_pct",
    "mgmt_phase2": "mgmt_fee_phase2",
    "hold_years": "hold_years",
    "selling_cost": "selling_cost_pct",
    "bah": "bah_monthly",
    "va_second_use": "_va_second_use",  # handled specially
}

# Fields that are stored as percentages in the JSON (e.g. 2.2 → 0.022)
_PCT_FIELDS = {
    "property_tax_pct",
    "vacancy_rate",
    "maintenance_pct",
    "mgmt_fee_phase2",
    "selling_cost_pct",
    "down_pct",
    "interest_rate",
}


def _normalise_key(key: str) -> str:
    """Resolve alias → canonical PropertyInput field name."""
    return _ALIASES.get(key, key)


def _parse_listing(raw: Dict[str, Any], defaults: Dict[str, Any]) -> Tuple[str, PropertyInput]:
    """
    Merge defaults + listing-specific values and build a PropertyInput.

    Returns (label, PropertyInput).
    """
    merged = {**defaults, **raw}

    label = merged.pop("label", None)

    # Resolve aliases
    resolved: Dict[str, Any] = {}
    va_second_use = False
    for k, v in merged.items():
        canonical = _normalise_key(k)
        if canonical == "_va_second_use":
            va_second_use = bool(v)
        else:
            resolved[canonical] = v

    # Percentage conversions: JSON stores human-readable numbers (e.g. 6.875),
    # PropertyInput expects fractional (0.06875) for rate, tax, etc.
    for field in _PCT_FIELDS:
        if field in resolved and resolved[field] is not None:
            val = float(resolved[field])
            # Heuristic: if >1 it's been written as a percentage (e.g. 6.875 not 0.06875)
            if val > 1.0:
                resolved[field] = val / 100.0

    # Normalise loan_type
    if "loan_type" in resolved:
        lt = str(resolved["loan_type"]).upper()
        resolved["loan_type"] = "VA" if lt in ("VA",) else "Conventional"

    resolved["va_first_use"] = not va_second_use

    # zip_code must be a string
    if "zip_code" in resolved:
        resolved["zip_code"] = str(resolved["zip_code"]).zfill(5)

    # Drop any keys that aren't PropertyInput fields
    valid_fields = {f.name for f in PropertyInput.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    # __dataclass_fields__ is a standard dataclass attribute
    filtered = {k: v for k, v in resolved.items() if k in valid_fields}

    prop = PropertyInput(**filtered)
    display_label = label or f"{prop.zip_code} @ ${prop.asking_price:,.0f}"
    return display_label, prop


def load_listings_file(path: Path) -> Tuple[Dict[str, Any], List[Tuple[str, PropertyInput]]]:
    """
    Parse a JSON or YAML listings file.

    Returns (raw_data_dict, [(label, PropertyInput), ...]).
    """
    suffix = path.suffix.lower()
    text = path.read_text()

    if suffix in (".yaml", ".yml"):
        if not _YAML_AVAILABLE:
            raise ImportError(
                "PyYAML is not installed. Run: pip install pyyaml\n"
                "Or use a .json file instead."
            )
        data = _yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        # Try JSON first, then YAML
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            if _YAML_AVAILABLE:
                data = _yaml.safe_load(text)
            else:
                raise ValueError(
                    f"Cannot parse '{path}'. Use a .json or .yaml extension."
                )

    if not isinstance(data, dict):
        raise ValueError("Listings file must be a JSON/YAML object with a 'listings' key.")
    if "listings" not in data:
        raise ValueError("Listings file must contain a 'listings' array.")
    if not data["listings"]:
        raise ValueError("'listings' array is empty — nothing to analyze.")

    defaults = data.get("defaults", {})
    listings = [_parse_listing(raw, defaults) for raw in data["listings"]]
    return data, listings


def _verdict_rank(verdict: str) -> int:
    """Sort order for comparison table: BUY first, SKIP last."""
    return {"BUY": 0, "CAUTION": 1, "SKIP": 2}.get(verdict, 3)


def _format_comparison_table(rows: List[Dict[str, Any]]) -> str:
    """
    Render a compact comparison table for multiple listings.

    Columns: Rank | Label | ZIP | Score | P1 Net | P2 Net | Yield | Verdict
    """
    COL_W = {
        "rank": 4,
        "label": 28,
        "zip": 6,
        "score": 6,
        "p1": 10,
        "p2": 10,
        "yield": 7,
        "verdict": 14,
    }

    def _trunc(s: str, w: int) -> str:
        return s[:w] if len(s) > w else s.ljust(w)

    def _money(v: Optional[float]) -> str:
        if v is None:
            return "N/A".ljust(10)
        sign = "+" if v >= 0 else "-"
        return f"{sign}${abs(v):,.0f}".ljust(10)

    header = (
        f"{'#':<{COL_W['rank']}} "
        f"{'Listing':<{COL_W['label']}} "
        f"{'ZIP':<{COL_W['zip']}} "
        f"{'Score':<{COL_W['score']}} "
        f"{'P1/mo':<{COL_W['p1']}} "
        f"{'P2/mo':<{COL_W['p2']}} "
        f"{'Yield':<{COL_W['yield']}} "
        f"{'Verdict':<{COL_W['verdict']}}"
    )
    sep = "-" * len(header)

    lines = [
        "",
        "=" * len(header),
        "  LISTING COMPARISON (ranked by verdict → score)",
        "=" * len(header),
        header,
        sep,
    ]

    for i, row in enumerate(rows, 1):
        label = _trunc(row["label"], COL_W["label"])
        score_str = f"{row['score']:.3f}" if row["score"] is not None else "N/A"
        yield_str = f"{row['yield']:.1%}" if row["yield"] is not None else "N/A"
        line = (
            f"{i:<{COL_W['rank']}} "
            f"{label} "
            f"{row['zip']:<{COL_W['zip']}} "
            f"{score_str:<{COL_W['score']}} "
            f"{_money(row['p1_net'])} "
            f"{_money(row['p2_net'])} "
            f"{yield_str:<{COL_W['yield']}} "
            f"{row['verdict']:<{COL_W['verdict']}}"
        )
        lines.append(line)

    lines += [sep, ""]
    return "\n".join(lines)


def _run_all(
    listings: List[Tuple[str, PropertyInput]],
    summary_only: bool,
    output_json: bool,
) -> List[Dict[str, Any]]:
    """
    Analyze all listings. Print per-listing reports unless summary_only.
    Returns a list of summary dicts for the comparison table / JSON output.
    """
    summary_rows = []

    for label, prop in listings:
        if not summary_only:
            divider = f"\n{'━' * 70}\n  {label}\n{'━' * 70}"
            print(divider)

        try:
            results = analyze_property(prop)
        except (FileNotFoundError, ValueError) as exc:
            error_row: Dict[str, Any] = {
                "label": label,
                "zip": prop.zip_code,
                "price": prop.asking_price,
                "score": None,
                "p1_net": None,
                "p2_net": None,
                "yield": None,
                "verdict": "ERROR",
                "error": str(exc),
            }
            summary_rows.append(error_row)
            if not summary_only:
                print(f"\n  Error: {exc}\n")
            continue

        verdict_raw = results.get("conditions", {}).get("_verdict", "?")
        summary_row: Dict[str, Any] = {
            "label": label,
            "zip": prop.zip_code,
            "price": prop.asking_price,
            "score": results.get("score"),
            "p1_net": results["cf_p1"].get("net"),
            "p2_net": results["cf_p2"].get("net"),
            "yield": results.get("gross_yield"),
            "verdict": verdict_raw,
        }
        summary_rows.append(summary_row)

        if not summary_only and not output_json:
            print_report(results)

    return summary_rows


def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyze one or more listings from a JSON/YAML file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="Path to a JSON or YAML listings file.",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format [default: text]",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the comparison table, skip per-listing full reports.",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(levelname)s | %(message)s",
    )

    listings_path = Path(args.file)
    if not listings_path.exists():
        print(f"\nError: file not found: {listings_path}\n", file=sys.stderr)
        sys.exit(1)

    try:
        _raw_data, listings = load_listings_file(listings_path)
    except (ValueError, ImportError, json.JSONDecodeError) as exc:
        print(f"\nError parsing listings file: {exc}\n", file=sys.stderr)
        sys.exit(1)

    summary_only = args.summary_only or args.output == "json"
    rows = _run_all(listings, summary_only=summary_only, output_json=args.output == "json")

    # Sort: BUY → CAUTION → SKIP → ERROR, then by score descending
    rows.sort(
        key=lambda r: (_verdict_rank(r["verdict"]), -(r["score"] or -999))
    )

    if args.output == "json":
        print(json.dumps(rows, indent=2))
    else:
        if len(listings) > 1:
            print(_format_comparison_table(rows))
        elif rows and rows[0].get("error"):
            print(f"\nError: {rows[0]['error']}\n", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
