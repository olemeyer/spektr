"""Protocol definitions for pluggable components.

Defines the interfaces that decouple spektr's subsystems:
    Sink         – receives finalized LogRecords for output
    Sampler      – decides whether a record should be emitted
    MetricBackend – records counters, gauges, histograms
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ._types import LogRecord


@runtime_checkable
class Sink(Protocol):
    """Receives finalized LogRecords for output."""

    def write(self, record: LogRecord) -> None: ...

    def flush(self) -> None: ...


@runtime_checkable
class Sampler(Protocol):
    """Decides whether a log record should be emitted."""

    def should_emit(self, level: int, message: str) -> bool: ...


@runtime_checkable
class MetricBackend(Protocol):
    """Backend for recording metrics."""

    def counter(self, name: str, value: float, labels: dict[str, str]) -> None: ...

    def gauge(self, name: str, value: float, labels: dict[str, str]) -> None: ...

    def histogram(self, name: str, value: float, labels: dict[str, str]) -> None: ...
