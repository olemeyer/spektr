# API Reference

Every public function, method, and class — with example code and output.

---

## Logging

### `log(message, **kwargs)`

Log at INFO level. The most common call — just `log()`. Equivalent to `log.info()`.

If the message contains `{placeholders}`, they are formatted with the kwargs:

```python
from spektr import log

log("server started", port=8080, env="production")
log("user {name} connected on port {port}", name="ole", port=8080)
```

```
 14:23:01.123 INFO   server started  port=8080 env='production'  main.py:3
 14:23:01.124 INFO   user ole connected on port 8080  name='ole' port=8080  main.py:4
```

If a placeholder key is missing from kwargs, the message stays unchanged (no crash).

---

### `log.debug(message, **kwargs)`

Log at DEBUG level. Suppressed by default when `min_level` is set above DEBUG.

```python
log.debug("cache lookup", key="user:42", hit=False)
```

```
 14:23:01.456 DEBUG  cache lookup  key='user:42' hit=False  cache.py:17
```

---

### `log.info(message, **kwargs)`

Log at INFO level. Equivalent to `log(message, **kwargs)`.

```python
log.info("request handled", method="GET", path="/users", status=200)
```

```
 14:23:01.789 INFO   request handled  method='GET' path='/users' status=200  api.py:42
```

---

### `log.warn(message, **kwargs)`

Log at WARNING level. Alias: `log.warning()`.

```python
log.warn("rate limit approaching", current=980, limit=1000)
```

```
 14:23:02.012 WARN   rate limit approaching  current=980 limit=1000  limiter.py:23
```

---

### `log.error(message, **kwargs)`

Log at ERROR level.

```python
log.error("connection failed", host="db.internal", retries=3)
```

```
 14:23:02.345 ERROR  connection failed  host='db.internal' retries=3  db.py:91
```

---

### `log.exception(message, **kwargs)`

Log at ERROR level with the current exception's traceback. Call inside an `except` block. Adds `error_type`, `error_message`, and `error_stacktrace` to the record's `data`.

```python
try:
    result = db.execute("SELECT * FROM orders WHERE id = %s", order_id)
except DatabaseError:
    log.exception("query failed", table="orders", order_id=order_id)
```

```
 14:23:03.456 ERROR  query failed  table='orders' order_id=42
                     error_type='DatabaseError' error_message='connection reset'
                     error_stacktrace='Traceback ...'  db.py:55
```

---

## Context

### `log.context(**kwargs)`

Add key-value pairs to all logs within a scope. Uses `contextvars` — works with async, no thread-local hacks.

```python
with log.context(request_id="abc-123", user_id=42):
    log("validating input")
    log("saving to database")
log("outside context")
```

```
 14:23:04.000 INFO   validating input  request_id='abc-123' user_id=42  handler.py:10
 14:23:04.010 INFO   saving to database  request_id='abc-123' user_id=42  handler.py:11
 14:23:04.020 INFO   outside context  handler.py:12
```

Also works with `async with`:

```python
async with log.context(request_id="abc-123"):
    await do_work()
```

---

### `log.bind(**kwargs)`

Return a new logger with permanent context attached. Chainable.

```python
db = log.bind(component="database")
cache = log.bind(component="cache")

db("query executed", table="users", rows=42)
cache("hit", key="user:42")
```

```
 14:23:05.000 INFO   query executed  component='database' table='users' rows=42  db.py:8
 14:23:05.001 INFO   hit  component='cache' key='user:42'  cache.py:12
```

Chaining:

```python
db = log.bind(component="database")
primary = db.bind(host="primary.db")
replica = db.bind(host="replica.db")

primary("connected")
replica("connected")
```

```
 14:23:05.100 INFO   connected  component='database' host='primary.db'  db.py:5
 14:23:05.101 INFO   connected  component='database' host='replica.db'  db.py:6
```

---

## Tracing

### `trace(name, **kwargs)`

Create a trace span. Measures duration and forms a tree. Returns a `SpanData` on enter.

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

Access span data inside:

```python
with trace("process", order_id=42) as span:
    print(span.trace_id)   # "4bf92f3577b34da6a3ce929d0e0e4736"
    print(span.span_id)    # "00f067aa0ba902b7"
```

---

### `@trace`

Decorator — wraps a function in a span. Auto-captures arguments as span attributes (`self`/`cls` excluded).

