<p align="center">
  <a href="https://github.com/olemeyer/spektr">
    <img src="docs/assets/logo.svg" alt="spektr" width="380">
  </a>
</p>

<p align="center">
  <em>Logging, tracing, and error tracking — unified. Zero config.</em>
</p>

<p align="center">
  <a href="https://github.com/olemeyer/spektr/actions"><img src="https://img.shields.io/github/actions/workflow/status/olemeyer/spektr/ci.yml?branch=main&style=flat-square&logo=github&label=CI" alt="CI"></a>
  <a href="https://pypi.org/project/spektr/"><img src="https://img.shields.io/pypi/v/spektr?style=flat-square&color=7C6CF0" alt="PyPI"></a>
  <a href="https://pypi.org/project/spektr/"><img src="https://img.shields.io/pypi/pyversions/spektr?style=flat-square" alt="Python"></a>
  <a href="https://github.com/olemeyer/spektr/blob/main/LICENSE"><img src="https://img.shields.io/github/license/olemeyer/spektr?style=flat-square" alt="License"></a>
</p>

---

<p align="center">
  <strong><a href="#quick-start">Quick Start</a></strong> &nbsp;|&nbsp;
  <strong><a href="docs/guide.md">Guide</a></strong> &nbsp;|&nbsp;
  <strong><a href="docs/api.md">API Reference</a></strong> &nbsp;|&nbsp;
  <strong><a href="https://github.com/olemeyer/spektr">Source</a></strong>
</p>

---

Python's observability story is fragmented. You need **loguru** for logging, **structlog** for structured output, **OpenTelemetry** for tracing, **Sentry** for errors — four libraries, four configs, four APIs that don't talk to each other.

**spektr replaces all of them with a single import.**

```bash
pip install spektr
```

## Quick Start

```python
from spektr import log

log("server started", port=8080)
```

No `getLogger()`. No handlers. No formatters. Colored console output with timestamps, structured data, and source locations — out of the box.

## Features

<details open>
<summary><strong>Structured Logging</strong></summary>

<br>

```python
from spektr import log

log("order created", order_id=42, amount=99.99)
log.debug("cache miss", key="user:42")
log.warn("disk almost full", used_pct=92)
log.error("connection refused", host="db.internal")
```

```
 14:23:01.123 INFO   order created  order_id=42 amount=99.99     orders.py:5
 14:23:01.124 DEBUG  cache miss  key='user:42'                   cache.py:18
 14:23:01.125 WARN   disk almost full  used_pct=92               health.py:7
 14:23:01.126 ERROR  connection refused  host='db.internal'      db.py:31
```

</details>

<details>
<summary><strong>Distributed Tracing</strong></summary>

<br>

See your entire request flow as a tree — directly in the terminal.

```python
from spektr import trace

@trace
def handle_order(order_id: int):
    fetch_user(user_id=order_id)      # also @trace decorated
    charge_payment(amount=99.99)      # also @trace decorated
    send_confirmation(to="ole@pm.me") # also @trace decorated
```

```
handle_order  86.5ms  order_id=42
├── fetch_user  10.1ms  user_id=42
├── charge_payment  50.1ms  amount=99.99
└── send_confirmation  20.1ms  to='ole@pm.me'
```

Works as a decorator or context manager:

```python
@trace                                    # auto-captures function arguments
def process(item_id: int): ...

with trace("db.query", table="users"):    # explicit name + attributes
    result = db.execute("SELECT * FROM users")
```

</details>

<details>
<summary><strong>Context Propagation</strong></summary>

<br>

Context flows across function calls and async boundaries via `contextvars`.

```python
with log.context(request_id="abc-123", user_id=42):
    log("processing")          # has request_id + user_id
    do_something()             # called functions see the same context
    log("done")                # still has them
```

Create permanent loggers with `bind()`:

```python
db = log.bind(component="database", host="db.prod")
db("query executed", table="users", rows=42)
# 14:23:01.456 INFO  query executed  component='database' host='db.prod' table='users' rows=42
```

</details>

<details>
<summary><strong>Exception Tracking</strong></summary>

<br>

Rich tracebacks with **local variables** at the point of failure.

```python
from spektr import log

@log.catch
def process_payment(order_id: int, amount: float):
    balance = get_balance(order_id)
    charge(balance, amount)
```

When it crashes, you see the local state:

```
 14:23:05 ERROR  InsufficientFunds: 12.50 < 99.99          payments.py:8

 ╭── InsufficientFunds ──────────────────────────────────────╮
 │  billing.py:17 in charge                                  │
 │    balance = 12.50                                        │
 │    amount  = 99.99                                        │
 │                                                           │
 │  InsufficientFunds: 12.50 < 99.99                         │
 ╰───────────────────────────────────────────────────────────╯
```

Install globally to catch all uncaught exceptions:

```python
import spektr
spektr.install()  # sets sys.excepthook + threading.excepthook
```

</details>

<details>
<summary><strong>Timing &amp; Metrics</strong></summary>

<br>

```python
# Measure duration — context manager or decorator
with log.time("db query", table="users"):
    rows = db.fetch_all()
# logs: "db query"  duration_ms=42.1  table='users'

@log.time
def process_batch():
    ...

# Counters, gauges, histograms
log.count("http.requests", method="GET", path="/users")
log.gauge("queue.depth", 42, queue="ingest")
log.histogram("request.duration_ms", 123.4, method="POST")

# Progress tracking for batch operations
with log.progress("import users", total=10000) as p:
    for user in users:
        process(user)
        p.advance()
```

