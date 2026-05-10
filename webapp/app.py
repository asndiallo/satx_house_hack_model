"""
webapp/app.py
-------------
API + static file server for the SATX House Hack results dashboard.

Usage:
    uvicorn webapp.app:app --reload
    then open http://localhost:8000
"""

import copy
import hashlib
import io
import json
import math
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from cache_manager import CacheManager
from config import CACHE_DIR

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
}

# Texas statewide ZIP boundary GeoJSON — filtered server-side before serving
_TX_GEOJSON_URL = (
    "https://raw.githubusercontent.com/OpenDataDE/State-zip-code-GeoJSON"
    "/master/tx_texas_zip_codes_geo.min.json"
)

# Full San Antonio metro area — all ZIPs shown as gray context on the map.
# Scored ZIPs are a subset; everything else provides geographic grounding.
_SA_AREA_ZIPS = {str(z) for z in range(78201, 78270)} | {
    "78109", "78148", "78150", "78154", "78266",
}


def _sanitize(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


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


@app.post("/api/run-pipeline")
def run_pipeline():
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--no-google-maps"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr[-2000:])
    return {"status": "ok", "stdout": result.stdout[-2000:]}


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
