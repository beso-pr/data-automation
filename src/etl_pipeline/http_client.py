"""Resilient HTTP client with retries, timeouts, and JSON disk caching.

Implements a small exponential-backoff retry loop on top of ``requests``
with no third-party retry dependency.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .cache import JsonDiskCache
from .config import HttpSettings
from .logging_setup import get_logger

logger = get_logger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class TransientHttpError(RuntimeError):
    """Raised when an HTTP call fails in a way we want to retry."""


class HttpClient:
    """Thin wrapper around :class:`requests.Session` with caching + retries."""

    def __init__(
        self,
        settings: HttpSettings,
        cache: JsonDiskCache,
        user_agent: str = "etl-pipeline/0.1 (+https://example.local)",
        sleep: Any = time.sleep,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self._sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int = 15,
        cache_key: str | None = None,
    ) -> Any:
        """GET ``url`` and return parsed JSON, caching by ``cache_key`` if provided."""
        if cache_key:
            cached = self.cache.get(cache_key)
            if cached is not None:
                logger.debug("cache hit: %s", cache_key)
                return cached

        payload = self._call_with_retry(url, params, timeout)

        if cache_key:
            self.cache.set(cache_key, payload)
        return payload

    def _call_with_retry(
        self, url: str, params: dict[str, Any] | None, timeout: int
    ) -> Any:
        attempts = max(1, self.settings.max_retries)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                if response.status_code in RETRYABLE_STATUS:
                    raise TransientHttpError(
                        f"GET {url} returned {response.status_code}: {response.text[:120]}"
                    )
                response.raise_for_status()
                return response.json()
            except (TransientHttpError, requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                # Exponential backoff: backoff * 2^(attempt-1), capped at 30s.
                delay = min(self.settings.backoff_seconds * (2 ** (attempt - 1)), 30.0)
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s. Retrying in %.1fs",
                    url,
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                self._sleep(delay)

        assert last_exc is not None  # pragma: no cover
        raise last_exc
