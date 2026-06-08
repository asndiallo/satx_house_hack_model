"""
webapp/app.py
-------------
API + static file server for the SATX House Hack results dashboard.

Usage:
    uvicorn webapp.app:app --reload
    then open http://localhost:8000
"""

import asyncio
import copy
import hashlib
import io
import json
import math
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from cache_manager import CacheManager
from config import CACHE_DIR

# Always run pipeline subprocesses with the project venv if it exists,
# regardless of what Python launched the server.
_VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PIPELINE_PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable

RANKED_CSV = ROOT / "data" / "final" / "ranked_zip_scores.csv"
STATIC_DIR = Path(__file__).parent / "static"

_cache = CacheManager(CACHE_DIR)

app = FastAPI(title="SATX House Hack", docs_url=None, redoc_url=None)

# Neighborhood names for San Antonio area ZIP codes.
# Most SA ZIPs return "San Antonio" from USPS/zippopotam — this gives
# meaningful sub-city names for house-hacking purposes.
ZIP_NAMES: dict[str, str] = {
    "78109": "Converse",
    "78148": "Universal City",
    "78150": "Randolph AFB",
    "78154": "Schertz",
    "78201": "Woodlawn Hills",
    "78202": "Dignowity Hill",
    "78203": "Lavaca / Near Southside",
    "78204": "King William / Near Westside",
    "78205": "Downtown SA",
    "78206": "Near North Side",
    "78207": "Lanier / West Side",
    "78208": "Eastside",
    "78209": "Alamo Heights / Terrell Hills",
    "78210": "Southtown / Riverside",
    "78211": "Palo Alto / South Side",
    "78212": "Monte Vista / Brackenridge",
    "78213": "Northwest SA",
    "78214": "Mission District",
    "78215": "Government Hill",
    "78216": "Airport / North Central",
    "78217": "Thousand Oaks",
    "78218": "Randolph Heights / NE SA",
    "78219": "Kirby / East SA",
    "78220": "Rigsby / East SA",
    "78221": "Brooks City Base",
    "78222": "Southeast SA",
    "78223": "South SA / Southeast",
    "78224": "South SA / Cassin",
    "78225": "Kelly Area / South SA",
    "78226": "Southwest SA",
    "78227": "Lackland Hills / West SA",
    "78228": "Woodlawn / West SA",
    "78229": "Medical Center",
    "78230": "USAA Area / NW SA",
    "78231": "Northwest SA",
    "78232": "North Central SA",
    "78233": "Forum / Northeast SA",
    "78234": "Fort Sam Houston",
    "78235": "South SA / Military",
    "78236": "Lackland AFB",
    "78237": "West SA / Harlandale",
    "78238": "West SA / Lackland",
    "78239": "Windcrest / Universal City",
    "78240": "Medical District / NW SA",
    "78241": "East SA",
    "78242": "Lackland Hills / SW SA",
    "78243": "Port San Antonio",
    "78244": "East SA / Converse Border",
    "78245": "Westover Hills / Lackland",
    "78247": "North SA / Stone Oak South",
    "78248": "Shavano Park",
    "78249": "UTSA / NW SA",
    "78250": "Bandera / NW SA",
    "78251": "Northwest SA",
    "78252": "Southwest SA",
    "78253": "Alamo Ranch / NW SA",
    "78254": "Helotes Area",
    "78255": "Leon Springs",
    "78256": "Fair Oaks Ranch",
    "78257": "Shavano Park North",
    "78258": "Stone Oak",
    "78259": "Stone Oak / NE SA",
    "78260": "Bulverde / Far North",
    "78261": "Schertz Area / Far NE",
    "78263": "China Grove",
    "78264": "South SA",
    "78266": "Schertz Area",
    # Guadalupe County suburbs
    "78108": "Cibolo",
    "78124": "Marion / Guadalupe",
    "78130": "New Braunfels",
    "78132": "New Braunfels East",
    "78155": "Seguin",
    # Comal / Kendall County
    "78006": "Boerne",
    "78015": "Boerne East",
    "78070": "Spring Branch",
    # Medina / Atascosa County
    "78059": "Natalia",
    "78065": "Pleasanton Area",
}

# Texas statewide ZIP boundary GeoJSON — filtered server-side before serving
_TX_GEOJSON_URL = (
    "https://raw.githubusercontent.com/OpenDataDE/State-zip-code-GeoJSON"
    "/master/tx_texas_zip_codes_geo.min.json"
)

# Full San Antonio metro area — all ZIPs shown as gray context on the map.
# Scored ZIPs are a subset; everything else provides geographic grounding.
# Includes Bexar County core (78201–78269) + SA suburbs across Guadalupe,
# Comal, Atascosa, and Medina counties that are in the SA MSA.
_SA_AREA_ZIPS = {str(z) for z in range(78201, 78270)} | {
    # Bexar County fringe / JBSA
    "78109", "78148", "78150", "78154", "78266",
    # Guadalupe County suburbs
    "78108",  # Cibolo
    "78124",  # Marion / Guadalupe area
    "78130",  # New Braunfels
    "78132",  # New Braunfels east
    "78155",  # Seguin
    # Comal County suburbs
    "78006",  # Boerne area / Kendall County
    "78015",  # Boerne
    "78070",  # Spring Branch
    # Medina / Atascosa County
    "78059",  # Natalia
    "78065",  # Pleasanton area
}


