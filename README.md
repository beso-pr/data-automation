# `etl-pipeline` — Multi-API ETL & Reporting

A small, production-shaped Python automation that turns a raw multi-currency
sales CSV into a normalised SQLite warehouse and a self-contained HTML report —
enriched with foreign-exchange rates and historical weather data pulled from
two free public APIs (no API keys required).

> **Story it tells.** A retail business records sales in local currencies across
> 6 cities in 6 countries. Finance wants daily revenue in USD; merchandising
> wants to know whether weather correlates with sales. This script automates the
> entire job end-to-end in seconds.

```
       sales.csv  ─┐
                   ├──►  Extract  ──►  Transform  ──►  Load
   Frankfurter ────┤    (validate)   (FX convert,     (SQLite +
   (FX rates)      │                  weather join,    HTML report)
   Open-Meteo  ────┘                  KPI rollups,
   (weather)                          anomalies)
```

## Highlights

- **Multi-source ETL** — one CSV + two REST APIs joined into a single fact table.
- **Resilient HTTP** — exponential-backoff retry loop with configurable timeouts (zero retry-library deps).
- **Disk caching** — repeated runs hit the cache instead of the API (24h TTL by default), making re-runs ~10× faster.
- **Strongly-typed config** — frozen dataclasses loaded from `config.yaml`.
- **Tidy outputs** — `output/etl.sqlite` (indexed, replaceable tables) + `output/report.html` (KPI dashboard).
- **Anomaly detection** — z-score flag for unusually high/low city-day revenue.
- **Weather correlation** — per-city Pearson correlation between temp/precip and revenue.
- **Tested** — 41 pytest cases mock HTTP at the client boundary; suite runs offline in <1s.
- **Lean dependency surface** — pandas, jinja2, requests, pyyaml. Stdlib for retries, CLI, logging.
- **Cross-platform** — works on macOS, Linux, and Windows. Python 3.10+.

## Quickstart

Requires **Python 3.10 or newer**. No API keys, no Docker, no system services needed.

### macOS / Linux

```bash
git clone https://github.com/<your-username>/data-automation.git
cd data-automation

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

# Run the pipeline against the bundled sample dataset.
etl run
```

### Windows (PowerShell)

```powershell
git clone https://github.com/<your-username>/data-automation.git
cd data-automation

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"

etl run
```

> If PowerShell blocks the activation script, run once per user:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Windows (cmd.exe)

```bat
git clone https://github.com/<your-username>/data-automation.git
cd data-automation

py -3 -m venv .venv
.venv\Scripts\activate.bat

pip install -e ".[dev]"

etl run
```

### Don't want to install the `etl` script?

The package always works as a module on every OS:

```bash
python -m etl_pipeline run
```

## What you get

After a successful run:

```
output/
├── etl.sqlite     # ref + fact + report tables, with indexes
└── report.html    # open in any browser
```

Open the report:

| OS      | Command                        |
| ------- | ------------------------------ |
| macOS   | `open output/report.html`      |
| Linux   | `xdg-open output/report.html`  |
| Windows | `start output\report.html`     |

## Useful flags

```bash
etl run --skip-weather           # Skip the weather API (faster, no enrichment)
etl run --no-cache               # Bypass the on-disk cache, force live API calls
etl run -c path/to/config.yaml   # Use an alternate config
etl --log-level DEBUG run        # Verbose logging (shows cache hits)
etl version                      # Print package version
etl --help                       # Show all options
```

## Tests

The full suite is offline (HTTP is mocked at the client boundary):

```bash
pytest -q                    # 41 tests in <1s
pytest -v                    # verbose
pytest -k transform          # filter by name substring
pytest --cov=etl_pipeline    # with coverage
```

If `pytest` isn't on `$PATH` after activation, use the module form:

```bash
python -m pytest -q
```

## Project layout

