# SATX House Hack Scoring Model

A data-driven tool that ranks San Antonio ZIP codes by how well they work for a **military house hack** — buying a property near BAMC / Fort Sam Houston, living in part of it, and renting out the rest to offset or eliminate your mortgage payment.

Built around the realities of military life: fixed duty station, 3-year typical hold period, VA loan eligibility, and a tenant pool that skews heavily military.

---

## What Is a House Hack?

A house hack means buying a property where part of it generates rental income while you live there. Common setups:

- **Duplex/triplex/fourplex** — you live in one unit, rent the others
- **Single-family home with extra rooms** — rent bedrooms to roommates
- **Garage apartment or ADU** — rent a separate structure on the same lot

The goal: your tenants pay your mortgage. In the best cases, you live for free or even cash flow positive. After your PCS, you convert the whole property to a full rental.

---

## What This Tool Does

This model pulls publicly available data for the San Antonio metro and scores every ZIP code across five dimensions that matter specifically for a military house hack:

1. **Crime rate** — Is it safe enough to actually live there?
2. **Rent-to-price ratio** — Will the rental income cover the mortgage?
3. **Owner-occupancy rate** — Is this a stable neighborhood or a transient one?
4. **Commute to BAMC** — How far is it from where you actually work?
5. **Price stability** — Will the home hold or grow its value over a 3-year hold?

It produces a ranked shortlist so you can focus your property search on ZIPs that make objective sense — instead of spending months Zillow-scrolling based on gut feel.

**What this tool is NOT:** It does not replace boots-on-the-ground research. It narrows your universe from 60+ ZIP codes down to ~10–15 worth seriously investigating. You still need to look at actual listings, drive the neighborhoods, and run the numbers on specific properties.

---

## The Philosophy: Path B (Military House Hack Logic)

Most real estate scoring tools are built for pure investors. They treat every factor as negotiable — a high yield can compensate for crime, a short commute can compensate for instability. Everything trades off against everything else.

**This model is built differently.** It uses what's called Path B logic:

> _Screen out unacceptable risk first. Then optimize within what's left._

For a military house hack, some things genuinely are not tradeable:

- You **live in the property** — crime is not negotiable against yield
- You need the property to **cashflow** — not just look attractive on paper
- You will **PCS in 3 years** — price stability matters as much as appreciation upside
- Your tenants are likely **military or military-adjacent** — the neighborhood has to be one they'd choose

Anything you're unwilling to compromise on becomes a **filter** that removes ZIPs before scoring. Everything else is a **scored weight** that ranks the survivors. That distinction — filter vs. weight — is the core design principle of this model.

---

## The Two-Stage Decision

### Stage 1 — Hard Filters (non-negotiable gates)

ZIPs that fail any of these are removed entirely and never scored:

| Filter                | Threshold    | Why                                                                                                    |
| --------------------- | ------------ | ------------------------------------------------------------------------------------------------------ |
| Minimum gross yield   | 3.5%         | Room-hack floor: `(est_room_rent × rooms_rented × 12) / home_value`. Lowered to accommodate multifamily ZIPs where rental-dense neighborhoods are the goal. |
| Maximum home price    | $450,000     | SA conforming VA loan limit — adjust to your COE.                                                      |
| Owner-occupancy range | 35%–85%      | Below 35% = too transient. Above 85% = low rental demand and harder PCS exit. Floor lowered from 50% to capture rental-dense neighborhoods suited for house hacking. |
| Minimum median income | $42,000      | Tenant base quality screen. Correlates with delinquency risk and resale strength. $42k ≈ E-5/E-6 BAH + base pay in SA. |
| Commute to BAMC       | ≤ 35 min     | You drive this daily. ZIPs beyond this are not candidates regardless of yield. Uses real Google Maps drive time when available; falls back to straight-line Haversine. |

**Crime is flagged, not hard-filtered.** SA SAPD Calls for Service data produces heavily inflated per-1k rates in many ZIP codes (commercial corridors, mixed-use areas with small residential populations). Removing ZIPs on a percentile cutoff throws away genuinely livable neighborhoods. Instead, every surviving ZIP gets a crime flag visible in all output — so you see the risk without the model silently discarding your candidates.

