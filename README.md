# `etl-pipeline` — Multi-API ETL & Reporting

[![tests](https://github.com/beso-pr/data-automation/actions/workflows/tests.yml/badge.svg)](https://github.com/beso-pr/data-automation/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)

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
- **Dry-run preview** — `--dry-run` diffs the proposed output against the live database and renders a preview HTML, without touching either.
- **Resilient HTTP** — exponential-backoff retries, honours `Retry-After` headers, and a per-host circuit breaker that fails fast when an upstream is dead.
- **Self-healing weather** — auto-falls back to the Open-Meteo forecast endpoint when sales data brushes up against today's date (the archive lags ~5 days).
- **Strict CSV validation** — schema, ISO currency/country shapes, non-negative amounts, integer units, duplicate detection. All errors collected in one pass and reported together.
- **Disk caching** — repeated runs hit the cache instead of the API (24h TTL by default), making re-runs ~10× faster.
- **Dual logging** — pretty console output + rotating file log under `output/etl.log` so old runs are still debuggable.
- **Strongly-typed config** — frozen dataclasses loaded from `config.yaml`.
- **Tidy outputs** — `output/etl.sqlite` (indexed, replaceable tables) + `output/report.html` (KPI dashboard).
- **Anomaly detection** — z-score flag for unusually high/low city-day revenue.
- **Weather correlation** — per-city Pearson correlation between temp/precip and revenue.
- **Tested** — 71 pytest cases (11 test files) mock HTTP at the client boundary; the suite runs offline in <1s.
- **Lean dependency surface** — pandas, jinja2, requests, pyyaml. Stdlib for retries, circuit breaker, CLI, logging.
- **Cross-platform** — works on macOS, Linux, and Windows. Python 3.10+.

## Quickstart — from zero in under 2 minutes

**Prerequisites** — Python **3.10 or newer**, `git`, and outbound HTTPS to
`frankfurter.app` and `api.open-meteo.com` for the first run (subsequent runs
use the cache). No API keys, no Docker, no system services needed.

Pick the section for your OS, copy-paste the block as-is, and you should see an
HTML report at `output/report.html` at the end.

### macOS / Linux

```bash
# 1. Get the code
git clone https://github.com/beso-pr/data-automation.git
cd data-automation

# 2. Create + activate an isolated environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install (with dev extras for tests)
python -m pip install --upgrade pip
pip install -e ".[dev]"

# 4. Verify the install (should print "71 passed in <1s")
pytest -q

# 5. Run the pipeline against the bundled sample dataset
etl run

# 6. Open the report
open output/report.html      # macOS
xdg-open output/report.html  # Linux
```

### Windows (PowerShell)

```powershell
# 1. Get the code
git clone https://github.com/beso-pr/data-automation.git
cd data-automation

# 2. Create + activate an isolated environment
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install (with dev extras for tests)
python -m pip install --upgrade pip
pip install -e ".[dev]"

# 4. Verify the install (should print "71 passed in <1s")
pytest -q

# 5. Run the pipeline against the bundled sample dataset
etl run

# 6. Open the report
start output\report.html
```

> If PowerShell blocks the activation script, run once per user:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Windows (cmd.exe)

```bat
git clone https://github.com/beso-pr/data-automation.git
cd data-automation

py -3 -m venv .venv
.venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -e ".[dev]"

pytest -q
etl run
start output\report.html
```

### Don't want to install the `etl` script?

The package always works as a module on every OS, no console-script needed:

```bash
python -m etl_pipeline run
python -m etl_pipeline run --dry-run
python -m etl_pipeline --help
```

### What "success" looks like

After step 5 (`etl run`) you should see roughly this on stdout:

```
00:58:02  INFO  etl_pipeline.cli                  ETL pipeline starting (base_currency=USD)
00:58:02  INFO  etl_pipeline.extract.sales_csv    Loaded 84 sales rows ...
00:58:02  INFO  etl_pipeline.extract.fx_api       Fetched FX rates: 70 (date,currency) pairs ...
00:58:02  INFO  etl_pipeline.extract.weather_api  Fetched weather: 84 (date,city) rows ...
00:58:02  INFO  etl_pipeline.cli                  Summary over 14 days
00:58:02  INFO  etl_pipeline.cli                  Revenue   : ...
00:58:02  INFO  etl_pipeline.cli                  SQLite : .../output/etl.sqlite
00:58:02  INFO  etl_pipeline.cli                  Report : .../output/report.html
```

…and two new files under `output/`:

```
output/
├── etl.log        # rotating run log
├── etl.sqlite     # ref + fact + report tables, with indexes
└── report.html    # open in any browser
```

## Useful flags

```bash
etl run --dry-run                # Preview changes without touching SQLite (see below)
etl run --skip-weather           # Skip the weather API (faster, no enrichment)
etl run --no-cache               # Bypass the on-disk cache, force live API calls
etl run -c path/to/config.yaml   # Use an alternate config
etl --log-level DEBUG run        # Verbose logging (shows cache hits)
etl version                      # Print package version
etl --help                       # Show all options
```

### Dry-run mode

`etl run --dry-run` runs **extract + transform** exactly as a real run, then
**diffs** the proposed output against the existing SQLite database and prints
a table — without writing anything to the DB. The HTML report is routed to
`output/report.preview.html` so the canonical `report.html` is also untouched.

Example output:

```
Dry-run preview for output/etl.sqlite
TABLE                         STATUS       EXISTING   PROPOSED        Δ
ref_fx_rates                  unchanged          70         70       +0
ref_weather                   replace            84         91       +7
fact_sales                    replace            84         91       +7
rpt_daily_summary             unchanged          14         14       +0
rpt_country_summary           replace             6          7       +1
...
```

| Status      | Meaning                                                        |
| ----------- | -------------------------------------------------------------- |
| `create`    | Table doesn't exist yet — first run                            |
| `replace`   | Row count would change — DB would be overwritten on a real run |
| `unchanged` | Proposed row count matches existing                            |

Use this before promoting a config or schema change in production.

## Tests

The full suite is offline (HTTP is mocked at the client boundary):

```bash
pytest -q                    # 71 tests in <1s
pytest -v                    # verbose
pytest -k transform          # filter by name substring
pytest --cov=etl_pipeline    # with coverage
```

If `pytest` isn't on `$PATH` after activation, use the module form:

```bash
python -m pytest -q
```

### Continuous integration

Every push and pull request is exercised by GitHub Actions across a 3 × 3
matrix:

| OS              | Python 3.10 | Python 3.11 | Python 3.12 |
| --------------- | :---------: | :---------: | :---------: |
| ubuntu-latest   | ✓ | ✓ | ✓ |
| macos-latest    | ✓ | ✓ | ✓ |
| windows-latest  | ✓ | ✓ | ✓ |

A separate `lint` job runs `ruff check` and `ruff format --check` on every
commit. See [`.github/workflows/tests.yml`](.github/workflows/tests.yml).

## Project layout

```
data-automation/
├── README.md
├── pyproject.toml
├── config.yaml                          # default pipeline configuration
├── .gitignore / .gitattributes
├── data/
│   └── sales_sample.csv                 # 84-row demo dataset
├── src/etl_pipeline/
│   ├── cli.py                           # argparse CLI (no third-party CLI lib)
│   ├── config.py                        # YAML -> frozen dataclasses
│   ├── http_client.py                   # retries + Retry-After + cache, around requests
│   ├── circuit_breaker.py               # per-host fail-fast breaker
│   ├── cache.py                         # JSON disk cache with TTL
│   ├── logging_setup.py                 # console + rotating file logging (stdlib)
│   ├── extract/
│   │   ├── sales_csv.py                 # CSV schema + value validation
│   │   ├── fx_api.py                    # Frankfurter date-range API
│   │   └── weather_api.py               # Open-Meteo geocoding + archive/forecast APIs
│   ├── transform/pipeline.py            # FX normalisation, KPIs, anomalies, correlation
│   ├── load/
│   │   ├── sqlite_loader.py             # DataFrames -> SQLite (indexed)
│   │   ├── dry_run.py                   # diff proposed vs existing without writing
│   │   └── html_report.py               # Jinja2-rendered dashboard
│   └── templates/report.html.j2         # self-contained HTML/CSS report
└── tests/                               # 11 test files, 71 cases
```

## Configuration

Everything's driven by `config.yaml` (paths in the file are resolved relative to
the config file itself, so the project is fully relocatable):

| Key                                       | Purpose                                                                |
| ----------------------------------------- | ---------------------------------------------------------------------- |
| `input.sales_csv`                         | Path to the raw sales CSV                                              |
| `base_currency`                           | Currency to normalise all revenue to (e.g. `USD`)                      |
| `cities`                                  | Cities to fetch weather for (resolved to coordinates)                  |
| `apis.fx`                                 | Frankfurter FX API URL + timeout                                       |
| `apis.weather_geocode`                    | Open-Meteo geocoding URL + timeout                                     |
| `apis.weather_archive`                    | Open-Meteo archive URL + timeout                                       |
| `apis.weather_forecast`                   | Open-Meteo forecast URL (omit to disable fallback)                     |
| `weather.archive_lag_days`                | How far behind today the archive trails (default 5)                    |
| `weather.fallback_to_forecast`            | If true, recent dates are pulled from the forecast endpoint            |
| `http.max_retries`                        | Retry budget per request                                               |
| `http.backoff_seconds`                    | Base for exponential backoff (capped at 30 s)                          |
| `http.circuit_breaker_threshold`          | Open the breaker after this many consecutive failures (per host)       |
| `http.circuit_breaker_reset_seconds`      | Cool-down before a single probe is allowed through                     |
| `cache.enabled` / `directory` / `ttl_hours` | On/off, on-disk cache directory, TTL in hours                        |
| `logging.file_path`                       | Rotating log file path (set to `null` to disable)                      |
| `logging.max_bytes` / `backup_count`      | Rotation thresholds                                                    |
| `output`                                  | SQLite + HTML output paths                                             |

To run against your own data, point `input.sales_csv` at your file. The CSV
needs these columns: `date, city, country, currency, amount_local, units_sold`
(plus any extras — they'll be carried through).

## How it works

```
1. EXTRACT   sales_csv.py     -> validate schema, parse dates, normalise text
             fx_api.py        -> fetch FX time series from Frankfurter (cached)
             weather_api.py   -> geocode cities, fetch daily weather (cached)

2. TRANSFORM pipeline.py      -> join sales × FX -> revenue in base currency
                              -> left-join weather on (date, city)
                              -> roll up to daily / country / city summaries
                              -> flag city-day revenue outliers (|z| ≥ 2.0)
                              -> compute weather/revenue Pearson correlation

3. LOAD      sqlite_loader.py -> write 8 indexed tables to SQLite
             html_report.py   -> render dashboard via Jinja2 template
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

- **`python3: command not found`** (Linux) — install Python 3.10+ via your
  distro (`sudo apt install python3.10 python3.10-venv`) or `pyenv`. macOS users
  can install via `brew install python@3.12`.
- **`pip install -e ".[dev]"` fails with a build error** — your `pip` is too
  old to handle PEP 517 builds. Run `python -m pip install --upgrade pip` and
  retry.
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
- **Open-Meteo says no data for recent dates** — the archive lags ~5 days. The
  pipeline auto-falls back to the forecast endpoint by default; if you turned
  that off (`weather.fallback_to_forecast: false`), turn it back on.
- **Behind a corporate proxy** — set `HTTPS_PROXY` and `HTTP_PROXY` env vars
  before running; `requests` honours them automatically.
- **First run hangs / very slow** — the first run hits live APIs to populate
  the cache (~2–4s typical). Re-runs are <1s. Force a fresh fetch with
  `etl run --no-cache`.
