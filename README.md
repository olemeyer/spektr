<p align="center">
  <a href="https://github.com/olemeyer/spektr">
    <img src="https://raw.githubusercontent.com/olemeyer/spektr/main/docs/assets/logo.svg" alt="spektr" width="380">
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

Point it at any OTLP-compatible backend and your traces just show up — without changing a single line of application code:

```bash
# Self-hosted (Jaeger, Grafana Tempo)
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py

# Managed (Dash0, Grafana Cloud, Honeycomb, Datadog, etc.)
OTEL_EXPORTER_OTLP_ENDPOINT=https://ingress.eu-west-1.aws.dash0.com \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <token>" \
python app.py
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

In dev you get colored console output. Set the endpoint and it switches to structured JSON with full OTel export:

```bash
# Self-hosted collector
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318 python app.py

# Managed backend
OTEL_EXPORTER_OTLP_ENDPOINT=https://ingress.eu-west-1.aws.dash0.com \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <token>" \
python app.py
```

```json
{"ts":"2026-03-22T14:23:01+00:00","level":"info","msg":"order created","order_id":42,"trace_id":"4bf92f3577b34da6a3ce929d0e0e4736","span_id":"00f067aa0ba902b7"}
```

Works with any OTLP-compatible backend: Dash0, Grafana Cloud, Honeycomb, Datadog, Jaeger, Grafana Tempo, SigNoz, Axiom, and more.

---

## Everything Else

```python
log("user {name} signed up", name="ole", plan="pro")
# 14:23:01 INFO  user ole signed up  name='ole' plan='pro'

try:
    db.execute(query)
except DatabaseError:
    log.exception("query failed", table="orders")
# 14:23:02 ERROR  query failed  table='orders' error_type='DatabaseError' error_message='timeout'

with log.time("db query"):
    rows = db.fetch_all()
# 14:23:03 INFO  db query  duration_ms=42.1

log.once("cache ready")                 # only the first call emits
log.every(1000, "heartbeat")            # every 1000th call
log.sample(0.01, "verbose detail")      # ~1% probability
log.once().warn("deprecated API")       # chaining picks the level

log.count("http.requests", method="GET")
log.gauge("queue.depth", 42)
log.histogram("latency_ms", 123.4)
log.emit_metrics()
# 14:23:04 INFO  metrics  http.requests=1 queue.depth=42 latency_ms=123.4

with log.progress("importing", total=10000) as p:
    for item in items:
        process(item)
        p.advance()
# importing: 100%|████████████████████| 10000/10000 [00:02<00:00, 3571.43it/s]
# 14:23:07 INFO  importing completed  total=10000 duration_ms=2800.0

db = log.bind(component="database")
db("connected", host="primary.db")
# 14:23:08 INFO  connected  component='database' host='primary.db'

log("auth", password="secret123", api_key="sk-abc")
# 14:23:09 INFO  auth  password='***' api_key='***'

headers = trace.inject()                # {"traceparent": "00-4bf92f35...-01"}
context = trace.extract(headers)        # context.trace_id, context.parent_id

configure(health_path="/healthz")
# GET /healthz → 200 {"status": "ok", "service": "order-api"}

with capture() as logs:
    create_order(42)
assert logs[0].message == "order created"

configure(sampler=RateLimitSampler(per_second=100))
configure(sinks=[DatadogSink(), SlackAlertSink()])
```

See the [Guide](docs/guide.md) for the full walkthrough and [API Reference](docs/api.md) for every method.

---

## Requirements

- Python 3.10+
- Dependencies: `rich`, `opentelemetry-api`, `opentelemetry-sdk`
- Optional: `pip install spektr[otlp]` for OTLP export, `spektr[tqdm]` for progress bars

## License

MIT
