# SATX House Hack Scoring Model

A data-driven tool that ranks San Antonio ZIP codes by how well they work for a **military house hack** — buying a property near BAMC / Fort Sam Houston, living in part of it, and renting out the rest to offset or eliminate your mortgage payment.

Built by a 4N0 (Aerospace Medical Technician) stationed at BAMC. Designed around the realities of military life: fixed duty station, 3-year typical hold period, VA loan eligibility, and a tenant pool that skews heavily military.

---

## What Is a House Hack?

A house hack means buying a property where part of it generates rental income while you live there. Common setups:

- **Duplex/triplex/fourplex** — you live in one unit, rent the others
- **Single-family home with extra rooms** — rent bedrooms to roommates
- **Garage apartment or ADU** — rent a separate structure on the same lot

The goal: your tenants pay your mortgage. In the best cases, you live for free or even cash flow positive. After your PCS, you convert the whole property to a rental.

---

## What This Tool Does

This model takes publicly available data for the San Antonio area and scores every ZIP code across four dimensions that matter for a military house hack:

1. **Rent-to-price ratio** — How strong is the rental yield relative to purchase price?
2. **Crime rate** — How safe is the area for you and your tenants?
3. **Owner-occupancy rate** — Is this a stable neighborhood or a transient one?
4. **Commute to BAMC** — How far is it from where you would actually work?

It combines those four scores into a single ranked list so you can focus your property search on the ZIPs that objectively make the most sense — instead of spending months Zillow-scrolling based on gut feel.

**What this tool is NOT:** It does not replace boots-on-the-ground research. It narrows your universe from 60+ ZIP codes down to 8–10 worth seriously investigating. You still need to look at actual listings, drive the neighborhoods, and run the numbers on specific properties.

---

## Why These Four Factors?

### 1. Rent-to-Price Ratio (35% of score)

**What it measures:** Annual rental income divided by home purchase price.

**Formula:** `(monthly rent × 12) ÷ home value`

**Example:** A $250,000 home renting for $1,500/month = `($1,500 × 12) ÷ $250,000 = 0.072` (7.2% yield)

**Why it matters:** This is the core investment signal. Higher yield means your tenants cover more of your mortgage. San Antonio is a moderate-yield market — the model is tuned to SA's realistic range (roughly 5.5%–13%), not national benchmarks.

**Minimum threshold:** 5.5% gross yield. Below this, the math rarely works even in the best-case scenario.

### 2. Crime Rate (25% of score)

**What it measures:** Reported criminal incidents per 1,000 residents, filtered to actual crimes (assault, robbery, burglary, theft, etc.) — not traffic stops, noise complaints, or medical calls.

**Why it matters:** High crime = harder to attract quality tenants, higher vacancy, more wear on the property, and frankly — you have to live there too.

**Important nuance:** The raw crime numbers are log-transformed before scoring. Without this, one extremely high-crime ZIP stretches the scale so much that all other ZIPs look equally safe by comparison. The log transform compresses the tail so that a ZIP with crime=25/1k and crime=200/1k are treated as genuinely different.

### 3. Owner-Occupancy Rate (20% of score)

**What it measures:** The percentage of homes in the ZIP that are owner-occupied (vs. renter-occupied), from U.S. Census data.

**Why it matters:** Neighborhoods where most people own their homes tend to be more stable — better maintained, lower turnover, less crime drift over time. However, extremely high owner-occupancy (80%+) can also mean very few renters in the area, making it harder to find tenants.

**Target range:** 40%–85%. Below 40% = too transient. Above 85% = low rental demand.

### 4. Commute to BAMC (20% of score)

**What it measures:** Estimated drive time from the center of each ZIP code to Brooke Army Medical Center at Fort Sam Houston.

**Why it matters:** You will be driving this every day, often at 0530 or after a 12-hour shift. A 10-minute difference compounds over a 3-year tour. It also affects which military tenants will realistically want to live in your property.

---

## How the Scoring Works

Each ZIP code gets a score between 0 and 1 for each factor. These are then combined:

```
Final Score = (Rent-to-Price × 0.35) + (Crime × 0.25) + (Owner Occupancy × 0.20) + (Commute × 0.20)
```

