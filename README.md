# SATX House Hack Scoring Model

A data-driven tool that ranks San Antonio ZIP codes by how well they work for a **military house hack** — buying a property near BAMC / Fort Sam Houston, living in part of it, and renting out the rest to offset or eliminate your mortgage payment.

Built by a 4N0 (Aerospace Medical Technician) stationed at BAMC. Designed around the realities of military life: fixed duty station, 3-year typical hold period, VA loan eligibility, and a tenant pool that skews heavily military.

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

**What this tool is NOT:** It does not replace boots-on-the-ground research. It narrows your universe from 60+ ZIP codes down to 6–10 worth seriously investigating. You still need to look at actual listings, drive the neighborhoods, and run the numbers on specific properties.

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

| Filter                | Threshold              | Why                                                                                                                                                                                                                         |
| --------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Minimum gross yield   | 5.5%                   | Recalibrated for SFR room hack: annual income = est_room_rent × rooms_rented × 12. SA room rents ($600–900/room) on a $250k SFR clear 5.5% easily. The 5.5% floor excludes ZIPs where rent fundamentals are genuinely weak. |
| Maximum home price    | $450,000               | SA conforming VA loan limit — adjust to your COE                                                                                                                                                                            |
| Owner-occupancy range | 50%–85%                | Below 50% = too transient. Above 85% = low rental demand and harder PCS exit.                                                                                                                                               |
| Minimum median income | $42,000                | Tenant base quality screen. Correlates with delinquency risk and resale strength. $42k ≈ E-5/E-6 BAH + base pay in SA.                                                                                                      |
| Crime floor           | Safer 45% of ZIPs      | You live there. Safety is not a slider. Only the safer 45% of the crime distribution qualifies.                                                                                                                             |
| Commute to BAMC       | ≤ 35 min straight-line | You drive this daily. ZIPs beyond this are not candidates regardless of yield.                                                                                                                                              |

### Stage 2 — Scored Ranking (graded optimization)

Surviving ZIPs are ranked by a weighted composite of five factors:

| Factor               | Weight | Role                                                                                       |
| -------------------- | ------ | ------------------------------------------------------------------------------------------ |
| Crime rate           | 30%    | Highest weight — neighborhood safety drives livability and tenant quality                  |
| Owner-occupancy rate | 25%    | Raised for room-hack: tenants share your home, so neighborhood character matters even more |
| Rent-to-price ratio  | 20%    | Per-room yield signal (ZORI ÷ median rooms), capped at 12% (above = suspicious)            |
| Commute to BAMC      | 15%    | Daily quality of life — but safety ranks above it                                          |
| Price stability      | 10%    | 5-year ZHVI volatility — for a 3-year hold, boring beats exciting                          |

---

## The Five Scoring Factors, Explained

### 1. Crime Rate (30% of score)

**What it measures:** Reported criminal incidents per 1,000 residents, filtered to actual crimes — assault, robbery, burglary, theft, narcotics, homicide. Traffic stops, noise complaints, and medical calls are excluded.

**Two-layer treatment:**

- First, it acts as a hard filter: only ZIPs in the safer half of SA qualify at all
- Then, among survivors, it's a scored dimension — safer ZIPs rank higher

**Why log-transformed:** Crime distributions are heavily skewed. Without transformation, one extreme outlier ZIP stretches the scale so that crime=25 and crime=200 look nearly identical. Log-transformation compresses the tail so every step up in crime is meaningfully penalized.

**What to look at in results:** The `crime_per_1k` column. Below 20 is genuinely quiet. 20–50 is moderate suburban. Above 50 should raise your eyebrows regardless of the score.

One data cleaning step worth knowing: ZIPs with fewer than 5,000 Census residents are excluded from crime scoring entirely, even if they have incident data. Commercial corridors, industrial zones, and fringe areas can have near-zero resident populations but high dispatch activity — producing absurd rates like 8,500 incidents per 1,000 "residents." These are not residential neighborhoods and their rates would corrupt the entire distribution if included.

