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

| Filter                | Threshold         | Why                                                                                                                                     |
| --------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Minimum gross yield   | 7.2%              | Math-derived: VA loan at 6.5%, $250k home needs ~$1,800/month rent to cover PITI + vacancy + maintenance. Below 7.2% it doesn't pencil. |
| Maximum home price    | $450,000          | SA conforming VA loan limit — adjust to your COE                                                                                        |
| Owner-occupancy range | 50%–80%           | Below 50% = too transient. Above 80% = low rental demand.                                                                               |
| Minimum median income | $45,000           | Tenant base quality screen. Correlates with delinquency risk and resale strength. $45k ≈ E-5/E-6 pay range in SA.                       |
| Crime floor           | Safer 50% of ZIPs | You live there. Safety is not a slider. Only the bottom half of the crime distribution qualifies.                                       |

### Stage 2 — Scored Ranking (graded optimization)

Surviving ZIPs are ranked by a weighted composite of five factors:

| Factor               | Weight | Role                                                                      |
| -------------------- | ------ | ------------------------------------------------------------------------- |
| Crime rate           | 30%    | Highest weight — neighborhood safety drives livability and tenant quality |
| Rent-to-price ratio  | 25%    | Cashflow viability, capped at 12% (above this = suspicious, not a bonus)  |
| Owner-occupancy rate | 20%    | Neighborhood stability proxy                                              |
| Commute to BAMC      | 15%    | Daily quality of life — but safety ranks above it                         |
| Price stability      | 10%    | 5-year ZHVI volatility — for a 3-year hold, boring beats exciting         |

---

## The Five Scoring Factors, Explained

### 1. Crime Rate (30% of score)

**What it measures:** Reported criminal incidents per 1,000 residents, filtered to actual crimes — assault, robbery, burglary, theft, narcotics, homicide. Traffic stops, noise complaints, and medical calls are excluded.

**Two-layer treatment:**

- First, it acts as a hard filter: only ZIPs in the safer half of SA qualify at all
- Then, among survivors, it's a scored dimension — safer ZIPs rank higher

**Why log-transformed:** Crime distributions are heavily skewed. Without transformation, one extreme outlier ZIP stretches the scale so that crime=25 and crime=200 look nearly identical. Log-transformation compresses the tail so every step up in crime is meaningfully penalized.

**What to look at in results:** The `crime_per_1k` column. Below 20 is genuinely quiet. 20–50 is moderate suburban. Above 50 should raise your eyebrows regardless of the score.

### 2. Rent-to-Price Ratio (25% of score)

**What it measures:** Annual rental income divided by home purchase price.

**Formula:** `(monthly rent × 12) ÷ home value`

**Example:** $250,000 home, $1,700/month rent → `($1,700 × 12) ÷ $250,000 = 0.0816` (8.2% gross yield)

**The 7.2% floor is math, not preference.** At 6.5% VA rate on a $250k home:

- Monthly mortgage (PITI): ~$1,580
- Add 5% vacancy reserve: +$79
- Add 8% maintenance reserve: +$126
- Total monthly need: ~$1,785
- $1,785 × 12 / $250,000 = 0.0857

  7.2% is set below break-even to allow for lower-priced ZIPs where the math shifts. If you're looking at $200k properties, the floor is conservative enough to keep viable options in.

**The 12% yield cap:** In SA, gross yields above 12% almost always mean distressed pricing, deferred maintenance, or data noise — not a hidden gem. Capping yield at 12% before scoring prevents these ZIPs from ranking artificially high on yield while hiding structural problems.

### 3. Owner-Occupancy Rate (20% of score)

**What it measures:** Percentage of homes in the ZIP that are owner-occupied vs. renter-occupied, from U.S. Census data.

**Why the 50%–80% target band:** Neighborhoods where most people own their homes are more stable — better maintained, lower turnover, less crime drift over time. But above 80% means very few renters exist, which makes finding tenants harder and complicates resale to other investors at PCS time.

The minimum was raised from 40% to 50% compared to earlier versions. Below 50% = primarily transient renters = not a neighborhood where military families tend to choose to live.

### 4. Commute to BAMC (15% of score)

**What it measures:** Estimated drive time from each ZIP code's geographic center to Brooke Army Medical Center.

