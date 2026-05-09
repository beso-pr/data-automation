"""Tests for the weather extractor: geocoding, archive, and forecast fallback."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from etl_pipeline.config import ApiEndpoint, City
from etl_pipeline.extract.weather_api import fetch_weather, geocode_cities
from etl_pipeline.http_client import HttpClient


@pytest.fixture
def geocode_api() -> ApiEndpoint:
    return ApiEndpoint(base_url="https://geocoding-api.example/v1/search", timeout_seconds=5)


@pytest.fixture
def archive_api() -> ApiEndpoint:
    return ApiEndpoint(base_url="https://archive-api.example/v1/archive", timeout_seconds=5)


@pytest.fixture
def forecast_api() -> ApiEndpoint:
    return ApiEndpoint(base_url="https://forecast-api.example/v1/forecast", timeout_seconds=5)


@pytest.fixture
def coords() -> pd.DataFrame:
    return pd.DataFrame([{"city": "Berlin", "country": "DE", "latitude": 52.52, "longitude": 13.41}])


def test_geocode_cities_resolves_lat_lon(http_client: HttpClient, geocode_api: ApiEndpoint) -> None:
    payload = {"results": [{"latitude": 52.52, "longitude": 13.41}]}
    with patch.object(HttpClient, "get_json", return_value=payload):
        df = geocode_cities(http_client, geocode_api, [City(name="Berlin", country="DE")])
    assert df.iloc[0]["latitude"] == pytest.approx(52.52)
    assert df.iloc[0]["longitude"] == pytest.approx(13.41)


def test_geocode_raises_on_empty_results(http_client: HttpClient, geocode_api: ApiEndpoint) -> None:
    with (
        patch.object(HttpClient, "get_json", return_value={"results": []}),
        pytest.raises(RuntimeError, match="Could not geocode"),
    ):
        geocode_cities(http_client, geocode_api, [City(name="Atlantis", country="XX")])


def test_archive_only_when_range_is_old_enough(
    http_client: HttpClient, archive_api: ApiEndpoint, coords: pd.DataFrame
) -> None:
    payload = {
        "daily": {
            "time": ["2024-09-02", "2024-09-03"],
            "temperature_2m_mean": [18.5, 19.2],
            "precipitation_sum": [0.0, 1.4],
        }
    }
    with patch.object(HttpClient, "get_json", return_value=payload) as mock:
        df = fetch_weather(
            http_client,
            archive_api,
            coords,
            date(2024, 9, 2),
            date(2024, 9, 3),
            today=date(2026, 5, 9),
        )
    assert mock.call_count == 1  # archive only
    assert df["temp_mean_c"].tolist() == [18.5, 19.2]


def test_forecast_fallback_for_recent_dates(
    http_client: HttpClient,
    archive_api: ApiEndpoint,
    forecast_api: ApiEndpoint,
    coords: pd.DataFrame,
) -> None:
    today = date(2026, 5, 9)
    archive_cutoff = today - timedelta(days=5)  # 2026-05-04
    forecast_start = archive_cutoff + timedelta(days=1)  # 2026-05-05

    archive_payload = {
        "daily": {
            "time": ["2026-05-02", "2026-05-03", "2026-05-04"],
            "temperature_2m_mean": [12.0, 13.0, 14.0],
            "precipitation_sum": [0.1, 0.2, 0.3],
        }
    }
    forecast_payload = {
        "daily": {
            "time": [d.isoformat() for d in pd.date_range(forecast_start, today)],
            "temperature_2m_mean": [15.0, 16.0, 17.0, 18.0, 19.0],
            "precipitation_sum": [0.4, 0.5, 0.6, 0.7, 0.8],
        }
    }
    with patch.object(HttpClient, "get_json", side_effect=[archive_payload, forecast_payload]):
        df = fetch_weather(
            http_client,
            archive_api,
            coords,
            date(2026, 5, 2),
            today,
            forecast_api=forecast_api,
            today=today,
        )

    assert len(df) == 8  # 3 archive + 5 forecast
    assert df["date"].min() == date(2026, 5, 2)
    assert df["date"].max() == today


def test_no_forecast_when_endpoint_missing(
    http_client: HttpClient,
    archive_api: ApiEndpoint,
    coords: pd.DataFrame,
    caplog,
) -> None:
    archive_payload = {
        "daily": {
            "time": ["2026-05-02"],
            "temperature_2m_mean": [12.0],
            "precipitation_sum": [0.1],
        }
    }
    with patch.object(HttpClient, "get_json", return_value=archive_payload):
        df = fetch_weather(
            http_client,
            archive_api,
            coords,
            date(2026, 5, 2),
            date(2026, 5, 9),  # extends past archive cutoff
            today=date(2026, 5, 9),
        )
    assert len(df) == 1
    assert any("forecast endpoint" in rec.message.lower() for rec in caplog.records)


def test_skip_cities_with_no_data(http_client: HttpClient, archive_api: ApiEndpoint) -> None:
    coords = pd.DataFrame(
        [
            {"city": "Berlin", "country": "DE", "latitude": 52.52, "longitude": 13.41},
            {"city": "Empty", "country": "XX", "latitude": 0.0, "longitude": 0.0},
        ]
    )
    payloads = [
        {
            "daily": {
                "time": ["2024-09-02"],
                "temperature_2m_mean": [18.5],
                "precipitation_sum": [0.0],
            }
        },
        {"daily": {}},
    ]
    with patch.object(HttpClient, "get_json", side_effect=payloads):
        df = fetch_weather(
            http_client,
            archive_api,
            coords,
            date(2024, 9, 2),
            date(2024, 9, 2),
            today=date(2026, 5, 9),
        )
    assert df["city"].tolist() == ["Berlin"]


def test_rejects_inverted_date_range(
    http_client: HttpClient, archive_api: ApiEndpoint, coords: pd.DataFrame
) -> None:
    with pytest.raises(ValueError, match="start"):
        fetch_weather(http_client, archive_api, coords, date(2024, 9, 10), date(2024, 9, 1))