### 2. Rent-to-Price Ratio (20% of score)

**What it measures:** Per-room annual rental income divided by home purchase price — a room-hack-specific yield signal.

**Formula:** `(est_room_rent × 12) ÷ home value`

Where `est_room_rent = ZORI ÷ median_rooms_in_ZIP` (Census ACS B25018).

**Example:** $250,000 home, ZORI $1,800/mo, median 5.5 rooms → est_room_rent ≈ $327/room → yield = `($327 × 12) ÷ $250,000 = 1.6%` per room. Two rooms rented: 3.2%. The point of this metric in the pipeline is relative ranking — ZIPs where room rents are high relative to prices rank better. Use the property analyzer with `--rent-override` for absolute cashflow decisions.

**The 5.5% pipeline yield floor** (ZORI-based proxy, not per-room): The pipeline's `rent_to_price` filter still uses `ZORI × 12 / ZHVI` as a proxy to screen out ZIPs with fundamentally weak rent-to-price ratios. SA SFR ZIPs typically yield 6–9% on this measure, so the 5.5% floor is permissive enough for SFR candidates while excluding structurally weak markets.

**The 12% yield cap:** In SA, gross yields above 12% almost always mean distressed pricing, deferred maintenance, or data noise — not a hidden gem. Capping yield at 12% before scoring prevents these ZIPs from ranking artificially high on yield while hiding structural problems.

### 3. Owner-Occupancy Rate (25% of score)

**What it measures:** Percentage of homes in the ZIP that are owner-occupied vs. renter-occupied, from U.S. Census data.

**Why 25% weight (raised from 20%):** In a room hack, your tenants live inside your home — they're not just neighbors, they're housemates. Neighborhood character, stability, and the type of people who choose to live there matter even more than in a duplex setup where you have physical separation. This is the one weight that rises directly from the SFR room-hack model shift.

**Why the 50%–85% target band:** Below 50% = primarily transient renters = not a neighborhood where military families tend to choose to live, and not the tenant pool you want sharing your home. Above 85% = low rental demand, harder to find tenants, and harder PCS exit (fewer investors as buyers).

### 4. Commute to BAMC (15% of score)

**What it measures:** Estimated drive time from each ZIP code's geographic center to Brooke Army Medical Center.

**Why it's 15%, not higher:** Commute matters — you drive it every day. But in this model, safety and cashflow rank above it. A 25-minute commute to a safe, cashflowing property beats a 10-minute commute to somewhere you're uneasy living.

**Current method:** Straight-line distance with a road correction factor. Accurate enough for relative ranking across SA ZIPs. For specific properties, verify with Google Maps.

### 5. Price Stability (10% of score)

**What it measures:** How much a ZIP's home values have varied over the last 5 years, using the Coefficient of Variation (standard deviation ÷ average) of monthly Zillow ZHVI data.

**Why it matters for a 3-year hold:** A ZIP where prices swung wildly during 2020–2024 is a ZIP that can swing against you. This isn't about finding the highest appreciation — it's about avoiding the ZIPs most likely to leave you underwater or illiquid at PCS time.

**Lower CoV = better.** A `zhvi_cov` of 0.05 means prices were very stable. A CoV of 0.20 means the market was volatile. This is free information from the ZHVI file you already download — it uses the full time-series instead of just the latest value.

**CoV vs. CAGR:** CoV measures the _bumpiness_ of the price path. CAGR (`zhvi_cagr_5yr`, `zhvi_cagr_10yr`) measures the _direction_ — where you actually end up. Both are computed from the same ZHVI file. For a 3-year hold, CoV matters more (risk of being underwater at PCS). For a 5–15 year hold, 10yr CAGR matters more. The output includes both so you can weigh them against your actual timeline.

---

## How the Final Score Is Calculated

```math
Final Score = (Crime × 0.30) + (Owner Occ × 0.25) + (Yield × 0.20) + (Commute × 0.15) + (Stability × 0.10)
```