### Stage 2 — Scored Ranking (graded optimization)

Surviving ZIPs are ranked by a weighted composite of five factors:

| Factor               | Weight | Role                                                                                        |
| -------------------- | ------ | ------------------------------------------------------------------------------------------- |
| Crime rate           | 30%    | Highest weight — neighborhood safety drives livability and tenant quality                   |
| Owner-occupancy rate | 25%    | Tenants share your home in a room hack — neighborhood character matters more than in a duplex |
| Rent-to-price ratio  | 20%    | Per-room yield signal, capped at 12% (above = suspicious)                                  |
| Commute to BAMC      | 15%    | Daily quality of life — but safety ranks above it                                           |
| Price stability      | 10%    | 5-year ZHVI volatility — for a 3-year hold, boring beats exciting                          |

---

## Crime Flags

Instead of removing ZIPs with high crime, the model flags every ZIP relative to the surviving pool:

| Flag           | Meaning                                                                                      |
| -------------- | -------------------------------------------------------------------------------------------- |
| `LOW`          | Bottom tercile of the candidate pool — safest group                                          |
| `ELEVATED`     | Middle tercile — worth investigating but not disqualifying                                   |
| `HIGH`         | Top tercile — 30% crime weight pushes these down; review carefully before committing         |
| `DATA_SUSPECT` | Above 700/1k — likely a commercial corridor or data artifact; CFS methodology inflates rates |

The `DATA_SUSPECT` threshold (700/1k) is calibrated to SA CFS data: the median SA ZIP is ~370/1k and the 90th percentile is ~750/1k. Values this high almost always reflect denominator issues (small residential population, large commercial activity) rather than a genuinely unlivable neighborhood. Ground-truth: 78227 at ~580/1k is a normal residential neighborhood.

---

## The Five Scoring Factors, Explained

### 1. Crime Rate (30% of score)

**What it measures:** Reported criminal incidents per 1,000 residents, filtered to actual crimes — assault, robbery, burglary, theft, narcotics, homicide. Traffic stops, noise complaints, and medical calls are excluded.

**Log-transformed before scoring:** Crime distributions are heavily skewed. Without transformation, one extreme outlier ZIP stretches the scale so that crime=25 and crime=200 look nearly identical. Log-transformation compresses the tail so every step up in crime is meaningfully penalized.

**What to look at in results:** The `crime_per_1k` column and `crime_flag`. Below 50 is genuinely quiet. 50–150 is moderate suburban. Above 300 should prompt a windshield survey before committing.

One data cleaning step worth knowing: ZIPs with fewer than 5,000 Census residents are excluded from crime scoring entirely. Commercial corridors and fringe areas can have near-zero resident populations but high dispatch activity — producing absurd rates that would corrupt the entire distribution if included.

### 2. Rent-to-Price Ratio (20% of score)

**What it measures:** Per-room annual rental income divided by home purchase price — a room-hack-specific yield signal.

**Room-hack formula:** `(est_room_rent × TARGET_ROOMS_RENTED × 12) / home_value`

Where `est_room_rent = ZORI / TARGET_BEDROOMS` (3-bed SFR assumption). `TARGET_ROOMS_RENTED = 2`.

**The 12% yield cap:** In SA, gross yields above 12% almost always mean distressed pricing, deferred maintenance, or data noise. Capping yield at 12% before scoring prevents these ZIPs from ranking artificially high on yield while hiding structural problems.

**Yield normalization is anchored to config constants** (not pool min/max) so scores are stable across pipeline runs — a ZIP with 8% yield always scores ~0.40 regardless of which other ZIPs survived the filters.

### 3. Owner-Occupancy Rate (25% of score)

**What it measures:** Percentage of homes in the ZIP that are owner-occupied vs. renter-occupied, from U.S. Census data.

**Why 25% weight:** In a room hack, your tenants live inside your home. Neighborhood character and the type of people who choose to live there matter even more than in a duplex setup with physical separation.