```python
@trace
def fetch_user(user_id: int, include_profile: bool = False):
    return db.get_user(user_id)

fetch_user(42, include_profile=True)
```

```
fetch_user  12.3ms  user_id=42 include_profile=True
```

Works with async:

```python
@trace
async def fetch_data(source: str):
    return await client.get(source)
```

---

### `@trace(**kwargs)`

Decorator factory — adds extra span attributes beyond the function's arguments.

```python
@trace(version="2.0", tier="critical")
def process_payment(amount: float):
    ...

process_payment(99.99)
```

```
process_payment  50.1ms  version='2.0' tier='critical' amount=99.99
```

---

### Log-Trace Correlation

Logs inside a span automatically get `trace_id` and `span_id`. No wiring needed.

```python
@trace
def handle_order(order_id: int):
    log("fetching user")
    log("charging payment", amount=99.99)

handle_order(42)
```

```
 14:23:06.000 INFO   fetching user  handle_order.py:3
 14:23:06.010 INFO   charging payment  amount=99.99  handle_order.py:4
handle_order  20.5ms  order_id=42
```

In JSON mode, `trace_id` and `span_id` appear in every log line:

```json
{"ts":"...","level":"info","msg":"fetching user","trace_id":"4bf92f...","span_id":"00f067..."}
```

---

### `trace.inject(headers=None)`

Inject a W3C `traceparent` header from the current span context. For outgoing HTTP calls.

```python
with trace("call downstream"):
    headers = trace.inject()
    response = httpx.get("http://service-b/api", headers=headers)
```

```python
# headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
```

Returns the dict unchanged if no active span.

---

### `trace.extract(headers)`

Extract W3C trace context from incoming HTTP headers. Returns `TraceContext` or `None`.

```python
context = trace.extract(request.headers)

if context:
    print(context.trace_id)     # "4bf92f3577b34da6a3ce929d0e0e4736"
    print(context.parent_id)    # "00f067aa0ba902b7"
    print(context.trace_flags)  # "01"
```

Case-insensitive header lookup. The ASGI middleware does this automatically.

---

## Exception Handling

### `@log.catch`

Decorator — catches exceptions, logs them at ERROR with a rich traceback, then re-raises.

```python
@log.catch
def process_payment(order_id: int, amount: float):
    balance = get_balance(order_id)
    charge(balance, amount)

process_payment(42, 99.99)  # raises InsufficientFunds
```

```
 14:23:07.000 ERROR  InsufficientFunds: 12.50 < 99.99  payments.py:8

 ╭── InsufficientFunds ──────────────────────────────────────╮
 │  billing.py:17 in charge                                  │
 │    balance = 12.50                                        │
 │    amount  = 99.99                                        │
 │                                                           │
 │  InsufficientFunds: 12.50 < 99.99                         │
 ╰───────────────────────────────────────────────────────────╯
```

---

### `@log.catch(reraise=False)`

Same, but suppresses the exception. Function returns `None` on failure.

```python
@log.catch(reraise=False)
def send_notification(user_id: int):
    email_service.send(user_id)  # may fail, but we don't want to crash

send_notification(42)  # logged but not raised — returns None
```

Works with async functions. Preserves `__name__`, `__doc__`, and `__wrapped__`.

---

## Timing

### `log.time(name, **kwargs)`

Context manager — measures and logs execution duration at INFO level.

```python
with log.time("db query", table="users"):
    rows = db.fetch_all()
```

```
 14:23:08.000 INFO   db query  duration_ms=42.1 table='users'  query.py:5
```

---

### `@log.time`

Decorator — uses the function's qualname as the timing label.

```python
@log.time
def process_batch():
    for item in items:
        process(item)

process_batch()
```

```
 14:23:09.000 INFO   process_batch  duration_ms=1234.5  batch.py:7
```

---

### `@log.time("custom name")`

Named decorator — override the timing label.

```python
@log.time("payment processing")
def handle_charge(amount: float):
    gateway.charge(amount)

handle_charge(99.99)
```

```
 14:23:10.000 INFO   payment processing  duration_ms=502.3  payments.py:12
```

All forms work with async functions.

---

## Rate Limiting

### `log.once(message, **kwargs)` / `log.once()`

Log only the first time. Subsequent calls with the same message are silently dropped.

```python
for i in range(1000):
    log.once("cache initialized")
```

```
 14:23:11.000 INFO   cache initialized  app.py:2
```

(Only one line, no matter how many times called.)

**Chaining** — call without a message to pick a severity level:

