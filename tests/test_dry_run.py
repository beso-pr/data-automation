"""Tests for the dry-run preview helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from etl_pipeline.load.dry_run import build_dry_run_report
from etl_pipeline.load.sqlite_loader import TABLE_MAP, load_to_sqlite
from etl_pipeline.transform.pipeline import run_transforms


def _make_result(sample_sales, sample_fx_rates, sample_weather):
    return run_transforms(sample_sales, sample_fx_rates, sample_weather, "USD")


def test_marks_all_tables_as_create_when_db_missing(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    result = _make_result(sample_sales, sample_fx_rates, sample_weather)
    db = tmp_path / "etl.sqlite"  # does not exist
    report = build_dry_run_report(result, sample_fx_rates, sample_weather, db)

    statuses = {d.table: d.status for d in report.deltas}
    expected_tables = {"ref_fx_rates", "ref_weather", *TABLE_MAP.values()}
    assert set(statuses) == expected_tables
    assert all(s == "create" for s in statuses.values())


def test_marks_tables_as_replace_when_counts_change(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    db = tmp_path / "etl.sqlite"
    result = _make_result(sample_sales, sample_fx_rates, sample_weather)
    load_to_sqlite(result, sample_fx_rates, sample_weather, db)

    bigger_sales = pd.concat([sample_sales, sample_sales], ignore_index=True)
    bigger_sales["date"] = bigger_sales["date"].astype(str)  # avoid duplicate-row collisions
    bigger_result = run_transforms(sample_sales, sample_fx_rates, sample_weather, "USD")
    # Pretend the proposed sales count is different by passing a longer fx_rates frame.
    longer_fx = pd.concat([sample_fx_rates, sample_fx_rates], ignore_index=True)
    report = build_dry_run_report(bigger_result, longer_fx, sample_weather, db)

    fx_delta = next(d for d in report.deltas if d.table == "ref_fx_rates")
    assert fx_delta.status == "replace"
    assert fx_delta.delta == len(sample_fx_rates)  # doubled


def test_marks_tables_as_unchanged_when_counts_match(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    db = tmp_path / "etl.sqlite"
    result = _make_result(sample_sales, sample_fx_rates, sample_weather)
    load_to_sqlite(result, sample_fx_rates, sample_weather, db)

    report = build_dry_run_report(result, sample_fx_rates, sample_weather, db)
    statuses = {d.table: d.status for d in report.deltas}
    assert all(s == "unchanged" for s in statuses.values()), statuses


def test_corrupt_db_is_treated_as_missing(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    db = tmp_path / "etl.sqlite"
    db.write_bytes(b"not a sqlite database")
    result = _make_result(sample_sales, sample_fx_rates, sample_weather)
    report = build_dry_run_report(result, sample_fx_rates, sample_weather, db)
    assert all(d.status == "create" for d in report.deltas)


def test_format_renders_a_human_readable_table(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    result = _make_result(sample_sales, sample_fx_rates, sample_weather)
    db = tmp_path / "etl.sqlite"
    report = build_dry_run_report(result, sample_fx_rates, sample_weather, db)
    text = report.format()
    assert "Dry-run preview" in text
    assert "fact_sales" in text
    assert "create" in text


def test_dry_run_does_not_touch_existing_database(
    tmp_path: Path, sample_sales, sample_fx_rates, sample_weather
) -> None:
    db = tmp_path / "etl.sqlite"
    result = _make_result(sample_sales, sample_fx_rates, sample_weather)
    load_to_sqlite(result, sample_fx_rates, sample_weather, db)
    mtime_before = db.stat().st_mtime
    size_before = db.stat().st_size

    # Building a report opens the DB read-only.
    build_dry_run_report(result, sample_fx_rates, sample_weather, db)

    assert db.stat().st_mtime == mtime_before
    assert db.stat().st_size == size_before
    # Confirm content is still queryable.
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
    assert n > 0
