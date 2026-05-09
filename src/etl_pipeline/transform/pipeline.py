"""Pure-pandas transformation pipeline.

All functions are pure (no I/O) so they're trivial to unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..logging_setup import get_logger

logger = get_logger(__name__)

ANOMALY_Z_THRESHOLD = 2.0


@dataclass(frozen=True)
class TransformResult:
    """Bundle of all dataframes produced by the pipeline."""

    sales_normalised: pd.DataFrame
    daily_summary: pd.DataFrame
    country_summary: pd.DataFrame
    city_summary: pd.DataFrame
    anomalies: pd.DataFrame
    weather_correlation: pd.DataFrame


def normalise_currency(sales: pd.DataFrame, fx_rates: pd.DataFrame, base_currency: str) -> pd.DataFrame:
    """Join sales with FX rates and compute ``amount_base`` and ``avg_unit_price_base``."""
    if sales.empty:
        raise ValueError("sales dataframe is empty")

    missing = {"date", "currency", "amount_local", "units_sold"} - set(sales.columns)
    if missing:
        raise ValueError(f"sales is missing columns: {sorted(missing)}")

    merged = sales.merge(fx_rates, on=["date", "currency"], how="left", validate="many_to_one")
    unmatched = merged[merged["rate_to_base"].isna()]
    if not unmatched.empty:
        sample = unmatched[["date", "currency"]].drop_duplicates().head(5).to_dict("records")
        raise ValueError(f"{len(unmatched)} sales rows have no FX rate. Sample: {sample}")

    merged["amount_base"] = (merged["amount_local"] * merged["rate_to_base"]).round(2)
    merged["avg_unit_price_base"] = (merged["amount_base"] / merged["units_sold"].replace(0, pd.NA)).round(4)
    merged["base_currency"] = base_currency
    return merged


def enrich_with_weather(sales_normalised: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Left-join weather on (date, city). Missing weather is preserved as NaN."""
    return sales_normalised.merge(
        weather[["date", "city", "temp_mean_c", "precipitation_mm"]],
        on=["date", "city"],
        how="left",
    )


def daily_summary(sales: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        sales.groupby("date", as_index=False)
        .agg(
            total_revenue_base=("amount_base", "sum"),
            total_units=("units_sold", "sum"),
            num_orders=("amount_base", "size"),
            num_cities=("city", "nunique"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    grouped["avg_order_value_base"] = (grouped["total_revenue_base"] / grouped["num_orders"]).round(2)
    return grouped


def country_summary(sales: pd.DataFrame) -> pd.DataFrame:
    return (
        sales.groupby("country", as_index=False)
        .agg(
            total_revenue_base=("amount_base", "sum"),
            total_units=("units_sold", "sum"),
            num_orders=("amount_base", "size"),
        )
        .sort_values("total_revenue_base", ascending=False)
        .reset_index(drop=True)
    )


def city_summary(sales: pd.DataFrame) -> pd.DataFrame:
    return (
        sales.groupby(["country", "city"], as_index=False)
        .agg(
            total_revenue_base=("amount_base", "sum"),
            total_units=("units_sold", "sum"),
            avg_temp_c=("temp_mean_c", "mean"),
            avg_precip_mm=("precipitation_mm", "mean"),
        )
        .sort_values("total_revenue_base", ascending=False)
        .reset_index(drop=True)
    )


def detect_anomalies(sales: pd.DataFrame, z_threshold: float = ANOMALY_Z_THRESHOLD) -> pd.DataFrame:
    """Flag city-day rows whose revenue is more than ``z_threshold`` SDs from that city's mean.

    Cities with fewer than 3 observations or zero variance are skipped.
    """
    out: list[pd.DataFrame] = []
    for _city, group in sales.groupby("city"):
        if len(group) < 3:
            continue
        std = group["amount_base"].std(ddof=0)
        if not std or pd.isna(std):
            continue
        mean = group["amount_base"].mean()
        z = (group["amount_base"] - mean) / std
        flagged = group.assign(z_score=z.round(2)).loc[z.abs() >= z_threshold]
        if not flagged.empty:
            out.append(flagged[["date", "city", "country", "amount_base", "z_score"]])

    if not out:
        return pd.DataFrame(columns=["date", "city", "country", "amount_base", "z_score"])
    return pd.concat(out, ignore_index=True).sort_values(["date", "city"]).reset_index(drop=True)


CORRELATION_COLUMNS = ["city", "n", "corr_temp_revenue", "corr_precip_revenue"]


def weather_correlation(sales: pd.DataFrame) -> pd.DataFrame:
    """Per-city Pearson correlation between weather features and revenue."""
    rows: list[dict[str, object]] = []
    for city, group in sales.groupby("city"):
        if len(group) < 4:
            continue
        rev = group["amount_base"]
        rows.append(
            {
                "city": city,
                "n": len(group),
                "corr_temp_revenue": _safe_corr(rev, group["temp_mean_c"]),
                "corr_precip_revenue": _safe_corr(rev, group["precipitation_mm"]),
            }
        )
    if not rows:
        return pd.DataFrame(columns=CORRELATION_COLUMNS)
    return pd.DataFrame(rows).sort_values("city").reset_index(drop=True)


def _safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    paired = pd.concat([a, b], axis=1).dropna()
    if len(paired) < 3 or paired.iloc[:, 1].std(ddof=0) == 0:
        return None
    value = float(paired.iloc[:, 0].corr(paired.iloc[:, 1]))
    return round(value, 3) if pd.notna(value) else None


def run_transforms(
    sales: pd.DataFrame,
    fx_rates: pd.DataFrame,
    weather: pd.DataFrame,
    base_currency: str,
) -> TransformResult:
    normalised = normalise_currency(sales, fx_rates, base_currency)
    enriched = enrich_with_weather(normalised, weather)
    return TransformResult(
        sales_normalised=enriched,
        daily_summary=daily_summary(enriched),
        country_summary=country_summary(enriched),
        city_summary=city_summary(enriched),
        anomalies=detect_anomalies(enriched),
        weather_correlation=weather_correlation(enriched),
    )
