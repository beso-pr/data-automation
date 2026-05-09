"""Tests for the sales CSV extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from etl_pipeline.extract.sales_csv import SalesValidationError, load_sales

GOOD_CSV = """date,city,country,currency,amount_local,units_sold,channel
2024-09-02,Berlin,DE,EUR,100.0,10,online
2024-09-02,London,GB,GBP,200.0,20,store
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "sales.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_sales_parses_clean_input(tmp_path: Path) -> None:
    df = load_sales(_write(tmp_path, GOOD_CSV))
    assert len(df) == 2
    assert df["currency"].tolist() == ["EUR", "GBP"]
    assert df["units_sold"].dtype.kind == "i"


def test_missing_columns_reported_at_schema_level(tmp_path: Path) -> None:
    bad = _write(tmp_path, "date,city\n2024-09-02,Berlin\n")
    with pytest.raises(SalesValidationError) as exc:
        load_sales(bad)
    assert "missing required columns" in str(exc.value)
    assert "amount_local" in str(exc.value)


def test_invalid_date_reports_row_index(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold\nnot-a-date,Berlin,DE,EUR,100,10\n",
    )
    with pytest.raises(SalesValidationError) as exc:
        load_sales(bad)
    msg = str(exc.value)
    assert "row 0" in msg and "date" in msg


def test_negative_amount_rejected(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold\n2024-09-02,Berlin,DE,EUR,-1,10\n",
    )
    with pytest.raises(SalesValidationError, match="non-negative"):
        load_sales(bad)


def test_non_integer_units_rejected(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold\n2024-09-02,Berlin,DE,EUR,100,1.5\n",
    )
    with pytest.raises(SalesValidationError, match="whole number"):
        load_sales(bad)


def test_bad_currency_code_rejected(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold\n2024-09-02,Berlin,DE,EU,100,10\n",
    )
    with pytest.raises(SalesValidationError, match="3-letter ISO"):
        load_sales(bad)


def test_bad_country_code_rejected(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold\n2024-09-02,Berlin,DEU,EUR,100,10\n",
    )
    with pytest.raises(SalesValidationError, match="2-letter ISO"):
        load_sales(bad)


def test_duplicate_rows_flagged(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold,channel\n"
        "2024-09-02,Berlin,DE,EUR,100,10,online\n"
        "2024-09-02,Berlin,DE,EUR,150,12,online\n",
    )
    with pytest.raises(SalesValidationError, match="duplicate row"):
        load_sales(bad)


def test_all_issues_collected_in_one_pass(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold\n"
        "not-a-date,Berlin,DE,EUR,-1,1.5\n"
        "2024-09-02,,DE,EU,100,10\n",
    )
    with pytest.raises(SalesValidationError) as exc:
        load_sales(bad)
    msg = str(exc.value)
    # Multiple issues from different rows / columns must all appear.
    assert "row 0" in msg
    assert "row 1" in msg
    assert "amount_local" in msg
    assert "units_sold" in msg
    assert "currency" in msg
    assert "city" in msg


def test_country_and_currency_are_normalised_to_upper(tmp_path: Path) -> None:
    good = _write(
        tmp_path,
        "date,city,country,currency,amount_local,units_sold\n2024-09-02,Berlin, de , eur ,100,10\n",
    )
    df = load_sales(good)
    assert df.loc[0, "country"] == "DE"
    assert df.loc[0, "currency"] == "EUR"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_sales(tmp_path / "nope.csv")