**Why the 35%–85% target band:** Below 35% = primarily transient renters = not the tenant pool you want sharing your home. Above 85% = low rental demand, harder to find tenants, and harder PCS exit. The lower floor (35% vs. the 50% common in SFR-focused models) is intentional — rental-dense neighborhoods have more multifamily inventory and stronger tenant demand, which fits the multifamily house hack strategy.

### 4. Commute to BAMC (15% of score)

**What it measures:** Drive time from each ZIP code's geographic center to Brooke Army Medical Center.

**Google Maps with 1-year cache:** When an API key is configured in `.env`, real drive times are fetched once and cached for 1 year. Falls back to Haversine straight-line estimates with a ~30% road correction factor if no key is available.

**Why it's 15%, not higher:** Commute matters — you drive it every day. But safety and cashflow rank above it. A 25-minute commute to a safe, cashflowing property beats a 10-minute commute to somewhere you're uneasy living.

### 5. Price Stability (10% of score)

**What it measures:** How much a ZIP's home values have varied over the last 5 years, using the Coefficient of Variation (standard deviation ÷ average) of monthly Zillow ZHVI data.

**Lower CoV = better.** A `zhvi_cov` of 0.05 means prices were very stable. A CoV of 0.20 means the market was volatile.

**CoV vs. CAGR:** CoV measures the _bumpiness_ of the price path. CAGR (`zhvi_cagr_5yr`, `zhvi_cagr_10yr`) measures the _direction_. For a 3-year hold, CoV matters more (risk of being underwater at PCS). For a 5–15 year hold, 10yr CAGR matters more. The output includes both.

---

## How the Final Score Is Calculated

```
Final Score = (Crime × 0.30) + (Owner Occ × 0.25) + (Yield × 0.20) + (Commute × 0.15) + (Stability × 0.10)
```

Each component is normalized 0–1 relative to the surviving ZIP pool before combining. **Scores are relative, not absolute.** A crime score of 0.8 means "safer than 80% of ZIPs that passed the hard filters" — not "objectively safe."

This is why you should always read the raw columns (`crime_per_1k`, `crime_flag`, `rent_to_price`, `commute_minutes`, `zhvi_cov`) alongside the score. The score tells you rank. The raw numbers tell you reality.

---

## Data Sources

All data is fetched automatically on first run and cached locally. **No manual downloads required.**

| Source | What It Provides | Cache TTL |
| ------ | ---------------- | --------- |
| Zillow ZHVI | Monthly median home values by ZIP — latest value, 5-yr stability (CoV), 5yr/10yr CAGR | 7 days |
| Zillow ZORI | Monthly median asking rent by ZIP — used for yield scoring and `est_room_rent` | 7 days |
| Zillow ZHVF | ZIP-level forward price forecasts (1-, 3-, 12-month) — used by notebooks | 7 days |
| U.S. Census ACS | Owner-occupancy, household income, median rooms per unit, population by ZIP | 30 days |
| SAPD Calls for Service | Every police dispatch call in SA with incident type and ZIP — ~631 MB | 7 days |
| Census ZCTA Gazetteer | ZIP centroid lat/lng for commute distance calculation | 1 year |

Data lands in `.cache/` as `.pkl` files with `.meta.json` TTL markers. Delete any `.cache/*.pkl` file to force a refresh of that source.

---

## Setup

### 1 — Check Python

```bash
python3 --version   # need 3.9+
```

### 2 — Navigate to the project

```bash
cd path/to/satx_house_hack_model
```

### 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### 4 — (Optional) Google Maps API key

For real drive times instead of straight-line estimates. The free tier is more than enough.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Enable the **Distance Matrix API**
3. Create an API key
4. Copy `.env.example` to `.env` and paste your key: `GOOGLE_MAPS_API_KEY=your_key_here`

Without a key the model uses Haversine distance — accurate for relative ranking, not for specific trip planning.

### 5 — Run the pipeline

```bash
# Straight-line commute estimate (no API key needed)
python main.py --no-google-maps

# With Google Maps real drive times (requires .env key)
python main.py
```

**First run:** downloads all data sources (~631 MB crime file takes 30–90 seconds on a typical connection). Subsequent runs complete in under 15 seconds from cache.