```
data-automation/
├── README.md
├── pyproject.toml
├── config.yaml                          # default pipeline configuration
├── data/
│   └── sales_sample.csv                 # 84-row demo dataset
├── src/etl_pipeline/
│   ├── cli.py                           # argparse CLI (no third-party CLI lib)
│   ├── config.py                        # YAML → frozen dataclasses
│   ├── http_client.py                   # retries + caching wrapper around requests
│   ├── cache.py                         # JSON disk cache with TTL
│   ├── logging_setup.py                 # stdlib logging
│   ├── extract/
│   │   ├── sales_csv.py                 # CSV validation + parsing
│   │   ├── fx_api.py                    # Frankfurter date-range API
│   │   └── weather_api.py               # Open-Meteo geocoding + archive APIs
│   ├── transform/pipeline.py            # FX normalisation, KPIs, anomalies, correlation
│   ├── load/
│   │   ├── sqlite_loader.py             # DataFrames → SQLite (indexed)
│   │   └── html_report.py               # Jinja2-rendered dashboard
│   └── templates/report.html.j2         # self-contained HTML/CSS report
└── tests/                               # 9 test files, 41 cases
```

## Configuration

Everything's driven by `config.yaml` (paths in the file are resolved relative to
the config file itself, so the project is fully relocatable):

| Key                | Purpose                                                |
| ------------------ | ------------------------------------------------------ |
| `input.sales_csv`  | Path to the raw sales CSV                              |
| `base_currency`    | Currency to normalise all revenue to (e.g. `USD`)      |
| `cities`           | Cities to fetch weather for (resolved to coordinates)  |
| `apis.*`           | Endpoint URLs + per-call timeouts                      |
| `http`             | Retry count + backoff seconds                          |
| `cache`            | On/off, directory, TTL hours                           |
| `output`           | SQLite + HTML output paths                             |

To run against your own data, point `input.sales_csv` at your file. The CSV
needs these columns: `date, city, country, currency, amount_local, units_sold`
(plus any extras — they'll be carried through).

## How it works

```
1. EXTRACT   sales_csv.py     → validate schema, parse dates, normalise text
             fx_api.py        → fetch FX time series from Frankfurter (cached)
             weather_api.py   → geocode cities, fetch daily weather (cached)

2. TRANSFORM pipeline.py      → join sales × FX → revenue in base currency
                              → left-join weather on (date, city)
                              → roll up to daily / country / city summaries
                              → flag city-day revenue outliers (|z| ≥ 2.0)
                              → compute weather/revenue Pearson correlation

3. LOAD      sqlite_loader.py → write 8 indexed tables to SQLite
             html_report.py   → render dashboard via Jinja2 template
```

## Why this exists (the practical pitch)

This template replaces a workflow where someone:

1. Pastes sales CSVs into a spreadsheet,
2. Looks up FX rates manually for each currency,
3. Hand-builds revenue summaries per country/city,
4. Emails screenshots of pivot tables.

It runs in **seconds**, is **deterministic**, has **automated tests**, and
produces a single shareable HTML report — saving an estimated **~5 hours/week**
of repetitive analyst work per market.

## APIs used (no auth required)

- [Frankfurter](https://www.frankfurter.app/) — ECB foreign-exchange rates with date-range queries.
- [Open-Meteo](https://open-meteo.com/) — geocoding + historical daily weather archive.

Both are free, key-less, and rate-limit friendly, which keeps the project
self-contained and easy to demo.

## Troubleshooting

- **`pytest: command not found`** — your venv isn't activated, or the `pytest`
  shim isn't on `$PATH`. Either activate (`source .venv/bin/activate` on
  macOS/Linux, `.\.venv\Scripts\Activate.ps1` on Windows) or use the module
  form: `python -m pytest`.
- **`ModuleNotFoundError: etl_pipeline`** — you ran from a different shell that
  hasn't activated the venv yet. Re-activate, or invoke the module via the
  venv's interpreter directly: `./.venv/bin/python -m etl_pipeline run`.
- **`Config file not found`** — pass `-c <path>` or run from the project root
  where `config.yaml` lives. Process substitution like `<(echo ...)` is **not**
  supported (the path must be a real file).
- **Open-Meteo says no data** — the historical archive lags ~5 days. If you
  point at very recent dates, swap `archive-api` for `api.open-meteo.com` (the
  forecast endpoint) in `config.yaml`.
- **Behind a corporate proxy** — set `HTTPS_PROXY` and `HTTP_PROXY` env vars
  before running; `requests` honours them automatically.
