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
