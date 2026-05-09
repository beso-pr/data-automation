"""Tests for SQLite + HTML loaders."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from etl_pipeline.load.html_report import render_html_report
from etl_pipeline.load.sqlite_loader import TABLE_MAP, load_to_sqlite
from etl_pipeline.transform.pipeline import run_transforms


def _build_result(
    sample_sales: pd.DataFrame,
    sample_fx_rates: pd.DataFrame,
    sample_weather: pd.DataFrame,
):
    return run_transforms(sample_sales, sample_fx_rates, sample_weather, "USD")


def test_load_to_sqlite_writes_all_expected_tables(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    result = _build_result(sample_sales, sample_fx_rates, sample_weather)
    db = tmp_path / "etl.sqlite"
    load_to_sqlite(result, sample_fx_rates, sample_weather, db)

    assert db.exists()
    with sqlite3.connect(db) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    expected = {"ref_fx_rates", "ref_weather", *TABLE_MAP.values()}
    assert expected.issubset(names)


def test_load_to_sqlite_creates_indexes(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    result = _build_result(sample_sales, sample_fx_rates, sample_weather)
    db = tmp_path / "etl.sqlite"
    load_to_sqlite(result, sample_fx_rates, sample_weather, db)
    with sqlite3.connect(db) as conn:
        idx = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "ix_fact_sales_date" in idx
    assert "ix_fx_rates_date_ccy" in idx


def test_render_html_report_writes_self_contained_html(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    result = _build_result(sample_sales, sample_fx_rates, sample_weather)
    out = tmp_path / "report.html"
    render_html_report(result, "USD", out)
    html = out.read_text(encoding="utf-8")

    assert "<!doctype html>" in html.lower()
    assert "Multi-API ETL" in html
    assert "USD" in html
    assert "Berlin" in html
    assert "London" in html
