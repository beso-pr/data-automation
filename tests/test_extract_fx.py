"""Tests for the FX rates extractor.

We mock at the ``HttpClient.get_json`` boundary so no real HTTP is required.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from etl_pipeline.config import ApiEndpoint
from etl_pipeline.extract.fx_api import fetch_fx_rates
from etl_pipeline.http_client import HttpClient


@pytest.fixture
def fx_api() -> ApiEndpoint:
    return ApiEndpoint(base_url="https://api.frankfurter.app", timeout_seconds=5)


def test_fetch_fx_rates_returns_long_format_with_base_rows(
    http_client: HttpClient, fx_api: ApiEndpoint
) -> None:
    payload = {
        "rates": {
            "2024-09-02": {"USD": 1.10},
            "2024-09-03": {"USD": 1.11},
        }
    }

    with patch.object(HttpClient, "get_json", return_value=payload):
        df = fetch_fx_rates(
            client=http_client,
            api=fx_api,
            currencies=["EUR", "USD"],
            base_currency="USD",
            start=date(2024, 9, 2),
            end=date(2024, 9, 3),
        )

    assert set(df.columns) == {"date", "currency", "rate_to_base"}
    assert df.loc[df["currency"] == "USD", "rate_to_base"].tolist() == [1.0, 1.0]
    eur = df[df["currency"] == "EUR"].sort_values("date")
    assert eur["rate_to_base"].tolist() == [1.10, 1.11]


def test_forward_fill_for_weekends(http_client: HttpClient, fx_api: ApiEndpoint) -> None:
    # API returns one day; ours spans 3. The two missing days should ffill.
    payload = {"rates": {"2024-09-02": {"USD": 1.20}}}

    with patch.object(HttpClient, "get_json", return_value=payload):
        df = fetch_fx_rates(
            client=http_client,
            api=fx_api,
            currencies=["GBP"],
            base_currency="USD",
            start=date(2024, 9, 2),
            end=date(2024, 9, 4),
        )

    gbp = df[df["currency"] == "GBP"].sort_values("date")
    assert gbp["rate_to_base"].tolist() == [1.20, 1.20, 1.20]


def test_raises_when_api_returns_no_rates(
    http_client: HttpClient, fx_api: ApiEndpoint
) -> None:
    with patch.object(HttpClient, "get_json", return_value={"rates": {}}):
        with pytest.raises(RuntimeError, match="no rates"):
            fetch_fx_rates(
                client=http_client,
                api=fx_api,
                currencies=["EUR"],
                base_currency="USD",
                start=date(2024, 9, 2),
                end=date(2024, 9, 3),
            )


def test_rejects_inverted_date_range(http_client: HttpClient, fx_api: ApiEndpoint) -> None:
    with pytest.raises(ValueError, match="start"):
        fetch_fx_rates(
            client=http_client,
            api=fx_api,
            currencies=["EUR"],
            base_currency="USD",
            start=date(2024, 9, 10),
            end=date(2024, 9, 1),
        )


def test_back_fills_when_only_later_data_available(
    http_client: HttpClient, fx_api: ApiEndpoint
) -> None:
    # API returns data only for the last day; earlier days should bfill.
    payload = {"rates": {"2024-09-04": {"USD": 1.30}}}
    with patch.object(HttpClient, "get_json", return_value=payload):
        df = fetch_fx_rates(
            client=http_client,
            api=fx_api,
            currencies=["GBP"],
            base_currency="USD",
            start=date(2024, 9, 2),
            end=date(2024, 9, 4),
        )
    assert df[df["currency"] == "GBP"]["rate_to_base"].tolist() == [1.30, 1.30, 1.30]
