"""Tiny on-disk JSON cache for API responses.

Keyed by an arbitrary string. Entries expire after ``ttl_hours``.
This dramatically reduces API calls during repeated runs and tests.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .logging_setup import get_logger

logger = get_logger(__name__)


class JsonDiskCache:
    def __init__(self, directory: Path, ttl_hours: int = 24, enabled: bool = True) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = ttl_hours * 3600
        self.enabled = enabled
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.debug("Cache read failed for %s; ignoring", key)
            return None
        if time.time() - payload.get("ts", 0) > self.ttl_seconds:
            return None
        return payload.get("value")

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        path = self._path_for(key)
        payload = {"ts": time.time(), "key": key, "value": value}
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write cache file %s: %s", path, exc)
