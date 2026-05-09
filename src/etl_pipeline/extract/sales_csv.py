"""Extractor for the local sales CSV file."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..logging_setup import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = {"date", "city", "country", "currency", "amount_local", "units_sold"}


class SalesValidationError(ValueError):
    """Raised when the sales CSV fails schema or value validation."""


def load_sales(csv_path: str | Path) -> pd.DataFrame:
    """Load and validate the sales CSV.

    Returns a dataframe with parsed dates and normalised text columns.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Sales CSV not found: {path}")

    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise SalesValidationError(f"Sales CSV is missing required columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    if df["date"].isna().any():
        bad = df[df["date"].isna()]
        raise SalesValidationError(f"Sales CSV has {len(bad)} rows with invalid dates")

    df["city"] = df["city"].astype(str).str.strip()
    df["country"] = df["country"].astype(str).str.strip().str.upper()
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["amount_local"] = pd.to_numeric(df["amount_local"], errors="coerce")
    df["units_sold"] = pd.to_numeric(df["units_sold"], errors="coerce", downcast="integer")

    invalid = df[df["amount_local"].isna() | (df["amount_local"] < 0)]
    if not invalid.empty:
        raise SalesValidationError(f"Sales CSV has {len(invalid)} rows with invalid amount_local")

    logger.info(
        "Loaded %d sales rows from %s spanning %s..%s",
        len(df),
        path,
        df["date"].min(),
        df["date"].max(),
    )
    return df