**Why it's 15%, not higher:** Commute matters — you drive it every day. But in this model, safety and cashflow rank above it. A 25-minute commute to a safe, cashflowing property beats a 10-minute commute to somewhere you're uneasy living.

**Current method:** Straight-line distance with a road correction factor. Accurate enough for relative ranking across SA ZIPs. For specific properties, verify with Google Maps.

### 5. Price Stability (10% of score)

**What it measures:** How much a ZIP's home values have varied over the last 5 years, using the Coefficient of Variation (standard deviation ÷ average) of monthly Zillow ZHVI data.

**Why it matters for a 3-year hold:** A ZIP where prices swung wildly during 2020–2024 is a ZIP that can swing against you. This isn't about finding the highest appreciation — it's about avoiding the ZIPs most likely to leave you underwater or illiquid at PCS time.

**Lower CoV = better.** A `zhvi_cov` of 0.05 means prices were very stable. A CoV of 0.20 means the market was volatile. This is free information from the ZHVI file you already download — it uses the full time-series instead of just the latest value.

---

## How the Final Score Is Calculated

```math
Final Score = (Crime × 0.30) + (Yield × 0.25) + (Owner Occ × 0.20) + (Commute × 0.15) + (Stability × 0.10)
```

Each component is normalized 0–1 relative to the surviving ZIP pool before combining. **Scores are relative, not absolute.** A crime score of 0.8 means "safer than 80% of ZIPs that passed the hard filters" — not "objectively safe."

This is why you should always read the raw columns (`crime_per_1k`, `rent_to_price`, `commute_minutes`, `zhvi_cov`) alongside the score. The score tells you rank. The raw numbers tell you reality.

---

## Data Sources

The model uses five sources. Two require a manual one-time download. Three are fetched automatically.

### Manual Downloads Required (One Time)

