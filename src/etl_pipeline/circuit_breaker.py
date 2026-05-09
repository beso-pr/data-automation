"""Per-host circuit breaker.

Stops hammering a flaky upstream after N consecutive failures. Once "open",
all calls to that host fail fast for ``reset_seconds`` before a single probe
is allowed through to test recovery.

Three states (kept implicit, no enums needed):

- *closed*    — normal operation; failures increment a counter.
- *open*      — failures crossed ``threshold``; calls fail fast for ``reset_seconds``.
- *half-open* — after the cool-down, the next call is allowed; success resets the
                counter to closed, failure reopens the breaker.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


class CircuitOpenError(RuntimeError):
    """Raised when the breaker for a host is open and the call is short-circuited."""


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    """Thread-safe per-host circuit breaker."""

    def __init__(self, threshold: int = 5, reset_seconds: float = 60.0) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if reset_seconds < 0:
            raise ValueError("reset_seconds must be >= 0")
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self._state: dict[str, _State] = {}
        self._lock = threading.Lock()
        self._now = time.monotonic  # injectable for tests

    def before_call(self, host: str) -> None:
        """Raise :class:`CircuitOpenError` if the breaker is open."""
        with self._lock:
            state = self._state.get(host)
            if state is None or state.opened_at is None:
                return
            if self._now() - state.opened_at < self.reset_seconds:
                raise CircuitOpenError(
                    f"Circuit breaker is OPEN for host '{host}'. "
                    f"Will retry after {self.reset_seconds:.0f}s cool-down."
                )
            # Cool-down elapsed — half-open: let the next call probe.
            state.opened_at = None

    def record_success(self, host: str) -> None:
        with self._lock:
            self._state[host] = _State()

    def record_failure(self, host: str) -> None:
        with self._lock:
            state = self._state.setdefault(host, _State())
            state.failures += 1
            if state.failures >= self.threshold:
                state.opened_at = self._now()

    def status(self) -> dict[str, dict[str, float | int | str]]:
        """Snapshot for diagnostics/logging."""
        out: dict[str, dict[str, float | int | str]] = {}
        with self._lock:
            for host, state in self._state.items():
                if state.opened_at is None:
                    out[host] = {"state": "closed", "failures": state.failures}
                else:
                    age = self._now() - state.opened_at
                    out[host] = {
                        "state": "open",
                        "failures": state.failures,
                        "opened_for_seconds": round(age, 1),
                    }
        return out