Each component is normalized 0–1 relative to the surviving ZIP pool before combining. **Scores are relative, not absolute.** A crime score of 0.8 means "safer than 80% of ZIPs that passed the hard filters" — not "objectively safe."

This is why you should always read the raw columns (`crime_per_1k`, `rent_to_price`, `commute_minutes`, `zhvi_cov`) alongside the score. The score tells you rank. The raw numbers tell you reality.

---

## Data Sources

The model uses five sources. Two require a manual one-time download. Three are fetched automatically.

### Manual Downloads Required (One Time)

1. Zillow Home Value Index (ZHVI)
   - What it is: Monthly median home values by ZIP code. The model uses the most recent value, the full 5-year time series for price stability scoring, and the longer history for CAGR calculations.
   - Where: [zillow.com/research/data](https://www.zillow.com/research/data/)
     - "Home Values" section → "ZHVI All Homes (SFR, Condo/Co-op) Time Series, Smoothed, Seasonally Adjusted"
     - Geography: ZIP code → Download
   - Save as: `data/raw/zillow_zhvi_zip.csv`

2. Zillow Observed Rent Index (ZORI)
   - What it is: Monthly median asking rent by ZIP code — a **per-unit** repeat-rent index, Census-weighted across all housing types (apartments, SFH, condos). Represents the market rate for one typical rental unit in the ZIP. For SFR room hacking, the pipeline derives `est_room_rent = ZORI ÷ median_rooms` (Census B25018) as a per-room rate estimate.
   - Where: Same page → "Rentals" → "ZORI (Smoothed): All Homes Plus Multifamily" → ZIP code → Download
   - Save as: `data/raw/zillow_zori_zip.csv`

3. Zillow Home Value Forecast (ZHVF) _(required for notebook analysis)_
   - What it is: ZIP-level forward-looking price change forecasts at 1-, 3-, and 12-month horizons. Used by both notebooks to analyze market timing and contextualize the 3-year P&L. Not used by the main pipeline scorer.
   - Where: Same Zillow research page → "Home Values" → "ZHVF: ZIP Code Forecast" → Download
   - Save as: `data/raw/zhvf_growth_zip.csv`

4. ZIP Code Coordinates (SimpleMaps)
   - What it is: Latitude/longitude center point for every U.S. ZIP code — needed for commute distance calculation
   - Where: [simplemaps.com/data/us-zips](https://simplemaps.com/data/us-zips) → Free download
   - Save as: `data/raw/uszips.csv`

### Auto-Downloaded (No Action Required)

1. U.S. Census Bureau — American Community Survey
   - Owner-occupancy rates, household income, median rooms per unit, and population by ZIP code
   - Auto-fetched from the Census API on first run and cached locally
   - Median rooms (B25018) is used to compute `est_room_rent = ZORI ÷ median_rooms`, the per-room rent estimate used by the property analyzer in room-hack mode

2. San Antonio Police Department — Calls for Service
   - Every police dispatch call in SA with incident type and ZIP code
   - Auto-downloaded from SA Open Data portal on first run (~600MB, 30–90 seconds)
   - The model filters this to 23 criminal incident types only — no medical, noise, or traffic calls

---

## Setup (Step by Step)

### Step 1 — Check Python

Open Terminal (Mac/Linux) or Command Prompt (Windows):

```bash
python3 --version
```

You need 3.9 or newer. Download from [python.org](https://www.python.org/downloads/) if needed.

### Step 2 — Navigate to the Project

```bash
cd path/to/satx_house_hack_model
```

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

Takes 1–2 minutes. Installs pandas, numpy, requests, and a few others.

### Step 4 — Download the Three Data Files

Place these in `data/raw/` following the Data Sources instructions above:

```text
data/
└── raw/
    ├── zillow_zhvi_zip.csv      ← from Zillow
    ├── zillow_zori_zip.csv      ← from Zillow
    └── uszips.csv               ← from SimpleMaps
```

### Step 5 (Optional) — Google Maps API Key

For real drive times instead of straight-line estimates. The free tier is more than enough.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Enable the "Distance Matrix API"
3. Create an API key
4. Copy `.env.example` to `.env` and paste your key after `GOOGLE_MAPS_API_KEY=`

Without a key the model uses straight-line distance — accurate for ranking, not for specific trip planning.

### Step 6 — Run

```bash
python main.py --no-google-maps
```

First run takes 2–4 minutes (crime data download). After that, cached files make it run in under 15 seconds.

---

## Reading the Results

The output table printed to your terminal and saved to `outputs/top_zips_summary.csv`:

| Column              | What It Means                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `rank`              | Overall rank. 1 = best.                                                                                             |
| `zip`               | ZIP code                                                                                                            |
| `median_home_value` | Estimated median home price                                                                                         |
| `median_rent`       | Estimated median asking rent (ZORI per unit)                                                                        |
| `est_room_rent`     | Estimated per-room rent (ZORI ÷ median rooms). Used as fallback in room-hack mode when no `--rent-override` is set. |
| `rent_to_price`     | Gross yield (annual rent ÷ price). Raw value, before the 12% cap.                                                   |
| `commute_minutes`   | Estimated drive time to BAMC                                                                                        |
| `crime_per_1k`      | Criminal incidents per 1,000 residents. Lower = safer.                                                              |
| `owner_occ_pct`     | % of homes owner-occupied                                                                                           |
| `median_hh_income`  | Median household income — tenant base quality indicator                                                             |
| `zhvi_cov`          | Price volatility (Coefficient of Variation). Lower = more stable.                                                   |
| `zhvi_cagr_5yr`     | Annualized home value growth over the last 5 years. Display only — not scored.                                      |
| `zhvi_cagr_10yr`    | Annualized home value growth over the last 10 years — the structural appreciation trend. Display only — not scored. |
| `final_score`       | Composite score 0–1. Higher = better overall.                                                                       |
| `weighted_*`        | Each factor's contribution to the final score — shows you _why_ a ZIP ranked where it did                           |

**How to actually use the table:**

Don't just look at `final_score` and move on. Look at the weighted columns — they show you what's driving the rank. A ZIP ranked #3 because of commute and yield might be a worse real-world choice than a ZIP ranked #5 with a stronger safety score. The numbers are telling you a story; read it.

---

## Commands

```bash
# Standard run — straight-line commute estimate (recommended starting point)
python main.py --no-google-maps

# With Google Maps real drive times (requires API key)
python main.py

# Show top 20 ZIPs instead of default 15
python main.py --no-google-maps --top 20

# Diagnostic mode — prints data stats at every pipeline step
# Use this to understand what's happening or debug unexpected results
python main.py --no-google-maps --diagnose

# Test ranking stability (run after main.py)
python sensitivity.py

# Stress test — top 8 ZIPs, ±15% weight shifts
python sensitivity.py --top 8 --delta 0.15

# Test filter dependency only (do your winners actually earn their rank?)
python sensitivity.py --test filters
```

---

## Property Analyzer — Evaluating a Specific Listing

Once the pipeline has produced `ranked_zip_scores.csv`, you can evaluate any specific property listing you find on Zillow, Realtor.com, or anywhere else. The property analyzer pulls ZIP-level market data from the pipeline output and layers in your exact financing terms to produce a property-specific report.

**Run the pipeline first**, then:

```bash
# SFR room hack — 3-bed home, rent 2 rooms (pipeline est_room_rent used automatically)
python analyze_property.py --zip 78239 --price 265000 --bedrooms 3 \
    --rooms-rented 2 --bah 1900

# SFR room hack — 4-bed home, rent 3 rooms, with actual comp rent override
python analyze_property.py --zip 78239 --price 285000 --bedrooms 4 \
    --rooms-rented 3 --rent-override 750 --bah 1900

# Duplex — unit hack mode (you live in one unit, rent the other)
python analyze_property.py --zip 78109 --price 265000 --units 2 --bah 1900

# Triplex, known rent (ZORI may not reflect actual unit rents in this ZIP)
python analyze_property.py --zip 78239 --price 320000 --units 3 --rent-override 1100

# Conventional loan, 5% down
python analyze_property.py --zip 78209 --price 285000 --units 2 \
    --loan-type conventional --down-pct 5

# JSON output for programmatic use
python analyze_property.py --zip 78239 --price 265000 --bedrooms 3 \
    --rooms-rented 2 --output json
```

### What the Report Covers

The report is organized into 8 sections:

| Section                     | What It Shows                                                                                                                 |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **1. ZIP Market Overview**  | Rank, score, median home value vs. asking, ZORI rent, commute, owner-occupancy, CAGR, ZHVF forecast                           |
| **2. Crime Intelligence**   | Crime type breakdown (assault, theft, robbery, etc.), 12-month trend vs. prior year, peak day                                 |
| **3. Negotiation Range**    | Max price at each yield target (6.5–8%), break-even price where tenant rent covers all costs                                  |
| **4. Cashflow Analysis**    | Phase 1 (house hack) and Phase 2 (full rental) monthly income, expenses, and net — including homestead exemption, VA fee, BAH |
| **5. 3-Year Hold P&L**      | Total return under flat, +3%, +5%, +8%/yr and ZHVF forecast appreciation scenarios                                            |
| **6. Sensitivity Analysis** | Phase 2 net at 5–8.5% rates; Phase 1 net across hack fraction range                                                           |
| **7. Filter Status**        | Pass/fail on every hard filter at the asking price, with the negotiation target to fix failures                               |
| **8. Decision Scorecard**   | Quick yes/no checklist covering filters, cashflow, return, crime trend, and ZIP rank                                          |

### Key Parameters

| Flag              | Default  | Description                                                                                                                                           |
| ----------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--zip`           | required | 5-digit ZIP code                                                                                                                                      |
| `--price`         | required | Asking price in dollars                                                                                                                               |
| `--units`         | 1        | 1=SFH (default — room hack), 2=duplex, 3=triplex, 4=fourplex                                                                                          |
| `--bedrooms`      | 3        | Total bedrooms in the property                                                                                                                        |
| `--rooms-rented`  | —        | Room-hack mode: number of bedrooms to rent. Pipeline `est_room_rent` used automatically; add `--rent-override` when you have actual comparable rents. |
| `--bah`           | 0        | Monthly BAH — shown as offset to your out-of-pocket Phase 1 cost                                                                                      |
| `--rent-override` | —        | Per-unit rent (unit mode) or per-room rate (room-hack mode). Use when you have real comps to validate or replace the pipeline estimate.               |
| `--rate`          | 6.875%   | Interest rate in percent                                                                                                                              |
| `--loan-type`     | VA       | `VA` or `conventional`                                                                                                                                |
| `--down-pct`      | 0        | Down payment in percent (e.g. `5` = 5%)                                                                                                               |
| `--va-second-use` | —        | Flag for 3.30% funding fee (vs. 2.15% first use)                                                                                                      |
| `--hack-fraction` | auto     | Override fraction rented (auto-set from `--units` or `--rooms-rented`)                                                                                |

### How Rent Is Used

**Unit hack mode (duplex, triplex…):** Uses ZORI as a per-unit rate.

- Phase 1 income = ZORI × `units` × `hack_fraction`
- Phase 2 income = ZORI × `units`

**Room hack mode (SFH bedrooms):** Uses a per-room rate — either `--rent-override` (preferred when you have real comps) or `est_room_rent` from the pipeline (ZORI ÷ median rooms per Census B25018).

- Phase 1 income = per-room rate × `rooms_rented`
- Phase 2 income = per-room rate × `bedrooms`

`est_room_rent` is a ZIP-level estimate from the pipeline and is automatically used when `--rooms-rented` is specified without `--rent-override`. It's a reasonable starting point but is derived from ZORI (which covers all unit types) divided by median rooms — not actual room-rental comparable data. Always validate against current listings on Zillow/Craigslist before finalizing cashflow decisions.

If actual unit rents differ from ZORI (common for duplexes in specific micro-markets), use `--rent-override` with real comparables in either mode.

---

## Notebooks

Two Jupyter notebooks go deeper than the pipeline output can. Run `jupyter notebook` from the project root.

### `notebooks/01_eda.ipynb` — Exploratory Data Analysis

Validates every model assumption before you trust the output. Each section answers a specific question about a data source:

| Section               | Question answered                                                                                                                                                                |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. ZHVI               | Where does the $450k ceiling cut? Is the stability metric actually discriminating?                                                                                               |
| 2. ZORI / Yield       | Where does the 6.5% floor land in the SA distribution? Are there borderline ZIPs worth reviewing?                                                                                |
| 3. Census             | Do the owner-occ and income filter thresholds reflect where SA's market actually clusters?                                                                                       |
| 4. Crime              | What fraction of 5.3M dispatch calls is actually crime? Does the allowlist hold up?                                                                                              |
| 5. Cross-source       | How many ZIPs survive each pipeline stage? What's the most constraining filter?                                                                                                  |
| 6. Findings           | Structured template to record config change decisions as you investigate                                                                                                         |
| 7. ZHVF (scored ZIPs) | For the ZIPs that made it through all filters: where have their prices been, where is Zillow's forecast pointing, and where in the 2022–2026 correction cycle does each one sit? |

Section 7 requires `data/final/ranked_zip_scores.csv` (run the pipeline first) and `data/raw/zhvf_growth_zip.csv`.

### `notebooks/02_cashflow.ipynb` — Property Cashflow Analysis

Takes the ranked ZIPs and models the actual monthly money. Designed around two phases of a military house hack:

- **Phase 1 (house hack):** Your net monthly out-of-pocket while you're stationed at BAMC and living in part of the property
- **Phase 2 (full rental):** Monthly cashflow after PCS when all units are rented

Key sections:

- Monthly PITI breakdown and cost stack per ZIP
- Break-even rent vs. ZORI estimate — how far above median do you need to be?
- Minimum rental fraction needed to break even (1 room vs. half duplex vs. full unit)
- 3-year hold P&L waterfall under $0 appreciation (conservative baseline)
- Interest rate and rent sensitivity curves
- **Section 9 — ZHVF Market Forecast:** Connects the pipeline's ZIP rankings to Zillow's forward-looking price data. Answers "when to buy" (wait vs. buy now analysis comparing price savings from forecasted decline against equity foregone) and "what to expect" (3-year P&L under ZHVF-informed appreciation scenarios)

Requires `data/final/ranked_zip_scores.csv` and `data/raw/zhvf_growth_zip.csv`.

---

## Sensitivity Testing

Run `python sensitivity.py` after the main pipeline. It answers two questions:

**Test 1 — Weight Stability**
Shifts each weight ±10% across 13 scenarios and checks if your top ZIPs hold. 80%+ scenarios with the same top ZIPs = real signal. Constant rank shuffling = your weights are doing the work, not the data.

**Test 2 — Filter Dependency**
Rescores all ZIPs with no hard filters, then checks if your top ZIPs still rank near the top when competing against the full unfiltered pool. If they hold up → your winners earn their rank on merit. If they collapse → the hard filters were selecting your winners for you.

A result that survives both tests is defensible. A result that fails Test 2 means you need to ask harder questions about what the filters are doing.

---

## Adjusting the Model

Everything tunable is in `src/config.py`. No other file needs to be touched.

### Scoring Weights

```python
WEIGHTS = {
    "rent_to_price":   0.20,   # per-room yield signal; viability, not maximization
    "crime":           0.30,   # highest — you live there, non-negotiable
    "owner_occupancy": 0.25,   # raised for room hack — tenants share your home
    "commute":         0.15,   # important, but below safety/cashflow
    "stability":       0.10,   # 3-year hold = price volatility is real risk
}
```

Must add up to 1.0 exactly. The model throws an error if they don't.

### Hard Filters

```python
THRESHOLDS = {
    "min_rent_to_price": 0.055,   # SFR room-hack floor (ZORI-based proxy; see above)
    "max_home_value":    450_000,  # SA VA loan conforming limit — adjust to your COE
    "min_owner_occ_pct": 0.50,    # below = too transient
    "max_owner_occ_pct": 0.85,    # above = low rental demand, hard PCS exit
    "min_median_income": 42_000,  # tenant base quality screen (~E-5/E-6 pay in SA)
}
```

### Crime Floor

```python
CRIME_PERCENTILE_CUTOFF = 0.45  # keep only the safer 55% of candidate ZIPs
```

Lower this number = stricter safety requirement. Raise it = more ZIPs qualify but some will be in areas you'd think twice about.

### Yield Cap

```python
YIELD_CAP = 0.12  # yields above 12% are capped before scoring — not rewarded
```

### Price Stability Window

```python
ZHVI_STABILITY_YEARS = 5  # how many years of monthly ZHVI data to use for CoV
```

### Long-Term Appreciation Windows

```python
ZHVI_CAGR_WINDOWS = [5, 10]  # years of ZHVI history for CAGR computation
```

These appear as `zhvi_cagr_5yr` and `zhvi_cagr_10yr` in the output — display-only context for equity-building decisions over longer holds. They do not affect scoring. The 10-year CAGR is the most useful signal for a 5–15 year hold; the 5-year CAGR reflects the post-2021 boom/bust cycle and will be negative for most SA ZIPs right now.

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

## What to Do After You Get Your Results

The model gives you a shortlist. Here's how to use it:

**1. Map the top ZIPs**
Look them up on Google Maps. Some will be instantly recognizable as good or bad fits for your situation. Cross off any that don't pass the gut check before you go further.

**2. Drive the neighborhoods**
Do a windshield survey on a weekday evening and a weekend morning. What you feel walking around a neighborhood is data the model can't capture.

**3. Pull actual listings**
Filter Zillow or Realtor.com to your surviving ZIPs. You're looking for duplexes, triplexes, or SFH with ADUs/garage apartments. If a ZIP ranks well but has zero relevant inventory, it's not a real option.

**4. Run the property analyzer on specific listings**
Use `analyze_property.py` to evaluate any property you're serious about. It runs the full cashflow math — Phase 1 house hack, Phase 2 full rental post-PCS, negotiation range, 3-year P&L, and sensitivity analysis — using your exact financing terms and the ZIP's market data.

```bash
python analyze_property.py --zip 78109 --price 265000 --units 2 --bah 1900
```

If the Phase 1 break-even price is above asking and Phase 2 is cash-positive → proceed. If not → negotiate to the yield target price shown in Section 3, or move on.

**5. Talk to a military-savvy SA agent**
One who understands VA loans, house hacking, and the PCS resale cycle. They'll know things about specific blocks and micro-markets that no dataset captures.

---

## Understanding the Limitations

**The model is a research funnel, not a buy signal.**

What it cannot see:

- HOA rules that prohibit renting rooms or separate units
- Whether a ZIP's housing stock actually contains duplexes and multi-unit properties
- Days-on-market — critical for PCS exit liquidity
- Block-level conditions within a ZIP (safe average, dangerous pocket)
- School quality — relevant for military family tenants and resale
- Military tenant density in the area

Known data constraints:

- **Zillow ZORI** measures asking rent for new leases — not what long-term tenants actually pay
- **Crime data** is SA police dispatch calls filtered to criminal types — not FBI UCR-verified statistics
- **Census data** is from the 2022 ACS 5-year survey — some figures are a few years old
- **Commute times** use straight-line estimates — verify specific routes with Google Maps
- **Stability scoring** is backward-looking — past price stability doesn't guarantee future stability
- **ZIPs with fewer than 5,000 Census residents are excluded from crime scoring** — their per-1k rates are mathematically unreliable and would corrupt the crime distribution.

---

## Project File Structure (For Developers)

```text
satx_house_hack_model/
│
├── data/
│   ├── raw/              ← source files, never modified
│   ├── processed/        ← merged intermediate dataset + crime caches (generated)
│   └── final/            ← scored and ranked output (generated)
│
├── src/
│   ├── config.py              ← ALL tunable parameters: weights, thresholds, flags
│   ├── data_loader.py         ← downloads and reads each raw data source
│   ├── preprocess.py          ← cleans, filters crime by type, computes ZHVI stability, merges
│   ├── feature_engineering.py ← hard filters, crime floor, yield cap, log transforms, normalization
│   ├── scoring.py             ← weighted combination, ranking, summary formatting
│   ├── commute.py             ← Google Maps API + Haversine fallback
│   ├── utils.py               ← logging, file I/O helpers
│   └── property_analyzer.py   ← listing-level analysis engine (cashflow, negotiation, crime breakdown)
│
├── tests/                ← pytest unit tests (257 tests, run with `python -m pytest`)
│   ├── conftest.py            ← shared fixtures and test data
│   ├── test_input.py          ← PropertyInput dataclass tests
│   ├── test_financing.py      ← mortgage math and cost component tests
│   ├── test_cashflow.py       ← Phase 1 / Phase 2 cashflow tests
│   ├── test_negotiation.py    ← yield targets, break-even, 3-yr P&L tests
│   ├── test_sensitivity.py    ← rate and hack-fraction sensitivity tests
│   ├── test_crime.py          ← crime categorization and cache I/O tests
│   └── test_analyzer.py       ← integration tests for analyze_property()
│
├── notebooks/
│   ├── 01_eda.ipynb           ← exploratory data analysis and assumption validation
│   └── 02_cashflow.ipynb      ← cashflow modeling and ZHVF market timing analysis
│
├── outputs/              ← final human-readable CSVs
├── main.py               ← full pipeline orchestrator (Path B logic)
├── analyze_property.py   ← CLI for listing-level analysis (wraps property_analyzer.py)
├── sensitivity.py        ← weight stability + filter dependency robustness tests
├── pytest.ini            ← test configuration
├── requirements.txt
└── README.md
```

**Pipeline execution order:**

```math
Load → Process + ZHVI Stability + ZHVI CAGR → Commute → Merge → Hard Filters → Crime Floor →
Yield Cap → Log Transform → Normalize → Score → Output (with CAGR columns)
```

The `--diagnose` flag prints row counts, value ranges, and ZIP overlap counts after every step — use it to understand what's happening at each stage.

---

## Troubleshooting

**"File not found" on startup**
One of the three manual files is missing or misnamed. Confirm `zillow_zhvi_zip.csv`, `zillow_zori_zip.csv`, and `uszips.csv` are all in `data/raw/` with those exact names.

**Few or zero results after filtering**
Run `--diagnose` to see the filter breakdown. Most common cause: `min_rent_to_price = 0.055` is still cutting most ZIPs. If SA yields have compressed further, try lowering to `0.045`. The diagnose output shows exactly how many ZIPs each filter removes.

**Crime download fails or times out**
The SA crime file is ~600MB. On a slow connection it may time out. Try again on a better connection, or manually download from the [SA Open Data portal](https://data.sanantonio.gov) and save as `data/raw/sa_crime_raw.csv`.

**Stability shows 0.50 (neutral) for all ZIPs**
The `zhvi_cov` column is missing from the merged dataset. This usually means the ZHVI file didn't have enough historical date columns. Run `--diagnose` and check the "ZHVI stability" output — it will show how many months of data were found.

**Results look identical every run**
Census data caches to `data/raw/census_acs_raw.csv`. Delete that file to force a fresh pull from the Census API.

---

## Disclaimer

This tool is for personal research and decision support only. It does not constitute financial, investment, or legal advice. Real estate involves risk, including the risk of loss. Always conduct independent due diligence and consult qualified professionals before making any purchase decision. VA loan eligibility and terms depend on individual circumstances and are subject to change.