```python
log.once().warn("deprecated API called")
log.once().debug("one-time init details", backend="redis")
```

```
 14:23:11.100 WARN   deprecated API called  app.py:5
```

---

### `log.every(n, message, **kwargs)` / `log.every(n)`

Log every `n`th call from this specific call site (identified by file + line).

```python
for i in range(10000):
    log.every(1000, "processing", current=i)
```

```
 14:23:12.000 INFO   processing  current=0  worker.py:3
 14:23:12.500 INFO   processing  current=1000  worker.py:3
 14:23:13.000 INFO   processing  current=2000  worker.py:3
 ...
```

**Chaining:**

```python
for i in range(10000):
    log.every(1000).warn("slow query detected", iteration=i)
```

---

### `log.sample(rate, message, **kwargs)` / `log.sample(rate)`

Log with probability `rate` (0.0–1.0). Useful for high-frequency paths.

```python
for request in requests:
    log.sample(0.01, "request detail", method=request.method)
```

```
 14:23:14.123 INFO   request detail  method='GET'  server.py:8
 14:23:14.789 INFO   request detail  method='POST'  server.py:8
```

(~1% of calls produce output.)

**Chaining:**

```python
log.sample(0.01).debug("verbose trace", payload=data)
```

### Chaining pattern

All three rate-limiting methods support chaining for level control:

```python
# Direct form — always INFO
log.once("msg")
log.every(1000, "msg")
log.sample(0.01, "msg")

# Chained form — pick any level
log.once().warn("msg")
log.every(1000).debug("msg")
log.sample(0.01).error("msg")
```

The chained form returns a rate-limited logger that can also be stored and reused:

```python
sampled = log.sample(0.01)
for request in requests:
    sampled.debug("request detail", method=request.method)
```

---

## Metrics

### `log.count(name, value=1, **labels)`

Increment a counter metric.

```python
log.count("http.requests", method="GET", path="/users")
log.count("http.requests", method="POST", path="/orders")
log.count("http.requests", 5, method="GET", path="/health")  # increment by 5
```

```python
# Verify in tests:
from spektr import InMemoryMetrics

metrics = InMemoryMetrics()
print(metrics.get_counter("http.requests"))  # 7.0
```

---

### `log.gauge(name, value, **labels)`

Set a gauge to an absolute value.

```python
log.gauge("queue.depth", len(queue), queue="ingest")
log.gauge("connections.active", 42, pool="primary")
```

```python
metrics.get_gauge("queue.depth")         # current value
metrics.get_gauge("connections.active")  # 42.0
```

---

### `log.histogram(name, value, **labels)`

Record a histogram observation. Useful for latencies and sizes.

```python
log.histogram("request.duration_ms", 123.4, method="POST")
log.histogram("response.size_bytes", 4096, endpoint="/api/users")
```

```python
metrics.get_histogram("request.duration_ms")  # [123.4]
```

---

### `log.emit_metrics(message="metrics", *, include=None, prefix=None, **kwargs)`

Log current metric values as a single INFO record. Counters, gauges, and latest histogram values are included as structured data.

```python
log.count("http.requests", 150)
log.count("http.errors", 3)
log.gauge("queue.depth", 42)
log.histogram("latency_ms", 12.3)
log.histogram("latency_ms", 45.6)

log.emit_metrics()
```

```
 14:23:15.000 INFO   metrics  http.requests=150 http.errors=3 queue.depth=42 latency_ms=45.6  app.py:7
```

**Filter by prefix** — emit only metrics in a group:

```python
log.emit_metrics("http status", prefix="http")
```

```
 14:23:16.000 INFO   http status  http.requests=150 http.errors=3  monitor.py:3
```

**Filter by name** — emit specific metrics:

```python
log.emit_metrics(include=["queue.depth", "cpu.usage"])
```

```
 14:23:16.500 INFO   metrics  queue.depth=42 cpu.usage=0.75  monitor.py:5
```

**Combine** — `include` and `prefix` use OR logic:

```python
log.emit_metrics("status", include=["queue.depth"], prefix="http")
```

```
 14:23:17.000 INFO   status  http.requests=150 http.errors=3 queue.depth=42  monitor.py:7
```

**Extra kwargs and formatting:**

```python
log.emit_metrics("{http.errors} errors in the last hour", prefix="http", service="api")
```

```
 14:23:18.000 INFO   3 errors in the last hour  http.requests=150 http.errors=3 service='api'  monitor.py:9
```

