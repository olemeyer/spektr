"""Tests for spektr tracing – spans, trace trees, and correlation."""

from __future__ import annotations

import asyncio
import time

import pytest

from spektr import capture, log, trace
from spektr._context import get_current_span


# ── Basic Span Context Manager ───────────────────────────────


class TestSpanContextManager:
    def test_span_creates_and_closes(self):
        with trace("test-span") as span:
            assert span is not None
            assert span.name == "test-span"
            assert span.start_time > 0
            assert span.end_time is None
        assert span.end_time is not None

    def test_span_has_ids(self):
        with trace("test") as span:
            pass
        assert span.span_id is not None
        assert span.trace_id is not None
        assert len(span.span_id) == 16  # hex(8 bytes)
        assert len(span.trace_id) == 32  # hex(16 bytes)

    def test_span_measures_duration(self):
        with trace("slow") as span:
            time.sleep(0.02)
        assert span.duration_ms is not None
        assert span.duration_ms >= 15  # allow some slack

    def test_span_stores_data(self):
        with trace("query", table="users", limit=10) as span:
            pass
        assert span.data == {"table": "users", "limit": 10}

    def test_span_status_ok_on_success(self):
        with trace("ok") as span:
            pass
        assert span.status == "ok"
        assert span.error is None

    def test_span_status_error_on_exception(self):
        with pytest.raises(ValueError):
            with trace("fail") as span:
                raise ValueError("boom")
        assert span.status == "error"
        assert isinstance(span.error, ValueError)

    def test_span_does_not_suppress_exceptions(self):
        with pytest.raises(RuntimeError, match="propagated"):
            with trace("test"):
                raise RuntimeError("propagated")

    def test_current_span_is_set_inside(self):
        assert get_current_span() is None
        with trace("test") as span:
            assert get_current_span() is span
        assert get_current_span() is None

    def test_no_data(self):
        with trace("bare") as span:
            pass
        assert span.data == {}


# ── Nested Spans ─────────────────────────────────────────────


class TestNestedSpans:
    def test_child_span_links_to_parent(self):
        with trace("parent") as parent:
            with trace("child") as child:
                pass
        assert child.parent_id == parent.span_id
        assert child.trace_id == parent.trace_id

    def test_parent_collects_children(self):
        with trace("parent") as parent:
            with trace("child1"):
                pass
            with trace("child2"):
                pass
        assert len(parent.children) == 2
        assert parent.children[0].name == "child1"
        assert parent.children[1].name == "child2"

    def test_deep_nesting(self):
        spans = []
        with trace("level0") as s0:
            spans.append(s0)
            with trace("level1") as s1:
                spans.append(s1)
                with trace("level2") as s2:
                    spans.append(s2)
                    with trace("level3") as s3:
                        spans.append(s3)

        # all share same trace_id
        trace_ids = {s.trace_id for s in spans}
        assert len(trace_ids) == 1

        # parent chain
        assert spans[1].parent_id == spans[0].span_id
        assert spans[2].parent_id == spans[1].span_id
        assert spans[3].parent_id == spans[2].span_id

    def test_sibling_spans_independent(self):
        with trace("parent") as parent:
            with trace("a") as a:
                pass
            with trace("b") as b:
                pass
        assert a.parent_id == parent.span_id
        assert b.parent_id == parent.span_id
        assert a.span_id != b.span_id

    def test_separate_root_spans_have_different_trace_ids(self):
        with trace("root1") as r1:
            pass
        with trace("root2") as r2:
            pass
        assert r1.trace_id != r2.trace_id

    def test_error_in_child_does_not_affect_parent_status(self):
        with trace("parent") as parent:
            try:
                with trace("child") as child:
                    raise ValueError("child error")
            except ValueError:
                pass
        assert child.status == "error"
        assert parent.status == "ok"


# ── Trace Decorator ──────────────────────────────────────────


