"""OpenTelemetry integration – tracing, metrics, and propagation."""

# Proxy mutable module state for tests that inspect _provider / _tracer.
from . import _tracing as _tracing_module
from ._tracing import (
    activate_span,
    deactivate_span,
    end_span,
    get_provider,
    get_span_ids,
    setup,
    shutdown,
    start_span,
)


def __getattr__(name: str):
    if name in ("_provider", "_tracer"):
        return getattr(_tracing_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "activate_span",
    "deactivate_span",
    "end_span",
    "get_provider",
    "get_span_ids",
    "setup",
    "shutdown",
    "start_span",
]
