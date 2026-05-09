"""Tests for HttpClient: caching, retries, Retry-After, and circuit-breaker handoff."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from etl_pipeline.cache import JsonDiskCache
from etl_pipeline.circuit_breaker import CircuitBreaker, CircuitOpenError
from etl_pipeline.config import HttpSettings
from etl_pipeline.http_client import HttpClient, TransientHttpError


def _client_with_responses(
    cache: JsonDiskCache,
    responses: list[Any],
    *,
    retries: int = 3,
    breaker: CircuitBreaker | None = None,
) -> tuple[HttpClient, MagicMock, MagicMock]:
    settings = HttpSettings(max_retries=retries, backoff_seconds=0.0)
    sleep_mock = MagicMock()
    client = HttpClient(
        settings=settings,
        cache=cache,
        circuit_breaker=breaker or CircuitBreaker(threshold=99),
        sleep=sleep_mock,
    )
    session_get = MagicMock(side_effect=responses)
    client.session.get = session_get  # type: ignore[method-assign]
    return client, session_get, sleep_mock


def _ok(payload: Any) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _retryable(status: int = 503, headers: dict[str, str] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = f"backend overloaded ({status})"
    resp.headers = headers or {}
    return resp


def test_returns_payload_on_success(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(tmp_cache, [_ok({"x": 1})])
    assert client.get_json("https://example.test/api") == {"x": 1}
    assert session_get.call_count == 1


def test_caches_successful_response(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(tmp_cache, [_ok({"x": 1})])
    client.get_json("https://example.test/api", cache_key="k1")
    client.get_json("https://example.test/api", cache_key="k1")
    assert session_get.call_count == 1


def test_retries_on_retryable_status_then_succeeds(tmp_cache: JsonDiskCache) -> None:
    client, session_get, sleep_mock = _client_with_responses(
        tmp_cache, [_retryable(503), _retryable(502), _ok({"y": 2})]
    )
    assert client.get_json("https://example.test/api") == {"y": 2}
    assert session_get.call_count == 3
    assert sleep_mock.call_count == 2


def test_retries_on_connection_error(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(
        tmp_cache, [requests.ConnectionError("boom"), _ok({"y": 2})]
    )
    assert client.get_json("https://example.test/api") == {"y": 2}
    assert session_get.call_count == 2


def test_gives_up_after_max_retries(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(
        tmp_cache,
        [_retryable(503), _retryable(503), _retryable(503)],
        retries=3,
    )
    with pytest.raises(TransientHttpError):
        client.get_json("https://example.test/api")
    assert session_get.call_count == 3


def test_429_with_retry_after_seconds_uses_server_hint(tmp_cache: JsonDiskCache) -> None:
    client, _, sleep_mock = _client_with_responses(
        tmp_cache,
        [_retryable(429, headers={"Retry-After": "7"}), _ok({"ok": True})],
    )
    assert client.get_json("https://example.test/api") == {"ok": True}
    sleep_mock.assert_called_once_with(7.0)


def test_429_with_invalid_retry_after_falls_back_to_backoff(tmp_cache: JsonDiskCache) -> None:
    client, _, sleep_mock = _client_with_responses(
        tmp_cache,
        [_retryable(429, headers={"Retry-After": "not-a-number"}), _ok({"ok": True})],
    )
    assert client.get_json("https://example.test/api") == {"ok": True}
    # falls back to exponential backoff (settings.backoff_seconds=0 → 0)
    assert sleep_mock.call_count == 1


def test_circuit_breaker_short_circuits_after_failures(tmp_cache: JsonDiskCache) -> None:
    breaker = CircuitBreaker(threshold=2, reset_seconds=600)
    client, session_get, _ = _client_with_responses(
        tmp_cache,
        [_retryable(503), _retryable(503), _retryable(503), _ok({"y": 2})],
        retries=10,
        breaker=breaker,
    )
    with pytest.raises(CircuitOpenError):
        client.get_json("https://example.test/api")
    # Only 2 calls reached the wire before the breaker opened.
    assert session_get.call_count == 2


def test_circuit_breaker_resets_on_success(tmp_cache: JsonDiskCache) -> None:
    breaker = CircuitBreaker(threshold=3)
    client, _, _ = _client_with_responses(tmp_cache, [_retryable(503), _ok({"ok": True})], breaker=breaker)
    client.get_json("https://example.test/api")
    assert breaker.status() == {"example.test": {"state": "closed", "failures": 0}}
