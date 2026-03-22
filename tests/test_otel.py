"""Tests for OpenTelemetry integration – verifies spektr spans export as real OTel spans."""

from __future__ import annotations

import asyncio

import pytest

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

from spektr import capture, log, trace
from spektr._context import get_current_span
import spektr._otel as otel_bridge


class InMemorySpanExporter(SpanExporter):
    """Simple in-memory exporter for testing (replaces removed upstream class)."""

    def __init__(self):
        self._spans = []
        self._stopped = False

    def export(self, spans):
        if self._stopped:
            return SpanExportResult.FAILURE
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def get_finished_spans(self):
        return list(self._spans)

    def clear(self):
        self._spans.clear()

    def shutdown(self):
        self._stopped = True


@pytest.fixture(autouse=True)
def otel_env(request):
    """Set up OTel with InMemorySpanExporter for each test."""
    if "no_otel_setup" in request.keywords:
        yield None
        return

    exporter = InMemorySpanExporter()
    otel_bridge.setup(service_name="test-svc", exporter=exporter, simple_processor=True)
    yield exporter
    exporter.clear()
    otel_bridge.shutdown()


# ── Basic Span Export ──────────────────────────────────────────


class TestOTelSpanExport:
    def test_single_span_exported(self, otel_env):
        with trace("my-operation"):
            pass

        spans = otel_env.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my-operation"

    def test_span_ids_match_spektr(self, otel_env):
        with trace("test") as spektr_span:
            pass

        otel_spans = otel_env.get_finished_spans()
        otel_span = otel_spans[0]
        ctx = otel_span.context
        assert format(ctx.trace_id, "032x") == spektr_span.trace_id
        assert format(ctx.span_id, "016x") == spektr_span.span_id

    def test_span_attributes_exported(self, otel_env):
        with trace("query", table="users", limit=10):
            pass

        otel_spans = otel_env.get_finished_spans()
        assert otel_spans[0].attributes["table"] == "users"
        assert otel_spans[0].attributes["limit"] == 10

    def test_span_attributes_various_types(self, otel_env):
        with trace("types", string="hello", integer=42, floating=3.14, boolean=True):
            pass

        attrs = otel_env.get_finished_spans()[0].attributes
        assert attrs["string"] == "hello"
        assert attrs["integer"] == 42
        assert attrs["floating"] == 3.14
        assert attrs["boolean"] is True

    def test_non_primitive_attributes_stringified(self, otel_env):
        with trace("complex", items=[1, 2, 3], meta={"key": "val"}):
            pass

        attrs = otel_env.get_finished_spans()[0].attributes
        assert attrs["items"] == "[1, 2, 3]"
        assert attrs["meta"] == "{'key': 'val'}"

    def test_none_attributes_skipped(self, otel_env):
        with trace("nullable", key=None):
            pass

        attrs = otel_env.get_finished_spans()[0].attributes or {}
        assert "key" not in attrs

    def test_span_status_ok(self, otel_env):
        with trace("ok"):
            pass

        assert otel_env.get_finished_spans()[0].status.status_code == StatusCode.OK

    def test_span_status_error(self, otel_env):
        with pytest.raises(ValueError):
            with trace("fail"):
                raise ValueError("boom")

        span = otel_env.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR
        assert "boom" in span.status.description

    def test_error_recorded_as_exception_event(self, otel_env):
        with pytest.raises(ValueError):
            with trace("fail"):
                raise ValueError("test error")

        events = otel_env.get_finished_spans()[0].events
        exc_events = [e for e in events if e.name == "exception"]
        assert len(exc_events) == 1
        assert exc_events[0].attributes["exception.type"] == "ValueError"
        assert exc_events[0].attributes["exception.message"] == "test error"

    def test_no_data_span(self, otel_env):
        with trace("bare"):
            pass

        span = otel_env.get_finished_spans()[0]
        assert span.attributes is None or len(span.attributes) == 0

    def test_multiple_spans_exported(self, otel_env):
        for i in range(5):
            with trace(f"span-{i}"):
                pass

        spans = otel_env.get_finished_spans()
        assert len(spans) == 5
        names = {s.name for s in spans}
        assert names == {f"span-{i}" for i in range(5)}


# ── Parent-Child Relationships ─────────────────────────────────