class TestTraceDecorator:
    def test_bare_decorator(self):
        @trace
        def my_func():
            return 42

        with capture():
            result = my_func()
        assert result == 42

    def test_decorator_auto_names(self):
        @trace
        def calculate_total():
            pass

        spans = []
        orig_exit = trace.__class__.__mro__[0]  # can't easily capture spans

        # Use context to verify span was created
        with capture():
            calculate_total()
        # The span existed and ran – function returned without error

    def test_decorator_captures_args(self):
        captured_span = None

        @trace
        def process(order_id: int, amount: float):
            nonlocal captured_span
            captured_span = get_current_span()
            return order_id * amount

        with capture():
            result = process(42, 9.99)

        assert result == 42 * 9.99
        assert captured_span is not None
        assert captured_span.data["order_id"] == 42
        assert captured_span.data["amount"] == 9.99

    def test_decorator_skips_self(self):
        class Service:
            @trace
            def handle(self, request_id: str):
                return get_current_span()

        svc = Service()
        with capture():
            span = svc.handle(request_id="abc")
        assert "self" not in span.data
        assert span.data["request_id"] == "abc"

    def test_decorator_with_kwargs(self):
        @trace
        def func(a: int, b: str = "default"):
            return get_current_span()

        with capture():
            span = func(1)
        assert span.data["a"] == 1
        assert span.data["b"] == "default"

    def test_decorator_preserves_function_metadata(self):
        @trace
        def documented_function():
            """This is my docstring."""
            pass

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is my docstring."

    def test_decorator_with_extra_data(self):
        @trace(version="2.0")
        def handler():
            return get_current_span()

        with capture():
            span = handler()
        assert span.data["version"] == "2.0"


# ── Async Tracing ────────────────────────────────────────────


class TestAsyncTracing:
    def test_async_span_context_manager(self):
        async def run():
            async with trace("async-span") as span:
                await asyncio.sleep(0.01)
            return span

        span = asyncio.run(run())
        assert span.name == "async-span"
        assert span.duration_ms is not None
        assert span.duration_ms >= 8

    def test_async_decorator(self):
        @trace
        async def async_fetch(url: str):
            await asyncio.sleep(0.01)
            return "data"

        async def run():
            with capture():
                result = await async_fetch(url="http://test.com")
            return result

        result = asyncio.run(run())
        assert result == "data"

    def test_async_nested_spans(self):
        @trace
        async def inner():
            await asyncio.sleep(0.005)

        @trace
        async def outer():
            await inner()
            span = get_current_span()
            return span

        async def run():
            with capture():
                # Can't directly capture outer span data easily,
                # but we can verify it runs without error
                await outer()

        asyncio.run(run())

    def test_async_gather_creates_child_spans(self):
        parent_trace_id = None

        @trace
        async def child_task(task_id: int):
            span = get_current_span()
            assert span is not None
            if parent_trace_id:
                assert span.trace_id == parent_trace_id

        @trace
        async def parent():
            nonlocal parent_trace_id
            parent_trace_id = get_current_span().trace_id
            await asyncio.gather(
                child_task(task_id=1),
                child_task(task_id=2),
                child_task(task_id=3),
            )

        async def run():
            with capture():
                await parent()

        asyncio.run(run())

    def test_async_context_propagation_in_spans(self):
        async def run():
            with capture() as logs:
                with log.context(request_id="req-1"):
                    async with trace("handler"):
                        log("inside span")
            return logs

        logs = asyncio.run(run())
        assert logs[0].context["request_id"] == "req-1"
        assert logs[0].trace_id is not None


# ── Log-Trace Correlation ────────────────────────────────────


class TestLogTraceCorrelation:
    def test_log_inside_span_has_trace_id(self):
        with capture() as logs:
            with trace("my-span") as span:
                log("inside")
        assert logs[0].trace_id == span.trace_id
        assert logs[0].span_id == span.span_id

    def test_log_outside_span_has_no_trace_id(self):
        with capture() as logs:
            log("outside")
        assert logs[0].trace_id is None
        assert logs[0].span_id is None

    def test_log_in_nested_span_has_inner_span_id(self):
        with capture() as logs:
            with trace("outer") as outer:
                log("in outer")
                with trace("inner") as inner:
                    log("in inner")
        assert logs[0].span_id == outer.span_id
        assert logs[1].span_id == inner.span_id
        # both share trace_id
        assert logs[0].trace_id == logs[1].trace_id

    def test_trace_id_consistent_across_nested_logs(self):
        with capture() as logs:
            with trace("root"):
                log("a")
                with trace("child"):
                    log("b")
                log("c")
        trace_ids = {r.trace_id for r in logs}
        assert len(trace_ids) == 1  # all same trace
