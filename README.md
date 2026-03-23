<p align="center">
  <a href="https://github.com/olemeyer/spektr">
    <img src="docs/assets/logo.svg" alt="spektr" width="380">
  </a>
</p>

<p align="center">
  <em>Observability that doesn't suck.</em>
</p>

<p align="center">
  <a href="https://github.com/olemeyer/spektr/actions"><img src="https://img.shields.io/github/actions/workflow/status/olemeyer/spektr/ci.yml?branch=main&style=flat-square&logo=github&label=CI" alt="CI"></a>
  <a href="https://pypi.org/project/spektr/"><img src="https://img.shields.io/pypi/v/spektr?style=flat-square&color=7C6CF0" alt="PyPI"></a>
  <a href="https://pypi.org/project/spektr/"><img src="https://img.shields.io/pypi/pyversions/spektr?style=flat-square" alt="Python"></a>
</p>

<p align="center">
  <a href="docs/guide.md">Guide</a> · <a href="docs/api.md">API Reference</a> · <a href="docs/architecture.md">Architecture</a>
</p>

---

Be honest — you've used `print()` for debugging because configuring Python's `logging` module felt like filing taxes. And when someone said "add tracing," you closed the browser tab.

**spektr is logging, tracing, and error tracking in a single import.** It replaces loguru, structlog, the OpenTelemetry SDK, and Sentry's error capture — with zero configuration.

```bash
pip install spektr
```

```python
from spektr import log

log("server started", port=8080, env="production")
```

```
 14:23:01.123 INFO  server started  port=8080 env='production'  main.py:3
```

That's it. No `getLogger()`. No handlers. No YAML files. Structured data, colors, source locations — out of the box.

---

## Tracing

Add `@trace` to see where time goes:

```python
from spektr import trace

@trace
def handle_order(order_id: int):
    user = fetch_user(user_id=order_id)       # also @trace
    charge_payment(amount=99.99)              # also @trace
    send_confirmation(to="ole@test.com")      # also @trace
```

```
handle_order  86.5ms  order_id=42
├── fetch_user  10.1ms  user_id=42
├── charge_payment  50.1ms  amount=99.99
└── send_confirmation  20.1ms  to='ole@test.com'
```

Logs inside spans automatically get `trace_id` and `span_id` — no wiring needed:

```python
@trace
def handle_order(order_id: int):
    log("fetching user")           # trace_id + span_id attached
    user = fetch_user(order_id)
    log("charging", amount=99.99)  # same trace
```

**Here's the thing — those are real OpenTelemetry spans.** spektr uses OTel as its tracing backbone, so every `@trace` creates a proper OTel span with W3C context propagation. You just don't have to think about it.

Point it at a collector and your traces show up in Jaeger, Grafana Tempo, or Datadog — without changing a single line of application code:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py
```

---

## Exception Tracking

Rich tracebacks with **local variables** at the point of failure:

```python
@log.catch
def process_payment(order_id: int, amount: float):
    balance = get_balance(order_id)
    charge(balance, amount)
```

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

No more staring at a naked traceback wondering what `x` was.

---

## Context That Flows

Context propagates through function calls and async boundaries — no thread-local hacks:

```python
with log.context(request_id="abc-123", user_id=42):
    log("processing")       # has request_id + user_id
    do_something()          # called functions inherit the context
    log("done")             # still has them
```

---

## FastAPI / Starlette

One line to instrument every HTTP request:

```python
import spektr

app = FastAPI()
spektr.install(app)
```

Every request automatically gets a unique `request_id`, a trace span, W3C context extraction, completion logging with status and duration, and request metrics. Also installs rich exception hooks and routes stdlib logging (uvicorn, SQLAlchemy, etc.) through spektr.

---

## Production

In dev you get colored console output. Set one env var and it switches to structured JSON with full OTel export:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py
```

```json
{"ts":"2026-03-22T14:23:01+00:00","level":"info","msg":"order created","order_id":42,"trace_id":"4bf92f3577b34da6a3ce929d0e0e4736","span_id":"00f067aa0ba902b7"}
```

Your existing Grafana dashboards, Jaeger UI, and Datadog APM just work — because it's standard OpenTelemetry under the hood.

---

## Everything Else

```python
# Timing
with log.time("db query"):              # logs duration_ms automatically
    rows = db.fetch_all()

# Rate limiting
log.once("cache ready")                 # first time only
log.every(1000, "heartbeat")            # every Nth call
log.sample(0.01, "verbose")             # 1% probability

# Metrics
log.count("http.requests", method="GET")
log.gauge("queue.depth", 42)
log.histogram("latency_ms", 123.4)

# Progress tracking (uses tqdm when available)
with log.progress("import", total=10000) as p:
    for item in items:
        process(item)
        p.advance()

# Bound loggers
db = log.bind(component="database")
db("query executed", table="users")     # component always attached

# W3C trace propagation
headers = trace.inject()                # outgoing
context = trace.extract(headers)        # incoming

# Testing — no mocks needed
with capture() as logs:
    create_order(42)
assert logs[0].message == "order created"

# Custom sinks and samplers
configure(
    sinks=[DatadogSink()],
    sampler=RateLimitSampler(per_second=100),
)
```

See the [Guide](docs/guide.md) for the full walkthrough and [API Reference](docs/api.md) for every method.

---

## Requirements

- Python 3.10+
- Dependencies: `rich`, `opentelemetry-api`, `opentelemetry-sdk`
- Optional: `pip install spektr[otlp]` for OTLP export, `spektr[tqdm]` for progress bars

## License

MIT
