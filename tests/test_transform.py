"""Tests for the transformation pipeline."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from etl_pipeline.transform.pipeline import (
    detect_anomalies,
    enrich_with_weather,
    normalise_currency,
    run_transforms,
    weather_correlation,
)


def test_normalise_currency_computes_amount_in_base(
    sample_sales: pd.DataFrame, sample_fx_rates: pd.DataFrame
) -> None:
    out = normalise_currency(sample_sales, sample_fx_rates, base_currency="USD")
    # 100 EUR * 1.10 = 110 USD on 2024-09-02
    berlin_d1 = out[(out["city"] == "Berlin") & (out["date"] == date(2024, 9, 2))]
    assert berlin_d1["amount_base"].iloc[0] == pytest.approx(110.0)
    # 200 GBP * 1.30 = 260 USD on 2024-09-02
    london_d1 = out[(out["city"] == "London") & (out["date"] == date(2024, 9, 2))]
    assert london_d1["amount_base"].iloc[0] == pytest.approx(260.0)
    assert (out["base_currency"] == "USD").all()
    assert "avg_unit_price_base" in out.columns


def test_normalise_currency_raises_on_missing_fx(sample_sales: pd.DataFrame) -> None:
    fx = pd.DataFrame({"date": [date(2024, 9, 2)], "currency": ["EUR"], "rate_to_base": [1.10]})
    with pytest.raises(ValueError, match="no FX rate"):
        normalise_currency(sample_sales, fx, base_currency="USD")


def test_normalise_currency_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalise_currency(pd.DataFrame(), pd.DataFrame(), base_currency="USD")


def test_enrich_with_weather_left_joins_keep_all_sales(
    sample_sales: pd.DataFrame, sample_fx_rates: pd.DataFrame, sample_weather: pd.DataFrame
) -> None:
    normalised = normalise_currency(sample_sales, sample_fx_rates, "USD")
    enriched = enrich_with_weather(normalised, sample_weather)
    assert len(enriched) == len(normalised)
    assert "temp_mean_c" in enriched.columns


def test_detect_anomalies_flags_outlier_revenue() -> None:
    rows = []
    for d in pd.date_range("2024-09-01", periods=10, freq="D"):
        rows.append(
            {
                "date": d.date(),
                "city": "Berlin",
                "country": "DE",
                "amount_base": 100.0,
                "units_sold": 10,
            }
        )
    rows[5]["amount_base"] = 100_000.0
    df = pd.DataFrame(rows)
    flagged = detect_anomalies(df, z_threshold=2.0)
    assert len(flagged) == 1
    assert flagged.iloc[0]["amount_base"] == 100_000.0


def test_detect_anomalies_skips_constant_series() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-09-01", periods=5, freq="D").date,
            "city": ["X"] * 5,
            "country": ["XX"] * 5,
            "amount_base": [10.0] * 5,
            "units_sold": [1] * 5,
        }
    )
    flagged = detect_anomalies(df)
    assert flagged.empty


def test_weather_correlation_handles_missing_weather() -> None:
    df = pd.DataFrame(
        {
            "city": ["A"] * 5,
            "amount_base": [10.0, 20.0, 30.0, 40.0, 50.0],
            "temp_mean_c": [np.nan] * 5,
            "precipitation_mm": [0.0, 1.0, 2.0, 3.0, 4.0],
        }
    )
    out = weather_correlation(df)
    assert out.iloc[0]["corr_temp_revenue"] is None
    assert out.iloc[0]["corr_precip_revenue"] == pytest.approx(1.0, rel=1e-3)


def test_run_transforms_produces_all_expected_frames(
    sample_sales: pd.DataFrame, sample_fx_rates: pd.DataFrame, sample_weather: pd.DataFrame
) -> None:
    result = run_transforms(sample_sales, sample_fx_rates, sample_weather, "USD")
    assert not result.sales_normalised.empty
    assert not result.daily_summary.empty
    assert not result.country_summary.empty
    assert not result.city_summary.empty
    assert "total_revenue_base" in result.daily_summary.columns
    assert result.country_summary["total_revenue_base"].is_monotonic_decreasing
