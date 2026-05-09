"""Tests for HttpClient: caching, retries, and error handling."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from etl_pipeline.cache import JsonDiskCache
from etl_pipeline.config import HttpSettings
from etl_pipeline.http_client import HttpClient, TransientHttpError


def _client_with_responses(
    cache: JsonDiskCache, responses: list[Any], *, retries: int = 3
) -> tuple[HttpClient, MagicMock, MagicMock]:
    """Build an HttpClient whose session.get returns ``responses`` in order."""
    settings = HttpSettings(max_retries=retries, backoff_seconds=0.0)
    sleep_mock = MagicMock()
    client = HttpClient(settings=settings, cache=cache, sleep=sleep_mock)
    session_get = MagicMock(side_effect=responses)
    client.session.get = session_get  # type: ignore[method-assign]
    return client, session_get, sleep_mock


def _ok_response(payload: Any) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _retryable_response(status: int = 503) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = f"backend overloaded ({status})"
    return resp


def test_returns_payload_on_success(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(tmp_cache, [_ok_response({"x": 1})])
    out = client.get_json("https://example.test/api")
    assert out == {"x": 1}
    assert session_get.call_count == 1


def test_caches_successful_response(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(tmp_cache, [_ok_response({"x": 1})])
    client.get_json("https://example.test/api", cache_key="k1")
    # Second call should hit the cache and not the session.
    client.get_json("https://example.test/api", cache_key="k1")
    assert session_get.call_count == 1


def test_retries_on_retryable_status_then_succeeds(tmp_cache: JsonDiskCache) -> None:
    client, session_get, sleep_mock = _client_with_responses(
        tmp_cache, [_retryable_response(503), _retryable_response(502), _ok_response({"y": 2})]
    )
    assert client.get_json("https://example.test/api") == {"y": 2}
    assert session_get.call_count == 3
    assert sleep_mock.call_count == 2


def test_retries_on_connection_error(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(
        tmp_cache, [requests.ConnectionError("boom"), _ok_response({"y": 2})]
    )
    assert client.get_json("https://example.test/api") == {"y": 2}
    assert session_get.call_count == 2


def test_gives_up_after_max_retries(tmp_cache: JsonDiskCache) -> None:
    client, session_get, _ = _client_with_responses(
        tmp_cache,
        [_retryable_response(503), _retryable_response(503), _retryable_response(503)],
        retries=3,
    )
    with pytest.raises(TransientHttpError):
        client.get_json("https://example.test/api")
    assert session_get.call_count == 3
