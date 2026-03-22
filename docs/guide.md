# Guide

Complete walkthrough of every spektr feature.

## Installation

```bash
pip install spektr
```

For OTLP export to collectors (Jaeger, Grafana Tempo, Datadog):

```bash
pip install spektr[otlp]
```

---

## Logging

### Basic Usage

`log` is a callable object. Call it directly for INFO-level messages:

```python
from spektr import log

log("server started", port=8080, env="production")
```

```
 14:23:01.123 INFO   server started  port=8080 env='production'  main.py:3
```

Every call accepts keyword arguments as structured data. No format strings, no positional args.

### Log Levels

```python
log.debug("cache miss", key="user:42")
log.info("request handled", method="GET", path="/users")
log.warn("rate limit close", current=980, limit=1000)
log.error("connection failed", host="db.internal", retries=3)
```

`log("message")` is shorthand for `log.info("message")`.

### Exception Logging

Inside an `except` block, `log.exception()` logs at ERROR level with the full traceback and structured error fields:

```python
try:
    process_payment(order_id)
except PaymentError:
    log.exception("payment failed", order_id=order_id)
```

The record's `data` dict will contain `error_type`, `error_message`, and `error_stacktrace` alongside your custom fields.

---

## Context

### Scoped Context

`log.context()` adds key-value pairs to all logs within its scope:

```python
def handle_request(request):
    with log.context(request_id=request.id, user_id=request.user.id):
        log("validating")               # has request_id + user_id
        result = process(request)        # called functions see the same context
        log("done", result=result)       # still has them
```

Context is based on `contextvars`. Each async task gets its own isolated copy — no thread-local hacks.

Works with `async with` as well:

```python
async with log.context(request_id="abc"):
    await do_work()
```

### Bound Loggers

`log.bind()` returns a new logger instance with permanent context:

```python
db = log.bind(component="database", host="db.prod")
cache = log.bind(component="cache", host="redis.prod")

db("query executed", table="users", rows=42)
cache("hit", key="user:42")
```

Bound loggers can be chained:

```python
db = log.bind(component="database")
db_primary = db.bind(host="primary.db")
db_replica = db.bind(host="replica.db")
```

---

## Tracing

### Spans

Spans measure the duration of operations and form a tree:

```python
from spektr import trace

with trace("handle request", method="GET", path="/users"):
    with trace("db.query", table="users"):
        users = db.fetch_all()
    with trace("serialize"):
        payload = json.dumps(users)
```

```
handle request  45.2ms  method='GET' path='/users'
├── db.query  30.1ms  table='users'
└── serialize  12.3ms
```

### Decorator

`@trace` auto-captures the function's arguments as span attributes:

```python
@trace
def fetch_user(user_id: int, include_profile: bool = False):
    ...

fetch_user(42, include_profile=True)
# span: fetch_user  user_id=42 include_profile=True
```

`self` and `cls` are automatically excluded.

### Log-Trace Correlation

Logs emitted inside a span automatically receive `trace_id` and `span_id`:

```python
@trace
def handle_order(order_id: int):
    log("fetching user")      # trace_id and span_id attached
    user = fetch_user()
    log("charging payment")   # same trace_id, same span_id
```

In JSON mode these fields appear in every log line, so your log aggregator can join them with distributed traces.

### W3C Trace Context

For distributed tracing across service boundaries, use `trace.inject()` and `trace.extract()`:

```python
# Service A — outgoing call
with trace("call downstream"):
    headers = trace.inject()
    response = httpx.get("http://service-b/api", headers=headers)

# Service B — incoming request
context = trace.extract(request.headers)
# context.trace_id, context.parent_id, context.trace_flags
```

The ASGI middleware does this automatically for incoming requests.

---

## Exception Handling

### @log.catch

Wraps a function to catch, log, and optionally re-raise exceptions:

```python
@log.catch
def risky_operation():
    ...  # exceptions are logged with rich traceback, then re-raised

@log.catch(reraise=False)
def optional_operation():
    ...  # exceptions are logged but suppressed, function returns None
```

Works with async functions and preserves the original function's name and signature.

### install()

Installs spektr globally:

```python
import spektr
spektr.install()
```

This sets:
- `sys.excepthook` — rich tracebacks with local variables for uncaught exceptions
- `threading.excepthook` — same for exceptions in threads
- stdlib logging bridge — routes third-party library logs (SQLAlchemy, httpx, etc.) through spektr

With a web framework:

```python
from fastapi import FastAPI
import spektr

app = FastAPI()
spektr.install(app)  # also adds SpektrMiddleware automatically
```

---

## Timing

### Context Manager

```python
with log.time("db query", table="users"):
    rows = db.fetch_all()
# logs: "db query"  duration_ms=42.1  table='users'
```

### Decorator

```python
@log.time
def process_batch():
    ...

@log.time("custom name")
def handler():
    ...
```

Both forms support async functions.

---

## Rate Limiting

Control log volume without losing visibility:

```python
# Log only the first occurrence of this message
log.once("cache initialized")

# Log every 1000th call from this specific call site
for item in items:
    log.every(1000, "processing", current=item.id)

# Log with 1% probability
log.sample(0.01, "detailed debug info", payload=data)
```

These all log at INFO level and accept arbitrary keyword arguments like regular `log()` calls.

---

## Metrics

### Counters, Gauges, Histograms

```python
log.count("http.requests", method="GET", path="/users")
log.gauge("queue.depth", len(queue), queue="ingest")
log.histogram("request.duration_ms", duration, method="POST")
```

