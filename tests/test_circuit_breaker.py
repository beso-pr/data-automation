"""Tests for CircuitBreaker."""

from __future__ import annotations

import pytest

from etl_pipeline.circuit_breaker import CircuitBreaker, CircuitOpenError


def _patched(threshold: int, reset_seconds: float = 60.0) -> tuple[CircuitBreaker, list[float]]:
    """Build a breaker with an injectable monotonic clock."""
    breaker = CircuitBreaker(threshold=threshold, reset_seconds=reset_seconds)
    now = [0.0]
    breaker._now = lambda: now[0]  # type: ignore[method-assign]
    return breaker, now


def test_closed_breaker_lets_calls_through() -> None:
    breaker, _ = _patched(threshold=3)
    breaker.before_call("api.example")  # no exception


def test_opens_after_threshold_failures() -> None:
    breaker, _ = _patched(threshold=3)
    for _ in range(3):
        breaker.record_failure("api.example")
    with pytest.raises(CircuitOpenError):
        breaker.before_call("api.example")


def test_does_not_open_below_threshold() -> None:
    breaker, _ = _patched(threshold=5)
    for _ in range(4):
        breaker.record_failure("api.example")
    breaker.before_call("api.example")  # still closed


def test_success_resets_failure_count() -> None:
    breaker, _ = _patched(threshold=3)
    breaker.record_failure("api.example")
    breaker.record_failure("api.example")
    breaker.record_success("api.example")
    breaker.record_failure("api.example")
    breaker.record_failure("api.example")
    breaker.before_call("api.example")  # still below threshold


def test_half_open_after_cooldown() -> None:
    breaker, now = _patched(threshold=2, reset_seconds=30.0)
    breaker.record_failure("api.example")
    breaker.record_failure("api.example")
    with pytest.raises(CircuitOpenError):
        breaker.before_call("api.example")

    now[0] = 31.0  # past cooldown
    breaker.before_call("api.example")  # half-open: probe allowed

    breaker.record_success("api.example")
    breaker.before_call("api.example")  # fully closed again


def test_isolated_per_host() -> None:
    breaker, _ = _patched(threshold=2)
    breaker.record_failure("a.example")
    breaker.record_failure("a.example")
    with pytest.raises(CircuitOpenError):
        breaker.before_call("a.example")
    breaker.before_call("b.example")  # different host unaffected


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(threshold=0)
