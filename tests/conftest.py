"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from etl_pipeline.cache import JsonDiskCache
from etl_pipeline.config import HttpSettings
from etl_pipeline.http_client import HttpClient


@pytest.fixture
def tmp_cache(tmp_path: Path) -> JsonDiskCache:
    return JsonDiskCache(directory=tmp_path / "cache", ttl_hours=1, enabled=True)


@pytest.fixture
def http_client(tmp_cache: JsonDiskCache) -> HttpClient:
    settings = HttpSettings(max_retries=2, backoff_seconds=0.01)
    return HttpClient(settings=settings, cache=tmp_cache)


@pytest.fixture
def sample_sales() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [date(2024, 9, 2), date(2024, 9, 2), date(2024, 9, 3), date(2024, 9, 3)],
            "city": ["Berlin", "London", "Berlin", "London"],
            "country": ["DE", "GB", "DE", "GB"],
            "currency": ["EUR", "GBP", "EUR", "GBP"],
            "amount_local": [100.0, 200.0, 150.0, 180.0],
            "units_sold": [10, 20, 15, 18],
            "channel": ["online", "store", "online", "store"],
        }
    )


@pytest.fixture
def sample_fx_rates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                date(2024, 9, 2),
                date(2024, 9, 3),
                date(2024, 9, 2),
                date(2024, 9, 3),
                date(2024, 9, 2),
                date(2024, 9, 3),
            ],
            "currency": ["EUR", "EUR", "GBP", "GBP", "USD", "USD"],
            "rate_to_base": [1.10, 1.11, 1.30, 1.31, 1.0, 1.0],
        }
    )


@pytest.fixture
def sample_weather() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [date(2024, 9, 2), date(2024, 9, 3), date(2024, 9, 2), date(2024, 9, 3)],
            "city": ["Berlin", "Berlin", "London", "London"],
            "country": ["DE", "DE", "GB", "GB"],
            "temp_mean_c": [18.5, 19.2, 16.0, 15.5],
            "precipitation_mm": [0.0, 1.2, 0.4, 2.1],
        }
    )