def _sanitize(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _deep_sanitize(obj):
    """Recursively replace NaN/Inf floats with None for JSON compliance."""
    if isinstance(obj, dict):
        return {k: _deep_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _load_results_df() -> pd.DataFrame:
    if not RANKED_CSV.exists():
        raise HTTPException(
            status_code=404,
            detail="ranked_zip_scores.csv not found — run `python main.py` first.",
        )
    df = pd.read_csv(RANKED_CSV, dtype={"zip": str})
    df["place_name"] = df["zip"].map(lambda z: ZIP_NAMES.get(z, z))
    return df


def _fetch_tx_geojson_raw() -> dict:
    """Download Texas ZIP GeoJSON (22 MB), cache for 1 year. Returns raw dict."""
    cached = _cache.get("tx_zip_geojson", ttl_hours=8760)
    if cached is not None:
        return cached
    resp = requests.get(_TX_GEOJSON_URL, timeout=60)
    resp.raise_for_status()
    geo = resp.json()
    _cache.set("tx_zip_geojson", geo, source="opendata_de_github")
    return geo


def _fetch_sa_area_geojson() -> list:
    """
    Filter the full Texas GeoJSON to all SA metro ZIPs and cache the subset.
    Called once on first map load; subsequent calls hit the small cached list.
    """
    cached = _cache.get("sa_area_geojson", ttl_hours=8760)
    if cached is not None:
        return cached
    tx_geo = _fetch_tx_geojson_raw()
    features = [
        f for f in tx_geo.get("features", [])
        if f.get("properties", {}).get("ZCTA5CE10") in _SA_AREA_ZIPS
    ]
    _cache.set("sa_area_geojson", features, source="tx_geojson_sa_area")
    return features


@app.get("/api/results")
def get_results():
    df = _load_results_df()
    records = [
        {k: _sanitize(v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]
    return JSONResponse(content=records)


@app.get("/api/geojson")
def get_geojson():
    """
    Returns GeoJSON covering the full SA metro area.
    Scored ZIPs get _scored=True + all pipeline columns.
    Unscored SA ZIPs get _scored=False + place_name only (gray context on map).
    """
    df = _load_results_df()
    scored_set = set(df["zip"].tolist())

    try:
        all_features = _fetch_sa_area_geojson()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ZIP boundary fetch failed: {exc}")

    features = copy.deepcopy(all_features)
    score_map = df.set_index("zip").to_dict(orient="index")

    for feature in features:
        zcta = feature["properties"].get("ZCTA5CE10")
        if not zcta:
            continue
        if zcta in scored_set:
            feature["properties"]["zip"] = zcta
            feature["properties"]["_scored"] = True
            feature["properties"].update(
                {k: _sanitize(v) for k, v in score_map[zcta].items()}
            )
        else:
            feature["properties"]["zip"] = zcta
            feature["properties"]["_scored"] = False
            feature["properties"]["place_name"] = ZIP_NAMES.get(zcta, zcta)

    return JSONResponse(content={"type": "FeatureCollection", "features": features})


@app.get("/api/run-pipeline/stream")
async def run_pipeline_stream():
    """
    SSE endpoint — streams pipeline stdout+stderr line-by-line as it runs.
    Sends a final `event: done` with data `ok` or `error:<returncode>`.
    """
    async def event_gen():
        proc = await asyncio.create_subprocess_exec(
            PIPELINE_PYTHON, str(ROOT / "main.py"), "--no-google-maps",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge so all output is visible
            cwd=str(ROOT),
        )
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            yield f"data: {line}\n\n"
        await proc.wait()
        status = "ok" if proc.returncode == 0 else f"error:{proc.returncode}"
        yield f"event: done\ndata: {status}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Property Analysis by Address ─────────────────────────────────────────────

class AddressLookupRequest(BaseModel):
    address: str


class AnalyzeAddressRequest(BaseModel):
    address: str
    price: float
    bah: float = 0.0
    rooms_rented: Optional[int] = None
    bedrooms: Optional[int] = None      # override auto-detected value
    units: Optional[int] = None         # override auto-detected value
    rent_override: Optional[float] = None
    rate: float = 6.875
    loan_type: str = "VA"
    va_second_use: bool = False
    down_pct: float = 0.0
    hoa: float = 0.0


def _load_property_modules():
    """Lazy-import src modules so they don't block server startup."""
    from property_analyzer import lookup_property, PropertyInput, analyze_property, format_report
    return lookup_property, PropertyInput, analyze_property, format_report


def _serialize_analysis(results: dict) -> dict:
    """Convert property analysis results to a JSON-serializable dict."""
    row = results.get("row")
    cf1 = results["cf_p1"]
    cf2 = results["cf_p2"]
    prop = results.get("prop")
    zip_code = (prop.zip_code if prop else None) or (
        str(row["zip"]) if row is not None and "zip" in row.index else None
    )

    return {
        "zip": zip_code,
        "score": results.get("score"),
        "rank": results.get("rank"),
        "median_rent": results.get("median_rent"),
        "gross_yield": round(results.get("gross_yield", 0), 4),
        "home_value": results.get("home_value"),
        "commute_min": results.get("commute_min"),
        "zhvf_12mo": results.get("zhvf_12mo"),
        "breakeven_price": round(results.get("breakeven_price", 0), 0),
        "cashflow": {
            "phase1_net": round(cf1.get("net", 0), 2),
            "phase1_net_with_bah": round(cf1.get("net_with_bah", cf1.get("net", 0)), 2),
            "phase1_pi": round(cf1.get("pi", 0), 2),
            "phase1_income": round(cf1.get("gross_rent", 0), 2),
            "phase2_net": round(cf2.get("net", 0), 2),
            "phase2_income": round(cf2.get("gross_rent", 0), 2),
            "phase2_pi": round(cf2.get("pi", 0), 2),
        },
        "yield_targets": {
            f"{k:.1%}": round(v["max_price"], 0)
            for k, v in results.get("yield_targets", {}).items()
        },
        "pnl_scenarios": [
            {
                "label": s["label"],
                "exit_price": round(s["exit_price"], 0),
                "net_proceeds": round(s["net_proceeds"], 0),
                "total_return": round(s["total_return"], 0),
            }
            for s in results.get("pnl_scenarios", [])
        ],
        "filters": {
            k: {"pass": v["pass"], "value": _sanitize(v["value"])}
            for k, v in results.get("filters", {}).items()
        },
        "scorecard": _deep_sanitize(results.get("scorecard", {})),
        "conditions": _deep_sanitize(results.get("conditions", {})),
        "verdict": results.get("conditions", {}).get("_verdict", "?"),
    }


@app.post("/api/lookup-address")
def lookup_address_endpoint(req: AddressLookupRequest):
    """
    Geocode an address and fetch BCAD parcel data.
    Returns ZIP code, lat/lng, estimated bedrooms/units from county records.
    Note: parcel data only available for Bexar County properties.
    """
    try:
        lookup_property, *_ = _load_property_modules()
        result = lookup_property(req.address)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return JSONResponse(content={
        "address": result.address,
        "zip_code": result.zip_code,
        "lat": result.lat,
        "lng": result.lng,
        "units": result.units,
        "estimated_bedrooms": result.estimated_bedrooms,
        "gba_sqft": result.gba_sqft,
        "year_built": result.year_built,
        "assessed_value": result.assessed_value,
        "bcad_address": result.bcad_address,
        "bcad_found": result.bcad_found,
        "state_cd": result.state_cd,
        "warnings": result.warnings,
    })


@app.post("/api/analyze-address")
def analyze_address_endpoint(req: AnalyzeAddressRequest):
    """
    Full property analysis from a street address + asking price.

    Geocodes the address to extract ZIP code, queries BCAD for parcel data
    (bedrooms, units), then runs the full house-hack model.
    """
    try:
        lookup_property, PropertyInput, analyze_property, _ = _load_property_modules()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Module load error: {exc}")

    # Step 1: geocode + BCAD lookup
    try:
        lookup = lookup_property(req.address)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Step 2: resolve bedrooms and units (user override > BCAD > defaults)
    bedrooms = req.bedrooms or lookup.estimated_bedrooms or 3
    units = req.units or lookup.units or 1
    rooms_rented = req.rooms_rented
    # Default room-hack: rent (bedrooms - 1) rooms, keep 1
    if rooms_rented is None and units == 1:
        rooms_rented = max(1, bedrooms - 1)

    loan_type = "VA" if req.loan_type.upper() == "VA" else "Conventional"

    prop = PropertyInput(
        zip_code=lookup.zip_code,
        asking_price=req.price,
        units=units,
        bedrooms=bedrooms,
        rooms_rented=rooms_rented if units == 1 else None,
        loan_type=loan_type,
        down_pct=req.down_pct / 100.0,
        interest_rate=req.rate / 100.0,
        va_first_use=not req.va_second_use,
        hoa_monthly=req.hoa,
        bah_monthly=req.bah,
        rent_override=req.rent_override,
    )

    # Step 3: run analysis
    try:
        results = analyze_property(prop)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc) + " — run `python main.py` first to build the pipeline data.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    output = _serialize_analysis(results)
    output["lookup"] = {
        "address": lookup.address,
        "zip_code": lookup.zip_code,
        "bcad_found": lookup.bcad_found,
        "bcad_address": lookup.bcad_address,
        "gba_sqft": lookup.gba_sqft,
        "year_built": lookup.year_built,
        "assessed_value": lookup.assessed_value,
        "warnings": lookup.warnings,
    }
    output["inputs"] = {
        "bedrooms": bedrooms,
        "units": units,
        "rooms_rented": rooms_rented,
        "price": req.price,
    }
    return JSONResponse(content=_deep_sanitize(output))


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