### 6 — Open the web dashboard

```bash
uvicorn webapp.app:app --reload
```

Then open [http://localhost:8000](http://localhost:8000).

---

## Web Dashboard

The project includes a browser-based results dashboard at `webapp/`.

**Table view**
- All ranked ZIPs with neighborhood names, home values, yield, drive time, crime flag, CAGR, and score
- Stacked score bar shows the per-factor contribution to each ZIP's rank
- Sortable by any column; filterable by crime flag
- Click any row to jump to that ZIP on the map

**Map view**
- Full San Antonio metro ZIP polygons — scored ZIPs colored by metric, unscored ZIPs in dark gray for geographic context
- Census TIGERweb WMS layer provides ZIP boundary outlines across all of Texas when zoomed out
- BAMC marker pinned at Fort Sam Houston
- Color-by switcher: Score / Crime / Yield / Drive time
- Click any polygon for a popup with full stats, Google Maps link, and Zillow link
- Hover tooltip shows ZIP + neighborhood name

**Re-run pipeline** button triggers a fresh `main.py` run server-side and refreshes the table.

---

## Commands

```bash
# Pipeline
python main.py --no-google-maps          # straight-line commute (fast, no API key)
python main.py                           # real drive times via Google Maps
python main.py --no-google-maps --top 20 # show top 20 ZIPs
python main.py --no-google-maps --diagnose  # print data stats at every step

# Web dashboard
uvicorn webapp.app:app --reload          # http://localhost:8000

# Sensitivity testing (run after main.py)
python sensitivity.py                    # both tests, top 5, ±10% weight delta
python sensitivity.py --top 8 --delta 0.15
python sensitivity.py --test weights     # weight stability only
python sensitivity.py --test filters     # filter dependency only

# Notebooks
jupyter notebook notebooks/01_eda.ipynb
jupyter notebook notebooks/02_cashflow.ipynb
```

---

## Property Analyzer — Evaluating a Specific Listing

Once the pipeline has produced `ranked_zip_scores.csv`, you can evaluate any specific listing against your exact financing terms:

```bash
# SFR room hack — 3-bed home, rent 2 rooms
python analyze_property.py --zip 78239 --price 265000 --bedrooms 3 \
    --rooms-rented 2 --bah 1900

# SFR room hack — with actual comp rent override
python analyze_property.py --zip 78239 --price 285000 --bedrooms 4 \
    --rooms-rented 3 --rent-override 750 --bah 1900

# Duplex — live in one unit, rent the other
python analyze_property.py --zip 78109 --price 265000 --units 2 --bah 1900

# Triplex, known unit rent
python analyze_property.py --zip 78239 --price 320000 --units 3 --rent-override 1100

# Conventional loan, 5% down
python analyze_property.py --zip 78209 --price 285000 --units 2 \
    --loan-type conventional --down-pct 5

# JSON output for scripting
python analyze_property.py --zip 78239 --price 265000 --bedrooms 3 \
    --rooms-rented 2 --output json
```

### What the Report Covers

| Section | What It Shows |
| ------- | ------------- |
| **1. ZIP Market Overview** | Rank, score, median home value vs. asking, ZORI rent, commute, owner-occupancy, CAGR, ZHVF forecast |
| **2. Crime Intelligence** | Crime type breakdown, 12-month trend vs. prior year, peak day |
| **3. Negotiation Range** | Max price at each yield target (6.5–8%), break-even price where tenant rent covers all costs |
| **4. Cashflow Analysis** | Phase 1 (house hack) and Phase 2 (full rental) monthly income, expenses, and net — including homestead exemption, VA fee, BAH |
| **5. 3-Year Hold P&L** | Total return under flat, +3%, +5%, +8%/yr and ZHVF forecast appreciation scenarios |
| **6. Sensitivity Analysis** | Phase 2 net at 5–8.5% rates; Phase 1 net across hack fraction range |
| **7. Filter Status** | Pass/fail on every hard filter at the asking price, with the negotiation target to fix failures |
| **8. Decision Scorecard** | Quick yes/no checklist covering filters, cashflow, return, crime trend, and ZIP rank |

### Key Parameters

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--zip` | required | 5-digit ZIP code |
| `--price` | required | Asking price in dollars |
| `--units` | 1 | 1=SFH (room hack), 2=duplex, 3=triplex, 4=fourplex |
| `--bedrooms` | 3 | Total bedrooms in the property |
| `--rooms-rented` | — | Room-hack mode: number of bedrooms to rent |
| `--bah` | 0 | Monthly BAH — shown as offset to Phase 1 out-of-pocket cost |
| `--rent-override` | — | Per-unit or per-room rate when you have real comps |
| `--rate` | 6.875% | Interest rate in percent |
| `--loan-type` | VA | `VA` or `conventional` |
| `--down-pct` | 0 | Down payment in percent |
| `--va-second-use` | — | 3.30% funding fee flag (vs. 2.15% first use) |

---

## Reading the Results

| Column | What It Means |
| ------ | ------------- |
| `rank` | Overall rank. 1 = best. |
| `zip` | ZIP code |
| `median_home_value` | Estimated median home price (Zillow ZHVI) |
| `median_rent` | Estimated median asking rent per unit (Zillow ZORI) |
| `est_room_rent` | Per-room estimate (`ZORI / TARGET_BEDROOMS`) — used for room-hack yield |
| `rent_to_price` | Gross yield (room-hack formula). Raw value, before the 12% cap. |
| `commute_minutes` | Drive time to BAMC (Google Maps or Haversine) |
| `crime_per_1k` | Criminal incidents per 1,000 residents |
| `crime_flag` | LOW / ELEVATED / HIGH / DATA_SUSPECT — tercile within surviving pool |
| `owner_occ_pct` | % of homes owner-occupied |
| `median_hh_income` | Median household income — tenant base quality indicator |
| `zhvi_cov` | Price volatility (Coefficient of Variation). Lower = more stable. |
| `zhvi_cagr_5yr` | Annualized home value growth, last 5 years — display only |
| `zhvi_cagr_10yr` | Annualized home value growth, last 10 years — display only |
| `final_score` | Composite score 0–1. Higher = better overall. |
| `weighted_*` | Each factor's contribution — shows _why_ a ZIP ranked where it did |

**How to actually use the table:** Don't just look at `final_score` and move on. Read the weighted columns — they show what's driving the rank. A ZIP ranked #3 because of commute and yield might be a worse real-world choice than a ZIP ranked #5 with a stronger safety score.

---

## Adjusting the Model

Everything tunable is in `src/config.py`. No other file needs to be touched.

### Scoring Weights

```python
WEIGHTS = {
    "rent_to_price":   0.20,
    "crime":           0.30,
    "owner_occupancy": 0.25,
    "commute":         0.15,
    "stability":       0.10,
}
```

Must sum to 1.0 exactly. The model asserts this on startup.

### Hard Filters

```python
THRESHOLDS = {
    "min_rent_to_price": 0.035,   # room-hack yield floor
    "max_home_value":    450_000,  # VA loan conforming limit — adjust to your COE
    "min_owner_occ_pct": 0.35,    # below = too transient for multifamily targeting
    "max_owner_occ_pct": 0.85,    # above = low rental demand, hard PCS exit
    "min_median_income": 42_000,  # tenant base quality screen
}

MAX_COMMUTE_MINS = 35   # real drive time (Google Maps) or straight-line Haversine
MAX_CRIME_PER_1K = 700  # DATA_SUSPECT flag threshold — informational only, not a filter
```

### Yield Cap

```python
YIELD_CAP = 0.12   # yields above 12% capped before scoring — not rewarded
```

### Different Duty Station

```python
DUTY_STATION = {
    "name": "BAMC - Fort Sam Houston",
    "lat": 29.4563,
    "lon": -98.4436,
}
```

Right-click any location in Google Maps to get coordinates. Also update `TARGET_METRO` to match the new city, and swap in the relevant metro's Zillow files.

---

## Notebooks

Two Jupyter notebooks go deeper than the pipeline output can.

### `notebooks/01_eda.ipynb` — Exploratory Data Analysis

Validates every model assumption before you trust the output:

| Section | Question answered |
| ------- | ----------------- |
| 1. ZHVI | Where does the $450k ceiling cut? Is the stability metric discriminating? |
| 2. ZORI / Yield | Where does the 3.5% floor land in the SA distribution? |
| 3. Census | Do the owner-occ and income filter thresholds reflect SA's actual clustering? |
| 4. Crime | What fraction of 5M+ dispatch calls is actually crime? Does the allowlist hold up? |
| 5. Cross-source | How many ZIPs survive each pipeline stage? |
| 6. Findings | Template to record config change decisions as you investigate |
| 7. ZHVF | Where have each top ZIP's prices been, and where is Zillow's forecast pointing? |

Section 7 requires `data/final/ranked_zip_scores.csv` (run the pipeline first).

### `notebooks/02_cashflow.ipynb` — Property Cashflow Analysis

Models the actual monthly money for the ranked ZIPs:

- Monthly PITI breakdown and cost stack per ZIP
- Break-even rent vs. ZORI estimate
- Minimum rental fraction needed to break even
- 3-year hold P&L waterfall under $0 appreciation (conservative baseline)
- Interest rate and rent sensitivity curves
- **Section 9 — ZHVF Market Forecast:** Connects rankings to Zillow's forward price data — "wait vs. buy now" analysis comparing price savings from forecasted decline against equity foregone

---

## Sensitivity Testing

```bash
python sensitivity.py
```

**Test 1 — Weight Stability:** Shifts each weight ±10% across 13 scenarios and checks if your top ZIPs hold. 80%+ scenarios with the same top ZIPs = real signal.

**Test 2 — Filter Dependency:** Rescores all ZIPs with no hard filters, then checks if your top ZIPs still rank near the top when competing against the full unfiltered pool. If they hold up → your winners earn their rank on merit. If they collapse → the filters were doing the work, not the data.

---

## What to Do After You Get Your Results

**1. Open the dashboard**
`uvicorn webapp.app:app --reload` → [http://localhost:8000](http://localhost:8000). Switch to the Map view. Visually confirm the top ZIPs make geographic sense relative to BAMC.

**2. Drive the neighborhoods**
Do a windshield survey on a weekday evening and a weekend morning. What you feel walking around is data the model can't capture.

**3. Pull actual listings**
Filter Zillow or Realtor.com to your surviving ZIPs. You're looking for duplexes, triplexes, or SFH with extra bedrooms. If a ZIP ranks well but has zero relevant inventory, it's not a real option.

**4. Run the property analyzer**
Use `analyze_property.py` on any listing you're serious about. It runs the full cashflow math using your exact financing terms.

```bash
python analyze_property.py --zip 78109 --price 265000 --units 2 --bah 1900
```

If the Phase 1 break-even price is above asking and Phase 2 is cash-positive → proceed. If not → negotiate to the yield target price shown in Section 3, or move on.

**5. Talk to a military-savvy SA agent**
One who understands VA loans, house hacking, and the PCS resale cycle. They'll know things about specific blocks and micro-markets that no dataset captures.

---

## Project Structure

```text
satx_house_hack_model/
│
├── .cache/                    ← all auto-fetched data (TTL-managed, git-ignored)
│   ├── zillow_zhvi.pkl / .meta.json
│   ├── zillow_zori.pkl / .meta.json
│   ├── census_acs.pkl / .meta.json
│   ├── sa_crime_raw.csv       ← ~631 MB SAPD data (streamed, not pickled)
│   └── ...
│
├── data/
│   ├── processed/             ← merged intermediate dataset + crime caches (generated)
│   └── final/                 ← scored and ranked output (generated)
│
├── src/
│   ├── config.py              ← ALL tunable parameters: weights, thresholds, paths
│   ├── cache_manager.py       ← TTL-based disk cache (atomic pickle writes)
│   ├── data_loader.py         ← auto-fetches every data source; reads from cache
│   ├── preprocess.py          ← cleans, filters crime by type, computes ZHVI stability + CAGR, merges
│   ├── feature_engineering.py ← hard filters, crime flagging, yield cap, log transforms, normalization
│   ├── scoring.py             ← weighted combination, ranking, summary formatting
│   ├── commute.py             ← Google Maps API + Haversine fallback; 1-year cache
│   ├── utils.py               ← logging, file I/O, ZIP centroid loader
│   └── property_analyzer.py   ← listing-level analysis engine
│
├── webapp/
│   ├── app.py                 ← FastAPI server (results API + GeoJSON endpoint)
│   └── static/
│       └── index.html         ← single-page dashboard (Leaflet map + sortable table)
│
├── tests/                     ← pytest suite (~257 tests)
├── notebooks/
│   ├── 01_eda.ipynb
│   └── 02_cashflow.ipynb
│
├── outputs/                   ← final human-readable CSVs
├── main.py                    ← full pipeline orchestrator
├── analyze_property.py        ← CLI for listing-level analysis
├── sensitivity.py             ← weight stability + filter dependency tests
├── requirements.txt
└── README.md
```

**Pipeline execution order:**

```
data_loader → preprocess (ZHVI stability + CAGR) → commute → merge →
hard filters → crime flagging → yield cap → log transform → normalize → score → output
```

The `--diagnose` flag prints row counts, value ranges, and ZIP overlap counts after every step.

---

## Troubleshooting

**First run is slow**
The SAPD crime file is ~631 MB and takes 30–90 seconds to download. Normal. Subsequent runs read from `.cache/` in under 15 seconds.

**Few or zero results after filtering**
Run `--diagnose` to see the filter breakdown. Most common causes: `min_rent_to_price` is cutting ZIPs where SA yields have compressed, or the commute filter is removing distant ZIPs. Lower the relevant threshold in `src/config.py`.

**Crime download fails or times out**
Try again on a better connection. Alternatively, download manually from the [SA Open Data portal](https://data.sanantonio.gov) (search "SAPD Calls for Service") and save to `.cache/sa_crime_raw.csv`, then create an empty file `.cache/crime_raw_marker.pkl` to signal the cache is fresh.

**Stability shows 0.50 (neutral) for all ZIPs**
The `zhvi_cov` column is missing from the merged dataset. Run `--diagnose` and check the "ZHVI stability" output — it will show how many months of history were found in the ZHVI file.

**Google Maps key not loading**
Confirm `.env` exists in the project root (not `src/`) and contains `GOOGLE_MAPS_API_KEY=your_key`. The key is loaded by `config.py` via `python-dotenv` before any pipeline module runs.

**Map shows no polygons**
The first `/api/geojson` request downloads the Texas ZIP boundary file (~22 MB). It only runs once and caches for 1 year. If it fails, check the server terminal for the error — most likely a transient network issue. Retry by reloading the map tab.

---

## Understanding the Limitations

**The model is a research funnel, not a buy signal.**

What it cannot see:
- HOA rules that prohibit renting rooms or separate units
- Whether a ZIP's housing stock actually contains duplexes and multifamily properties
- Days-on-market — critical for PCS exit liquidity
- Block-level conditions within a ZIP (safe average, dangerous pocket)
- School quality — relevant for military family tenants and resale
- Military tenant density in the area

Known data constraints:
- **Zillow ZORI** measures asking rent for new leases — not what long-term tenants actually pay
- **Crime data** is SA police dispatch calls filtered to criminal types — not FBI UCR-verified statistics. Rates are inflated across all ZIPs due to CFS methodology; use `crime_flag` as a relative signal, not an absolute one.
- **Census data** is from the ACS 5-year survey — some figures are a few years old
- **Commute times** default to Haversine estimates when no Google Maps key is set — verify specific routes before committing
- **Stability scoring** is backward-looking — past price stability doesn't guarantee future stability

---

## Disclaimer

This tool is for personal research and decision support only. It does not constitute financial, investment, or legal advice. Real estate involves risk, including the risk of loss. Always conduct independent due diligence and consult qualified professionals before making any purchase decision. VA loan eligibility and terms depend on individual circumstances and are subject to change.