class TestOTelParentChild:
    def test_child_has_parent_span_id(self, otel_env):
        with trace("parent"):
            with trace("child"):
                pass

        spans = otel_env.get_finished_spans()
        parent_otel = next(s for s in spans if s.name == "parent")
        child_otel = next(s for s in spans if s.name == "child")
        assert child_otel.parent.span_id == parent_otel.context.span_id

    def test_shared_trace_id(self, otel_env):
        with trace("root"):
            with trace("child1"):
                with trace("grandchild"):
                    pass
            with trace("child2"):
                pass

        spans = otel_env.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1

    def test_separate_roots_different_trace_ids(self, otel_env):
        with trace("root1"):
            pass
        with trace("root2"):
            pass

        spans = otel_env.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 2

    def test_deep_nesting_parent_chain(self, otel_env):
        with trace("l0"):
            with trace("l1"):
                with trace("l2"):
                    with trace("l3"):
                        with trace("l4"):
                            pass

        spans = otel_env.get_finished_spans()
        assert len(spans) == 5

        by_name = {s.name: s for s in spans}
        for i in range(1, 5):
            child = by_name[f"l{i}"]
            parent = by_name[f"l{i - 1}"]
            assert child.parent.span_id == parent.context.span_id

    def test_siblings_share_parent(self, otel_env):
        with trace("parent"):
            with trace("a"):
                pass
            with trace("b"):
                pass
            with trace("c"):
                pass

        spans = otel_env.get_finished_spans()
        parent_otel = next(s for s in spans if s.name == "parent")
        children = [s for s in spans if s.name in ("a", "b", "c")]

        for child in children:
            assert child.parent.span_id == parent_otel.context.span_id

        child_ids = {c.context.span_id for c in children}
        assert len(child_ids) == 3

    def test_error_in_child_parent_ok(self, otel_env):
        with trace("parent"):
            try:
                with trace("child"):
                    raise ValueError("child error")
            except ValueError:
                pass

        spans = otel_env.get_finished_spans()
        parent_otel = next(s for s in spans if s.name == "parent")
        child_otel = next(s for s in spans if s.name == "child")

        assert child_otel.status.status_code == StatusCode.ERROR
        assert parent_otel.status.status_code == StatusCode.OK

    def test_spektr_parent_id_matches_otel(self, otel_env):
        with trace("parent") as parent_span:
            with trace("child") as child_span:
                pass

        assert child_span.parent_id == parent_span.span_id

        spans = otel_env.get_finished_spans()
        parent_otel = next(s for s in spans if s.name == "parent")
        assert child_span.parent_id == format(parent_otel.context.span_id, "016x")


# ── Trace Decorator with OTel ──────────────────────────────────


class TestOTelDecorator:
    def test_decorated_function_exports_span(self, otel_env):
        @trace
        def process(order_id: int):
            return order_id * 2

        with capture():
            result = process(42)

        assert result == 84
        spans = otel_env.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["order_id"] == 42

    def test_async_decorated_exports_span(self, otel_env):
        @trace
        async def async_process(name: str):
            await asyncio.sleep(0.001)
            return f"done-{name}"

        async def run():
            with capture():
                return await async_process("test")

        result = asyncio.run(run())
        assert result == "done-test"

        spans = otel_env.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["name"] == "test"

    def test_nested_decorators_parent_chain(self, otel_env):
        @trace
        def inner(x: int):
            return x + 1

        @trace
        def outer(x: int):
            return inner(x=x * 2)

        with capture():
            result = outer(x=5)

        assert result == 11
        spans = otel_env.get_finished_spans()
        assert len(spans) == 2

        outer_otel = next(s for s in spans if "outer" in s.name)
        inner_otel = next(s for s in spans if "inner" in s.name)
        assert inner_otel.parent.span_id == outer_otel.context.span_id

    def test_decorator_with_extra_data(self, otel_env):
        @trace(version="2.0")
        def handler():
            return get_current_span()

        with capture():
            handler()

        otel_spans = otel_env.get_finished_spans()
        assert otel_spans[0].attributes["version"] == "2.0"

    def test_decorator_skips_self(self, otel_env):
        class Service:
            @trace
            def handle(self, request_id: str):
                return get_current_span()

        svc = Service()
        with capture():
            svc.handle(request_id="abc")

        otel_spans = otel_env.get_finished_spans()
        assert "self" not in (otel_spans[0].attributes or {})
        assert otel_spans[0].attributes["request_id"] == "abc"


# ── Log-Trace Correlation with OTel ────────────────────────────


