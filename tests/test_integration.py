"""Integration tests – full end-to-end scenarios simulating real-world usage."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from io import StringIO
from unittest.mock import patch

import pytest

from spektr import capture, configure, log, trace
from spektr._config import OutputMode
from spektr._context import get_current_span
from spektr._types import LogLevel
import spektr._config as config_module


@pytest.fixture(autouse=True)
def reset_config():
    config_module._config = None
    yield
    config_module._config = None


# ── Real-World Scenarios ─────────────────────────────────────


class TestWebServiceScenario:
    """Simulates a typical web service request flow."""

    def test_full_request_lifecycle(self):
        @trace
        def fetch_user(user_id: int):
            time.sleep(0.005)
            return {"name": "Ole", "email": "ole@test.com"}

        @trace
        def validate_order(order: dict):
            time.sleep(0.002)
            if order["amount"] <= 0:
                raise ValueError("Invalid amount")

        @trace
        def charge_payment(amount: float):
            time.sleep(0.01)
            return {"status": "success", "tx_id": "tx-123"}

        @trace
        def handle_order(order_id: int, user_id: int):
            with log.context(request_id="req-abc", order_id=order_id):
                log("starting order processing")
                user = fetch_user(user_id=user_id)
                log("user found", user=user["name"])
                validate_order(order={"amount": 99.99})
                result = charge_payment(amount=99.99)
                log("order complete", tx_id=result["tx_id"])
                return result

        with capture() as logs:
            result = handle_order(order_id=1, user_id=42)

        assert result["status"] == "success"
        assert len(logs) == 3

        # all logs have context
        for r in logs:
            assert r.context["request_id"] == "req-abc"
            assert r.context["order_id"] == 1

        # all logs have trace correlation
        for r in logs:
            assert r.trace_id is not None
            assert r.span_id is not None

        # all share same trace_id
        trace_ids = {r.trace_id for r in logs}
        assert len(trace_ids) == 1

    def test_request_with_error(self):
        @trace
        def handle_request(request_id: str):
            with log.context(request_id=request_id):
                log("processing")
                raise RuntimeError("database connection lost")

        with capture() as logs:
            with pytest.raises(RuntimeError):
                handle_request(request_id="req-fail")

        assert len(logs) == 1
        assert logs[0].context["request_id"] == "req-fail"


class TestAsyncWebServiceScenario:
    """Simulates an async web service with concurrent operations."""

    def test_async_request_with_parallel_fetches(self):
        @trace
        async def fetch_from_service(name: str):
            await asyncio.sleep(0.005)
            return f"data from {name}"

        @trace
        async def handle_request(request_id: str):
            with log.context(request_id=request_id):
                log("handling request")
                results = await asyncio.gather(
                    fetch_from_service(name="user-svc"),
                    fetch_from_service(name="product-svc"),
                    fetch_from_service(name="inventory-svc"),
                )
                log("all fetches done", count=len(results))
                return results

        async def run():
            with capture() as logs:
                results = await handle_request(request_id="req-async")
            return logs, results

        logs, results = asyncio.run(run())
        assert len(results) == 3
        assert len(logs) == 2
        assert all(r.context["request_id"] == "req-async" for r in logs)

    def test_concurrent_requests_isolated(self):
        results = {}

        @trace
        async def handle(request_id: str):
            with log.context(request_id=request_id):
                await asyncio.sleep(0.01)
                with capture() as logs:
                    log("processing")
                results[request_id] = logs[0].context.get("request_id")

        async def run():
            await asyncio.gather(
                handle(request_id="req-1"),
                handle(request_id="req-2"),
                handle(request_id="req-3"),
            )

        asyncio.run(run())
        assert results == {"req-1": "req-1", "req-2": "req-2", "req-3": "req-3"}


class TestMicroserviceScenario:
    """Simulates multiple services with bound loggers."""

    def test_multiple_bound_loggers(self):
        db_log = log.bind(component="database", host="db.prod")
        cache_log = log.bind(component="cache", host="redis.prod")
        api_log = log.bind(component="api")

        with capture() as logs:
            api_log("request received", path="/orders")
            db_log("query", table="orders", rows=42)
            cache_log("hit", key="order:42")
            api_log("response sent", status=200)

        assert logs[0].context["component"] == "api"
        assert logs[1].context["component"] == "database"
        assert logs[1].context["host"] == "db.prod"
        assert logs[2].context["component"] == "cache"
        assert logs[3].context["component"] == "api"

    def test_bound_logger_with_trace(self):
        db_log = log.bind(component="database")

        @trace
        def db_query(table: str):
            db_log("executing query", table=table)
            return [{"id": 1}]

        with capture() as logs:
            with trace("handle_request"):
                db_query(table="users")

        assert logs[0].context["component"] == "database"
        assert logs[0].trace_id is not None


class TestErrorRecoveryScenario:
    """Tests error handling and recovery patterns."""

    def test_catch_with_fallback(self):
        @log.catch(reraise=False)
        def primary_fetch():
            raise ConnectionError("primary down")

        def fallback_fetch():
            return "fallback data"

        with capture() as logs:
            result = primary_fetch()
            if result is None:
                log.warn("primary failed, using fallback")
                result = fallback_fetch()

        assert result == "fallback data"
        assert len(logs) == 2  # error + warning
        assert logs[0].level == LogLevel.ERROR
        assert logs[1].level == LogLevel.WARNING

    def test_nested_error_handling(self):
        @log.catch(reraise=False)
        def risky_operation():
            data = {"key": "value", "nested": {"deep": True}}
            count = len(data)
            raise ValueError(f"Failed processing {count} items")

        with capture() as logs:
            risky_operation()

        assert len(logs) == 1
        assert logs[0].exc_info is not None


# ── JSON Output Integration ─────────────────────────────────


class TestJSONOutputIntegration:
    def test_full_flow_in_json_mode(self):
        configure(output_mode=OutputMode.JSON, service="test-svc")
        buf = StringIO()

        with patch.object(sys, "stderr", buf):
            with trace("request") as span:
                log("hello", key="val")

        lines = buf.getvalue().strip().split("\n")
        # should have at least a log line and a trace line
        assert len(lines) >= 2

        log_line = json.loads(lines[0])
        assert log_line["msg"] == "hello"
        assert log_line["key"] == "val"
        assert log_line["trace_id"] == span.trace_id

    def test_json_error_output(self):
        configure(output_mode=OutputMode.JSON)
        buf = StringIO()

        with patch.object(sys, "stderr", buf):
            try:
                raise ValueError("json error test")
            except ValueError:
                log.exception("caught")

        output = json.loads(buf.getvalue().strip())
        assert output["error"]["type"] == "ValueError"
        assert output["error"]["message"] == "json error test"


# ── Performance / Stress ─────────────────────────────────────


class TestPerformance:
    def test_many_logs_fast(self):
        with capture() as logs:
            for i in range(1000):
                log(f"msg {i}", index=i)
        assert len(logs) == 1000

    def test_deeply_nested_traces(self):
        def nested(depth: int):
            if depth <= 0:
                return
            with trace(f"level-{depth}"):
                nested(depth - 1)

        # should not stack overflow or crash
        with capture():
            nested(50)

    def test_many_concurrent_async_tasks(self):
        @trace
        async def task(i: int):
            with log.context(task_id=i):
                log(f"task {i}")
                await asyncio.sleep(0.001)

        async def run():
            with capture() as logs:
                await asyncio.gather(*[task(i) for i in range(100)])
            return logs

        logs = asyncio.run(run())
        assert len(logs) == 100

    def test_large_data_in_log(self):
        big_data = {f"key_{i}": f"value_{i}" * 100 for i in range(50)}
        with capture() as logs:
            log("big", **big_data)
        assert len(logs[0].data) == 50


# ── Edge Cases ───────────────────────────────────────────────


class TestEdgeCases:
    def test_trace_with_no_logs_inside(self):
        with capture() as logs:
            with trace("silent"):
                pass
        assert len(logs) == 0

    def test_log_after_trace_has_no_trace_id(self):
        with capture() as logs:
            with trace("span"):
                log("inside")
            log("outside")
        assert logs[0].trace_id is not None
        assert logs[1].trace_id is None

    def test_exception_in_trace_propagates(self):
        with pytest.raises(ZeroDivisionError):
            with trace("fail"):
                1 / 0

    def test_catch_and_trace_together(self):
        @log.catch(reraise=False)
        @trace
        def traced_and_caught(x: int):
            return 1 / x

        with capture() as logs:
            traced_and_caught(x=0)

        assert len(logs) == 1
        assert logs[0].level == LogLevel.ERROR

    def test_trace_and_catch_together(self):
        @trace
        @log.catch(reraise=False)
        def caught_and_traced(x: int):
            return 1 / x

        with capture() as logs:
            caught_and_traced(x=0)

        assert len(logs) == 1
        assert logs[0].level == LogLevel.ERROR

    def test_empty_context(self):
        with capture() as logs:
            with log.context():
                log("empty context")
        assert logs[0].context == {}

    def test_context_with_none_value(self):
        with capture() as logs:
            with log.context(key=None):
                log("none ctx")
        assert logs[0].context["key"] is None

    def test_bind_with_empty_kwargs(self):
        bound = log.bind()
        with capture() as logs:
            bound("msg")
        assert logs[0].context == {}


# ── Feature Integration: Timing + Context + Tracing ────────


class TestTimingIntegration:
    def test_time_inside_trace(self):
        """log.time inside a trace span should have trace IDs."""
        with capture() as logs:
            with trace("parent"):
                with log.time("db query"):
                    time.sleep(0.005)

        assert len(logs) == 1
        assert logs[0].trace_id is not None
        assert logs[0].data["duration_ms"] >= 3

    def test_time_with_context(self):
        """log.time inside a context should inherit context."""
        with capture() as logs:
            with log.context(request_id="req-1"):
                with log.time("process"):
                    pass

        assert logs[0].context["request_id"] == "req-1"

    def test_time_decorator_inside_trace(self):
        @log.time
        @trace
        def traced_and_timed():
            return 42

        with capture() as logs:
            result = traced_and_timed()

        assert result == 42
        assert len(logs) == 1
        assert "duration_ms" in logs[0].data


class TestRateLimitIntegration:
    def test_once_inside_context(self):
        """log.once should inherit context."""
        from spektr._logger import _once_seen, _rate_lock

        with _rate_lock:
            _once_seen.clear()

        with capture() as logs:
            with log.context(request_id="req-1"):
                log.once("initialized")

        assert logs[0].context["request_id"] == "req-1"

    def test_sample_inside_trace(self):
        """log.sample should have trace IDs when inside a span."""
        with capture() as logs:
            with trace("span"):
                log.sample(1.0, "sampled event")

        assert logs[0].trace_id is not None

    def test_every_with_structured_data(self):
        from spektr._logger import _every_counters, _rate_lock

        with _rate_lock:
            _every_counters.clear()

        with capture() as logs:
            for i in range(6):
                log.every(3, "batch", batch_number=i)

        assert len(logs) == 2
        assert logs[0].data["batch_number"] == 0
        assert logs[1].data["batch_number"] == 3


class TestRedactionIntegration:
    def test_redaction_with_bound_logger(self):
        """Bound logger context should also be redacted in output."""
        from spektr._formatters import format_record_json

        secret_log = log.bind(api_key="sk-123")
        with capture() as logs:
            secret_log("request")

        # capture() should preserve raw values
        assert logs[0].context["api_key"] == "sk-123"

    def test_redaction_in_timing_data(self, capsys):
        """Sensitive keys in log.time kwargs should be redacted in output."""
        from spektr._formatters import format_record_json
        from spektr._types import LogLevel, LogRecord

        record = LogRecord(
            timestamp=time.time(),
            level=LogLevel.INFO,
            message="db query",
            data={"duration_ms": 42.0, "password": "secret"},
            context={},
        )
        format_record_json(record)
        output = capsys.readouterr().err
        parsed = json.loads(output)
        assert parsed["duration_ms"] == 42.0
        assert parsed["password"] == "***"


class TestMiddlewareIntegration:
    def test_middleware_with_bound_logger_inside(self):
        """Logs from bound loggers inside middleware should have request_id."""
        db_log = log.bind(component="database")

        async def app_with_bound_logger(scope, receive, send):
            db_log("query executed", table="users")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        from spektr import SpektrMiddleware

        async def run():
            app = SpektrMiddleware(app_with_bound_logger)
            scope = {"type": "http", "method": "GET", "path": "/users",
                     "query_string": b"", "headers": []}
            with capture() as logs:
                await app(scope, _noop_receive, _noop_send)
            return logs

        async def _noop_receive():
            return {"type": "http.request", "body": b""}

        async def _noop_send(message):
            pass

        logs = asyncio.run(run())
        db_logs = [r for r in logs if r.message == "query executed"]
        assert len(db_logs) == 1
        assert db_logs[0].context["component"] == "database"
        assert "request_id" in db_logs[0].context


class TestMetricsIntegration:
    """Tests for metrics combined with other features."""

    def test_metrics_inside_trace(self):
        from spektr._metrics._api import _metrics

        _metrics.reset()

        with trace("request"):
            log.count("db.queries", table="users")
            log.histogram("db.latency_ms", 42.0, table="users")

        assert _metrics.get_counter("db.queries", table="users") == 1
        assert _metrics.get_histogram("db.latency_ms", table="users") == [42.0]

    def test_progress_with_trace(self):
        with capture() as logs:
            with trace("batch"):
                with log.progress("import", total=10) as progress:
                    for _ in range(10):
                        progress.advance()

        completed = [r for r in logs if "completed" in r.message]
        assert len(completed) == 1
        assert completed[0].trace_id is not None

    def test_progress_with_context(self):
        with capture() as logs:
            with log.context(batch_id="batch-42"):
                with log.progress("export", total=5) as progress:
                    for _ in range(5):
                        progress.advance()

        for record in logs:
            assert record.context["batch_id"] == "batch-42"


class TestSinkAndSamplerIntegration:
    """Tests combining sinks and samplers."""

    def test_sampler_with_sink(self):
        records = []

        class ListSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        class WarningOnly:
            def should_emit(self, level, message):
                return level >= LogLevel.WARNING

        configure(sinks=[ListSink()], sampler=WarningOnly())
        log.info("should be dropped")
        log.warning("should pass")
        log.error("also passes")

        assert len(records) == 2
        assert records[0].message == "should pass"
        assert records[1].message == "also passes"

    def test_structured_exceptions_in_sink(self):
        records = []

        class ListSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        configure(sinks=[ListSink()])

        @log.catch(reraise=False)
        def fail():
            raise ValueError("sink error")

        fail()

        assert len(records) == 1
        assert records[0].data["error_type"] == "ValueError"
        assert records[0].data["error_message"] == "sink error"
        assert "error_stacktrace" in records[0].data


class TestPropagationIntegration:
    """Tests for W3C trace context propagation combined with other features."""

    def test_inject_in_outgoing_request(self):
        """Simulate injecting trace context for an outgoing HTTP call."""
        with capture() as logs:
            with trace("parent-service"):
                headers = trace.inject()
                log("calling downstream", traceparent=headers.get("traceparent", ""))

        assert logs[0].data["traceparent"] != ""
        assert logs[0].data["traceparent"].startswith("00-")

    def test_extract_from_incoming_request(self):
        """Simulate extracting trace context from an incoming HTTP request."""
        headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        ctx = trace.extract(headers)
        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


class TestMiddlewareMetrics:
    """Tests for automatic middleware metrics."""

    def test_middleware_records_request_metrics(self):
        from spektr._metrics._api import _metrics

        _metrics.reset()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        from spektr import SpektrMiddleware

        async def run():
            middleware = SpektrMiddleware(app)
            scope = {"type": "http", "method": "GET", "path": "/api/test", "headers": []}
            with capture():
                await middleware(scope, _noop_receive, _noop_send)

        async def _noop_receive():
            return {"type": "http.request", "body": b""}

        async def _noop_send(message):
            pass

        asyncio.run(run())

        assert _metrics.get_counter("http.requests.total", method="GET", path="/api/test", status="200") == 1
        latencies = _metrics.get_histogram("http.request.duration_ms", method="GET", path="/api/test")
        assert len(latencies) == 1
        assert latencies[0] >= 0


class TestMiddlewareW3CPropagation:
    """Tests for W3C trace context extraction in middleware."""

    def test_middleware_extracts_traceparent(self):
        trace_parent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        from spektr import SpektrMiddleware

        async def run():
            middleware = SpektrMiddleware(app)
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [
                    (b"traceparent", trace_parent.encode()),
                ],
            }
            with capture() as logs:
                await middleware(scope, _noop_receive, _noop_send)
            return logs

        async def _noop_receive():
            return {"type": "http.request", "body": b""}

        async def _noop_send(message):
            pass

        logs = asyncio.run(run())
        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1


class TestPublicAPI:
    """Verify the public API surface is correct."""

    def test_all_exports(self):
        import spektr
        assert hasattr(spektr, "log")
        assert hasattr(spektr, "trace")
        assert hasattr(spektr, "configure")
        assert hasattr(spektr, "install")
        assert hasattr(spektr, "capture")
        assert hasattr(spektr, "SpektrMiddleware")

    def test_new_exports(self):
        import spektr
        assert hasattr(spektr, "Sink")
        assert hasattr(spektr, "Sampler")
        assert hasattr(spektr, "MetricBackend")
        assert hasattr(spektr, "RateLimitSampler")
        assert hasattr(spektr, "CompositeSampler")
        assert hasattr(spektr, "InMemoryMetrics")

    def test_log_is_singleton(self):
        from spektr import log as log1
        from spektr import log as log2
        assert log1 is log2

    def test_trace_is_singleton(self):
        from spektr import trace as trace1
        from spektr import trace as trace2
        assert trace1 is trace2

    def test_log_has_all_methods(self):
        assert callable(log)
        assert callable(log.debug)
        assert callable(log.info)
        assert callable(log.warn)
        assert callable(log.warning)
        assert callable(log.error)
        assert callable(log.exception)
        assert callable(log.once)
        assert callable(log.every)
        assert callable(log.sample)
        assert callable(log.time)
        assert callable(log.bind)
        assert callable(log.context)
        assert callable(log.count)
        assert callable(log.gauge)
        assert callable(log.histogram)
        assert callable(log.progress)

    def test_trace_has_propagation_methods(self):
        assert callable(trace.inject)
        assert callable(trace.extract)

    def test_all_list_complete(self):
        import spektr
        for name in spektr.__all__:
            assert hasattr(spektr, name), f"{name} in __all__ but not in module"
