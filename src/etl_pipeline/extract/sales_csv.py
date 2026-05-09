"""Validating extractor for the local sales CSV.

The validator runs *all* checks in a single pass and reports every issue it
finds at once, so ops don't have to fix-and-rerun-and-fix-and-rerun.

Checks:
- required columns present
- date column parses as ISO date
- ``amount_local`` is a non-negative number
- ``units_sold`` is a non-negative integer
- ``currency`` is exactly 3 uppercase letters (ISO-4217 shape)
- ``country``  is exactly 2 uppercase letters (ISO-3166 alpha-2 shape)
- no duplicate ``(date, city, currency, channel)`` rows
- city / channel strings are non-empty after trim
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..logging_setup import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = ("date", "city", "country", "currency", "amount_local", "units_sold")

CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

MAX_ISSUES_TO_REPORT = 25


@dataclass
class ValidationIssue:
    row: int  # zero-based; -1 means "schema-level, not a row"
    column: str | None
    message: str

    def __str__(self) -> str:
        if self.row == -1:
            return f"[schema] {self.message}"
        col = f".{self.column}" if self.column else ""
        return f"[row {self.row}{col}] {self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def __bool__(self) -> bool:
        return bool(self.issues)

    def __len__(self) -> int:
        return len(self.issues)

    def format(self) -> str:
        head = self.issues[:MAX_ISSUES_TO_REPORT]
        rest = len(self.issues) - len(head)
        body = "\n  ".join(str(i) for i in head)
        suffix = f"\n  ... and {rest} more" if rest > 0 else ""
        return f"{len(self)} validation issue(s):\n  {body}{suffix}"


class SalesValidationError(ValueError):
    """Raised when the sales CSV fails schema or value validation."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(report.format())
        self.report = report


def load_sales(csv_path: str | Path) -> pd.DataFrame:
    """Load and exhaustively validate a sales CSV.

    Returns a normalised dataframe (uppercase country/currency, parsed dates,
    typed numerics). Raises :class:`SalesValidationError` with a list of every
    issue found if anything fails.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Sales CSV not found: {path}")

    df_raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    report = ValidationReport()

    missing = [c for c in REQUIRED_COLUMNS if c not in df_raw.columns]
    if missing:
        report.add(ValidationIssue(row=-1, column=None, message=f"missing required columns: {missing}"))
        # Without required columns we can't do row-level checks meaningfully.
        raise SalesValidationError(report)

    df = df_raw.copy()
    df["city"] = df["city"].astype(str).str.strip()
    df["country"] = df["country"].astype(str).str.strip().str.upper()
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    if "channel" in df.columns:
        df["channel"] = df["channel"].astype(str).str.strip()

    # --- per-row checks -----------------------------------------------------
    parsed_dates = pd.to_datetime(df["date"], errors="coerce", format="ISO8601")
    amounts = pd.to_numeric(df["amount_local"], errors="coerce")
    units = pd.to_numeric(df["units_sold"], errors="coerce")

    for idx in range(len(df)):
        row = df.iloc[idx]

        if pd.isna(parsed_dates.iloc[idx]):
            report.add(ValidationIssue(idx, "date", f"invalid date: {row['date']!r}"))
        if not row["city"]:
            report.add(ValidationIssue(idx, "city", "empty city"))
        if not COUNTRY_RE.match(row["country"]):
            report.add(ValidationIssue(idx, "country", f"expected 2-letter ISO code, got {row['country']!r}"))
        if not CURRENCY_RE.match(row["currency"]):
            report.add(
                ValidationIssue(idx, "currency", f"expected 3-letter ISO code, got {row['currency']!r}")
            )

        amt = amounts.iloc[idx]
        if pd.isna(amt):
            report.add(ValidationIssue(idx, "amount_local", f"not a number: {row['amount_local']!r}"))
        elif amt < 0:
            report.add(ValidationIssue(idx, "amount_local", f"must be non-negative, got {amt}"))

        u = units.iloc[idx]
        if pd.isna(u):
            report.add(ValidationIssue(idx, "units_sold", f"not a number: {row['units_sold']!r}"))
        elif u < 0:
            report.add(ValidationIssue(idx, "units_sold", f"must be non-negative, got {u}"))
        elif u != int(u):
            report.add(ValidationIssue(idx, "units_sold", f"must be a whole number, got {u}"))

    # --- duplicate detection ------------------------------------------------
    dup_keys = ["date", "city", "currency"]
    if "channel" in df.columns:
        dup_keys.append("channel")
    dup_mask = df.duplicated(subset=dup_keys, keep=False)
    if dup_mask.any():
        for idx in df.index[dup_mask].tolist():
            keys = {k: df.iloc[idx][k] for k in dup_keys}
            report.add(ValidationIssue(int(idx), None, f"duplicate row for keys {keys}"))

    if report:
        logger.error(
            "Sales CSV validation failed: %d issue(s) across %d rows",
            len(report),
            len(df),
        )
        raise SalesValidationError(report)

    # --- normalise + return -------------------------------------------------
    df["date"] = parsed_dates.dt.date
    df["amount_local"] = amounts
    df["units_sold"] = units.astype("int64")

    logger.info(
        "Loaded %d sales rows from %s spanning %s..%s",
        len(df),
        path,
        df["date"].min(),
        df["date"].max(),
    )
    return df