</details>

<details>
<summary><strong>Rate Limiting</strong></summary>

<br>

Control log volume in hot paths:

```python
log.once("cache initialized")         # only the first time ever
log.every(1000, "heartbeat")          # every 1000th call from this site
log.sample(0.01, "detailed trace")    # 1% of calls (probabilistic)
```

</details>

<details>
<summary><strong>ASGI Middleware</strong></summary>

<br>

Auto-instrument HTTP requests with one line:

```python
from spektr import SpektrMiddleware

app.add_middleware(SpektrMiddleware)  # FastAPI / Starlette / Litestar
```

Every request automatically gets:

- Unique `request_id` in the log context
- Trace span covering the full request lifecycle
- W3C `traceparent` header extraction for distributed tracing
- Completion log with method, path, status code, and duration
- `http.requests.total` counter and `http.request.duration_ms` histogram

</details>

<details>
<summary><strong>Production Mode</strong></summary>

<br>

In development, spektr outputs colored console formatting. In production, set one environment variable and it switches to structured JSON:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py
```

```json
{"ts":"2026-03-22T14:23:01+00:00","level":"info","msg":"order created","order_id":42,"trace_id":"4bf92f3577b34da6a3ce929d0e0e4736","span_id":"00f067aa0ba902b7"}
```

Or configure in code:

```python
import spektr
spektr.configure(service="order-api", endpoint="http://collector:4318")
```

</details>

<details>
<summary><strong>Testing</strong></summary>

<br>

```python
from spektr import capture, log

def test_order_logging():
    with capture() as logs:
        create_order(42)

    assert len(logs) == 1
    assert logs[0].message == "order created"
    assert logs[0].data["order_id"] == 42
    assert "order created" in logs          # substring search
```

No mocks. No patches. Just capture and assert.

</details>

## Log + Trace Correlation

Logs inside spans are automatically correlated. Every log record gets `trace_id` and `span_id` — your log aggregator can join them with traces.

```python
from spektr import log, trace

@trace
def handle_order(order_id: int):
    log("fetching user")           # trace_id + span_id attached
    user = fetch_user(order_id)
    log("charging", amount=99.99)  # same trace, same span
    charge(user, 99.99)
```

## Pluggable Architecture

Every subsystem is replaceable via protocols:

```python
from spektr import configure, RateLimitSampler

# Custom sink — send logs anywhere
class DatadogSink:
    def write(self, record): ...
    def flush(self): ...

configure(
    sinks=[DatadogSink()],
    sampler=RateLimitSampler(per_second=100),
)
```

See the [Guide](docs/guide.md#pluggable-architecture) for details on `Sink`, `Sampler`, and `MetricBackend` protocols.

## Complete API

```python
import spektr
from spektr import log, trace, capture

# Setup (optional — works without any config)
spektr.install()                              # rich exception hooks + stdlib bridge
spektr.configure(service="my-app")            # override auto-detected settings

# Logging
log("message", key="value")                   # INFO (default level)
log.debug("msg")                              # DEBUG
log.warn("msg")                               # WARNING
log.error("msg")                              # ERROR
log.exception("msg")                          # ERROR + current traceback

# Context
with log.context(request_id="abc"): ...       # scoped key-value context
bound = log.bind(component="db")              # permanent context on new logger

# Exceptions
@log.catch                                    # catch, log with traceback, re-raise
@log.catch(reraise=False)                     # catch, log, suppress (returns None)

# Tracing
with trace("name", key="value"): ...          # span as context manager
@trace                                        # span as decorator (auto-captures args)
headers = trace.inject()                      # W3C traceparent → outgoing headers
context = trace.extract(headers)              # incoming headers → TraceContext

# Timing & Metrics
with log.time("query"): ...                   # measure and log duration
log.count("requests", method="GET")           # increment counter
log.gauge("queue.depth", 42)                  # set gauge value
log.histogram("latency_ms", 123.4)            # record histogram observation

# Rate Limiting
log.once("startup complete")                  # log only the first time
log.every(1000, "heartbeat")                  # every Nth call from this site
log.sample(0.01, "verbose")                   # 1% probability

# Progress
with log.progress("import", total=N) as p:    # batch progress tracking
    p.advance()                                # advance by 1

# Testing
with capture() as logs: ...                   # intercept log records
```

## Comparison

| | stdlib | loguru | structlog | OpenTelemetry | **spektr** |
|---|---|---|---|---|---|
| Zero config | | Yes | | | **Yes** |
| Structured data | | Partial | Yes | Yes | **Yes** |
| Distributed tracing | | | | Yes | **Yes** |
| Error tracking | | Partial | | | **Yes** |
| Local variables in tracebacks | | Yes | | | **Yes** |
| Log ↔ trace correlation | | | | Manual | **Automatic** |
| Metrics (counters, histograms) | | | | Yes | **Yes** |
| W3C trace propagation | | | | Yes | **Yes** |
| ASGI middleware | | | | Community | **Built-in** |
| Console output quality | Basic | Good | Good | None | **Rich** |
| Lines of setup code | 10+ | 1 | 5+ | 30+ | **0** |

## Requirements

- Python 3.10+
- Dependencies: `rich`, `opentelemetry-api`, `opentelemetry-sdk`
- Optional: `pip install spektr[otlp]` for OTLP export to collectors

## License

MIT
