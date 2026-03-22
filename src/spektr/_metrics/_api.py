"""In-memory metrics backend and API.

Provides a simple in-memory implementation of the MetricBackend protocol.
Metrics are stored locally and can optionally be forwarded to OTel when
configured.

Usage::

    from spektr import log

    log.count("http.requests", method="GET", path="/users")
    log.gauge("queue.depth", 42, queue="ingest")
    log.histogram("request.duration_ms", 123.4, method="POST")
"""

from __future__ import annotations

import threading
from typing import Any


class InMemoryMetrics:
    """Thread-safe in-memory metrics store.

    Implements the MetricBackend protocol. Counters are additive, gauges
    store the latest value, histograms collect all observed values.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple], float] = {}
        self._gauges: dict[tuple[str, tuple], float] = {}
        self._histograms: dict[tuple[str, tuple], list[float]] = {}

    def _label_key(self, labels: dict[str, Any]) -> tuple:
        return tuple(sorted((k, str(v)) for k, v in labels.items()))

    def count(self, name: str, value: float = 1, **labels: Any) -> None:
        """Increment a counter metric."""
        key = (name, self._label_key(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def gauge(self, name: str, value: float, **labels: Any) -> None:
        """Set a gauge metric to a specific value."""
        key = (name, self._label_key(labels))
        with self._lock:
            self._gauges[key] = value

    def histogram(self, name: str, value: float, **labels: Any) -> None:
        """Record a value in a histogram metric."""
        key = (name, self._label_key(labels))
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)

    def get_counter(self, name: str, **labels: Any) -> float:
        """Read the current value of a counter."""
        key = (name, self._label_key(labels))
        with self._lock:
            return self._counters.get(key, 0)

    def get_gauge(self, name: str, **labels: Any) -> float | None:
        """Read the current value of a gauge."""
        key = (name, self._label_key(labels))
        with self._lock:
            return self._gauges.get(key)

    def get_histogram(self, name: str, **labels: Any) -> list[float]:
        """Read all observed values for a histogram."""
        key = (name, self._label_key(labels))
        with self._lock:
            return list(self._histograms.get(key, []))

    def reset(self) -> None:
        """Clear all metrics (useful in tests)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# Module-level singleton.
_metrics = InMemoryMetrics()
