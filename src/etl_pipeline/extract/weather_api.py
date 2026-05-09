"""Weather extractor backed by `Open-Meteo <https://open-meteo.com>`_.

Open-Meteo splits its catalogue into two endpoints with different freshness:

* **archive-api** — historical, but lags ~5 days behind today.
* **forecast**    — current/recent, supports ``past_days`` up to 92.

This module fetches whichever endpoint(s) cover the requested date range and
stitches the results back together transparently. No manual config changes
needed when sales data brushes up against today's date.

Pipeline:

1. Resolve each ``(city, country)`` to coordinates via the geocoding API.
2. For each city, fetch:
   - ``archive_api`` for any portion of the range older than ``archive_lag_days``;
   - ``forecast_api`` (with ``past_days``) for the recent portion.
3. Concat per-city, return a tidy long-format dataframe.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from ..config import ApiEndpoint, City
from ..http_client import HttpClient
from ..logging_setup import get_logger

logger = get_logger(__name__)

DAILY_VARS = "temperature_2m_mean,precipitation_sum"


def geocode_cities(client: HttpClient, api: ApiEndpoint, cities: list[City]) -> pd.DataFrame:
    """Return a dataframe with columns: city, country, latitude, longitude."""
    rows: list[dict[str, object]] = []
    for city in cities:
        params = {"name": city.name, "country": city.country, "count": 1, "format": "json"}
        cache_key = f"geocode:{city.name}:{city.country}"
        payload = client.get_json(
            api.base_url, params=params, timeout=api.timeout_seconds, cache_key=cache_key
        )
        results = payload.get("results") or []
        if not results:
            raise RuntimeError(f"Could not geocode city {city.name}, {city.country}")
        top = results[0]
        rows.append(
            {
                "city": city.name,
                "country": city.country,
                "latitude": float(top["latitude"]),
                "longitude": float(top["longitude"]),
            }
        )
    df = pd.DataFrame(rows)
    logger.info("Geocoded %d cities", len(df))
    return df


def fetch_weather(
    client: HttpClient,
    archive_api: ApiEndpoint,
    cities_with_coords: pd.DataFrame,
    start: date,
    end: date,
    *,
    forecast_api: ApiEndpoint | None = None,
    archive_lag_days: int = 5,
    today: date | None = None,
) -> pd.DataFrame:
    """Return a tidy long-format dataframe with one row per (date, city).

    If part of ``[start, end]`` is more recent than ``today - archive_lag_days``
    and a ``forecast_api`` is supplied, that slice is fetched from the forecast
    endpoint instead of the archive (which would return empty for fresh dates).
    """
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    today = today or date.today()
    archive_cutoff = today - timedelta(days=archive_lag_days)

    archive_end = min(end, archive_cutoff)
    forecast_start = max(start, archive_cutoff + timedelta(days=1))

    use_archive = start <= archive_end
    use_forecast = forecast_start <= end and forecast_api is not None
    fallback_skipped = forecast_start <= end and forecast_api is None

    if fallback_skipped:
        logger.warning(
            "Date range extends past the archive lag (%s) but no forecast endpoint "
            "was configured — recent days will be missing.",
            archive_cutoff.isoformat(),
        )

    frames: list[pd.DataFrame] = []
    for _, row in cities_with_coords.iterrows():
        if use_archive:
            frame = _fetch_for_city(client, archive_api, row, start, archive_end, source="archive")
            if frame is not None:
                frames.append(frame)
        if use_forecast:
            assert forecast_api is not None
            past_days = (today - forecast_start).days + 1
            frame = _fetch_for_city(
                client,
                forecast_api,
                row,
                forecast_start,
                end,
                source="forecast",
                past_days=past_days,
            )
            if frame is not None:
                frames.append(frame)

    if not frames:
        raise RuntimeError("Weather API returned no data for any city")

    df = pd.concat(frames, ignore_index=True)
    df["temp_mean_c"] = pd.to_numeric(df["temp_mean_c"], errors="coerce")
    df["precipitation_mm"] = pd.to_numeric(df["precipitation_mm"], errors="coerce")
    # Same (date, city) might appear from both endpoints if a window straddles
    # the cutoff — prefer the archive (it's "more authoritative" historically).
    df = df.sort_values(["date", "city", "source"]).drop_duplicates(subset=["date", "city"], keep="first")
    df = df.drop(columns=["source"]).reset_index(drop=True)
    logger.info(
        "Fetched weather: %d (date,city) rows across %d cities",
        len(df),
        df["city"].nunique(),
    )
    return df


def _fetch_for_city(
    client: HttpClient,
    api: ApiEndpoint,
    row: pd.Series,
    start: date,
    end: date,
    *,
    source: str,
    past_days: int | None = None,
) -> pd.DataFrame | None:
    params: dict[str, Any] = {
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "daily": DAILY_VARS,
        "timezone": "auto",
    }
    if past_days is not None:
        params["past_days"] = past_days
        params["forecast_days"] = 1
    else:
        params["start_date"] = start.isoformat()
        params["end_date"] = end.isoformat()

    cache_key = f"weather:{source}:{row['city']}:{start}:{end}"
    payload = client.get_json(api.base_url, params=params, timeout=api.timeout_seconds, cache_key=cache_key)
    daily = payload.get("daily") or {}
    if not daily.get("time"):
        logger.warning("No %s weather data returned for %s", source, row["city"])
        return None

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(pd.Series(daily["time"])).dt.date,
            "city": row["city"],
            "country": row["country"],
            "temp_mean_c": daily.get("temperature_2m_mean", []),
            "precipitation_mm": daily.get("precipitation_sum", []),
            "source": source,
        }
    )
    # Trim to the requested window (forecast can return extra days).
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()
    return frame
