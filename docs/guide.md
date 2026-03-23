# Guide

From zero to fully instrumented in 5 minutes. Every feature with example code and output.

---

## Install

```bash
pip install spektr
```

Optional extras:

```bash
pip install spektr[otlp]   # OTLP export (Dash0, Grafana Cloud, Datadog, Jaeger, etc.)
pip install spektr[tqdm]   # tqdm progress bars
```

---

## 1. Logging

### Your first log

```python
from spektr import log

log("server started", port=8080, env="production")
```

```
 14:23:01.123 INFO   server started  port=8080 env='production'  main.py:3
```

That's it. No `getLogger()`, no handlers, no YAML files.

### Message formatting

If the message contains `{placeholders}`, they are formatted with the kwargs:

```python
log("user {name} connected on port {port}", name="ole", port=8080)
```

```
 14:23:01.200 INFO   user ole connected on port 8080  name='ole' port=8080  main.py:4
```

Plain strings without `{}` are passed through unchanged. Missing keys don't crash — the message stays as-is.

### Levels

```python
log.debug("cache miss", key="user:42")
log.info("request handled", method="GET", status=200)
log.warn("disk usage high", percent=92.5)
log.error("connection lost", host="db.internal")
```

```
 14:23:01.100 DEBUG  cache miss  key='user:42'  cache.py:5
 14:23:01.200 INFO   request handled  method='GET' status=200  api.py:12
 14:23:01.300 WARN   disk usage high  percent=92.5  monitor.py:8
 14:23:01.400 ERROR  connection lost  host='db.internal'  db.py:23
```

`log("message")` is shorthand for `log.info("message")`.

### Exceptions

Inside an `except` block, `log.exception()` captures the full traceback:

```python
try:
    result = db.execute(query)
except DatabaseError:
    log.exception("query failed", table="orders")
```

```
 14:23:02.000 ERROR  query failed  table='orders'
                     error_type='DatabaseError' error_message='timeout'  db.py:55
```

The record's `data` dict contains `error_type`, `error_message`, and `error_stacktrace`.

---

## 2. Structured Context

### Scoped context

`log.context()` adds fields to every log within its scope — including logs from called functions:

```python
def handle_request(request):
    with log.context(request_id=request.id, user_id=request.user.id):
        log("validating")
        validate(request)          # logs inside here also get request_id
        log("saving")
        save(request)              # and here too
```

```
 14:23:03.000 INFO   validating  request_id='abc-123' user_id=42  handler.py:3
 14:23:03.010 INFO   saving  request_id='abc-123' user_id=42  handler.py:5
```

Uses `contextvars` — works correctly with `async`, no thread-local hacks:

```python
async with log.context(request_id="abc-123"):
    await do_async_work()
```

### Bound loggers

`log.bind()` returns a new logger with permanent fields:

```python
db = log.bind(component="database")
cache = log.bind(component="cache")

db("connected", host="primary.db")
cache("hit", key="user:42")
```

```
 14:23:04.000 INFO   connected  component='database' host='primary.db'  db.py:4
 14:23:04.001 INFO   hit  component='cache' key='user:42'  cache.py:5
```

Bound loggers are chainable:

```python
db = log.bind(component="database")
primary = db.bind(host="primary.db")
replica = db.bind(host="replica.db")
```

---

## 3. Tracing

### Spans as context manager

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

### Spans as decorator

`@trace` auto-captures the function's arguments:

```python
@trace
def fetch_user(user_id: int, include_profile: bool = False):
    return db.get_user(user_id)

fetch_user(42, include_profile=True)
```

```
fetch_user  12.3ms  user_id=42 include_profile=True
```

`self` and `cls` are automatically excluded.

### Nested trace tree

```python
@trace
def handle_order(order_id: int):
    user = fetch_user(user_id=order_id)
    charge_payment(amount=99.99)
    send_confirmation(to="ole@test.com")

handle_order(42)
```

```
handle_order  86.5ms  order_id=42
├── fetch_user  10.1ms  user_id=42
├── charge_payment  50.1ms  amount=99.99
└── send_confirmation  20.1ms  to='ole@test.com'
```

### Log-trace correlation

Logs inside a span automatically get `trace_id` and `span_id`:

```python
@trace
def handle_order(order_id: int):
    log("fetching user")           # trace_id + span_id attached
    user = fetch_user(order_id)
    log("charging", amount=99.99)  # same trace
```

In JSON mode these appear in every line — your log aggregator can join them with traces.

### It's real OpenTelemetry

Every `@trace` creates a real OTel span with W3C context propagation. Point it at any OTLP-compatible backend and traces show up — no code changes needed:

```bash
# Self-hosted (Jaeger, Grafana Tempo)
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py

# Dash0
OTEL_EXPORTER_OTLP_ENDPOINT=https://ingress.eu-west-1.aws.dash0.com \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <dash0-token>" \
python app.py

# Datadog (via OTel Collector or Datadog Agent)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python app.py

# Grafana Cloud
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-eu-west-0.grafana.net/otlp \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64-credentials>" \
python app.py
```

