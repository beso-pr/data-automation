"""Tests for config loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etl_pipeline.config import Config


def _write_config(tmp_path: Path, **overrides: object) -> Path:
    body = {
        "input": {"sales_csv": "sales.csv"},
        "base_currency": "USD",
        "cities": [{"name": "Berlin", "country": "DE"}],
        "apis": {
            "fx": {"base_url": "https://fx.example", "timeout_seconds": 5},
            "weather_geocode": {"base_url": "https://geo.example"},
            "weather_archive": {"base_url": "https://wx.example"},
            "weather_forecast": {"base_url": "https://forecast.example"},
        },
        "weather": {"archive_lag_days": 5, "fallback_to_forecast": True},
        "http": {
            "max_retries": 2,
            "backoff_seconds": 0.5,
            "circuit_breaker_threshold": 3,
            "circuit_breaker_reset_seconds": 30,
        },
        "cache": {"enabled": True, "directory": ".cache", "ttl_hours": 1},
        "logging": {"file_path": "output/etl.log", "max_bytes": 1024, "backup_count": 3},
        "output": {
            "directory": "output",
            "sqlite_path": "output/etl.sqlite",
            "html_path": "output/report.html",
        },
    }
    body.update(overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def test_loads_a_well_formed_config(tmp_path: Path) -> None:
    cfg = Config.from_file(_write_config(tmp_path))
    assert cfg.base_currency == "USD"
    assert cfg.cities[0].name == "Berlin"
    assert cfg.fx_api.base_url == "https://fx.example"
    assert cfg.weather_forecast_api is not None
    assert cfg.weather.archive_lag_days == 5
    assert cfg.http.max_retries == 2
    assert cfg.http.circuit_breaker_threshold == 3
    assert cfg.logging.file_path is not None
    assert cfg.logging.max_bytes == 1024


def test_optional_forecast_api_can_be_omitted(tmp_path: Path) -> None:
    cfg = Config.from_file(
        _write_config(
            tmp_path,
            apis={
                "fx": {"base_url": "https://fx.example"},
                "weather_geocode": {"base_url": "https://geo.example"},
                "weather_archive": {"base_url": "https://wx.example"},
            },
        )
    )
    assert cfg.weather_forecast_api is None


def test_resolves_relative_paths_against_config_dir(tmp_path: Path) -> None:
    cfg = Config.from_file(_write_config(tmp_path))
    assert cfg.sales_csv.parent == tmp_path
    assert cfg.output.directory.parent == tmp_path
    assert cfg.logging.file_path is not None
    assert cfg.logging.file_path.is_absolute()


def test_logging_can_be_disabled_with_null_file_path(tmp_path: Path) -> None:
    cfg = Config.from_file(_write_config(tmp_path, logging={"file_path": None}))
    assert cfg.logging.file_path is None


def test_rejects_empty_cities_list(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cities"):
        Config.from_file(_write_config(tmp_path, cities=[]))


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Config.from_file(tmp_path / "nope.yaml")
