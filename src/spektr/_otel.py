"""OpenTelemetry backbone – always active, powers all span management.

spektr uses OTel as the single source of truth for span IDs, context
propagation, and trace correlation. A TracerProvider is lazily created
on the first span – no exporter by default (pure in-process). When an
endpoint is configured, an OTLP exporter is attached automatically.

Architecture:
    _ensure_provider()  → lazy-init a default TracerProvider (no export)
    setup()             → (re)configure with exporter, service name, etc.
    start_span()        → create an OTel span (auto-parents via context)
    activate_span()     → set span as current in OTel context
    end_span()          → finalize span with status and optional error
    shutdown()          → flush and tear down the provider
"""

from __future__ import annotations

from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import StatusCode, set_span_in_context

# Module-level state – managed exclusively through setup() / shutdown().
_provider: TracerProvider | None = None
_tracer: otel_trace.Tracer | None = None


# ── Initialization ─────────────────────────────────────────────


def _ensure_provider() -> otel_trace.Tracer:
    """Lazily initialize a minimal TracerProvider (no exporter).

    Called automatically by start_span(). Creates a bare provider so
    spans get valid OTel IDs even when no collector endpoint is set.
    """
    global _provider, _tracer
    if _tracer is None:
        _provider = TracerProvider()
        _tracer = _provider.get_tracer("spektr")
    return _tracer


def setup(
    service_name: str = "default",
    endpoint: str | None = None,
    exporter: SpanExporter | None = None,
    *,
    simple_processor: bool = False,
) -> None:
    """(Re)initialize the TracerProvider with a specific configuration.

    Args:
        service_name: Populates the ``service.name`` OTel resource attribute.
        endpoint: OTLP collector URL. Creates an OTLPSpanExporter unless
                  an explicit *exporter* is provided.
        exporter: Custom span exporter (e.g. InMemorySpanExporter for tests).
        simple_processor: Use SimpleSpanProcessor (synchronous export,
                          useful for tests). Default is BatchSpanProcessor.
    """
    global _provider, _tracer

    # Tear down previous provider if one exists.
    if _provider is not None:
        _provider.shutdown()

    resource = Resource.create({"service.name": service_name})
    _provider = TracerProvider(resource=resource)

    # Auto-create OTLP exporter from endpoint (requires optional `spektr[otlp]`).
    if exporter is None and endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
        except ImportError:
            pass  # OTLP package not installed – spans are created but not exported.

    if exporter is not None:
        processor = SimpleSpanProcessor(exporter) if simple_processor else BatchSpanProcessor(exporter)
        _provider.add_span_processor(processor)

    _tracer = _provider.get_tracer("spektr", "0.1.0")


# ── Span Lifecycle ─────────────────────────────────────────────


def start_span(name: str, attributes: dict[str, Any] | None = None) -> otel_trace.Span:
    """Create a new OTel span. Auto-parents to the current context span."""
    tracer = _ensure_provider()

    # OTel attributes only accept str, int, float, bool (and sequences thereof).
    # Non-primitive values are stringified; None values are dropped.
    attrs: dict[str, Any] = {}
    if attributes:
        for k, v in attributes.items():
            if isinstance(v, (str, int, float, bool)):
                attrs[k] = v
            elif v is not None:
                attrs[k] = str(v)

    return tracer.start_span(name, attributes=attrs or None)


def activate_span(span: otel_trace.Span) -> object:
    """Push *span* as current in the OTel context. Returns a token for restore."""
    return otel_context.attach(set_span_in_context(span))


def deactivate_span(token: object | None) -> None:
    """Restore the OTel context to the state before the matching activate_span()."""
    if token is not None:
        otel_context.detach(token)


def get_span_ids(span: otel_trace.Span) -> tuple[str, str]:
    """Extract ``(trace_id, span_id)`` as 32/16-char hex strings from an OTel span."""
    ctx = span.get_span_context()
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def end_span(span: otel_trace.Span, error: BaseException | None = None) -> None:
    """Finalize a span – set status and optionally record an exception."""
    if error:
        span.set_status(StatusCode.ERROR, str(error))
        span.record_exception(error)
    else:
        span.set_status(StatusCode.OK)
    span.end()


# ── Teardown ───────────────────────────────────────────────────


def shutdown() -> None:
    """Flush pending exports and release the TracerProvider."""
    global _tracer, _provider
    if _provider is not None:
        _provider.shutdown()
    _tracer = None
    _provider = None


def get_provider() -> TracerProvider | None:
    """Return the active TracerProvider (primarily for test introspection)."""
    return _provider