spektr uses the standard `OTLPSpanExporter` — any backend that speaks OTLP/HTTP works out of the box.

---

## 4. Distributed Tracing

### Inject context (outgoing)

```python
with trace("call downstream"):
    headers = trace.inject()
    response = httpx.get("http://service-b/api", headers=headers)
```

```python
# headers = {"traceparent": "00-4bf92f3577b34da6...-00f067aa...-01"}
```

### Extract context (incoming)

```python
context = trace.extract(request.headers)
if context:
    print(context.trace_id)     # "4bf92f3577b34da6a3ce929d0e0e4736"
    print(context.parent_id)    # "00f067aa0ba902b7"
```

The ASGI middleware does both automatically.

---

## 5. Exception Handling

### @log.catch

Wraps a function to catch, log with a rich traceback, and re-raise:

```python
@log.catch
def process_payment(order_id: int, amount: float):
    balance = get_balance(order_id)
    charge(balance, amount)

process_payment(42, 99.99)
```

```
 14:23:05.000 ERROR  InsufficientFunds: 12.50 < 99.99  payments.py:8

 ╭── InsufficientFunds ──────────────────────────────────────╮
 │  billing.py:17 in charge                                  │
 │    balance = 12.50                                        │
 │    amount  = 99.99                                        │
 │                                                           │
 │  InsufficientFunds: 12.50 < 99.99                         │
 ╰───────────────────────────────────────────────────────────╯
```

### Suppress exceptions

```python
@log.catch(reraise=False)
def send_notification(user_id: int):
    email_service.send(user_id)

result = send_notification(42)  # logged but not raised — returns None
```

### Global exception hooks

```python
import spektr
spektr.install()
```

Now every uncaught exception gets a rich traceback with local variables — in the main thread, in child threads, and in the ASGI error handler.

---

## 6. Timing

### Context manager

```python
with log.time("db query", table="users"):
    rows = db.fetch_all()
```

```
 14:23:06.000 INFO   db query  duration_ms=42.1 table='users'  query.py:3
```

### Decorator

```python
@log.time
def process_batch():
    ...
```

```
 14:23:07.000 INFO   process_batch  duration_ms=1234.5  batch.py:5
```

### Named decorator

```python
@log.time("payment processing")
def handle_charge(amount: float):
    ...
```

```
 14:23:08.000 INFO   payment processing  duration_ms=502.3  payments.py:8
```

All forms work with async.

---

## 7. Rate Limiting

### First occurrence only

```python
for i in range(1000):
    log.once("cache initialized")
```

```
 14:23:09.000 INFO   cache initialized  app.py:2
```

### Every Nth call

```python
for i in range(10000):
    log.every(1000, "processing", current=i)
```

```
 14:23:10.000 INFO   processing  current=0  worker.py:2
 14:23:10.500 INFO   processing  current=1000  worker.py:2
 14:23:11.000 INFO   processing  current=2000  worker.py:2
```

### Probabilistic sampling

```python
for request in requests:
    log.sample(0.01, "request detail", method=request.method)
```

~1% of calls produce output.

### Chaining for custom levels

Call without a message to chain a severity level:

```python
log.once().warn("deprecated API called")
log.every(1000).debug("heartbeat")
log.sample(0.01).debug("verbose trace", payload=data)
```

```
 14:23:11.000 WARN   deprecated API called  app.py:2
```

Store for reuse:

```python
sampled = log.sample(0.01)
for request in requests:
    sampled.debug("request detail", method=request.method)
```

---

## 8. Metrics

### Counters

```python
log.count("http.requests", method="GET", path="/users")
log.count("http.requests", method="POST", path="/orders")
```

### Gauges

```python
log.gauge("queue.depth", len(queue), queue="ingest")
log.gauge("connections.active", 42, pool="primary")
```

### Histograms

```python
log.histogram("request.duration_ms", 123.4, method="POST")
log.histogram("response.size_bytes", 4096, endpoint="/api/users")
```

### Logging metrics

Metrics are stored in-memory. To output them as a log line, use `emit_metrics()`:

```python
log.count("http.requests", 150)
log.count("http.errors", 3)
log.gauge("queue.depth", 42)

log.emit_metrics()
```

```
 14:23:12.500 INFO   metrics  http.requests=150 http.errors=3 queue.depth=42  app.py:5
```

Filter by group or specific names:

```python
log.emit_metrics("http status", prefix="http")          # only http.* metrics
log.emit_metrics(include=["queue.depth", "cpu.usage"])   # specific names
```

```
 14:23:13.000 INFO   http status  http.requests=150 http.errors=3  monitor.py:3
```

### Progress tracking

```python
with log.progress("import users", total=10000) as p:
    for user in users:
        process(user)
        p.advance()
```

