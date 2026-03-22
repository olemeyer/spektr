# API Reference

Complete reference for every public function, method, class, and type.

---

## `log`

Module-level `Logger` instance. The primary logging interface.

### `log(message, **kwargs)`

Log at INFO level.

```python
log("order created", order_id=42, amount=99.99)
```

### `log.debug(message, **kwargs)`

Log at DEBUG level.

### `log.info(message, **kwargs)`

Log at INFO level. Equivalent to `log(message, **kwargs)`.

### `log.warn(message, **kwargs)`

Log at WARNING level. Alias: `log.warning()`.

### `log.error(message, **kwargs)`

Log at ERROR level.

### `log.exception(message, **kwargs)`

Log at ERROR level with the current exception's traceback attached. Call inside an `except` block. Adds `error_type`, `error_message`, and `error_stacktrace` to the record's `data`.

```python
try:
    process()
except Exception:
    log.exception("processing failed", item_id=42)
```

---

### `log.context(**kwargs)` → context manager

Adds key-value pairs to all logs within its scope. Supports `with` and `async with`.

```python
with log.context(request_id="abc"):
    log("inside")   # context["request_id"] == "abc"
log("outside")      # no request_id
```

### `log.bind(**kwargs)` → `Logger`

Returns a new `Logger` with permanent context attached.

```python
db = log.bind(component="database")
db("query executed")  # context["component"] == "database"
```

---

### `log.time(name=None, **kwargs)` → context manager / decorator

Measures and logs execution duration at INFO level.

```python
# Context manager
with log.time("db query", table="users"):
    ...
# logs: "db query"  duration_ms=42.1  table='users'

# Bare decorator — uses function qualname
@log.time
def process():
    ...

# Named decorator
@log.time("custom name")
def handler():
    ...
```

---

### `log.once(message, **kwargs)`

Log only the first time this message is seen. Subsequent calls with the same message string are silently dropped.

### `log.every(n, message, **kwargs)`

Log every `n`th call from this specific call site (identified by file + line number).

### `log.sample(rate, message, **kwargs)`

Log with probability `rate` (float between 0.0 and 1.0).

---

### `log.count(name, value=1, **labels)`

Increment a counter metric.

```python
log.count("http.requests", method="GET", path="/users")
```

### `log.gauge(name, value, **labels)`

Set a gauge to an absolute value.

```python
log.gauge("queue.depth", 42, queue="ingest")
```

### `log.histogram(name, value, **labels)`

Record a histogram observation.

```python
log.histogram("request.duration_ms", 123.4, method="POST")
```

### `log.progress(name, total=None, *, log_interval=1.0)` → context manager

Track progress of a batch operation. Returns a `ProgressTracker`.

```python
with log.progress("import", total=10000) as p:
    for item in items:
        process(item)
        p.advance()
```

**ProgressTracker methods:**

| Method | Description |
|---|---|
| `p.advance(n=1)` | Advance by `n` items |
| `p.set(current)` | Set absolute progress position |

Supports `async with`.

---

### `log.catch` / `log.catch(reraise=True)` → decorator

Catches exceptions, logs them at ERROR with a rich traceback, and optionally re-raises.

```python
@log.catch                    # logs + re-raises
@log.catch(reraise=False)     # logs + suppresses (returns None)
```

Works with sync and async functions. Preserves `__name__`, `__doc__`, and `__wrapped__`.

---

## `trace`

Module-level `Trace` instance. The primary tracing interface.

### `trace(name, **kwargs)` → context manager

Create a span. Returns the `SpanData` object on enter.

```python
with trace("db.query", table="users") as span:
    print(span.trace_id, span.span_id)
```

### `@trace` → decorator

Wrap a function in a span. Auto-captures arguments as span attributes (excluding `self`/`cls`).

```python
@trace
def fetch_user(user_id: int):
    ...
```

### `@trace(**kwargs)` → decorator factory

Decorator with extra span attributes:

```python
@trace(version="2.0")
def handler():
    ...
```

### `trace.inject(headers=None)` → `dict`

Inject a W3C `traceparent` header from the current span context. If `headers` is `None`, creates a new dict.

```python
with trace("outgoing"):
    headers = trace.inject()
    # headers["traceparent"] == "00-{trace_id}-{span_id}-01"
```

Returns the headers dict unchanged if no valid span is active.

### `trace.extract(headers)` → `TraceContext | None`

Extract W3C trace context from HTTP headers (case-insensitive lookup).

```python
ctx = trace.extract(request.headers)
if ctx is not None:
    print(ctx.trace_id, ctx.parent_id, ctx.trace_flags)
```

---

## `configure(**kwargs)`

