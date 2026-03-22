"""OpenTelemetry metrics backend for spektr.

Implements the MetricBackend protocol using OpenTelemetry SDK metrics.
Instruments (counters, gauges, histograms) are cached by name and lazily
initialized on first use.

Architecture:
    OTelMetricBackend  -- wraps a MeterProvider, caches instruments
    setup_metrics()    -- configure with a service name and optional reader
    shutdown_metrics() -- tear down the MeterProvider
"""

from __future__ import annotations

from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import Resource

from .._protocols import MetricBackend

# Module-level state -- managed exclusively through setup_metrics() / shutdown_metrics().
_backend: OTelMetricBackend | None = None


class OTelMetricBackend:
    """MetricBackend implementation backed by OpenTelemetry SDK metrics.

    Caches instrument objects by name to avoid re-creating them on every call.
    """

    def __init__(self, provider: MeterProvider) -> None:
        self._provider = provider
        self._meter = provider.get_meter("spektr", "0.1.0")
        self._counters: dict[str, Any] = {}
        self._gauges: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

    def counter(self, name: str, value: float, labels: dict[str, str]) -> None:
        """Increment a counter metric."""
        instrument = self._counters.get(name)
        if instrument is None:
            instrument = self._meter.create_counter(name)
            self._counters[name] = instrument
        instrument.add(value, labels)

    def gauge(self, name: str, value: float, labels: dict[str, str]) -> None:
        """Set a gauge metric to the given value."""
        instrument = self._gauges.get(name)
        if instrument is None:
            instrument = self._meter.create_gauge(name)
            self._gauges[name] = instrument
        instrument.set(value, labels)

    def histogram(self, name: str, value: float, labels: dict[str, str]) -> None:
        """Record a value in a histogram metric."""
        instrument = self._histograms.get(name)
        if instrument is None:
            instrument = self._meter.create_histogram(name)
            self._histograms[name] = instrument
        instrument.record(value, labels)


def setup_metrics(
    service_name: str = "default",
    reader: MetricReader | None = None,
) -> OTelMetricBackend:
    """(Re)initialize the metrics backend with a MeterProvider.

    Args:
        service_name: Populates the ``service.name`` OTel resource attribute.
        reader: A MetricReader (e.g. InMemoryMetricReader for tests,
                PeriodicExportingMetricReader for production).

    Returns:
        The configured OTelMetricBackend instance.
    """
    global _backend

    if _backend is not None:
        shutdown_metrics()

    resource = Resource.create({"service.name": service_name})
    metric_readers = [reader] if reader is not None else []
    provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    _backend = OTelMetricBackend(provider)
    return _backend


def shutdown_metrics() -> None:
    """Flush pending metrics and release the MeterProvider."""
    global _backend
    if _backend is not None:
        _backend._provider.shutdown()
    _backend = None


def get_backend() -> OTelMetricBackend | None:
    """Return the active metrics backend (primarily for test introspection)."""
    return _backend