Metrics are stored in an in-memory backend by default. An OpenTelemetry metrics backend is available for production export.

### Progress Tracking

For long-running batch operations:

```python
with log.progress("import users", total=10000) as p:
    for user in users:
        process(user)
        p.advance()          # advance by 1
        # or p.advance(100)  # advance by N
        # or p.set(5000)     # jump to absolute position
```

Progress is logged at configurable intervals (default: once per second) with `current`, `total`, `percent`, and `rate` fields. A final summary with total duration is always logged on exit.

```python
# Custom interval
with log.progress("export", total=50000, log_interval=5.0) as p:
    ...
```

---

## ASGI Middleware

### Setup

```python
from spektr import SpektrMiddleware

# Wrap any ASGI app
app = SpektrMiddleware(app)

# Or add via framework API
app.add_middleware(SpektrMiddleware)  # FastAPI / Starlette
```

### What It Does

For every HTTP request the middleware automatically:

1. Generates a unique `request_id` (UUID4) and adds it to the log context
2. Creates a trace span covering the full request lifecycle
3. Extracts incoming W3C `traceparent` headers for distributed tracing
4. Logs a completion message with method, path, status code, and duration
5. Records an `http.requests.total` counter and `http.request.duration_ms` histogram

### Health Check

Configure a health endpoint that bypasses instrumentation:

```python
import spektr
spektr.configure(health_path="/healthz")
```

Returns `{"status": "ok", "service": "<your-service-name>"}` with HTTP 200.

---

## Configuration

### Environment Variables

spektr auto-detects its environment. No configuration required for basic usage.

| Variable | Effect |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint, auto-switches to JSON mode |
| `SPEKTR_ENDPOINT` | Same (spektr-specific alias) |
| `SPEKTR_JSON=1` | Force JSON output without an endpoint |
| `NO_COLOR` | Respects [no-color.org](https://no-color.org) |
| `SPEKTR_LOG_LEVEL` | Minimum level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SPEKTR_SERVICE` | Service name for OTel resource |
| `OTEL_SERVICE_NAME` | Same (standard OTel env var) |

### Runtime Configuration

```python
import spektr
from spektr import RateLimitSampler
from spektr._types import LogLevel

spektr.configure(
    service="order-api",
    endpoint="http://collector:4318",
    min_level=LogLevel.WARNING,
    redact=["password", "secret", "token", "authorization"],
    sampler=RateLimitSampler(per_second=100),
    health_path="/healthz",
)
```

### Sensitive Data Redaction

Keys matching any redaction pattern are replaced with `***` in all output (console and JSON):

```python
log("auth attempt", password="secret123", api_key="sk-abc")
# output: auth attempt  password='***' api_key='***'
```

Default patterns: `password`, `secret`, `token`, `authorization`, `api_key`, `apikey`. Override via `configure(redact=[...])`.

---

## Pluggable Architecture

### Custom Sinks

Implement the `Sink` protocol to route logs to any destination:

```python
from spektr import configure

class DatadogSink:
    def write(self, record):
        datadog_client.log(
            record.message,
            level=record.level.name,
            **record.data,
        )

    def flush(self):
        datadog_client.flush()

configure(sinks=[DatadogSink()])
```

Multiple sinks receive every record:

```python
configure(sinks=[DatadogSink(), PagerDutySink(), FileSink("/var/log/app.jsonl")])
```

When `capture()` is active (in tests), it intercepts records before they reach sinks.

### Custom Samplers

Implement the `Sampler` protocol to control which logs are emitted:

```python
from spektr import configure, CompositeSampler, RateLimitSampler
from spektr._types import LogLevel

class WarningAndAbove:
    def should_emit(self, level, message):
        return level >= LogLevel.WARNING

# Chain samplers — all must agree for a record to pass
configure(sampler=CompositeSampler(
    WarningAndAbove(),
    RateLimitSampler(per_second=50),
))
```

The built-in `RateLimitSampler` uses a token bucket and always passes ERROR-level messages regardless of the rate limit.

---

## Testing

### capture()

`capture()` intercepts log records without producing any output:

```python
from spektr import capture, log

def test_order_created():
    with capture() as logs:
        create_order(42)

    assert len(logs) == 1
    assert logs[0].message == "order created"
    assert logs[0].data["order_id"] == 42
```

### Substring Search

`capture()` supports the `in` operator for quick message assertions:

```python
with capture() as logs:
    log("order created", order_id=42)

assert "order created" in logs
```

### Filtering

Filter captured records by level or data fields:

```python
with capture() as logs:
    log.debug("verbose")
    log.error("critical", code=500)

errors = logs.filter(level=LogLevel.ERROR)
assert len(errors) == 1

by_code = logs.filter(code=500)
assert len(by_code) == 1
```

### Record Fields

Each captured `LogRecord` has these fields:

| Field | Type | Description |
|---|---|---|
| `message` | `str` | The log message |
| `level` | `LogLevel` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `data` | `dict` | Structured key-value data from the call |
| `context` | `dict` | Context from `log.context()` and `log.bind()` |
| `timestamp` | `float` | Unix timestamp |
| `source` | `SourceLocation` | `file`, `line`, `function` of the caller |
| `trace_id` | `str \| None` | OTel trace ID if inside a span |
| `span_id` | `str \| None` | OTel span ID if inside a span |
| `exc_info` | `tuple \| None` | Exception triple if `log.exception()` or `@log.catch` |