Override auto-detected configuration at runtime. Unknown keys raise `ValueError`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `service` | `str` | `"default"` | Service name (OTel resource attribute) |
| `output_mode` | `OutputMode` | `RICH` | `OutputMode.RICH` or `OutputMode.JSON` |
| `min_level` | `LogLevel` | `DEBUG` | Minimum log level to emit |
| `endpoint` | `str \| None` | `None` | OTLP endpoint URL (auto-enables JSON) |
| `show_source` | `bool` | `True` | Append `file:line` to log output |
| `redact` | `list[str]` | see below | Key substrings to redact in output |
| `sinks` | `list[Sink]` | `[]` | Custom output sinks |
| `sampler` | `Sampler \| None` | `None` | Log sampling strategy |
| `health_path` | `str \| None` | `None` | Health check endpoint for middleware |

Default redact patterns: `password`, `secret`, `token`, `authorization`, `api_key`, `apikey`.

Setting `endpoint` auto-switches `output_mode` to JSON unless `output_mode` is explicitly provided.

---

## `install(app=None)`

Install spektr globally:

- `sys.excepthook` → rich tracebacks with local variables
- `threading.excepthook` → same for thread exceptions
- stdlib logging bridge → routes `logging.getLogger()` calls through spektr
- If `app` is a FastAPI or Starlette instance, adds `SpektrMiddleware`

Idempotent — safe to call multiple times.

---

## `capture()` → context manager

Intercept log records for testing. Returns a `CapturedLogs` object.

```python
with capture() as logs:
    log("hello", key="value")

assert len(logs) == 1
assert logs[0].message == "hello"
assert "hello" in logs             # substring search across messages
```

**CapturedLogs interface:**

| Operation | Description |
|---|---|
| `len(logs)` | Number of captured records |
| `logs[0]` | Access by index |
| `"text" in logs` | True if any record's message contains the substring |
| `for record in logs` | Iterate over records |
| `logs.filter(level=..., **kwargs)` | Filter by level and/or data/context fields |
| `logs.messages` | List of all message strings |

---

## `SpektrMiddleware`

ASGI middleware for HTTP request instrumentation.

```python
from spektr import SpektrMiddleware

app = SpektrMiddleware(app)
```

Automatically instruments each request with: `request_id`, trace span, W3C context extraction, completion logging, and metrics recording. Non-HTTP scopes (WebSocket, lifespan) are passed through.

---

## Protocols

### `Sink`

```python
class Sink(Protocol):
    def write(self, record: LogRecord) -> None: ...
    def flush(self) -> None: ...
```

### `Sampler`

```python
class Sampler(Protocol):
    def should_emit(self, level: int, message: str) -> bool: ...
```

### `MetricBackend`

```python
class MetricBackend(Protocol):
    def counter(self, name: str, value: float, labels: dict[str, str]) -> None: ...
    def gauge(self, name: str, value: float, labels: dict[str, str]) -> None: ...
    def histogram(self, name: str, value: float, labels: dict[str, str]) -> None: ...
```

---

## Built-in Implementations

### `RateLimitSampler(per_second: float)`

Token-bucket sampler. Limits log throughput to `per_second` records. ERROR-level messages always pass regardless of the rate limit.

### `CompositeSampler(*samplers)`

Chains multiple samplers. A record is emitted only if every sampler in the chain returns `True`.

### `InMemoryMetrics`

Thread-safe in-memory metrics store. Default backend for `log.count()`, `log.gauge()`, and `log.histogram()`. Provides `get_counter()`, `get_gauge()`, `get_histogram()`, and `reset()` for test introspection.

### `StderrSink`

Default sink that dispatches to the Rich or JSON formatter based on `output_mode`. Used when no custom sinks are configured.

### `OTelMetricBackend`

OpenTelemetry SDK metrics backend. Wraps a `MeterProvider` and caches instruments by name. See `spektr._otel._metrics` for `setup_metrics()` and `shutdown_metrics()`.

---

## Data Types

### `LogLevel`

```python
class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
```

### `LogRecord`

```python
@dataclass(frozen=True)
class LogRecord:
    timestamp: float
    level: LogLevel
    message: str
    data: dict[str, Any]
    context: dict[str, Any]
    source: SourceLocation | None = None
    trace_id: str | None = None
    span_id: str | None = None
    exc_info: tuple | None = None
```

### `SpanData`

```python
@dataclass
class SpanData:
    name: str
    span_id: str
    trace_id: str
    parent_id: str | None
    start_time: float
    data: dict[str, Any]
    children: list[SpanData]
    end_time: float | None
    status: str             # "ok" or "error"
    error: BaseException | None
    duration_ms: float | None  # computed property
```

### `SourceLocation`

```python
@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    function: str
```

### `TraceContext`

```python
@dataclass(frozen=True)
class TraceContext:
    trace_id: str      # 32 hex characters
    parent_id: str     # 16 hex characters
    trace_flags: str   # "01" (sampled) or "00"
```
