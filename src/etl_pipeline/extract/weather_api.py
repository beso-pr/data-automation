"""Weather extractor backed by `Open-Meteo <https://open-meteo.com>`_.

Two-step flow:

1. Resolve each ``(city, country)`` pair to coordinates via the geocoding API.
2. Pull a daily archive (mean temperature + precipitation) per city.

Both endpoints are free and key-less. Responses are cached on disk.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..config import ApiEndpoint, City
from ..http_client import HttpClient
from ..logging_setup import get_logger

logger = get_logger(__name__)


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
    api: ApiEndpoint,
    cities_with_coords: pd.DataFrame,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Return a tidy long-format dataframe with one row per (date, city)."""
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    frames: list[pd.DataFrame] = []
    for _, row in cities_with_coords.iterrows():
        params = {
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_mean,precipitation_sum",
            "timezone": "auto",
        }
        cache_key = f"weather:{row['city']}:{start}:{end}"
        payload = client.get_json(
            api.base_url, params=params, timeout=api.timeout_seconds, cache_key=cache_key
        )
        daily = payload.get("daily") or {}
        if not daily.get("time"):
            logger.warning("No weather data returned for %s", row["city"])
            continue

        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(pd.Series(daily["time"])).dt.date,
                "city": row["city"],
                "country": row["country"],
                "temp_mean_c": daily.get("temperature_2m_mean", []),
                "precipitation_mm": daily.get("precipitation_sum", []),
            }
        )
        frames.append(frame)

    if not frames:
        raise RuntimeError("Weather API returned no data for any city")

    df = pd.concat(frames, ignore_index=True)
    df["temp_mean_c"] = pd.to_numeric(df["temp_mean_c"], errors="coerce")
    df["precipitation_mm"] = pd.to_numeric(df["precipitation_mm"], errors="coerce")
    logger.info("Fetched weather: %d (date,city) rows across %d cities", len(df), df["city"].nunique())
    return df
