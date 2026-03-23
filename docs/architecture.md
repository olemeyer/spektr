# Architecture

Internal architecture reference for contributors.

## Design Principles

1. **Zero config** — works out of the box, environment auto-detection
2. **Single import** — `from spektr import log, trace` is the complete API
3. **Protocols over inheritance** — pluggable via structural typing, no base classes
4. **contextvars everywhere** — correct async propagation, no thread-locals
5. **Layered dependencies** — strict import order, no circular imports

## Package Structure

```
src/spektr/
├── __init__.py              # Public API surface
├── _types.py                # LogLevel, LogRecord, SpanData, SourceLocation
├── _config.py               # Config singleton (env vars + runtime overrides)
├── _context.py              # ContextVars: log context, current span, capture sink
├── _protocols.py            # Sink, Sampler, MetricBackend protocol definitions
├── _repr.py                 # safe_repr / safe_str for arbitrary objects
│
├── _core/
│   ├── _logger.py           # Logger class — the `log` singleton
│   ├── _tracer.py           # Trace class — the `trace` singleton
│   └── _capture.py          # capture() context manager + CapturedLogs
│
├── _output/
│   ├── _formatters.py       # Rich console formatter + JSON stderr formatter
│   ├── _sinks.py            # StderrSink (Sink protocol implementation)
│   └── _redaction.py        # Key-based value redaction
│
├── _otel/
│   ├── _tracing.py          # OTel TracerProvider lifecycle + span management
│   ├── _propagation.py      # W3C Trace Context (traceparent parsing/formatting)
│   └── _metrics.py          # OTelMetricBackend (MeterProvider wrapper)
│
├── _sampling/
│   ├── _sampler.py          # RateLimitSampler, CompositeSampler
│   └── _ratelimit.py        # TokenBucket implementation
│
├── _metrics/
│   ├── _api.py              # InMemoryMetrics (default backend)
│   └── _progress.py         # ProgressTracker for batch operations
│
└── _integrations/
    ├── _bridge.py           # stdlib logging.Handler → spektr bridge
    ├── _middleware.py        # ASGI middleware (request instrumentation)
    ├── _exceptions.py       # sys.excepthook / threading.excepthook
    └── _health.py           # JSON health check ASGI endpoint
```

## Dependency Layers

Dependencies flow strictly downward. No module imports from a higher layer.

```
Layer 0  _types
Layer 1  _config, _repr
Layer 2  _context, _protocols
Layer 3  _output      (_formatters, _sinks, _redaction)
Layer 4  _otel        (_tracing, _propagation, _metrics)
Layer 5  _sampling    (_ratelimit, _sampler)
Layer 6  _metrics     (_api, _progress)
Layer 7  _core        (_logger, _tracer, _capture)
Layer 8  _integrations (_bridge, _middleware, _exceptions, _health)
Layer 9  __init__     (public API)
```

Layers 6 and 7 use deferred imports (inside function bodies) for references to lower layers where needed, avoiding circular import issues.

## Design Decisions

### Why `log` is a callable instance

`log` is an instance of `Logger`, not a class or module. This makes `log("message")` work — the most common operation (INFO logging) requires the least typing. Named levels are available as methods (`log.debug()`, `log.error()`, etc.) for when you need them.

### Why sinks are resolved at emit time

`Logger._emit()` checks `config.sinks` on every call rather than caching sink references. This allows sinks to be reconfigured at runtime, and critically allows `capture()` to intercept records without affecting sink configuration.

### Why capture() uses a ContextVar

`capture()` stores its record list in a `ContextVar`, which means:

- Each async task gets its own isolated capture scope
- Concurrent requests don't leak records into each other's captures
- No global mutable state needs to be locked or restored

### Why OTel is always initialized

spektr unconditionally creates a `TracerProvider` at startup, even without an OTLP endpoint. This ensures `trace_id` and `span_id` are always real OTel-generated identifiers. When no endpoint is configured, spans are created but not exported — no network traffic, no overhead beyond ID generation.

## Data Flow

### Log Record Lifecycle

```
log("message", key=value)
    │
    ▼
Logger._emit()
    ├── min_level check         → drop if level too low
    ├── sampler.should_emit()   → drop if sampled out
    ├── resolve source location → walk stack past spektr frames
    ├── get current span        → attach trace_id, span_id
    ├── merge context           → contextvars + bound context
    ├── enrich exceptions       → error_type, error_message, error_stacktrace
    ├── build LogRecord
    │
    ▼
Dispatch (first match wins)
    ├── capture() active?      → append to ContextVar list
    ├── custom sinks?          → sink.write() for each sink
    └── default                → format_record_rich() or format_record_json()
```

### Span Lifecycle

```
with trace("name", key=value):
    │
    ▼
_SpanContext.__enter__()
    ├── read parent span from ContextVar
    ├── create OTel span (auto-parents via OTel context)
    ├── extract trace_id, span_id from OTel span
    ├── build SpanData (lightweight mirror for console rendering)
    ├── link as child of parent SpanData
    ├── set as current span in ContextVar
    │
    ▼
  [user code]
    │
    ▼
_SpanContext.__exit__()
    ├── record end_time, compute duration
    ├── set status ("ok" or "error")
    ├── end OTel span (records exception event if error)
    ├── restore parent span in ContextVar
    └── if root span → render trace tree to console/JSON
```