---

### `log.progress(name, total=None, *, log_interval=1.0)`

Track progress of a batch operation. Returns a `ProgressTracker`.

```python
with log.progress("import users", total=10000) as p:
    for user in users:
        process(user)
        p.advance()
```

```
 14:23:15.000 INFO   import users  current=0 total=10000 percent=0.0 rate=0.0  import.py:1
 14:23:16.000 INFO   import users  current=3200 total=10000 percent=32.0 rate=3200.0  import.py:1
 14:23:17.000 INFO   import users  current=6800 total=10000 percent=68.0 rate=3600.0  import.py:1
 14:23:17.800 INFO   import users completed  current=10000 total=10000 percent=100.0 duration_ms=2800.0  import.py:1
```

When `tqdm` is installed and output is a TTY, automatically shows a tqdm progress bar instead:

```
import users: 100%|████████████████████████| 10000/10000 [00:02<00:00, 3571.43it/s]
 14:23:17.800 INFO   import users completed  current=10000 total=10000 percent=100.0 duration_ms=2800.0  import.py:1
```

**ProgressTracker methods:**

| Method | Description |
|---|---|
| `p.advance(n=1)` | Advance by `n` items |
| `p.set(current)` | Jump to absolute position |

Custom interval:

```python
with log.progress("export", total=50000, log_interval=5.0) as p:
    ...
```

Without `total` (unknown length):

```python
with log.progress("streaming") as p:
    for chunk in stream:
        process(chunk)
        p.advance()
```

```
 14:23:20.000 INFO   streaming  current=0  stream.py:1
 14:23:21.000 INFO   streaming  current=1500 rate=1500.0  stream.py:1
 14:23:22.000 INFO   streaming  current=3200 rate=1700.0  stream.py:1
 14:23:22.500 INFO   streaming completed  current=3200 duration_ms=2500.0  stream.py:1
```

Supports `async with`.

---

## Configuration

### `configure(**kwargs)`

Override auto-detected configuration at runtime. Unknown keys raise `ValueError`.

```python
import spektr
from spektr._types import LogLevel

spektr.configure(
    service="order-api",
    endpoint="http://collector:4318",
    min_level=LogLevel.WARNING,
    redact=["password", "secret", "token", "authorization"],
    health_path="/healthz",
)
```

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

Setting `endpoint` auto-switches to JSON mode unless `output_mode` is explicitly provided.

### Environment Variables

