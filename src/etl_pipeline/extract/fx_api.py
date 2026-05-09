"""FX rates extractor backed by the free `Frankfurter <https://www.frankfurter.app>`_ API.

We fetch a date-range time series per source currency in one request, then
forward-fill to cover weekends/holidays where the ECB does not publish.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..config import ApiEndpoint
from ..http_client import HttpClient
from ..logging_setup import get_logger

logger = get_logger(__name__)


def fetch_fx_rates(
    client: HttpClient,
    api: ApiEndpoint,
    currencies: list[str],
    base_currency: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Return a tidy long-format dataframe of (date, currency, rate_to_base).

    ``rate_to_base`` is the multiplier from ``currency`` to ``base_currency``,
    i.e. ``amount_local * rate_to_base = amount_in_base``.

    Weekends/holidays are forward-filled so every (date, currency) is covered.
    """
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    base_currency = base_currency.upper()
    foreign = sorted({c.upper() for c in currencies if c.upper() != base_currency})

    # Build a continuous daily index that callers can left-join against.
    all_dates = pd.date_range(start=start, end=end, freq="D").date
    rows: list[dict[str, object]] = [
        {"date": d, "currency": base_currency, "rate_to_base": 1.0} for d in all_dates
    ]

    for ccy in foreign:
        rows.extend(_fetch_pair(client, api, ccy, base_currency, start, end, all_dates))

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values(["currency", "date"]).reset_index(drop=True)
    logger.info(
        "Fetched FX rates: %d (date,currency) pairs covering %d currencies",
        len(df),
        df["currency"].nunique(),
    )
    return df


def _fetch_pair(
    client: HttpClient,
    api: ApiEndpoint,
    foreign: str,
    base: str,
    start: date,
    end: date,
    all_dates: pd.DatetimeIndex | pd.Index,
) -> list[dict[str, object]]:
    # Frankfurter's range endpoint: /YYYY-MM-DD..YYYY-MM-DD?from=EUR&to=USD
    # Pad the start by 7 days so we have a value to forward-fill from.
    pad_start = start - timedelta(days=7)
    url = f"{api.base_url.rstrip('/')}/{pad_start.isoformat()}..{end.isoformat()}"
    params = {"from": foreign, "to": base}
    cache_key = f"fx:{foreign}->{base}:{pad_start}:{end}"
    payload = client.get_json(url, params=params, timeout=api.timeout_seconds, cache_key=cache_key)

    raw: dict[str, dict[str, float]] = payload.get("rates", {}) or {}
    if not raw:
        raise RuntimeError(f"FX API returned no rates for {foreign}->{base}")

    series = pd.Series(
        {pd.Timestamp(d).date(): float(rates[base]) for d, rates in raw.items() if base in rates}
    ).sort_index()

    # Reindex to every day in [pad_start, end] and forward-fill.
    full_idx = pd.date_range(start=pad_start, end=end, freq="D").date
    series = series.reindex(full_idx).ffill()

    # Slice down to caller's requested window.
    series = series.loc[[d for d in all_dates if d in series.index]]

    if series.isna().any():
        # No earlier publication available; back-fill from the first known value.
        series = series.bfill()

    return [{"date": d, "currency": foreign, "rate_to_base": float(rate)} for d, rate in series.items()]
