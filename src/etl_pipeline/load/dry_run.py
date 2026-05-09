"""Dry-run preview helpers.

The pipeline runs extract + transform exactly as it would in production, then
this module diffs the *proposed* state against the *existing* SQLite database
(if any) and logs a tabular preview — without touching the database or the
canonical HTML report.

The same module is used by tests, so it's importable in isolation.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.request import pathname2url

import pandas as pd

from ..logging_setup import get_logger
from ..transform.pipeline import TransformResult
from .sqlite_loader import TABLE_MAP

logger = get_logger(__name__)


@dataclass(frozen=True)
class TableDelta:
    table: str
    existing_rows: int | None  # None => table didn't exist
    proposed_rows: int

    @property
    def delta(self) -> int:
        return self.proposed_rows - (self.existing_rows or 0)

    @property
    def status(self) -> str:
        if self.existing_rows is None:
            return "create"
        return "unchanged" if self.delta == 0 else "replace"


@dataclass(frozen=True)
class DryRunReport:
    sqlite_path: Path
    deltas: list[TableDelta]

    def format(self) -> str:
        header = (
            f"Dry-run preview for {self.sqlite_path}\n"
            f"{'TABLE':<28}  {'STATUS':<10}  {'EXISTING':>9}  {'PROPOSED':>9}  {'Δ':>7}"
        )
        rows = []
        for d in self.deltas:
            existing = "—" if d.existing_rows is None else f"{d.existing_rows:>9,}"
            delta = "" if d.existing_rows is None else f"{d.delta:+,}"
            rows.append(f"{d.table:<28}  {d.status:<10}  {existing:>9}  {d.proposed_rows:>9,}  {delta:>7}")
        return header + "\n" + "\n".join(rows)


def build_dry_run_report(
    result: TransformResult,
    fx_rates: pd.DataFrame,
    weather: pd.DataFrame,
    sqlite_path: Path,
) -> DryRunReport:
    """Compare what *would* be written against what's currently in ``sqlite_path``."""
    proposed: dict[str, int] = {
        "ref_fx_rates": len(fx_rates),
        "ref_weather": len(weather),
    }
    for attr, table_name in TABLE_MAP.items():
        proposed[table_name] = len(getattr(result, attr))

    existing = _read_existing_row_counts(sqlite_path)

    deltas = [
        TableDelta(
            table=table,
            existing_rows=existing.get(table),
            proposed_rows=count,
        )
        for table, count in proposed.items()
    ]
    return DryRunReport(sqlite_path=sqlite_path, deltas=deltas)


def _read_existing_row_counts(sqlite_path: Path) -> dict[str, int]:
    """Return ``{table_name: row_count}`` for tables that currently exist."""
    if not sqlite_path.exists():
        return {}
    # ``pathname2url`` correctly encodes spaces and other special characters so
    # the read-only URI works even when the project lives under e.g. "My Code/".
    ro_uri = f"file:{pathname2url(str(sqlite_path))}?mode=ro"
    out: dict[str, int] = {}
    try:
        with sqlite3.connect(ro_uri, uri=True) as conn:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for (name,) in tables:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    out[name] = int(count)
                except sqlite3.DatabaseError as exc:
                    logger.warning("Could not count rows in existing %s: %s", name, exc)
    except sqlite3.DatabaseError as exc:
        logger.warning(
            "Existing SQLite at %s could not be read for dry-run diff: %s",
            sqlite_path,
            exc,
        )
        return {}
    return out
