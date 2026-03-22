"""Tests for the OTel metrics backend."""

from __future__ import annotations

import pytest

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from spektr._otel._metrics import (
    OTelMetricBackend,
    get_backend,
    setup_metrics,
    shutdown_metrics,
)
from spektr._protocols import MetricBackend


@pytest.fixture(autouse=True)
def cleanup():
    yield
    shutdown_metrics()


def _get_metric_data(reader: InMemoryMetricReader) -> dict:
    """Helper: collect metrics from the reader and return as {name: data_points}."""
    data = reader.get_metrics_data()
    result = {}
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                result[metric.name] = metric.data.data_points
    return result


class TestOTelMetricBackend:
    def test_implements_protocol(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(reader=reader)
        assert isinstance(backend, MetricBackend)

    def test_counter_increment(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(reader=reader)
        backend.counter("test.requests", 1.0, {})
        backend.counter("test.requests", 1.0, {})

        data = _get_metric_data(reader)
        assert "test.requests" in data
        points = data["test.requests"]
        total = sum(p.value for p in points)
        assert total == 2.0

    def test_counter_with_labels(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(reader=reader)
        backend.counter("http.requests", 1.0, {"method": "GET"})
        backend.counter("http.requests", 1.0, {"method": "POST"})

        data = _get_metric_data(reader)
        assert "http.requests" in data
        points = data["http.requests"]
        assert len(points) == 2

    def test_gauge_set(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(reader=reader)
        backend.gauge("queue.depth", 42.0, {})

        data = _get_metric_data(reader)
        assert "queue.depth" in data

    def test_histogram_record(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(reader=reader)
        backend.histogram("latency_ms", 10.0, {})
        backend.histogram("latency_ms", 20.0, {})
        backend.histogram("latency_ms", 30.0, {})

        data = _get_metric_data(reader)
        assert "latency_ms" in data
        points = data["latency_ms"]
        assert len(points) == 1
        assert points[0].count == 3
        assert points[0].sum == 60.0


class TestSetupShutdown:
    def test_setup_returns_backend(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(reader=reader)
        assert backend is not None
        assert get_backend() is backend

    def test_shutdown_clears_backend(self):
        setup_metrics()
        shutdown_metrics()
        assert get_backend() is None

    def test_double_shutdown_safe(self):
        setup_metrics()
        shutdown_metrics()
        shutdown_metrics()  # Should not raise

    def test_setup_replaces_previous(self):
        reader1 = InMemoryMetricReader()
        backend1 = setup_metrics(reader=reader1)
        reader2 = InMemoryMetricReader()
        backend2 = setup_metrics(reader=reader2)
        assert backend1 is not backend2
        assert get_backend() is backend2

    def test_service_name_in_resource(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(service_name="my-service", reader=reader)
        backend.counter("test", 1.0, {})
        data = reader.get_metrics_data()
        resource_attrs = dict(data.resource_metrics[0].resource.attributes)
        assert resource_attrs["service.name"] == "my-service"

    def test_instrument_caching(self):
        reader = InMemoryMetricReader()
        backend = setup_metrics(reader=reader)
        backend.counter("cached", 1.0, {})
        backend.counter("cached", 1.0, {})
        # Same instrument should be reused
        assert len(backend._counters) == 1