```
 14:23:12.000 INFO   import users  current=0 total=10000 percent=0.0 rate=0.0  import.py:1
 14:23:13.000 INFO   import users  current=3200 total=10000 percent=32.0 rate=3200.0  import.py:1
 14:23:14.000 INFO   import users  current=6800 total=10000 percent=68.0 rate=3600.0  import.py:1
 14:23:14.800 INFO   import users completed  current=10000 total=10000 percent=100.0 duration_ms=2800.0  import.py:1
```

With `tqdm` installed (auto-detected):

```
import users: 100%|████████████████████████| 10000/10000 [00:02<00:00, 3571.43it/s]
 14:23:14.800 INFO   import users completed  current=10000 total=10000 percent=100.0 duration_ms=2800.0  import.py:1
```

---

## 9. FastAPI / Starlette

### One-line setup

```python
from fastapi import FastAPI
import spektr

app = FastAPI()
spektr.install(app)
```

Every request automatically gets:
- Unique `request_id` in all logs
- Trace span for the full request
- W3C context extraction from incoming headers
- Completion log with method, path, status, and duration
- `http.requests.total` counter and `http.request.duration_ms` histogram

```
 14:23:15.000 INFO   GET /users 200 12ms  request_id='a1b2c3d4'  server.py:15
 14:23:15.100 INFO   POST /orders 201 45ms  request_id='e5f6g7h8'  server.py:15
 14:23:15.200 ERROR  GET /fail 500 2ms  request_id='i9j0k1l2'  server.py:15
```

### Manual middleware

```python
from spektr import SpektrMiddleware

app.add_middleware(SpektrMiddleware)
# or: app = SpektrMiddleware(app)
```

### Health check

```python
spektr.configure(health_path="/healthz")
# GET /healthz → 200 {"status": "ok", "service": "order-api"}
```

### Stdlib bridge

Third-party libraries using `logging.getLogger()` (uvicorn, SQLAlchemy, httpx) automatically route through spektr after `install()`:

```python
import logging
logger = logging.getLogger("sqlalchemy.engine")
logger.info("SELECT * FROM users")
```

```
 14:23:16.000 INFO   SELECT * FROM users  logger='sqlalchemy.engine'  connection.py:42
```

---

## 10. Production

### Dev → Prod switch

In dev you get colored console output. Set the endpoint and it switches to structured JSON with full OTel export:

```bash
# Self-hosted collector
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py

# Managed backends (Dash0, Grafana Cloud, Honeycomb, etc.)
OTEL_EXPORTER_OTLP_ENDPOINT=https://ingress.eu-west-1.aws.dash0.com \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <token>" \
python app.py
```

```json
{"ts":"2026-03-22T14:23:01+00:00","level":"info","msg":"order created","order_id":42,"trace_id":"4bf92f35...","span_id":"00f067aa..."}
```

Works with any OTLP-compatible backend: Dash0, Grafana Cloud, Honeycomb, Datadog (via Agent), Jaeger, Grafana Tempo, SigNoz, Axiom, and more.

### Runtime configuration

```python
import spektr
from spektr import LogLevel

spektr.configure(
    service="order-api",
    endpoint="http://collector:4318",
    min_level=LogLevel.WARNING,
    redact=["password", "secret", "token"],
    health_path="/healthz",
)
```

### Custom sinks

Route logs to any destination:

```python
class DatadogSink:
    def write(self, record):
        datadog_client.log(record.message, level=record.level.name, **record.data)

    def flush(self):
        datadog_client.flush()

spektr.configure(sinks=[DatadogSink()])
```

### Sampling

Control log volume in production:

```python
from spektr import RateLimitSampler, CompositeSampler

spektr.configure(sampler=RateLimitSampler(per_second=100))

# Or chain samplers:
spektr.configure(sampler=CompositeSampler(
    WarningAndAbove(),
    RateLimitSampler(per_second=50),
))
```

### Redaction

Sensitive fields are automatically replaced with `***`:

```python
log("auth", password="secret123", api_key="sk-abc")
```

```
 14:23:17.000 INFO   auth  password='***' api_key='***'  auth.py:3
```

Default patterns: `password`, `secret`, `token`, `authorization`, `api_key`, `apikey`.

---

## 11. Testing

### capture()

Intercept log records without output. No mocks needed.

```python
from spektr import capture, log

def test_order_created():
    with capture() as logs:
        create_order(42)

    assert len(logs) == 1
    assert logs[0].message == "order created"
    assert logs[0].data["order_id"] == 42
```

### Substring search

```python
with capture() as logs:
    log("order created", order_id=42)

assert "order created" in logs
```

### Filtering

```python
from spektr import LogLevel

with capture() as logs:
    log.debug("verbose")
    log.error("critical", code=500)

errors = logs.filter(level=LogLevel.ERROR)
assert len(errors) == 1
```

### Trace correlation in tests

```python
from spektr import capture, log, trace

def test_trace_correlation():
    with capture() as logs:
        with trace("request"):
            log("inside span")

    assert logs[0].trace_id is not None
    assert logs[0].span_id is not None
```

---

## Next Steps

- [API Reference](api.md) — every method with signatures and parameter tables
- [Architecture](architecture.md) — internal design, data flow, dependency layers
