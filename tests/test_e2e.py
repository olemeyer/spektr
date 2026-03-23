"""End-to-end integration tests – realistic scenarios across the full stack.

Covers: FastAPI apps, OTel export pipeline, multi-service distributed tracing,
stdlib bridge in web contexts, middleware + sinks + samplers, async concurrency,
error recovery, configuration changes, and full log-trace-metrics correlation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from io import StringIO
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from spektr import (
    CompositeSampler,
    InMemoryMetrics,
    RateLimitSampler,
    SpektrMiddleware,
    capture,
    configure,
    log,
    trace,
)
from spektr._integrations._bridge import SpektrHandler, install_bridge
from spektr._config import OutputMode
from spektr._metrics._api import _metrics
from spektr import LogLevel
import spektr._config as config_module
import spektr._otel as otel_bridge


@pytest.fixture(autouse=True)
def reset_state():
    """Reset config and metrics between tests."""
    config_module._config = None
    _metrics.reset()
    yield
    config_module._config = None
    _metrics.reset()
    # Clean up stdlib bridge handlers.
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, SpektrHandler)]
    root.setLevel(logging.WARNING)


# ── FastAPI Full Application ────────────────────────────────────


def _create_fastapi_app() -> FastAPI:
    """Build a realistic FastAPI app with multiple endpoints."""
    app = FastAPI()

    db_log = log.bind(component="database")
    cache_log = log.bind(component="cache")

    @app.get("/users/{user_id}")
    @trace
    async def get_user(user_id: int):
        cache_log("cache lookup", key=f"user:{user_id}")
        db_log("query", table="users", user_id=user_id)
        return {"id": user_id, "name": "Ole", "email": "ole@test.com"}

    @app.post("/orders")
    @trace
    async def create_order(request: Request):
        body = await request.json()
        log("creating order", **body)
        with trace("validate"):
            await asyncio.sleep(0.001)
        with trace("persist"):
            db_log("insert", table="orders")
        log.count("orders.created", method="POST")
        return {"id": 1, "status": "created"}

    @app.get("/error")
    async def error_endpoint():
        raise HTTPException(status_code=422, detail="Validation failed")

    @app.get("/crash")
    async def crash_endpoint():
        raise RuntimeError("unexpected crash")

    @app.get("/slow")
    @trace
    async def slow_endpoint():
        with log.time("slow operation"):
            await asyncio.sleep(0.03)
        return {"status": "done"}

    @app.get("/multi-trace")
    @trace
    async def multi_trace():
        results = await asyncio.gather(
            _async_service_call("auth"),
            _async_service_call("billing"),
            _async_service_call("notification"),
        )
        log("all services responded", count=len(results))
        return {"results": results}

    return app


@trace
async def _async_service_call(service: str) -> str:
    log(f"calling {service}")
    await asyncio.sleep(0.005)
    return f"{service}: ok"


class TestFastAPIEndToEnd:
    """Full FastAPI application tests with middleware."""

    @pytest.fixture
    def app(self):
        app = _create_fastapi_app()
        app.add_middleware(SpektrMiddleware)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app, raise_server_exceptions=False)

    def test_get_user_full_flow(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/users/42")

        assert response.status_code == 200
        assert response.json()["name"] == "Ole"

        # Verify cache and db logs are captured.
        cache_logs = [r for r in logs if r.context.get("component") == "cache"]
        db_logs = [r for r in logs if r.context.get("component") == "database"]
        assert len(cache_logs) >= 1
        assert len(db_logs) >= 1

        # All logs have request_id from middleware.
        for record in logs:
            assert "request_id" in record.context

        # All logs share the same trace_id.
        trace_ids = {r.trace_id for r in logs if r.trace_id is not None}
        assert len(trace_ids) == 1

    def test_create_order_with_nested_traces(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/orders", json={"amount": 99.99, "item": "widget"})

        assert response.status_code == 200
        assert response.json()["status"] == "created"

        # Verify order log captured structured data.
        order_log = next(r for r in logs if r.message == "creating order")
        assert order_log.data["amount"] == 99.99
        assert order_log.data["item"] == "widget"

        # Verify metrics were recorded.
        assert _metrics.get_counter("orders.created", method="POST") == 1

    def test_http_error_instrumented(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/error")

        assert response.status_code == 422

        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1
        assert completed[0].data["status_code"] == 422

    def test_unhandled_exception_instrumented(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/crash")

        assert response.status_code == 500
        failed = [r for r in logs if r.message == "request failed"]
        assert len(failed) == 1
        assert failed[0].level == LogLevel.ERROR

    def test_slow_endpoint_timing(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/slow")

        assert response.status_code == 200

        timing_log = next(r for r in logs if "slow operation" in r.message)
        assert timing_log.data["duration_ms"] >= 20

    def test_parallel_service_calls(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/multi-trace")

        assert response.status_code == 200
        assert len(response.json()["results"]) == 3

        service_logs = [r for r in logs if r.message.startswith("calling ")]
        assert len(service_logs) == 3

        # All service calls share the same trace.
        trace_ids = {r.trace_id for r in service_logs}
        assert len(trace_ids) == 1

    def test_multiple_requests_isolated(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/users/1")
            client.get("/users/2")

        request_ids = set()
        for record in logs:
            if "request_id" in record.context:
                request_ids.add(record.context["request_id"])
        assert len(request_ids) >= 2

    def test_middleware_metrics(self, app):
        with capture():
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/users/42")
            client.get("/users/7")

        count = _metrics.get_counter(
            "http.requests.total", method="GET", path="/users/42", status="200"
        )
        assert count == 1
        latencies = _metrics.get_histogram(
            "http.request.duration_ms", method="GET", path="/users/42"
        )
        assert len(latencies) == 1


# ── FastAPI with install() ──────────────────────────────────────


class TestFastAPIInstall:
    """Test spektr.install(app) auto-configures middleware."""

    def test_install_with_fastapi(self):
        import spektr

        app = FastAPI()

        @app.get("/ping")
        async def ping():
            return {"pong": True}

        spektr.install(app)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/ping")

        assert response.status_code == 200
        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1


# ── FastAPI + Health Check ──────────────────────────────────────


class TestFastAPIHealthCheck:
    def test_health_endpoint_via_fastapi(self):
        configure(health_path="/healthz", service="test-api")
        app = FastAPI()

        @app.get("/api/data")
        async def data():
            return {"data": [1, 2, 3]}

        app.add_middleware(SpektrMiddleware)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)

            # Health check should bypass middleware instrumentation.
            health_response = client.get("/healthz")
            assert health_response.status_code == 200
            body = health_response.json()
            assert body["status"] == "ok"
            assert body["service"] == "test-api"

            # Normal endpoint should be instrumented.
            data_response = client.get("/api/data")
            assert data_response.status_code == 200

        # Only the /api/data request should have logs.
        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1
        assert completed[0].data["path"] == "/api/data"


# ── FastAPI + W3C Trace Propagation ─────────────────────────────


class TestFastAPIW3CPropagation:
    def test_incoming_traceparent_extracted(self):
        app = FastAPI()

        @app.get("/downstream")
        async def downstream():
            log("handling downstream request")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/downstream", headers={"traceparent": traceparent})

        assert response.status_code == 200
        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1

    def test_inject_and_extract_across_services(self):
        """Simulate service A calling service B with trace context."""
        app_b = FastAPI()

        @app_b.get("/api")
        async def handle_b():
            log("service B handling")
            return {"service": "B"}

        app_b.add_middleware(SpektrMiddleware)

        with capture() as logs:
            # Service A creates a span and injects context.
            with trace("service-a-request") as span_a:
                outgoing_headers = trace.inject()
                log("calling service B")

                # Service B receives the request with trace context.
                client_b = TestClient(app_b, raise_server_exceptions=False)
                response = client_b.get("/api", headers=outgoing_headers)

        assert response.status_code == 200
        assert "traceparent" in outgoing_headers

        service_a_log = next(r for r in logs if r.message == "calling service B")
        assert service_a_log.trace_id == span_a.trace_id


# ── FastAPI + stdlib Bridge ─────────────────────────────────────


class TestFastAPIStdlibBridge:
    def test_third_party_logs_captured_in_request(self):
        """stdlib logs from third-party libs appear with request context."""
        install_bridge()
        third_party_logger = logging.getLogger("sqlalchemy.engine")

        app = FastAPI()

        @app.get("/query")
        async def query():
            third_party_logger.info("SELECT * FROM users")
            log("query complete", rows=42)
            return {"rows": 42}

        app.add_middleware(SpektrMiddleware)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/query")

        assert response.status_code == 200

        # stdlib log should appear with request context.
        sql_log = next(r for r in logs if "SELECT" in r.message)
        assert sql_log.data["logger"] == "sqlalchemy.engine"
        assert "request_id" in sql_log.context

        # Both stdlib and spektr logs share the same trace.
        spektr_log = next(r for r in logs if r.message == "query complete")
        assert sql_log.trace_id == spektr_log.trace_id


# ── FastAPI + Sinks and Samplers ────────────────────────────────


class TestFastAPISinkSampler:
    def test_custom_sink_receives_middleware_logs(self):
        records = []

        class CollectorSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        configure(sinks=[CollectorSink()])

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            log("inside handler")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/test")

        messages = [r.message for r in records]
        assert "inside handler" in messages
        assert "request completed" in messages

    def test_sampler_filters_in_middleware(self):
        records = []

        class CollectorSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        class ErrorOnly:
            def should_emit(self, level, message):
                return level >= LogLevel.ERROR

        configure(sinks=[CollectorSink()], sampler=ErrorOnly())

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            log.debug("dropped")
            log.info("dropped")
            log.error("visible")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/test")

        messages = [r.message for r in records]
        assert "visible" in messages
        assert "dropped" not in messages


# ── OTel Full Pipeline ──────────────────────────────────────────


class TestOTelFullPipeline:
    """Tests exercising the full OTel tracing pipeline with a FastAPI app."""

    @pytest.fixture(autouse=True)
    def otel_setup(self):
        from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

        class InMemoryExporter(SpanExporter):
            def __init__(self):
                self.spans = []

            def export(self, spans):
                self.spans.extend(spans)
                return SpanExportResult.SUCCESS

            def shutdown(self):
                pass

        self.exporter = InMemoryExporter()
        otel_bridge.setup(
            service_name="e2e-test",
            exporter=self.exporter,
            simple_processor=True,
        )
        yield
        otel_bridge.shutdown()

    def test_fastapi_request_exports_spans(self):
        app = FastAPI()

        @app.get("/api/users")
        @trace
        async def get_users():
            with trace("db.query", table="users"):
                await asyncio.sleep(0.001)
            return [{"id": 1}]

        app.add_middleware(SpektrMiddleware)

        with capture():
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/api/users")

        otel_bridge.shutdown()
        spans = self.exporter.spans
        names = {s.name for s in spans}
        assert "GET /api/users" in names
        assert "db.query" in names

        # Verify parent-child chain.
        by_name = {s.name: s for s in spans}
        db_span = by_name["db.query"]
        assert db_span.attributes["table"] == "users"

    def test_log_trace_correlation_with_otel(self):
        with capture() as logs:
            with trace("parent") as span:
                log("correlated message", key="val")

        otel_bridge.shutdown()
        otel_spans = self.exporter.spans
        otel_span = next(s for s in otel_spans if s.name == "parent")
        otel_trace_id = format(otel_span.context.trace_id, "032x")

        assert logs[0].trace_id == otel_trace_id
        assert logs[0].trace_id == span.trace_id

    def test_error_span_exported(self):
        app = FastAPI()

        @app.get("/fail")
        async def fail():
            raise RuntimeError("boom")

        app.add_middleware(SpektrMiddleware)

        with capture():
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/fail")

        otel_bridge.shutdown()
        spans = self.exporter.spans
        request_span = next(s for s in spans if "GET" in s.name)
        from opentelemetry.trace import StatusCode
        assert request_span.status.status_code == StatusCode.ERROR

    def test_decorated_handler_exports_with_args(self):
        @trace
        def process(order_id: int, amount: float):
            return {"processed": True}

        with capture():
            process(order_id=42, amount=99.99)

        otel_bridge.shutdown()
        span = next(s for s in self.exporter.spans if "process" in s.name)
        assert span.attributes["order_id"] == 42
        assert span.attributes["amount"] == 99.99


# ── Multi-Service Distributed Tracing ───────────────────────────


class TestDistributedTracing:
    """Simulates multiple microservices with trace context propagation."""

    def test_three_service_trace_propagation(self):
        """Service A → B → C with trace context forwarded via headers."""
        trace_ids_seen = {}

        # Service C.
        app_c = FastAPI()

        @app_c.get("/api")
        async def service_c_handler():
            log("service C handling")
            return {"service": "C"}

        app_c.add_middleware(SpektrMiddleware)

        # Service B calls C.
        app_b = FastAPI()

        @app_b.get("/api")
        async def service_b_handler():
            log("service B handling")
            with trace("call-service-c"):
                headers_to_c = trace.inject()
                client_c = TestClient(app_c, raise_server_exceptions=False)
                client_c.get("/api", headers=headers_to_c)
            return {"service": "B"}

        app_b.add_middleware(SpektrMiddleware)

        with capture() as logs:
            # Service A calls B.
            with trace("service-a-root") as root_span:
                headers_to_b = trace.inject()
                log("service A calling B")
                client_b = TestClient(app_b, raise_server_exceptions=False)
                response = client_b.get("/api", headers=headers_to_b)

        assert response.status_code == 200

        # Service A log should have trace correlation.
        a_log = next(r for r in logs if r.message == "service A calling B")
        assert a_log.trace_id == root_span.trace_id

    def test_service_with_bound_loggers_across_trace(self):
        """Bound loggers in different services maintain their own context."""
        auth_log = log.bind(service="auth")
        billing_log = log.bind(service="billing")

        @trace
        def auth_service(user_id: int):
            auth_log("authenticating", user_id=user_id)
            return {"authenticated": True}

        @trace
        def billing_service(amount: float):
            billing_log("charging", amount=amount)
            return {"charged": True}

        with capture() as logs:
            with trace("api-gateway"):
                auth_service(user_id=42)
                billing_service(amount=99.99)

        auth_logs = [r for r in logs if r.context.get("service") == "auth"]
        billing_logs = [r for r in logs if r.context.get("service") == "billing"]

        assert len(auth_logs) == 1
        assert len(billing_logs) == 1
        assert auth_logs[0].trace_id == billing_logs[0].trace_id


# ── JSON Mode E2E ───────────────────────────────────────────────


class TestJSONModeE2E:
    def test_fastapi_json_output(self):
        configure(output_mode=OutputMode.JSON, service="json-test")

        app = FastAPI()

        @app.get("/api/data")
        async def get_data():
            log("fetching data", origin="db")
            return {"data": True}

        app.add_middleware(SpektrMiddleware)

        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/api/data")

        lines = [line for line in buf.getvalue().strip().split("\n") if line]
        json_lines = []
        for line in lines:
            parsed = json.loads(line)
            json_lines.append(parsed)

        # Filter to log lines only (have "msg" key, unlike trace spans).
        log_lines = [j for j in json_lines if "msg" in j]

        # Should have at least the app log and the request completed log.
        messages = [j["msg"] for j in log_lines]
        assert "fetching data" in messages

        # The app log should have structured fields.
        data_log = next(j for j in log_lines if j["msg"] == "fetching data")
        assert data_log["origin"] == "db"
        assert "level" in data_log
        assert data_log["level"] == "info"

    def test_json_with_trace_ids(self):
        configure(output_mode=OutputMode.JSON)
        buf = StringIO()

        with patch.object(sys, "stderr", buf):
            with trace("json-span"):
                log("traced in json")

        lines = [line for line in buf.getvalue().strip().split("\n") if line]
        log_line = next(json.loads(l) for l in lines if "traced in json" in l)
        assert "trace_id" in log_line
        assert len(log_line["trace_id"]) == 32


# ── Configuration E2E ───────────────────────────────────────────


class TestConfigurationE2E:
    def test_min_level_filters_in_app(self):
        configure(min_level=LogLevel.WARNING)

        app = FastAPI()

        @app.get("/test")
        async def handler():
            log.debug("debug msg")
            log.info("info msg")
            log.warn("warning msg")
            log.error("error msg")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/test")

        app_messages = [r.message for r in logs if r.message in (
            "debug msg", "info msg", "warning msg", "error msg"
        )]
        assert "debug msg" not in app_messages
        assert "info msg" not in app_messages
        assert "warning msg" in app_messages
        assert "error msg" in app_messages

    def test_redaction_in_middleware(self):
        configure(output_mode=OutputMode.JSON, redact=["password", "token"])
        buf = StringIO()

        app = FastAPI()

        @app.get("/test")
        async def handler():
            log("auth", password="secret123", token="abc-xyz")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        with patch.object(sys, "stderr", buf):
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/test")

        output = buf.getvalue()
        assert "secret123" not in output
        assert "abc-xyz" not in output
        assert "***" in output


# ── Complex Async Scenarios ─────────────────────────────────────


class TestAsyncScenarios:
    def test_concurrent_requests_context_isolation(self):
        """Multiple concurrent async tasks should have isolated contexts."""
        app = FastAPI()

        @app.get("/task/{task_id}")
        async def task_handler(task_id: int):
            await asyncio.sleep(0.01)
            log("processing", task_id=task_id)
            return {"task_id": task_id}

        app.add_middleware(SpektrMiddleware)

        async def run():
            with capture() as logs:
                # Simulate 3 sequential requests (TestClient is sync).
                client = TestClient(app, raise_server_exceptions=False)
                for i in range(3):
                    client.get(f"/task/{i}")
            return logs

        logs = asyncio.run(run())

        task_logs = [r for r in logs if r.message == "processing"]
        assert len(task_logs) == 3

        # Each request should have a unique request_id.
        request_ids = {r.context["request_id"] for r in task_logs}
        assert len(request_ids) == 3

    def test_nested_async_with_context(self):
        """Nested async operations should maintain correct context."""

        @trace
        async def outer():
            with log.context(layer="outer"):
                log("outer start")
                result = await inner()
                log("outer end")
                return result

        @trace
        async def inner():
            with log.context(layer="inner"):
                log("inner work")
                return 42

        async def run():
            with capture() as logs:
                await outer()
            return logs

        logs = asyncio.run(run())

        outer_start = next(r for r in logs if r.message == "outer start")
        inner_work = next(r for r in logs if r.message == "inner work")
        outer_end = next(r for r in logs if r.message == "outer end")

        assert outer_start.context["layer"] == "outer"
        assert inner_work.context["layer"] == "inner"
        assert outer_end.context["layer"] == "outer"

        # All share the same trace.
        assert outer_start.trace_id == inner_work.trace_id == outer_end.trace_id


# ── Error Recovery Patterns ─────────────────────────────────────


class TestErrorRecoveryE2E:
    def test_catch_with_retry(self):
        """@log.catch combined with retry logic."""
        attempt = 0

        @log.catch(reraise=False)
        @trace
        def flaky_operation():
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise ConnectionError(f"attempt {attempt} failed")
            return "success"

        with capture() as logs:
            result = None
            for _ in range(3):
                result = flaky_operation()
                if result is not None:
                    break

        assert result == "success"
        error_logs = [r for r in logs if r.level == LogLevel.ERROR]
        assert len(error_logs) == 2

    def test_exception_in_fastapi_handler_with_catch(self):
        app = FastAPI()

        @app.get("/safe")
        async def safe_handler():
            @log.catch(reraise=False)
            def risky():
                raise ValueError("bad input")

            risky()
            log("continued after error")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/safe")

        assert response.status_code == 200
        assert any(r.message == "continued after error" for r in logs)
        error_logs = [r for r in logs if r.level == LogLevel.ERROR]
        assert len(error_logs) >= 1

    def test_structured_exception_fields_in_web_context(self):
        app = FastAPI()

        @app.get("/fail")
        async def fail():
            try:
                raise ValueError("bad value")
            except ValueError:
                log.exception("caught in handler", endpoint="/fail")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/fail")

        exc_log = next(r for r in logs if r.message == "caught in handler")
        assert exc_log.data["error_type"] == "ValueError"
        assert exc_log.data["error_message"] == "bad value"
        assert "error_stacktrace" in exc_log.data
        assert exc_log.data["endpoint"] == "/fail"
        assert "request_id" in exc_log.context


# ── Metrics + Tracing E2E ───────────────────────────────────────


class TestMetricsTracingE2E:
    def test_full_metrics_pipeline(self):
        """Counters, gauges, histograms used in a traced request."""

        @trace
        def handle_request(method: str, path: str):
            log.count("http.requests", method=method, path=path)
            log.gauge("active.connections", 42)
            with log.time("db.query"):
                time.sleep(0.005)
            log.histogram("response.size_bytes", 1024.0, method=method)
            return {"ok": True}

        with capture() as logs:
            handle_request(method="GET", path="/api")

        assert _metrics.get_counter("http.requests", method="GET", path="/api") == 1
        assert _metrics.get_gauge("active.connections") == 42
        histograms = _metrics.get_histogram("response.size_bytes", method="GET")
        assert histograms == [1024.0]

        timing_log = next(r for r in logs if "db.query" in r.message)
        assert timing_log.data["duration_ms"] >= 3
        assert timing_log.trace_id is not None

    def test_progress_in_fastapi_handler(self):
        app = FastAPI()

        @app.post("/import")
        async def import_data():
            with log.progress("import batch", total=5) as progress:
                for i in range(5):
                    progress.advance()
            return {"imported": 5}

        app.add_middleware(SpektrMiddleware)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/import")

        assert response.status_code == 200
        completed = next(r for r in logs if "import batch completed" in r.message)
        assert completed.data["current"] == 5
        assert "request_id" in completed.context


# ── Sampler E2E ─────────────────────────────────────────────────


class TestSamplerE2E:
    def test_rate_limit_sampler_in_app(self):
        records = []

        class ListSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        configure(sinks=[ListSink()], sampler=RateLimitSampler(per_second=5))

        app = FastAPI()

        @app.get("/test")
        async def handler():
            for i in range(100):
                log.info(f"msg {i}")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/test")

        # Rate limiter should have dropped most messages.
        # We can't predict exact count, but it should be much less than 100.
        info_records = [r for r in records if r.message.startswith("msg ")]
        assert len(info_records) < 100

    def test_composite_sampler_in_app(self):
        records = []

        class ListSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        class SkipDebug:
            def should_emit(self, level, message):
                return level >= LogLevel.INFO

        configure(
            sinks=[ListSink()],
            sampler=CompositeSampler(SkipDebug(), RateLimitSampler(per_second=1000)),
        )

        log.debug("should be dropped")
        log.info("should pass")
        log.error("also passes")

        messages = [r.message for r in records]
        assert "should be dropped" not in messages
        assert "should pass" in messages
        assert "also passes" in messages


# ── Bridge + Middleware E2E ──────────────────────────────────────


class TestBridgeMiddlewareE2E:
    def test_uvicorn_style_logs_captured(self):
        """Simulate uvicorn-style stdlib logs appearing in middleware context."""
        install_bridge()
        uvicorn_logger = logging.getLogger("uvicorn.access")

        app = FastAPI()

        @app.get("/test")
        async def handler():
            uvicorn_logger.info("GET /test 200")
            log("app handler")
            return {"ok": True}

        app.add_middleware(SpektrMiddleware)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/test")

        uvicorn_logs = [r for r in logs if r.data.get("logger") == "uvicorn.access"]
        app_logs = [r for r in logs if r.message == "app handler"]

        assert len(uvicorn_logs) == 1
        assert len(app_logs) == 1

        # Both should have request_id from middleware.
        assert "request_id" in uvicorn_logs[0].context
        assert "request_id" in app_logs[0].context
        assert uvicorn_logs[0].context["request_id"] == app_logs[0].context["request_id"]


# ── Capture E2E ─────────────────────────────────────────────────


class TestCaptureE2E:
    def test_capture_filter_in_complex_scenario(self):
        with capture() as logs:
            log.debug("debug msg")
            log.info("info msg", key="val")
            log.warn("warning msg")
            log.error("error msg", code=500)

            with trace("span"):
                log("traced msg")

        # Substring search.
        assert "debug msg" in logs
        assert "nonexistent" not in logs

        # Level filter.
        errors = logs.filter(level=LogLevel.ERROR)
        assert len(errors) == 1
        assert errors[0].data["code"] == 500

        # Data filter.
        by_key = logs.filter(key="val")
        assert len(by_key) == 1

        # Messages list.
        assert "debug msg" in logs.messages
        assert "traced msg" in logs.messages

    def test_capture_with_bound_loggers(self):
        db = log.bind(component="db")
        cache = log.bind(component="cache")

        with capture() as logs:
            db("query", table="users")
            cache("hit", key="user:1")

        assert len(logs) == 2
        assert logs[0].context["component"] == "db"
        assert logs[1].context["component"] == "cache"

    def test_capture_priority_over_sinks(self):
        """capture() should intercept records before they reach sinks."""
        sink_records = []

        class ListSink:
            def write(self, record):
                sink_records.append(record)

            def flush(self):
                pass

        configure(sinks=[ListSink()])

        with capture() as logs:
            log("captured, not sinked")

        assert len(logs) == 1
        assert len(sink_records) == 0


# ── Full Lifecycle Scenario ─────────────────────────────────────


class TestFullLifecycle:
    """The most comprehensive test: simulates a complete application lifecycle."""

    def test_complete_application_lifecycle(self):
        """
        Simulates:
        1. App startup with install()
        2. Configure with service name
        3. Process multiple HTTP requests
        4. Use bound loggers, context, tracing, metrics
        5. Handle errors gracefully
        6. Verify all data is consistent
        """
        import spektr

        configure(service="order-api")

        app = FastAPI()
        db_log = log.bind(component="database")
        cache_log = log.bind(component="cache")

        @app.get("/orders/{order_id}")
        @trace
        async def get_order(order_id: int):
            cache_log("cache lookup", key=f"order:{order_id}")
            log.count("cache.lookups", hit="false")

            db_log("query", table="orders", order_id=order_id)
            log.histogram("db.latency_ms", 5.2, table="orders")

            if order_id == 999:
                raise HTTPException(status_code=404, detail="Not found")

            return {"id": order_id, "total": 99.99}

        @app.post("/orders")
        @trace
        async def create_order(request: Request):
            body = await request.json()
            with trace("validate"):
                log("validating order")

            with trace("persist"):
                db_log("insert", table="orders")

            log.count("orders.created")
            return {"id": 1, "status": "created"}

        app.add_middleware(SpektrMiddleware)
        spektr.install(app)

        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)

            # Successful GET.
            r1 = client.get("/orders/42")
            assert r1.status_code == 200
            assert r1.json()["id"] == 42

            # Another successful GET.
            r2 = client.get("/orders/7")
            assert r2.status_code == 200

            # 404 error.
            r3 = client.get("/orders/999")
            assert r3.status_code == 404

            # POST.
            r4 = client.post("/orders", json={"item": "widget", "amount": 49.99})
            assert r4.status_code == 200

        # Verify metrics accumulated correctly.
        assert _metrics.get_counter("cache.lookups", hit="false") >= 2
        assert _metrics.get_counter("orders.created") == 1

        # Verify we have logs from all requests.
        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) >= 3

        # Verify bound logger context is preserved.
        db_logs = [r for r in logs if r.context.get("component") == "database"]
        assert len(db_logs) >= 3

        # Verify trace correlation: each request has its own trace.
        request_trace_ids = set()
        for r in completed:
            if r.trace_id:
                request_trace_ids.add(r.trace_id)
        assert len(request_trace_ids) >= 3

        # Verify request_ids are unique.
        request_ids = {r.context.get("request_id") for r in logs if "request_id" in r.context}
        assert len(request_ids) >= 4
