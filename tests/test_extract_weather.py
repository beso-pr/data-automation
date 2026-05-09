"""Tests for the weather extractor (HTTP mocked at the client boundary)."""

from __future__ import annotations

from datetime import date
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


def test_geocode_cities_resolves_lat_lon(http_client: HttpClient, geocode_api: ApiEndpoint) -> None:
    payload = {"results": [{"latitude": 52.52, "longitude": 13.41}]}
    with patch.object(HttpClient, "get_json", return_value=payload):
        df = geocode_cities(http_client, geocode_api, [City(name="Berlin", country="DE")])

    assert df.iloc[0]["latitude"] == pytest.approx(52.52)
    assert df.iloc[0]["longitude"] == pytest.approx(13.41)


def test_geocode_raises_on_empty_results(
    http_client: HttpClient, geocode_api: ApiEndpoint
) -> None:
    with patch.object(HttpClient, "get_json", return_value={"results": []}):
        with pytest.raises(RuntimeError, match="Could not geocode"):
            geocode_cities(http_client, geocode_api, [City(name="Atlantis", country="XX")])


def test_fetch_weather_returns_one_row_per_city_day(
    http_client: HttpClient, archive_api: ApiEndpoint
) -> None:
    coords = pd.DataFrame(
        [{"city": "Berlin", "country": "DE", "latitude": 52.52, "longitude": 13.41}]
    )
    payload = {
        "daily": {
            "time": ["2024-09-02", "2024-09-03"],
            "temperature_2m_mean": [18.5, 19.2],
            "precipitation_sum": [0.0, 1.4],
        }
    }
    with patch.object(HttpClient, "get_json", return_value=payload):
        df = fetch_weather(http_client, archive_api, coords, date(2024, 9, 2), date(2024, 9, 3))

    assert len(df) == 2
    assert df["temp_mean_c"].tolist() == [18.5, 19.2]
    assert df["precipitation_mm"].tolist() == [0.0, 1.4]


def test_fetch_weather_skips_cities_with_no_data(
    http_client: HttpClient, archive_api: ApiEndpoint
) -> None:
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
        df = fetch_weather(http_client, archive_api, coords, date(2024, 9, 2), date(2024, 9, 2))

    assert df["city"].tolist() == ["Berlin"]


def test_rejects_inverted_date_range(http_client: HttpClient, archive_api: ApiEndpoint) -> None:
    coords = pd.DataFrame(
        [{"city": "Berlin", "country": "DE", "latitude": 52.52, "longitude": 13.41}]
    )
    with pytest.raises(ValueError, match="start"):
        fetch_weather(http_client, archive_api, coords, date(2024, 9, 10), date(2024, 9, 1))
