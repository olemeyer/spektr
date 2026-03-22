"""Tests for the metrics subsystem – counters, gauges, histograms."""

from __future__ import annotations

import threading

import pytest

from spektr import capture, log
from spektr._metrics._api import InMemoryMetrics, _metrics


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset the global metrics singleton before each test."""
    _metrics.reset()
    yield
    _metrics.reset()


class TestInMemoryMetrics:
    def test_counter_increments(self):
        metrics = InMemoryMetrics()
        metrics.count("requests")
        metrics.count("requests")
        metrics.count("requests")
        assert metrics.get_counter("requests") == 3

    def test_counter_with_value(self):
        metrics = InMemoryMetrics()
        metrics.count("bytes", 1024)
        metrics.count("bytes", 2048)
        assert metrics.get_counter("bytes") == 3072

    def test_counter_with_labels(self):
        metrics = InMemoryMetrics()
        metrics.count("requests", method="GET")
        metrics.count("requests", method="GET")
        metrics.count("requests", method="POST")
        assert metrics.get_counter("requests", method="GET") == 2
        assert metrics.get_counter("requests", method="POST") == 1

    def test_counter_missing_returns_zero(self):
        metrics = InMemoryMetrics()
        assert metrics.get_counter("nonexistent") == 0

    def test_gauge_set_value(self):
        metrics = InMemoryMetrics()
        metrics.gauge("queue.depth", 42)
        assert metrics.get_gauge("queue.depth") == 42

    def test_gauge_overwrites(self):
        metrics = InMemoryMetrics()
        metrics.gauge("temperature", 20.5)
        metrics.gauge("temperature", 22.0)
        assert metrics.get_gauge("temperature") == 22.0

    def test_gauge_with_labels(self):
        metrics = InMemoryMetrics()
        metrics.gauge("cpu", 0.75, core="0")
        metrics.gauge("cpu", 0.50, core="1")
        assert metrics.get_gauge("cpu", core="0") == 0.75
        assert metrics.get_gauge("cpu", core="1") == 0.50

    def test_gauge_missing_returns_none(self):
        metrics = InMemoryMetrics()
        assert metrics.get_gauge("nonexistent") is None

    def test_histogram_records_values(self):
        metrics = InMemoryMetrics()
        metrics.histogram("latency", 10.0)
        metrics.histogram("latency", 20.0)
        metrics.histogram("latency", 15.0)
        assert metrics.get_histogram("latency") == [10.0, 20.0, 15.0]

    def test_histogram_with_labels(self):
        metrics = InMemoryMetrics()
        metrics.histogram("latency", 10.0, endpoint="/users")
        metrics.histogram("latency", 50.0, endpoint="/orders")
        assert metrics.get_histogram("latency", endpoint="/users") == [10.0]
        assert metrics.get_histogram("latency", endpoint="/orders") == [50.0]

    def test_histogram_missing_returns_empty(self):
        metrics = InMemoryMetrics()
        assert metrics.get_histogram("nonexistent") == []

    def test_reset_clears_all(self):
        metrics = InMemoryMetrics()
        metrics.count("a")
        metrics.gauge("b", 1.0)
        metrics.histogram("c", 1.0)
        metrics.reset()
        assert metrics.get_counter("a") == 0
        assert metrics.get_gauge("b") is None
        assert metrics.get_histogram("c") == []

    def test_label_order_does_not_matter(self):
        metrics = InMemoryMetrics()
        metrics.count("req", method="GET", path="/users")
        metrics.count("req", path="/users", method="GET")
        assert metrics.get_counter("req", method="GET", path="/users") == 2

    def test_thread_safety(self):
        metrics = InMemoryMetrics()
        barrier = threading.Barrier(10)

        def increment():
            barrier.wait()
            for _ in range(1000):
                metrics.count("threaded")

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert metrics.get_counter("threaded") == 10000


class TestLoggerMetrics:
    def test_log_count(self):
        log.count("requests", method="GET")
        assert _metrics.get_counter("requests", method="GET") == 1

    def test_log_gauge(self):
        log.gauge("queue.depth", 42)
        assert _metrics.get_gauge("queue.depth") == 42

    def test_log_histogram(self):
        log.histogram("latency", 123.4)
        assert _metrics.get_histogram("latency") == [123.4]

    def test_log_count_default_value(self):
        log.count("events")
        log.count("events")
        assert _metrics.get_counter("events") == 2

    def test_bound_logger_metrics(self):
        bound = log.bind(service="api")
        bound.count("requests")
        assert _metrics.get_counter("requests") == 1

    def test_metrics_with_labels(self):
        log.count("http.errors", method="POST", path="/api")
        log.count("http.errors", method="GET", path="/health")
        assert _metrics.get_counter("http.errors", method="POST", path="/api") == 1
        assert _metrics.get_counter("http.errors", method="GET", path="/health") == 1
