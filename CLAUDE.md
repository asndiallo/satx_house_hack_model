# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A data-driven pipeline for ranking San Antonio ZIP codes for military house hacks — buying property near BAMC, living in part, renting the rest. The model implements **Path B logic**: screen out unacceptable risk first (hard filters), then optimize within what remains (weighted scoring).

## Running the Pipeline

```bash
# Full run with Google Maps commute data
python main.py

# Run without Google Maps (uses Haversine straight-line fallback)
python main.py --no-google-maps

# Show diagnostic info after each pipeline step
python main.py --no-google-maps --diagnose

# Show only top N results
python main.py --top 10
```

## Sensitivity / Robustness Testing

```bash
python sensitivity.py                     # both tests, top 5, ±10% weight delta
python sensitivity.py --test weights      # weight stability only
python sensitivity.py --test filters      # filter dependency only (scores without hard filters)
python sensitivity.py --top 8 --delta 0.15
```

## Notebooks

```bash
jupyter notebook notebooks/01_eda.ipynb         # exploratory data analysis
jupyter notebook notebooks/02_cashflow.ipynb    # cashflow analysis
```

## Environment Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # then add GOOGLE_MAPS_API_KEY
```

The `.env` file needs `GOOGLE_MAPS_API_KEY` for drive-time commute calculation. Without it, the pipeline falls back to Haversine distance.

## Architecture

### Pipeline Flow

```math
data_loader.py  →  preprocess.py  →  commute.py  →  feature_engineering.py  →  scoring.py
(load raw data)    (clean/merge)     (drive times)   (filters + normalize)      (weighted score)
```

Orchestrated by `main.py` with all parameters sourced from `src/config.py`.

### Key Architectural Decisions

**`src/config.py` is the single source of truth.** All weights, thresholds, paths, API URLs, and crime type definitions live here. To change model behavior (e.g., raise the price ceiling, adjust scoring weights), edit only this file.

**Filters vs. weights are intentionally separate:**

- Hard filters in `feature_engineering.py` are non-negotiables (high-crime ZIPs are dropped regardless of yield)
- Weights in `scoring.py` express relative priorities among acceptable ZIPs

**Data integrity via inner joins:** All data sources are joined on ZIP code; rows with missing data are dropped rather than imputed. This ensures clean, complete records.

**Crime data quirks:**

- The SA Open Data portal returns 403 to Python's default user-agent — `data_loader.py` uses browser-spoofing headers
- The 631 MB SAPD dataset is cached locally after first download
- Military ZIPs (78234, 78235, 78236, 78243) are excluded because base populations distort crime normalization

**Log-transform on crime** (in `feature_engineering.py`) corrects for right-skewed distribution; this is validated visually in `01_eda.ipynb`.

### Scoring Factors and Weights

| Factor              | Weight | Notes                                        |
| ------------------- | ------ | -------------------------------------------- |
| Crime rate          | 30%    | Log-transformed; top 45% safest ZIPs only    |
| Rent-to-price ratio | 25%    | Gross yield; 6.5% floor, 12% cap             |
| Owner-occupancy     | 20%    | 50%–80% target range                         |
| Commute to BAMC     | 15%    | Google Maps drive time or Haversine fallback |
| Price stability     | 10%    | 5-year ZHVI coefficient of variation         |

### Output Files

- `data/final/ranked_zip_scores.csv` — all ZIPs that passed filters, with raw values + `weighted_*` breakdown columns
- `outputs/top_zips_summary.csv` — top 15 ZIPs in human-readable format
- `model_run.log` — execution log from latest run
- `data/processed/merged_zip_dataset.csv` — pre-filter merged data (for sensitivity tests)
