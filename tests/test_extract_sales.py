"""Tests for the sales CSV extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from etl_pipeline.extract.sales_csv import SalesValidationError, load_sales

GOOD_CSV = """date,city,country,currency,amount_local,units_sold,channel
2024-09-02,Berlin,DE,EUR,100.0,10,online
2024-09-02,London,GB,GBP,200.0,20,store
"""


def test_load_sales_parses_clean_input(tmp_path: Path) -> None:
    path = tmp_path / "sales.csv"
    path.write_text(GOOD_CSV, encoding="utf-8")
    df = load_sales(path)
    assert len(df) == 2
    assert set(df.columns) >= {"date", "city", "country", "currency", "amount_local", "units_sold"}
    assert df["currency"].tolist() == ["EUR", "GBP"]


def test_load_sales_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "sales.csv"
    path.write_text("date,city\n2024-09-02,Berlin\n", encoding="utf-8")
    with pytest.raises(SalesValidationError, match="missing required columns"):
        load_sales(path)


def test_load_sales_rejects_invalid_dates(tmp_path: Path) -> None:
    path = tmp_path / "sales.csv"
    path.write_text(
        "date,city,country,currency,amount_local,units_sold\nnot-a-date,Berlin,DE,EUR,100,10\n",
        encoding="utf-8",
    )
    with pytest.raises(SalesValidationError, match="invalid dates"):
        load_sales(path)


def test_load_sales_rejects_negative_amounts(tmp_path: Path) -> None:
    path = tmp_path / "sales.csv"
    path.write_text(
        "date,city,country,currency,amount_local,units_sold\n2024-09-02,Berlin,DE,EUR,-1,10\n",
        encoding="utf-8",
    )
    with pytest.raises(SalesValidationError, match="invalid amount_local"):
        load_sales(path)


def test_load_sales_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_sales(tmp_path / "nope.csv")


def test_country_and_currency_are_normalised_to_upper(tmp_path: Path) -> None:
    path = tmp_path / "sales.csv"
    path.write_text(
        "date,city,country,currency,amount_local,units_sold\n2024-09-02,Berlin, de , eur ,100,10\n",
        encoding="utf-8",
    )
    df = load_sales(path)
    assert df.loc[0, "country"] == "DE"
    assert df.loc[0, "currency"] == "EUR"
