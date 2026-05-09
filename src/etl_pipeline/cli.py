"""Command-line entry point for the ETL pipeline (stdlib argparse only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import __version__
from .cache import JsonDiskCache
from .config import Config
from .extract.fx_api import fetch_fx_rates
from .extract.sales_csv import SalesValidationError, load_sales
from .extract.weather_api import fetch_weather, geocode_cities
from .http_client import HttpClient
from .load.dry_run import build_dry_run_report
from .load.html_report import render_html_report
from .load.sqlite_loader import load_to_sqlite
from .logging_setup import configure_logging, get_logger
from .transform.pipeline import TransformResult, run_transforms

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="etl",
        description="Multi-API ETL: sales CSV + FX + weather -> SQLite + HTML report.",
    )
    parser.add_argument("--version", action="version", version=f"etl-pipeline {__version__}")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the full ETL pipeline end-to-end.")
    run.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config.yaml (default: ./config.yaml).",
    )
    run.add_argument(
        "--skip-weather",
        action="store_true",
        help="Skip the weather API (faster, no enrichment).",
    )
    run.add_argument("--no-cache", action="store_true", help="Bypass the disk cache.")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run extract + transform but DO NOT touch SQLite. "
            "The HTML report is written to <html_path>.preview.html so it doesn't "
            "clobber the existing report. A summary diff is logged."
        ),
    )

    sub.add_parser("version", help="Print the package version and exit.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "version":
        configure_logging(args.log_level)
        print(f"etl-pipeline {__version__}")
        return 0

    if args.command == "run":
        return _run(
            args.config,
            args.log_level,
            skip_weather=args.skip_weather,
            no_cache=args.no_cache,
            dry_run=args.dry_run,
        )

    return 2  # pragma: no cover


def _run(
    config_path: Path,
    log_level: str,
    *,
    skip_weather: bool,
    no_cache: bool,
    dry_run: bool,
) -> int:
    if not config_path.is_file():
        configure_logging(log_level)
        logger.error("Config file not found: %s", config_path)
        return 2

    cfg = Config.from_file(config_path)
    configure_logging(
        log_level,
        log_file=cfg.logging.file_path,
        max_bytes=cfg.logging.max_bytes,
        backup_count=cfg.logging.backup_count,
    )
    if dry_run:
        logger.warning("DRY-RUN mode: no SQLite writes; HTML routed to *.preview.html")
    logger.info("ETL pipeline starting (base_currency=%s)", cfg.base_currency)

    cache = JsonDiskCache(
        directory=cfg.cache.directory,
        ttl_hours=cfg.cache.ttl_hours,
        enabled=cfg.cache.enabled and not no_cache,
    )
    client = HttpClient(cfg.http, cache)

    try:
        sales = load_sales(cfg.sales_csv)
    except SalesValidationError as exc:
        logger.error("Sales CSV validation failed:\n%s", exc)
        return 3

    start, end = sales["date"].min(), sales["date"].max()

    currencies = sorted(sales["currency"].unique().tolist())
    fx_rates = fetch_fx_rates(client, cfg.fx_api, currencies, cfg.base_currency, start, end)

    if skip_weather:
        logger.warning("Weather enrichment skipped (--skip-weather)")
        weather = pd.DataFrame(columns=["date", "city", "country", "temp_mean_c", "precipitation_mm"])
    else:
        coords = geocode_cities(client, cfg.geocode_api, cfg.cities)
        forecast_api = cfg.weather_forecast_api if cfg.weather.fallback_to_forecast else None
        weather = fetch_weather(
            client,
            cfg.weather_archive_api,
            coords,
            start,
            end,
            forecast_api=forecast_api,
            archive_lag_days=cfg.weather.archive_lag_days,
        )

    result = run_transforms(sales, fx_rates, weather, cfg.base_currency)

    html_path = cfg.output.html_path
    if dry_run:
        report = build_dry_run_report(result, fx_rates, weather, cfg.output.sqlite_path)
        logger.info("\n%s", report.format())
        html_path = html_path.with_suffix(".preview.html")
        render_html_report(result, cfg.base_currency, html_path)
    else:
        load_to_sqlite(result, fx_rates, weather, cfg.output.sqlite_path)
        render_html_report(result, cfg.base_currency, html_path)

    _log_summary(result, cfg.base_currency, dry_run=dry_run)
    if dry_run:
        logger.info("Preview HTML : %s", html_path)
        logger.info("(SQLite was NOT modified)")
    else:
        logger.info("SQLite : %s", cfg.output.sqlite_path)
        logger.info("Report : %s", html_path)
    if cfg.logging.file_path:
        logger.info("Log    : %s", cfg.logging.file_path)
    cb_status = client.circuit.status()
    if cb_status:
        logger.info("Circuit breaker status: %s", cb_status)
    return 0


def _log_summary(result: TransformResult, base_currency: str, *, dry_run: bool = False) -> None:
    daily = result.daily_summary
    total_revenue = float(daily["total_revenue_base"].sum())
    banner = "= DRY RUN " + "=" * 50 if dry_run else "=" * 60
    logger.info(banner)
    logger.info("Summary over %d days", len(daily))
    logger.info("  Revenue   : %s %s", f"{total_revenue:,.2f}", base_currency)
    logger.info("  Units     : %s", f"{int(daily['total_units'].sum()):,}")
    logger.info("  Orders    : %s", f"{int(daily['num_orders'].sum()):,}")
    logger.info("  Anomalies : %d", len(result.anomalies))
    logger.info("=" * 60)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