| Variable | Effect |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint, auto-switches to JSON mode |
| `SPEKTR_ENDPOINT` | Same (spektr-specific alias) |
| `SPEKTR_JSON=1` | Force JSON output without an endpoint |
| `NO_COLOR` | Respects [no-color.org](https://no-color.org) |
| `SPEKTR_LOG_LEVEL` | Minimum level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SPEKTR_SERVICE` | Service name for OTel resource |
| `OTEL_SERVICE_NAME` | Same (standard OTel env var) |

---

### Sensitive Data Redaction

Keys matching any redaction pattern are replaced with `***` in all output:

```python
log("auth attempt", password="secret123", api_key="sk-abc")
```

```
 14:23:21.000 INFO   auth attempt  password='***' api_key='***'  auth.py:5
```

Override patterns:

```python
spektr.configure(redact=["password", "secret", "ssn", "credit_card"])
```

---

## Global Setup

### `install(app=None)`

Install spektr globally. Idempotent — safe to call multiple times.

```python
import spektr
spektr.install()
```

What it sets up:
- `sys.excepthook` → rich tracebacks with local variables for uncaught exceptions
- `threading.excepthook` → same for exceptions in threads
- stdlib logging bridge → routes `logging.getLogger()` calls through spektr

With a web framework:

```python
from fastapi import FastAPI
import spektr

app = FastAPI()
spektr.install(app)  # also adds SpektrMiddleware automatically
```

**Uncaught exception output:**

```python
# Without install():
Traceback (most recent call last):
  File "app.py", line 5, in <module>
    process(data)
ValueError: invalid input

# With install():
 14:23:22.000 ERROR  ValueError: invalid input  app.py:5

 ╭── ValueError ─────────────────────────────────────────────╮
 │  app.py:5 in process                                      │
 │    data   = {'user_id': 42, 'action': 'delete'}           │
 │    status = 'pending'                                     │
 │                                                           │
 │  ValueError: invalid input                                │
 ╰───────────────────────────────────────────────────────────╯
```

**Stdlib bridge:**

```python
import logging

# Third-party libraries use stdlib logging
sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
sqlalchemy_logger.info("SELECT * FROM users")
```

```
 14:23:23.000 INFO   SELECT * FROM users  logger='sqlalchemy.engine'  connection.py:42
```

---

## ASGI Middleware

### `SpektrMiddleware`

HTTP request instrumentation for FastAPI / Starlette / any ASGI app.

```python
from spektr import SpektrMiddleware

app.add_middleware(SpektrMiddleware)
# or: app = SpektrMiddleware(app)
```

**What every request gets automatically:**

```python
# A single GET /users request produces:
```

```
 14:23:24.000 INFO   GET /users 200 12ms  request_id='a1b2c3d4'  server.py:15
```

Behind the scenes:
- Unique `request_id` (UUID4) added to log context
- Trace span covering the full request lifecycle
- W3C `traceparent` header extraction for distributed tracing
- `http.requests.total` counter and `http.request.duration_ms` histogram

**Error handling:**

```python
@app.get("/fail")
async def fail():
    raise ValueError("boom")
```

```
 14:23:25.000 ERROR  GET /fail 500 2ms  request_id='e5f6g7h8'  server.py:15
```

**Health check endpoint:**

```python
spektr.configure(health_path="/healthz")
# GET /healthz → 200 {"status": "ok", "service": "order-api"}
```

---

## Testing

### `capture()`

Context manager — intercepts log records without producing any output. The primary testing tool.

```python
from spektr import capture, log

def test_order_created():
    with capture() as logs:
        log("order created", order_id=42, amount=99.99)

    assert len(logs) == 1
    assert logs[0].message == "order created"
    assert logs[0].data["order_id"] == 42
    assert logs[0].data["amount"] == 99.99
```

**Substring search:**

```python
with capture() as logs:
    log("order created", order_id=42)
    log("payment processed")

assert "order created" in logs   # True — searches all messages
assert "not found" not in logs   # True — no match
```

**Filtering:**

```python
from spektr._types import LogLevel

with capture() as logs:
    log.debug("verbose detail")
    log.info("normal info")
    log.error("something broke", code=500)

errors = logs.filter(level=LogLevel.ERROR)
assert len(errors) == 1
assert errors[0].data["code"] == 500

by_code = logs.filter(code=500)
assert len(by_code) == 1
```

**All messages:**

```python
with capture() as logs:
    log("first")
    log("second")
    log("third")

assert logs.messages == ["first", "second", "third"]
```

**CapturedLogs interface:**

| Operation | Description |
|---|---|
| `len(logs)` | Number of captured records |
| `logs[0]` | Access by index |
| `"text" in logs` | True if any message contains the substring |
| `for record in logs` | Iterate over records |
| `logs.filter(level=..., **kwargs)` | Filter by level and/or data/context fields |
| `logs.messages` | List of all message strings |

---

## Pluggable Architecture

### Custom Sinks

Implement the `Sink` protocol to route logs to any destination.

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

Multiple sinks:

```python
configure(sinks=[DatadogSink(), PagerDutySink(), FileSink("/var/log/app.jsonl")])
```

When `capture()` is active, it intercepts records before they reach sinks.

**Protocol:**

```python
class Sink(Protocol):
    def write(self, record: LogRecord) -> None: ...
    def flush(self) -> None: ...
```

---

### Custom Samplers

Implement the `Sampler` protocol to control which logs are emitted.

```python
from spektr import configure, RateLimitSampler
from spektr._types import LogLevel

class WarningAndAbove:
    def should_emit(self, level, message):
        return level >= LogLevel.WARNING

configure(sampler=WarningAndAbove())
```

```python
log.debug("dropped")     # sampled out
log.info("dropped")      # sampled out
log.warn("emitted")      # passes
log.error("emitted")     # passes
```

**Protocol:**

```python
class Sampler(Protocol):
    def should_emit(self, level: int, message: str) -> bool: ...
```

---

### `RateLimitSampler(per_second)`

Token-bucket sampler. Limits log throughput. ERROR always passes.

```python
from spektr import configure, RateLimitSampler

configure(sampler=RateLimitSampler(per_second=100))
```

```python
# Up to 100 log calls per second pass through.
# ERROR-level messages always pass regardless of the rate limit.
for i in range(10000):
    log("high volume", i=i)         # rate-limited
    log.error("always passes")      # never dropped
```

---

### `CompositeSampler(*samplers)`

Chain multiple samplers. A record passes only if every sampler returns `True`.

```python
from spektr import configure, CompositeSampler, RateLimitSampler
from spektr._types import LogLevel

class ProductionFilter:
    def should_emit(self, level, message):
        return level >= LogLevel.WARNING

configure(sampler=CompositeSampler(
    ProductionFilter(),
    RateLimitSampler(per_second=50),
))
```

---

### `InMemoryMetrics`

Thread-safe in-memory metrics store. Default backend for `log.count()`, `log.gauge()`, `log.histogram()`.

```python
from spektr import InMemoryMetrics

metrics = InMemoryMetrics()

# After some log.count/gauge/histogram calls:
metrics.get_counter("http.requests")           # 42.0
metrics.get_gauge("queue.depth")               # 15.0
metrics.get_histogram("request.duration_ms")   # [12.3, 45.6, 78.9]

metrics.reset()  # Clear all metrics (useful between tests)
```

---

## Output Modes

### Rich (Dev)

Default when outputting to a terminal. Colored, human-readable.

```python
log("order created", order_id=42, amount=99.99)
```

```
 14:23:01.123 INFO   order created  order_id=42 amount=99.99  orders.py:5
```

```
 ↑ timestamp    ↑ level  ↑ message       ↑ structured data       ↑ source
```

### JSON (Prod)

Auto-enabled when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, or forced with `SPEKTR_JSON=1`.

```python
log("order created", order_id=42, amount=99.99)
```

```json
{"ts":"2026-03-22T14:23:01+00:00","level":"info","msg":"order created","order_id":42,"amount":99.99,"source":"orders.py:5"}
```

With trace context:

```json
{"ts":"...","level":"info","msg":"order created","order_id":42,"trace_id":"4bf92f35...","span_id":"00f067aa...","source":"orders.py:5"}
```

Trace spans in JSON:

```json
{"name":"handle_request","span_id":"00f067aa...","trace_id":"4bf92f35...","duration_ms":45.2,"status":"ok","attributes":{"method":"GET","path":"/users"}}
```

---

## Data Types

### `LogLevel`

```python
from spektr._types import LogLevel

LogLevel.DEBUG    # 10
LogLevel.INFO     # 20
LogLevel.WARNING  # 30
LogLevel.ERROR    # 40
```

### `LogRecord`

Each captured record (via `capture()`) has these fields:

```python
record = logs[0]

record.timestamp    # float — Unix timestamp
record.level        # LogLevel — DEBUG, INFO, WARNING, ERROR
record.message      # str — the log message
record.data         # dict — structured kwargs from the log call
record.context      # dict — context from log.context() / log.bind()
record.source       # SourceLocation | None — file, line, function
record.trace_id     # str | None — OTel trace ID if inside a span
record.span_id      # str | None — OTel span ID if inside a span
record.exc_info     # tuple | None — (type, value, traceback) if exception
```

### `SpanData`

Returned by `trace()` context manager on enter:

```python
with trace("db.query", table="users") as span:
    span.name          # "db.query"
    span.span_id       # "00f067aa0ba902b7"
    span.trace_id      # "4bf92f3577b34da6a3ce929d0e0e4736"
    span.parent_id     # str | None — parent span ID
    span.start_time    # float — perf_counter timestamp
    span.data          # {"table": "users"}
    span.children      # list[SpanData] — child spans
    span.end_time      # float | None — set on exit
    span.status        # "ok" or "error"
    span.error         # BaseException | None
    span.duration_ms   # float | None — computed on exit
```

### `SourceLocation`

```python
record.source.file      # "orders.py"
record.source.line      # 42
record.source.function  # "create_order"
```

### `TraceContext`

Returned by `trace.extract()`:

```python
context = trace.extract(headers)

context.trace_id      # "4bf92f3577b34da6a3ce929d0e0e4736" (32 hex)
context.parent_id     # "00f067aa0ba902b7" (16 hex)
context.trace_flags   # "01" (sampled) or "00"
```

### `MetricBackend`

Protocol for custom metric backends:

```python
class MetricBackend(Protocol):
    def counter(self, name: str, value: float, labels: dict[str, str]) -> None: ...
    def gauge(self, name: str, value: float, labels: dict[str, str]) -> None: ...
    def histogram(self, name: str, value: float, labels: dict[str, str]) -> None: ...
```