1. Zillow Home Value Index (ZHVI)
   - What it is: Monthly median home values by ZIP code. The model uses the most recent value AND the full 5-year time series for price stability scoring.
   - Where: [zillow.com/research/data](https://www.zillow.com/research/data/)
     - "Home Values" section → "ZHVI All Homes (SFR, Condo/Co-op) Time Series, Smoothed, Seasonally Adjusted"
     - Geography: ZIP code → Download
   - Save as: `data/raw/zillow_zhvi_zip.csv`

2. Zillow Observed Rent Index (ZORI)
   - What it is: Monthly median asking rent by ZIP code
   - Where: Same page → "Rentals" → "ZORI (Smoothed): All Homes Plus Multifamily" → ZIP code → Download
   - Save as: `data/raw/zillow_zori_zip.csv`

3. ZIP Code Coordinates (SimpleMaps)
   - What it is: Latitude/longitude center point for every U.S. ZIP code — needed for commute distance calculation
   - Where: [simplemaps.com/data/us-zips](https://simplemaps.com/data/us-zips) → Free download
   - Save as: `data/raw/uszips.csv`

### Auto-Downloaded (No Action Required)

1. U.S. Census Bureau — American Community Survey
   - Owner-occupancy rates, household income, and population by ZIP code
   - Auto-fetched from the Census API on first run and cached locally
   - Income data is used for the tenant base quality filter

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

| Column              | What It Means                                                                             |
| ------------------- | ----------------------------------------------------------------------------------------- |
| `rank`              | Overall rank. 1 = best.                                                                   |
| `zip`               | ZIP code                                                                                  |
| `median_home_value` | Estimated median home price                                                               |
| `median_rent`       | Estimated median asking rent                                                              |
| `rent_to_price`     | Gross yield (annual rent ÷ price). Raw value, before the 12% cap.                         |
| `commute_minutes`   | Estimated drive time to BAMC                                                              |
| `crime_per_1k`      | Criminal incidents per 1,000 residents. Lower = safer.                                    |
| `owner_occ_pct`     | % of homes owner-occupied                                                                 |
| `median_hh_income`  | Median household income — tenant base quality indicator                                   |
| `zhvi_cov`          | Price volatility (Coefficient of Variation). Lower = more stable.                         |
| `final_score`       | Composite score 0–1. Higher = better overall.                                             |
| `weighted_*`        | Each factor's contribution to the final score — shows you _why_ a ZIP ranked where it did |

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
    "rent_to_price":   0.25,   # viability, not maximization
    "crime":           0.30,   # highest — you live there, non-negotiable
    "owner_occupancy": 0.20,   # neighborhood stability
    "commute":         0.15,   # important, but below safety/cashflow
    "stability":       0.10,   # 3-year hold = price volatility is real risk
}
```

Must add up to 1.0 exactly. The model throws an error if they don't.

### Hard Filters

```python
THRESHOLDS = {
    "min_rent_to_price": 0.072,   # math-derived cashflow floor (see above)
    "max_home_value":    450_000,  # SA VA loan conforming limit — adjust to your COE
    "min_owner_occ_pct": 0.50,    # below = too transient
    "max_owner_occ_pct": 0.80,    # above = low rental demand
    "min_median_income": 45_000,  # tenant base quality screen
}
```

### Crime Floor

```python
CRIME_PERCENTILE_CUTOFF = 0.50  # keep only the safer half of candidate ZIPs
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

**4. Run the actual cashflow math on specific properties**
The model scores ZIP-level averages. Specific properties vary. For any property you're serious about, build a monthly cashflow sheet:

- Expected rent from tenant unit(s)
- Monthly PITI (principal, interest, taxes, insurance)
- Vacancy reserve (5% of gross rent)
- Maintenance reserve (8% of gross rent)
- Management (if applicable — even if you self-manage, budget for it for PCS planning)

If the numbers work → proceed. If not → move to the next listing.

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

---

## Project File Structure (For Developers)

```text
satx_house_hack_model/
│
├── data/
│   ├── raw/              ← source files, never modified
│   ├── processed/        ← merged intermediate dataset (generated)
│   └── final/            ← scored and ranked output (generated)
│
├── src/
│   ├── config.py         ← ALL tunable parameters: weights, thresholds, flags
│   ├── data_loader.py    ← downloads and reads each raw data source
│   ├── preprocess.py     ← cleans, filters crime by type, computes ZHVI stability, merges
│   ├── feature_engineering.py  ← hard filters, crime floor, yield cap, log transforms, normalization
│   ├── scoring.py        ← weighted combination, ranking, summary formatting
│   ├── commute.py        ← Google Maps API + Haversine fallback
│   └── utils.py          ← logging, file I/O helpers
│
├── outputs/              ← final human-readable CSVs
├── main.py               ← full pipeline orchestrator (Path B logic)
├── sensitivity.py        ← weight stability + filter dependency robustness tests
├── requirements.txt
└── README.md
```

**Pipeline execution order:**

```math
Load → Process + ZHVI Stability → Commute → Merge → Hard Filters → Crime Floor →
Yield Cap → Log Transform → Normalize → Score → Output
```

The `--diagnose` flag prints row counts, value ranges, and ZIP overlap counts after every step — use it to understand what's happening at each stage.

---

## Troubleshooting

**"File not found" on startup**
One of the three manual files is missing or misnamed. Confirm `zillow_zhvi_zip.csv`, `zillow_zori_zip.csv`, and `uszips.csv` are all in `data/raw/` with those exact names.

**Few or zero results after filtering**
Run `--diagnose` to see the filter breakdown. Most common cause: `min_rent_to_price = 0.072` is cutting most ZIPs. If SA yields have compressed, try lowering to `0.065`. The diagnose output shows exactly how many ZIPs each filter removes.

**Crime download fails or times out**
The SA crime file is ~600MB. On a slow connection it may time out. Try again on a better connection, or manually download from the [SA Open Data portal](https://data.sanantonio.gov) and save as `data/raw/sa_crime_raw.csv`.

**Stability shows 0.50 (neutral) for all ZIPs**
The `zhvi_cov` column is missing from the merged dataset. This usually means the ZHVI file didn't have enough historical date columns. Run `--diagnose` and check the "ZHVI stability" output — it will show how many months of data were found.

**Results look identical every run**
Census data caches to `data/raw/census_acs_raw.csv`. Delete that file to force a fresh pull from the Census API.

---

## Disclaimer

This tool is for personal research and decision support only. It does not constitute financial, investment, or legal advice. Real estate involves risk, including the risk of loss. Always conduct independent due diligence and consult qualified professionals before making any purchase decision. VA loan eligibility and terms depend on individual circumstances and are subject to change.