class TestOTelLogCorrelation:
    def test_log_trace_id_matches_otel(self, otel_env):
        with capture() as logs:
            with trace("span") as span:
                log("inside")

        otel_spans = otel_env.get_finished_spans()
        otel_trace_id = format(otel_spans[0].context.trace_id, "032x")

        assert logs[0].trace_id == otel_trace_id
        assert logs[0].trace_id == span.trace_id

    def test_log_span_id_matches_otel(self, otel_env):
        with capture() as logs:
            with trace("span") as span:
                log("inside")

        otel_spans = otel_env.get_finished_spans()
        otel_span_id = format(otel_spans[0].context.span_id, "016x")

        assert logs[0].span_id == otel_span_id
        assert logs[0].span_id == span.span_id

    def test_nested_span_log_correlation(self, otel_env):
        with capture() as logs:
            with trace("outer"):
                log("in outer")
                with trace("inner"):
                    log("in inner")

        otel_spans = otel_env.get_finished_spans()
        outer_otel = next(s for s in otel_spans if s.name == "outer")
        inner_otel = next(s for s in otel_spans if s.name == "inner")

        assert logs[0].span_id == format(outer_otel.context.span_id, "016x")
        assert logs[1].span_id == format(inner_otel.context.span_id, "016x")

        otel_trace_id = format(outer_otel.context.trace_id, "032x")
        assert logs[0].trace_id == otel_trace_id
        assert logs[1].trace_id == otel_trace_id

    def test_log_outside_span_no_otel_ids(self, otel_env):
        with capture() as logs:
            log("outside")

        assert logs[0].trace_id is None
        assert logs[0].span_id is None

    def test_log_context_preserved_with_otel(self, otel_env):
        with capture() as logs:
            with log.context(request_id="req-123"):
                with trace("span"):
                    log("inside", key="val")

        assert logs[0].context["request_id"] == "req-123"
        assert logs[0].data["key"] == "val"
        assert logs[0].trace_id is not None

    def test_bound_logger_with_otel(self, otel_env):
        db_log = log.bind(component="database")

        with capture() as logs:
            with trace("query"):
                db_log("executing", table="users")

        assert logs[0].context["component"] == "database"
        assert logs[0].trace_id is not None

        otel_spans = otel_env.get_finished_spans()
        otel_trace_id = format(otel_spans[0].context.trace_id, "032x")
        assert logs[0].trace_id == otel_trace_id


# ── Async with OTel ────────────────────────────────────────────


class TestOTelAsync:
    def test_async_span_exported(self, otel_env):
        async def run():
            async with trace("async-op"):
                await asyncio.sleep(0.001)

        asyncio.run(run())

        spans = otel_env.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "async-op"

    def test_async_nested_parent_chain(self, otel_env):
        @trace
        async def child_task(task_id: int):
            await asyncio.sleep(0.001)

        @trace
        async def outer_task():
            await child_task(task_id=1)
            await child_task(task_id=2)

        async def run():
            with capture():
                await outer_task()

        asyncio.run(run())

        spans = otel_env.get_finished_spans()
        assert len(spans) == 3

        outer = next(s for s in spans if "outer" in s.name)
        children = [s for s in spans if "child" in s.name]
        for child in children:
            assert child.parent.span_id == outer.context.span_id

    def test_async_gather_preserves_parent(self, otel_env):
        @trace
        async def worker(i: int):
            await asyncio.sleep(0.001)

        async def run():
            with capture():
                async with trace("root"):
                    await asyncio.gather(
                        worker(i=1),
                        worker(i=2),
                        worker(i=3),
                    )

        asyncio.run(run())

        spans = otel_env.get_finished_spans()
        assert len(spans) == 4

        root = next(s for s in spans if s.name == "root")
        workers = [s for s in spans if "worker" in s.name]

        for w in workers:
            assert w.parent.span_id == root.context.span_id

        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1

    def test_async_log_correlation(self, otel_env):
        async def run():
            with capture() as logs:
                async with trace("handler"):
                    log("processing")
                    await asyncio.sleep(0.001)
                    log("done")
            return logs

        logs = asyncio.run(run())

        otel_spans = otel_env.get_finished_spans()
        otel_trace_id = format(otel_spans[0].context.trace_id, "032x")

        assert logs[0].trace_id == otel_trace_id
        assert logs[1].trace_id == otel_trace_id


# ── Resource & Service Name ────────────────────────────────────


class TestOTelResource:
    def test_service_name_in_resource(self, otel_env):
        provider = otel_bridge.get_provider()
        assert provider.resource.attributes["service.name"] == "test-svc"

    @pytest.mark.no_otel_setup
    def test_custom_service_name(self):
        exporter = InMemorySpanExporter()
        otel_bridge.setup(service_name="my-api", exporter=exporter, simple_processor=True)

        try:
            provider = otel_bridge.get_provider()
            assert provider.resource.attributes["service.name"] == "my-api"
        finally:
            exporter.clear()
            otel_bridge.shutdown()


