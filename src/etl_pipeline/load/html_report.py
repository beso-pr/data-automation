"""Render a self-contained HTML report from the transform output."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..logging_setup import get_logger
from ..transform.pipeline import TransformResult

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def render_html_report(
    result: TransformResult,
    base_currency: str,
    output_path: str | Path,
) -> Path:
    """Render the HTML report and return the path it was written to."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    daily = result.daily_summary
    if daily.empty:
        raise ValueError("Cannot render report: daily_summary is empty")

    max_rev = float(daily["total_revenue_base"].max() or 1.0)
    daily_rows = []
    for row in daily.to_dict("records"):
        row["bar_pct"] = round((float(row["total_revenue_base"]) / max_rev) * 100.0, 1)
        daily_rows.append(row)

    total_revenue = float(daily["total_revenue_base"].sum())
    country = result.country_summary.copy()
    country["share"] = country["total_revenue_base"] / total_revenue if total_revenue else 0.0

    kpis = {
        "total_revenue": f"{total_revenue:,.2f}",
        "total_units": f"{int(daily['total_units'].sum()):,}",
        "num_orders": f"{int(daily['num_orders'].sum()):,}",
        "avg_order_value": f"{(total_revenue / daily['num_orders'].sum()):,.2f}",
        "num_cities": int(daily["num_cities"].max()),
        "num_anomalies": len(result.anomalies),
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.html.j2")

    html = template.render(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        base_currency=base_currency,
        date_range=(daily["date"].min(), daily["date"].max()),
        kpis=kpis,
        daily=daily_rows,
        country=country.to_dict("records"),
        city=_records_with_nan_to_none(result.city_summary),
        anomalies=result.anomalies.to_dict("records"),
        correlations=_records_with_nan_to_none(result.weather_correlation),
    )

    output.write_text(html, encoding="utf-8")
    logger.info("Wrote HTML report: %s", output)
    return output


def _records_with_nan_to_none(df: pd.DataFrame) -> list[dict[str, object]]:
    """Convert a dataframe to records, replacing NaN with None for clean Jinja rendering."""
    return [{k: (None if pd.isna(v) else v) for k, v in record.items()} for record in df.to_dict("records")]
