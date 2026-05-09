"""Tests for config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

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
        },
        "http": {"max_retries": 2, "backoff_seconds": 0.5},
        "cache": {"enabled": True, "directory": ".cache", "ttl_hours": 1},
        "output": {
            "directory": "output",
            "sqlite_path": "output/etl.sqlite",
            "html_path": "output/report.html",
        },
    }
    body.update(overrides)
    import yaml

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def test_loads_a_well_formed_config(tmp_path: Path) -> None:
    cfg = Config.from_file(_write_config(tmp_path))
    assert cfg.base_currency == "USD"
    assert cfg.cities[0].name == "Berlin"
    assert cfg.fx_api.base_url == "https://fx.example"
    assert cfg.http.max_retries == 2
    assert cfg.output.sqlite_path.is_absolute()


def test_resolves_relative_paths_against_config_dir(tmp_path: Path) -> None:
    cfg = Config.from_file(_write_config(tmp_path))
    assert cfg.sales_csv.parent == tmp_path
    assert cfg.output.directory.parent == tmp_path


def test_rejects_empty_cities_list(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cities"):
        Config.from_file(_write_config(tmp_path, cities=[]))


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Config.from_file(tmp_path / "nope.yaml")
