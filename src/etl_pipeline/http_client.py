"""Resilient HTTP client.

Features:
- Exponential-backoff retry on 408/425/429/5xx, ``ConnectionError``, ``Timeout``.
- Honours ``Retry-After`` headers (both seconds and HTTP-date forms).
- Per-host circuit breaker that stops hammering a dead upstream.
- Disk-cached JSON responses keyed by an arbitrary string.

No third-party retry/CB libraries — everything is stdlib + ``requests``.
"""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import requests

from .cache import JsonDiskCache
from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .config import HttpSettings
from .logging_setup import get_logger

logger = get_logger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class TransientHttpError(RuntimeError):
    """Raised when an HTTP call fails in a way we want to retry."""


class HttpClient:
    """Thin wrapper around :class:`requests.Session` with caching + retries + CB."""

    def __init__(
        self,
        settings: HttpSettings,
        cache: JsonDiskCache,
        circuit_breaker: CircuitBreaker | None = None,
        user_agent: str = "etl-pipeline/0.1 (+https://example.local)",
        sleep: Any = time.sleep,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.circuit = circuit_breaker or CircuitBreaker(
            threshold=settings.circuit_breaker_threshold,
            reset_seconds=settings.circuit_breaker_reset_seconds,
        )
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

        host = urlparse(url).netloc or url
        payload = self._call_with_retry(host, url, params, timeout)

        if cache_key:
            self.cache.set(cache_key, payload)
        return payload

    def _call_with_retry(self, host: str, url: str, params: dict[str, Any] | None, timeout: int) -> Any:
        attempts = max(1, self.settings.max_retries)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            # Circuit breaker veto fails fast and short-circuits all retries.
            try:
                self.circuit.before_call(host)
            except CircuitOpenError as exc:
                logger.error("Aborting GET %s — %s", url, exc)
                raise

            try:
                response = self.session.get(url, params=params, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                self.circuit.record_failure(host)
                if attempt >= attempts:
                    break
                self._backoff(attempt, exc)
                continue

            if response.status_code in RETRYABLE_STATUS:
                exc = TransientHttpError(f"GET {url} returned {response.status_code}: {response.text[:120]}")
                last_exc = exc
                self.circuit.record_failure(host)
                if attempt >= attempts:
                    break
                hint = _retry_after_seconds(response)
                self._backoff(attempt, exc, hint=hint)
                continue

            try:
                response.raise_for_status()
                payload = response.json()
            except (requests.HTTPError, ValueError) as exc:
                # 4xx (non-retryable) or invalid JSON — count as failure but raise immediately.
                self.circuit.record_failure(host)
                raise

            self.circuit.record_success(host)
            return payload

        assert last_exc is not None  # pragma: no cover
        raise last_exc

    def _backoff(self, attempt: int, exc: Exception, hint: float | None = None) -> None:
        # Server-supplied hint always wins; otherwise exponential backoff capped at 30s.
        if hint is not None:
            delay = min(hint, 60.0)
        else:
            delay = min(self.settings.backoff_seconds * (2 ** (attempt - 1)), 30.0)
        logger.warning(
            "Request failed on attempt %d (%s). Retrying in %.1fs",
            attempt,
            exc,
            delay,
        )
        self._sleep(delay)


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Parse the ``Retry-After`` header. Supports seconds or HTTP-date."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    delta = when.timestamp() - time.time()
    return max(0.0, delta)
