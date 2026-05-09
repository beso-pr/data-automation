"""Tests for JsonDiskCache."""

from __future__ import annotations

import time
from pathlib import Path

from etl_pipeline.cache import JsonDiskCache


def test_set_then_get_round_trips(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path, ttl_hours=1)
    cache.set("k", {"hello": "world", "n": 42})
    assert cache.get("k") == {"hello": "world", "n": 42}


def test_get_returns_none_for_missing_key(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path, ttl_hours=1)
    assert cache.get("missing") is None


def test_disabled_cache_is_a_noop(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path, ttl_hours=1, enabled=False)
    cache.set("k", "v")
    assert cache.get("k") is None
    assert not any(tmp_path.iterdir())


def test_expired_entries_are_ignored(tmp_path: Path, monkeypatch) -> None:
    cache = JsonDiskCache(tmp_path, ttl_hours=1)
    cache.set("k", "v")
    fake_now = time.time() + 60 * 60 * 2
    monkeypatch.setattr("etl_pipeline.cache.time.time", lambda: fake_now)
    assert cache.get("k") is None


def test_corrupt_file_is_treated_as_miss(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path, ttl_hours=1)
    cache.set("k", "v")
    file = next(tmp_path.iterdir())
    file.write_text("{not json", encoding="utf-8")
    assert cache.get("k") is None
