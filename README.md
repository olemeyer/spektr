# spektr

Zero-config Python observability. Logging, tracing, and error tracking — unified in one library.

```bash
pip install spektr
```

## Why spektr?

Python's observability story is fragmented. You need **loguru** for logging, **structlog** for structured output, **OpenTelemetry** for tracing, **Sentry** for errors — four libraries, four configs, four APIs. None of them talk to each other.

**spektr unifies all of them into one library with zero config.**

## Quick Start

```python
from spektr import log

log("server started", port=8080)
```

That's it. No `getLogger()`, no handlers, no formatters. Rich console output with timestamps, structured data, and source locations — out of the box.

## Logging

```python
from spektr import log

# log() defaults to INFO — the level you use 90% of the time
log("order created", order_id=42, amount=99.99)

# Other levels when you need them
log.debug("loading config", path="/etc/app.yaml")
log.warn("disk almost full", used_pct=92)
log.error("connection refused", host="db.internal")
```

Output:

```
 14:23:01.123 INFO   order created  order_id=42 amount=99.99     api.py:12
 14:23:01.124 DEBUG  loading config  path=/etc/app.yaml           api.py:13
 14:23:01.125 WARN   disk almost full  used_pct=92                api.py:14
 14:23:01.126 ERROR  connection refused  host=db.internal          api.py:15
```

## Context

Context flows through your code — across function calls, async boundaries, and threads.

```python
from spektr import log

with log.context(request_id="abc-123", user_id=42):
    log("processing")          # → has request_id + user_id
    await do_something()       # → still has them in async
    log("done")                # → still has them
```

Create permanent loggers with `bind()`:

```python
db = log.bind(component="database", host="db.prod")
db("query", table="users", rows=42)
# → 14:23:01 query  component=database host=db.prod table=users rows=42
```

## Tracing

See your entire request flow — directly in your terminal.

```python
from spektr import trace

@trace
def handle_order(order_id: int):
    user = fetch_user(user_id=order_id)    # child span
    charge_payment(amount=99.99)           # child span
    send_email(to="user@test.com")         # child span
```

Output:

```
handle_order  86.5ms  order_id=42
├── fetch_user  10.1ms  user_id=42
├── charge_payment  50.1ms  amount=99.99
└── send_email  20.1ms  to=user@test.com
```

Works as a decorator (auto-captures function arguments) or context manager:

```python
with trace("db.query", table="users"):
    result = db.execute("SELECT * FROM users")
```

## Exceptions

See **local variables** at the point of failure — no more guessing.

```python
from spektr import log

@log.catch
def process_payment(order_id: int, amount: float):
    balance = get_balance(order_id)
    charge(balance, amount)
```

When it crashes:

```
 14:23:05 ERROR  InsufficientFunds: 12.50 < 99.99          api.py:5

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
spektr.install()
```

## Logs + Traces = One Stream

Logs inside spans are automatically correlated. Every log gets `trace_id` and `span_id`.

```python
@trace
async def handle_order(order_id: int):
    log("fetching user")
    user = await fetch_user(order_id)
    log("charging", amount=99.99)
    await charge(user, 99.99)
```

## Production

In dev, spektr outputs rich console formatting. In production, set one environment variable and it switches to structured JSON with OpenTelemetry trace correlation:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py
```

Or configure in code:

```python
import spektr

spektr.configure(
    service="order-api",
    endpoint="http://collector:4318",
)
```

JSON output:

```json
{"ts":"2026-03-22T14:23:01Z","level":"info","msg":"order created","order_id":42,"trace_id":"a1b2c3","span_id":"d4e5f6"}
```

## Testing

```python
from spektr import capture, log

def test_order_logging():
    with capture() as logs:
        create_order(42)

    assert "order created" in logs
    assert logs[0].data["order_id"] == 42
    assert logs[0].trace_id is not None
```

## Complete API

```python
import spektr
from spektr import log, trace, capture

# Setup (optional)
spektr.install()                              # rich exception handler
spektr.configure(service="my-app")            # production config

# Logging
log("message", key=value)                     # info (default)
log.debug("msg", key=value)                   # debug
log.warn("msg", key=value)                    # warning
log.error("msg", key=value)                   # error
log.exception("msg")                          # error + traceback

# Context
with log.context(request_id="abc"): ...       # scoped context
bound = log.bind(component="db")              # permanent context

# Exceptions
@log.catch                                    # catch + log + reraise
@log.catch(reraise=False)                     # catch + log + suppress

# Tracing
with trace("name", key=value): ...            # span context manager
@trace                                        # span decorator (auto args)

# Testing
with capture() as logs: ...                   # capture logs for assertions
```

**10 concepts. That's the entire library.**

## Comparison

| | stdlib logging | loguru | structlog | OpenTelemetry | **spektr** |
|---|---|---|---|---|---|
| Zero config | No | Yes | No | No | **Yes** |
| Structured data | No | Partial | Yes | Yes | **Yes** |
| Tracing | No | No | No | Yes | **Yes** |
| Error tracking | No | Partial | No | No | **Yes** |
| Local variables | No | Yes | No | No | **Yes** |
| Trace correlation | No | No | No | Yes | **Yes** |
| Console output | Basic | Good | Good | None | **Beautiful** |
| Lines to set up | 10+ | 1 | 5+ | 30+ | **0** |

## Requirements

- Python 3.10+
- Dependencies: `rich`, `opentelemetry-api`, `opentelemetry-sdk`
- Optional: `pip install spektr[otlp]` for OTLP export to collectors

## License

MIT
