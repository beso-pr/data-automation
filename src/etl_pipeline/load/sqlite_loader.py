"""Persist the transformed dataframes into a single SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ..logging_setup import get_logger
from ..transform.pipeline import TransformResult

logger = get_logger(__name__)


TABLE_MAP: dict[str, str] = {
    "sales_normalised": "fact_sales",
    "daily_summary": "rpt_daily_summary",
    "country_summary": "rpt_country_summary",
    "city_summary": "rpt_city_summary",
    "anomalies": "rpt_anomalies",
    "weather_correlation": "rpt_weather_correlation",
}


def load_to_sqlite(
    result: TransformResult,
    fx_rates: pd.DataFrame,
    weather: pd.DataFrame,
    sqlite_path: str | Path,
) -> None:
    """Write all output dataframes to ``sqlite_path``, replacing existing tables."""
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as conn:
        # Reference data
        _write(conn, fx_rates, "ref_fx_rates")
        _write(conn, weather, "ref_weather")
        # Fact + report tables
        for attr, table in TABLE_MAP.items():
            _write(conn, getattr(result, attr), table)

        _create_indexes(conn)
        conn.commit()

    logger.info("Wrote %d tables to %s", len(TABLE_MAP) + 2, path)


def _write(conn: sqlite3.Connection, df: pd.DataFrame, table: str) -> None:
    df.to_sql(table, conn, if_exists="replace", index=False)
    logger.debug("  %s: %d rows", table, len(df))


def _create_indexes(conn: sqlite3.Connection) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_fact_sales_date ON fact_sales(date)",
        "CREATE INDEX IF NOT EXISTS ix_fact_sales_city ON fact_sales(city)",
        "CREATE INDEX IF NOT EXISTS ix_fact_sales_country ON fact_sales(country)",
        "CREATE INDEX IF NOT EXISTS ix_fx_rates_date_ccy ON ref_fx_rates(date, currency)",
    ]
    cur = conn.cursor()
    for stmt in statements:
        cur.execute(stmt)