**Key thing to understand:** Scores are _relative_, not absolute. A crime score of 0.8 means "this ZIP is safer than 80% of other SA ZIPs in this dataset" — not "this ZIP has objectively safe crime levels." Always look at the raw numbers alongside the score.

The weights are fully adjustable. If commute is your top priority, you can bump it to 0.40. See the **Adjusting the Model** section below.

---

## Data Sources

The model uses five data sources. Two require a manual one-time download. Three are fetched automatically.

### Manual Downloads Required (One Time)

1. Zillow Home Value Index (ZHVI)
   - What it is: Estimated median home values by ZIP code, updated monthly
   - Where to get it: [zillow.com/research/data](https://www.zillow.com/research/data/)
     - Scroll to "Home Values" section
     - Find "ZHVI All Homes (SFR, Condo/Co-op) Time Series, Smoothed, Seasonally Adjusted"
     - Select "ZIP code" from the Geography dropdown
     - Click Download
   - Save as: `data/raw/zillow_zhvi_zip.csv`

2. Zillow Observed Rent Index (ZORI)
   - What it is: Estimated median asking rents by ZIP code, updated monthly
   - Where to get it: Same page ([zillow.com/research/data](https://www.zillow.com/research/data/))
     - Scroll to "Rentals" section
     - Find "ZORI (Smoothed): All Homes Plus Multifamily"
     - Select "ZIP code"
     - Click Download
   - Save as: `data/raw/zillow_zori_zip.csv`

3. ZIP Code Coordinates (SimpleMaps)
   - What it is: The geographic center point (latitude/longitude) of every U.S. ZIP code — needed to calculate commute distances
   - Where to get it: [simplemaps.com/data/us-zips](https://simplemaps.com/data/us-zips)
     - Scroll to the free download option
     - Download the CSV file
   - Save as: `data/raw/uszips.csv`

### Auto-Downloaded (Nothing Required)

1. U.S. Census Bureau — American Community Survey
   - Owner-occupancy rates, population counts, and household income by ZIP code
   - Downloaded automatically from the Census API on first run and cached locally

2. San Antonio Police Department — Calls for Service
   - Every police dispatch call in SA with incident type and ZIP code
   - Downloaded automatically from the SA Open Data portal on first run (~600MB, takes 30–90 seconds)
   - Only criminal incident types are counted — medical emergencies, noise complaints, and welfare checks are filtered out

---

## Setup Instructions (Step by Step)

### Step 1 — Check Your Python Version

Open Terminal (Mac/Linux) or Command Prompt (Windows) and run:

```bash
python3 --version
```

You need version 3.9 or newer. If you don't have Python, download it from [python.org](https://www.python.org/downloads/).

### Step 2 — Open the Project Folder

Navigate to the project folder in your terminal:

```bash
cd path/to/satx_house_hack_model
```

### Step 3 — Install Required Packages

```bash
pip install -r requirements.txt
```

This installs everything the model needs. Takes 1–2 minutes.

### Step 4 — Download the Three Manual Data Files

Following the instructions in the Data Sources section above, download the three files and place them in `data/raw/`. Your folder should look like this when done:

```
data/
└── raw/
    ├── zillow_zhvi_zip.csv      ← downloaded from Zillow
    ├── zillow_zori_zip.csv      ← downloaded from Zillow
    └── uszips.csv               ← downloaded from SimpleMaps
```

### Step 5 (Optional) — Add a Google Maps API Key

For real drive times instead of straight-line estimates, you can add a free Google Maps API key. The free tier provides $200/month in credits which is far more than this model needs.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project and enable the "Distance Matrix API"
3. Generate an API key
4. In the project folder, copy `.env.example` to a new file called `.env`
5. Open `.env` and paste your key after `GOOGLE_MAPS_API_KEY=`

Without a key, the model estimates commute times using straight-line distance — accurate enough for ranking purposes.

### Step 6 — Run the Model

```bash
python main.py --no-google-maps
```

**First run:** Takes 2–4 minutes (mostly the ~600MB SA crime data download). You will see progress in the terminal.

**Subsequent runs:** Under 10 seconds — all data is cached locally.

Your results appear in the terminal and are saved to `outputs/top_zips_summary.csv`.

---

## Reading the Results

The output table looks like this:

```
rank   zip   median_home_value  median_rent  rent_to_price  commute_minutes  crime_per_1k  owner_occ_pct  final_score
   1  78109         $244,063       $1,686          0.083           22 min         12.09          75.3%        0.565
   2  78239         $213,816       $1,446          0.081           15 min         16.11          72.5%        0.558
```

**How to read it:**

- **rank** — Overall ranking. Lower is better.
- **zip** — The ZIP code being scored.
- **median_home_value** — Estimated median price of homes in that ZIP.
- **median_rent** — Estimated median asking rent in that ZIP.
- **rent_to_price** — Gross yield. Divide annual rent by home value. 0.083 = 8.3% yield.
- **commute_minutes** — Estimated drive time to BAMC.
- **crime_per_1k** — Criminal incidents per 1,000 residents. Lower = safer.
- **owner_occ_pct** — Percentage of homes that are owner-occupied.
- **final_score** — Composite score from 0–1. Higher = better overall.

**The weighted columns** (not shown above but in the full CSV) break down exactly how much each factor contributed to the final score for that ZIP. This tells you _why_ a ZIP ranked where it did.

---

## Command Reference

```bash
# Standard run — straight-line commute estimate
python main.py --no-google-maps

# With Google Maps drive times (requires API key in .env)
python main.py

# Show top 20 ZIPs instead of default 15
python main.py --no-google-maps --top 20

# Diagnostic mode — shows data details at every step, useful for troubleshooting
python main.py --no-google-maps --diagnose

# Test how stable rankings are across different weight assumptions
python sensitivity.py

# Stress test top 8 ZIPs with larger ±15% weight shifts
python sensitivity.py --top 8 --delta 0.15
```

---

## Sensitivity Testing — Is Your #1 ZIP Really #1?

Run this after the main pipeline:

```bash
python sensitivity.py
```

This runs two tests to make sure your results are real signal, not just artifacts of your configuration:

**Test 1 — Weight Stability**
Systematically shifts each weight up and down by 10% and checks whether your top ZIPs stay on top. If 80%+ of scenarios show the same winners → your results have genuine signal. If rankings flip constantly → the model is sensitive to your arbitrary weight choices.

**Test 2 — Filter Dependency**
Scores all ZIPs without any hard filters applied. Checks whether your top ZIPs still rank highly when they have to compete against the full pool. If they hold → they earned their rank on merit. If they collapse → the hard filters were doing the heavy lifting.

A real result survives both tests.

---

## Adjusting the Model

Everything tunable lives in `src/config.py`. You do not need to edit any other file.

### Change Priority Weights

```python
WEIGHTS = {
    "rent_to_price":   0.35,   # raise if yield is your #1 priority
    "crime":           0.25,   # raise if safety is your #1 priority
    "owner_occupancy": 0.20,
    "commute":         0.20,   # raise if commute matters most to you
}
```

Weights must add up to 1.0 exactly. The model will throw an error if they don't.

### Change Hard Filters

These cut ZIPs before scoring — failing ZIPs don't appear in results at all:

```python
THRESHOLDS = {
    "min_rent_to_price": 0.055,   # minimum gross yield (5.5%)
    "max_home_value":    500_000,  # adjust to your VA loan / budget limit
    "min_owner_occ_pct": 0.40,    # below this = too transient
    "max_owner_occ_pct": 0.85,    # above this = likely low rental demand
}
```

### Change the Crime Filter Aggressiveness

```python
CRIME_PERCENTILE_CUTOFF = 0.60  # keep the 60% least-criminal ZIPs
```

This is a relative filter — it keeps the bottom 60% of ZIPs by crime rate within your scored pool. Increase toward 1.0 to include more ZIPs (more lenient on crime). Decrease toward 0.5 to keep only the safest half.

### Adapt for a Different Duty Station

```python
DUTY_STATION = {
    "name": "BAMC - Fort Sam Houston",
    "lat": 29.4563,
    "lon": -98.4436,
}
```

Replace the name, latitude, and longitude with your actual workplace. Right-click any location in Google Maps to see its coordinates.

Also update `TARGET_METRO` to match the new city, and replace the Zillow files with the relevant metro data.

---

## Understanding the Limitations

**This model is a macro filter, not a purchase decision.** Before acting on any result:

**What the model cannot see:**

- HOA restrictions that may prohibit renting rooms or units
- Whether the actual housing stock in that ZIP contains duplexes or multi-unit properties
- Days-on-market and liquidity — important for a PCS exit strategy
- Block-level conditions — a ZIP can average "safe" while having dangerous pockets
- School quality — relevant if your target tenants are military families
- Military renter density — are other service members already living there?

**Known data limitations:**

- Zillow ZORI measures asking rent for new leases, not long-term stabilized rents
- Crime data is SA police dispatch calls filtered to criminal types — not FBI-verified crime statistics
- Census data is from the 2022 ACS 5-year survey — some figures may be a few years old
- Straight-line commute estimates can diverge from actual drive times, especially for ZIPs with geographic barriers or traffic-heavy routes

**The right workflow:**

1. Run the model → get a ranked shortlist
2. Look up the top 8–10 ZIPs on Google Maps — drive through them
3. Search Zillow/Realtor.com filtered to those ZIPs for actual listings
4. For any property you are serious about, run a complete cash-flow analysis: mortgage payment, estimated vacancy, maintenance reserves, insurance, taxes
5. Consult a military-friendly real estate agent in SA who understands VA loans and house hacking

---

## Project File Structure (For Developers)

```
satx_house_hack_model/
│
├── data/
│   ├── raw/              ← source files, never modified by the pipeline
│   ├── processed/        ← merged intermediate dataset (generated)
│   └── final/            ← scored and ranked output (generated)
│
├── src/
│   ├── config.py         ← ALL tunable parameters — weights, thresholds, API keys
│   ├── data_loader.py    ← downloads and reads each raw data source
│   ├── preprocess.py     ← cleans each source, filters crime by type, merges
│   ├── feature_engineering.py  ← computes yield, log-transforms crime, applies filters
│   ├── scoring.py        ← weighted scoring, ranking, summary table formatting
│   ├── commute.py        ← distance/drive time from each ZIP centroid to BAMC
│   └── utils.py          ← logging setup, file I/O, validation helpers
│
├── outputs/              ← final human-readable results
├── main.py               ← orchestrates the full pipeline end-to-end
├── sensitivity.py        ← robustness tests (weight stability + filter dependency)
├── requirements.txt      ← Python package dependencies
└── README.md             ← this file
```

**Pipeline execution order:**

```
data_loader → preprocess → feature_engineering → scoring → outputs
```

Each step is isolated and logged. If something breaks, the terminal output tells you exactly which step failed and why. The `--diagnose` flag prints a data snapshot after every step with row counts, value ranges, and ZIP overlap analysis across all sources.

---

## Troubleshooting

**"File not found" error on startup**
One of the three manual download files is missing or misnamed. Check that `zillow_zhvi_zip.csv`, `zillow_zori_zip.csv`, and `uszips.csv` are all in `data/raw/` with those exact names.

**"Empty DataFrame" / zero results**
Run with `--diagnose` to see which step is failing. Common causes:

- The Zillow Metro filter is not matching "San Antonio" (check your ZHVI/ZORI file has a "Metro" column)
- The hard filters in `config.py` are too aggressive for your data — try loosening `min_rent_to_price` to 0.05

**Crime download fails or times out**
The SA crime file is ~600MB. On a slow connection it may time out. Try again, or manually download from [data.sanantonio.gov/dataset/sapd-calls-for-service](https://data.sanantonio.gov/dataset/sapd-calls-for-service) and save as `data/raw/sa_crime_raw.csv`.

**Results look the same every run**
The Census data caches to `data/raw/census_acs_raw.csv` after the first pull. If you want fresh data, delete that file and re-run.

---

## Disclaimer

This tool is for personal research and decision-support only. It does not constitute financial, investment, or legal advice. Real estate investment involves risk. Always conduct independent due diligence and consult qualified professionals before making any purchase decision. VA loan eligibility and terms are subject to individual circumstances.