# ── Lifecycle ──────────────────────────────────────────────────


class TestOTelLifecycle:
    def test_shutdown_clears_state(self, otel_env):
        otel_bridge.shutdown()
        assert otel_bridge._tracer is None
        assert otel_bridge._provider is None

    @pytest.mark.no_otel_setup
    def test_spans_auto_initialize_after_shutdown(self):
        """After shutdown, spans still work via lazy re-initialization."""
        otel_bridge.shutdown()

        with trace("auto-init") as span:
            pass

        # IDs come from the auto-initialized OTel provider.
        assert len(span.span_id) == 16
        assert len(span.trace_id) == 32
        # Provider was re-created by _ensure_provider().
        assert otel_bridge._tracer is not None

        otel_bridge.shutdown()

    @pytest.mark.no_otel_setup
    def test_setup_then_shutdown_then_new_spans(self):
        """After shutdown, new spans use a fresh auto-initialized provider."""
        exporter = InMemorySpanExporter()
        otel_bridge.setup(service_name="test", exporter=exporter, simple_processor=True)

        with trace("exported"):
            pass
        assert len(exporter.get_finished_spans()) == 1

        otel_bridge.shutdown()

        # New span uses auto-initialized provider (no exporter attached).
        with trace("not-exported") as span:
            pass

        assert len(span.span_id) == 16
        assert len(span.trace_id) == 32
        # Exporter still only has the first span.
        assert len(exporter.get_finished_spans()) == 1

        otel_bridge.shutdown()

    @pytest.mark.no_otel_setup
    def test_double_shutdown_is_safe(self):
        exporter = InMemorySpanExporter()
        otel_bridge.setup(service_name="test", exporter=exporter, simple_processor=True)
        otel_bridge.shutdown()
        otel_bridge.shutdown()  # should not raise


# ── Full Integration Scenario ──────────────────────────────────


class TestOTelFullScenario:
    def test_web_request_lifecycle(self, otel_env):
        @trace
        def fetch_user(user_id: int):
            return {"name": "Ole", "id": user_id}

        @trace
        def process_order(order_id: int, amount: float):
            return {"status": "success", "order_id": order_id}

        with capture() as logs:
            with trace("handle_request"):
                with log.context(request_id="req-abc"):
                    log("request started")
                    user = fetch_user(user_id=42)
                    log("user found", user=user["name"])
                    result = process_order(order_id=1, amount=99.99)
                    log("order complete", status=result["status"])

        assert len(logs) == 3
        for r in logs:
            assert r.context["request_id"] == "req-abc"
            assert r.trace_id is not None

        spans = otel_env.get_finished_spans()
        assert len(spans) == 3

        root_otel = next(s for s in spans if s.name == "handle_request")
        fetch_otel = next(s for s in spans if "fetch_user" in s.name)
        order_otel = next(s for s in spans if "process_order" in s.name)

        assert fetch_otel.parent.span_id == root_otel.context.span_id
        assert order_otel.parent.span_id == root_otel.context.span_id

        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1

        assert fetch_otel.attributes["user_id"] == 42
        assert order_otel.attributes["order_id"] == 1
        assert order_otel.attributes["amount"] == 99.99

        otel_trace_id = format(root_otel.context.trace_id, "032x")
        assert all(r.trace_id == otel_trace_id for r in logs)

    def test_error_scenario_with_otel(self, otel_env):
        @trace
        def risky_operation(x: int):
            return 1 / x

        with pytest.raises(ZeroDivisionError):
            with trace("request"):
                risky_operation(x=0)

        spans = otel_env.get_finished_spans()
        assert len(spans) == 2

        risky_span = next(s for s in spans if "risky" in s.name)
        request_span = next(s for s in spans if s.name == "request")

        assert risky_span.status.status_code == StatusCode.ERROR
        assert request_span.status.status_code == StatusCode.ERROR

        exc_events = [e for e in risky_span.events if e.name == "exception"]
        assert len(exc_events) == 1
        assert exc_events[0].attributes["exception.type"] == "ZeroDivisionError"

    def test_many_spans_performance(self, otel_env):
        for i in range(100):
            with trace(f"span-{i}", index=i):
                pass

        spans = otel_env.get_finished_spans()
        assert len(spans) == 100
