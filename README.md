# SATX House Hack Scoring Model

Geo-spatial decision scoring system to identify military-compatible house-hack submarkets near BAMC / Fort Sam Houston.

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your Google Maps API key (optional but recommended)
cp .env.example .env
# edit .env and add your key

# 3. Download required data files into data/raw/
# See DATA SOURCES section below

# 4. Run the pipeline
python main.py

# Run without Google Maps (uses straight-line distance)
python main.py --no-google-maps

# Show top 20 ZIPs
python main.py --top 20
```

## Data Sources (Manual Downloads Required)

| File                  | Source                         | URL                                     |
| --------------------- | ------------------------------ | --------------------------------------- |
| `zillow_zhvi_zip.csv` | Zillow ZHVI ZIP-level          | <https://www.zillow.com/research/data/> |
| `zillow_zori_zip.csv` | Zillow ZORI ZIP-level          | <https://www.zillow.com/research/data/> |
| `uszips.csv`          | SimpleMaps ZIP centroids       | <https://simplemaps.com/data/us-zips>   |
| `sa_crime_raw.csv`    | SA Open Data (auto-downloaded) | Auto                                    |
| `census_acs_raw.csv`  | Census ACS API (auto-fetched)  | Auto                                    |

## Scoring Weights

Configured in `src/config.py`. Current defaults:

| Factor              | Weight | Why                           |
| ------------------- | ------ | ----------------------------- |
| Rent-to-Price Ratio | 35%    | Core investment signal        |
| Crime Rate          | 25%    | Tenant safety filter          |
| Owner Occupancy     | 20%    | Neighborhood stability        |
| Commute to BAMC     | 20%    | Military lifestyle constraint |

**Challenge these weights before using results for real decisions.**

## Output

Results saved to:

- `data/final/ranked_zip_scores.csv` — full scored dataset
- `outputs/top_zips_summary.csv` — human-readable top ZIPs
