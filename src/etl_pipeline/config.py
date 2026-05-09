"""Strongly-typed configuration loaded from a YAML file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class City:
    name: str
    country: str


@dataclass(frozen=True)
class ApiEndpoint:
    base_url: str
    timeout_seconds: int = 15


@dataclass(frozen=True)
class HttpSettings:
    max_retries: int = 4
    backoff_seconds: float = 1.5


@dataclass(frozen=True)
class CacheSettings:
    enabled: bool = True
    directory: Path = Path(".cache")
    ttl_hours: int = 24


@dataclass(frozen=True)
class OutputSettings:
    directory: Path
    sqlite_path: Path
    html_path: Path


@dataclass(frozen=True)
class Config:
    sales_csv: Path
    base_currency: str
    cities: list[City]
    fx_api: ApiEndpoint
    geocode_api: ApiEndpoint
    weather_api: ApiEndpoint
    http: HttpSettings
    cache: CacheSettings
    output: OutputSettings

    @classmethod
    def from_file(cls, path: str | Path) -> Config:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}
        return cls.from_dict(raw, base_dir=path.parent)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], base_dir: Path | None = None) -> Config:
        base = base_dir or Path.cwd()

        def _resolve(p: str | Path) -> Path:
            p = Path(p)
            return p if p.is_absolute() else (base / p).resolve()

        cities = [City(name=c["name"], country=c["country"]) for c in raw.get("cities", [])]
        if not cities:
            raise ValueError("config.cities must contain at least one city")

        apis = raw.get("apis", {})
        http = raw.get("http", {})
        cache = raw.get("cache", {})
        output = raw.get("output", {})
        if not output:
            raise ValueError("config.output is required")

        return cls(
            sales_csv=_resolve(raw["input"]["sales_csv"]),
            base_currency=str(raw.get("base_currency", "USD")).upper(),
            cities=cities,
            fx_api=ApiEndpoint(**apis["fx"]),
            geocode_api=ApiEndpoint(**apis["weather_geocode"]),
            weather_api=ApiEndpoint(**apis["weather_archive"]),
            http=HttpSettings(
                max_retries=int(http.get("max_retries", 4)),
                backoff_seconds=float(http.get("backoff_seconds", 1.5)),
            ),
            cache=CacheSettings(
                enabled=bool(cache.get("enabled", True)),
                directory=_resolve(cache.get("directory", ".cache")),
                ttl_hours=int(cache.get("ttl_hours", 24)),
            ),
            output=OutputSettings(
                directory=_resolve(output["directory"]),
                sqlite_path=_resolve(output["sqlite_path"]),
                html_path=_resolve(output["html_path"]),
            ),
        )
