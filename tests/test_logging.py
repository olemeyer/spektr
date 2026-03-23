"""Tests for spektr logging – the core of the library."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from spektr import capture, log
from spektr import LogLevel


# ── Basic Logging ────────────────────────────────────────────


class TestBasicLogging:
    def test_log_default_is_info(self):
        with capture() as logs:
            log("hello world")
        assert len(logs) == 1
        assert logs[0].level == LogLevel.INFO
        assert logs[0].message == "hello world"

    def test_log_debug(self):
        with capture() as logs:
            log.debug("debug msg")
        assert logs[0].level == LogLevel.DEBUG

    def test_log_info(self):
        with capture() as logs:
            log.info("info msg")
        assert logs[0].level == LogLevel.INFO

    def test_log_warn(self):
        with capture() as logs:
            log.warn("warn msg")
        assert logs[0].level == LogLevel.WARNING

    def test_log_warning(self):
        with capture() as logs:
            log.warning("warning msg")
        assert logs[0].level == LogLevel.WARNING

    def test_log_error(self):
        with capture() as logs:
            log.error("error msg")
        assert logs[0].level == LogLevel.ERROR

    def test_log_exception_captures_exc_info(self):
        with capture() as logs:
            try:
                raise ValueError("boom")
            except ValueError:
                log.exception("caught it")
        assert logs[0].level == LogLevel.ERROR
        assert logs[0].exc_info is not None
        assert logs[0].exc_info[0] is ValueError

    def test_log_exception_without_active_exception(self):
        with capture() as logs:
            log.exception("no exception active")
        assert logs[0].level == LogLevel.ERROR
        # exc_info should be (None, None, None)
        assert logs[0].exc_info[0] is None


# ── Structured Data ──────────────────────────────────────────


class TestStructuredData:
    def test_kwargs_stored_as_data(self):
        with capture() as logs:
            log("order created", order_id=42, amount=99.99)
        assert logs[0].data == {"order_id": 42, "amount": 99.99}

    def test_no_kwargs_empty_data(self):
        with capture() as logs:
            log("plain message")
        assert logs[0].data == {}

    def test_various_value_types(self):
        with capture() as logs:
            log(
                "types",
                string="hello",
                integer=42,
                floating=3.14,
                boolean=True,
                none_val=None,
                a_list=[1, 2, 3],
                a_dict={"nested": "value"},
            )
        d = logs[0].data
        assert d["string"] == "hello"
        assert d["integer"] == 42
        assert d["floating"] == 3.14
        assert d["boolean"] is True
        assert d["none_val"] is None
        assert d["a_list"] == [1, 2, 3]
        assert d["a_dict"] == {"nested": "value"}

    def test_special_characters_in_message(self):
        with capture() as logs:
            log("hello\nworld\ttab")
        assert logs[0].message == "hello\nworld\ttab"

    def test_empty_string_message(self):
        with capture() as logs:
            log("")
        assert logs[0].message == ""

    def test_unicode_message(self):
        with capture() as logs:
            log("日本語テスト 🚀", emoji="🎉")
        assert logs[0].message == "日本語テスト 🚀"
        assert logs[0].data["emoji"] == "🎉"


# ── Context ──────────────────────────────────────────────────


class TestContext:
    def test_context_adds_to_logs(self):
        with capture() as logs:
            with log.context(request_id="abc-123"):
                log("inside context")
        assert logs[0].context["request_id"] == "abc-123"

    def test_context_removed_after_exit(self):
        with capture() as logs:
            with log.context(request_id="abc"):
                log("inside")
            log("outside")
        assert "request_id" in logs[0].context
        assert "request_id" not in logs[1].context

    def test_nested_context(self):
        with capture() as logs:
            with log.context(a="1"):
                with log.context(b="2"):
                    log("nested")
                log("outer only")
        assert logs[0].context == {"a": "1", "b": "2"}
        assert logs[1].context == {"a": "1"}

    def test_context_override(self):
        with capture() as logs:
            with log.context(x="old"):
                with log.context(x="new"):
                    log("overridden")
                log("restored")
        assert logs[0].context["x"] == "new"
        assert logs[1].context["x"] == "old"

    def test_context_with_data_kwargs(self):
        with capture() as logs:
            with log.context(request_id="abc"):
                log("msg", extra_key="val")
        assert logs[0].context == {"request_id": "abc"}
        assert logs[0].data == {"extra_key": "val"}

    def test_context_async(self):
        async def run():
            with capture() as logs:
                with log.context(async_ctx="yes"):
                    log("before await")
                    await asyncio.sleep(0)
                    log("after await")
            return logs

        logs = asyncio.run(run())
        assert all(r.context.get("async_ctx") == "yes" for r in logs)

    def test_context_isolated_across_tasks(self):
        results = {}

        async def task(name: str):
            with log.context(task=name):
                await asyncio.sleep(0.01)
                with capture() as logs:
                    log(f"from {name}")
                results[name] = logs[0].context.get("task")

        async def run():
            await asyncio.gather(task("a"), task("b"), task("c"))

        asyncio.run(run())
        assert results == {"a": "a", "b": "b", "c": "c"}

    def test_many_context_levels(self):
        from contextlib import ExitStack

        with capture() as logs:
            with ExitStack() as stack:
                for i in range(20):
                    stack.enter_context(log.context(**{f"level_{i}": i}))
                log("deep")
        assert len(logs[0].context) == 20
        assert logs[0].context["level_0"] == 0
        assert logs[0].context["level_19"] == 19


# ── Bind ─────────────────────────────────────────────────────


class TestBind:
    def test_bind_creates_new_logger(self):
        db = log.bind(component="database")
        assert db is not log

    def test_bind_adds_permanent_context(self):
        with capture() as logs:
            db = log.bind(component="database")
            db("query executed")
        assert logs[0].context["component"] == "database"

    def test_bind_does_not_affect_original(self):
        with capture() as logs:
            db = log.bind(component="database")
            log("from original")
            db("from bound")
        assert "component" not in logs[0].context
        assert logs[1].context["component"] == "database"

    def test_bind_chaining(self):
        with capture() as logs:
            db = log.bind(component="db").bind(host="localhost")
            db("connected")
        assert logs[0].context == {"component": "db", "host": "localhost"}

    def test_bind_with_context(self):
        with capture() as logs:
            db = log.bind(component="db")
            with db.context(query_id="q1"):
                db("executing")
        assert logs[0].context["component"] == "db"
        assert logs[0].context["query_id"] == "q1"

    def test_bind_override(self):
        with capture() as logs:
            db = log.bind(env="prod")
            db2 = db.bind(env="staging")
            db2("msg")
        assert logs[0].context["env"] == "staging"


# ── Source Location ──────────────────────────────────────────


class TestSourceLocation:
    def test_source_file_and_line(self):
        with capture() as logs:
            log("source test")
        src = logs[0].source
        assert src is not None
        assert "test_logging.py" in src.file
        assert isinstance(src.line, int)
        assert src.line > 0

    def test_source_points_to_caller_not_internals(self):
        with capture() as logs:
            log("hello")
        src = logs[0].source
        assert src is not None
        assert "spektr" not in src.file or "test_" in src.file

    def test_source_from_different_methods(self):
        with capture() as logs:
            log("call")
            log.info("info")
            log.debug("debug")
            log.warn("warn")
            log.error("error")
        for record in logs:
            assert record.source is not None
            assert "test_logging.py" in record.source.file


# ── Timestamp ────────────────────────────────────────────────


class TestTimestamp:
    def test_timestamp_is_recent(self):
        before = time.time()
        with capture() as logs:
            log("now")
        after = time.time()
        assert before <= logs[0].timestamp <= after

    def test_timestamps_are_ordered(self):
        with capture() as logs:
            for i in range(10):
                log(f"msg {i}")
        timestamps = [r.timestamp for r in logs]
        assert timestamps == sorted(timestamps)


# ── Thread Safety ────────────────────────────────────────────


class TestThreadSafety:
    def test_logging_from_multiple_threads(self):
        """Threads get their own context, so we test that logging doesn't crash."""
        results = []
        lock = threading.Lock()

        def worker(i: int):
            with capture() as logs:
                log(f"thread-{i}")
            with lock:
                results.append(logs[0].message)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 10
        assert set(results) == {f"thread-{i}" for i in range(10)}

    def test_context_isolated_across_threads(self):
        results = {}

        def worker(thread_id: int):
            with log.context(thread=thread_id):
                time.sleep(0.01)
                with capture() as logs:
                    log("from thread")
                results[thread_id] = logs[0].context.get("thread")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for i in range(5):
            assert results[i] == i


# ── Capture ──────────────────────────────────────────────────


class TestCapture:
    def test_capture_collects_logs(self):
        with capture() as logs:
            log("one")
            log("two")
            log("three")
        assert len(logs) == 3

    def test_capture_contains(self):
        with capture() as logs:
            log("hello world")
        assert "hello" in logs
        assert "nonexistent" not in logs

    def test_capture_messages(self):
        with capture() as logs:
            log("a")
            log("b")
        assert logs.messages == ["a", "b"]

    def test_capture_filter_by_level(self):
        with capture() as logs:
            log.debug("d")
            log.info("i")
            log.warn("w")
            log.error("e")
        errors = logs.filter(level=LogLevel.ERROR)
        assert len(errors) == 1
        assert errors[0].message == "e"

    def test_capture_filter_by_data(self):
        with capture() as logs:
            log("a", x=1)
            log("b", x=2)
            log("c", x=1)
        filtered = logs.filter(x=1)
        assert len(filtered) == 2

    def test_capture_iteration(self):
        with capture() as logs:
            log("a")
            log("b")
        messages = [r.message for r in logs]
        assert messages == ["a", "b"]

    def test_capture_indexing(self):
        with capture() as logs:
            log("first")
            log("second")
        assert logs[0].message == "first"
        assert logs[1].message == "second"

    def test_nested_capture(self):
        with capture() as outer:
            log("outer")
            with capture() as inner:
                log("inner")
            log("outer again")
        assert len(inner) == 1
        assert inner[0].message == "inner"
        assert len(outer) == 2
        assert outer.messages == ["outer", "outer again"]

    def test_capture_does_not_leak(self):
        """After capture exits, logs should go to normal output again."""
        with capture() as logs:
            log("captured")
        # This should NOT raise – it goes to the real formatter
        log("not captured")
        assert len(logs) == 1


# ── Message Formatting ─────────────────────────────────────


class TestMessageFormatting:
    def test_format_with_kwargs(self):
        with capture() as logs:
            log("user {name} connected", name="ole")

        assert logs[0].message == "user ole connected"
        assert logs[0].data["name"] == "ole"

    def test_format_multiple_placeholders(self):
        with capture() as logs:
            log("{method} {path} completed", method="GET", path="/users")

        assert logs[0].message == "GET /users completed"
        assert logs[0].data["method"] == "GET"
        assert logs[0].data["path"] == "/users"

    def test_no_placeholders_unchanged(self):
        with capture() as logs:
            log("plain message", key="value")

        assert logs[0].message == "plain message"

    def test_missing_placeholder_key_keeps_original(self):
        with capture() as logs:
            log("user {name} on {host}", name="ole")

        # {host} not in kwargs — message stays as-is
        assert logs[0].message == "user {name} on {host}"

    def test_format_with_numbers(self):
        with capture() as logs:
            log("processed {count} items in {duration_ms}ms", count=42, duration_ms=123.4)

        assert logs[0].message == "processed 42 items in 123.4ms"

    def test_format_on_all_levels(self):
        with capture() as logs:
            log.debug("debug {x}", x=1)
            log.info("info {x}", x=2)
            log.warn("warn {x}", x=3)
            log.error("error {x}", x=4)

        assert logs[0].message == "debug 1"
        assert logs[1].message == "info 2"
        assert logs[2].message == "warn 3"
        assert logs[3].message == "error 4"

    def test_format_with_exception(self):
        with capture() as logs:
            try:
                raise ValueError("test")
            except ValueError:
                log.exception("failed in {component}", component="db")

        assert logs[0].message == "failed in db"

    def test_format_on_bound_logger(self):
        db = log.bind(component="database")
        with capture() as logs:
            db("query on {table}", table="users")

        assert logs[0].message == "query on users"
        assert logs[0].context["component"] == "database"

    def test_format_empty_braces_no_crash(self):
        """Empty braces {} without positional args should not crash."""
        with capture() as logs:
            log("value is {}", key="val")

        # format() with {} but no positional args raises IndexError,
        # so message stays unchanged
        assert logs[0].message == "value is {}"


# ── Async Context Manager ──────────────────────────────────


class TestAsyncContextManager:
    def test_async_context_manager(self):
        async def run():
            with capture() as logs:
                async with log.context(request_id="abc"):
                    log("inside async context")
            return logs

        logs = asyncio.run(run())
        assert logs[0].context["request_id"] == "abc"


# ── LogLevel ────────────────────────────────────────────────


class TestLogLevel:
    def test_label_property(self):
        assert LogLevel.DEBUG.label == "DEBUG"
        assert LogLevel.INFO.label == "INFO"
        assert LogLevel.WARNING.label == "WARNING"
        assert LogLevel.ERROR.label == "ERROR"


# ── Source Location Edge Cases ──────────────────────────────


class TestSourceLocationEdgeCases:
    def test_get_source_with_deep_depth(self):
        """_get_source should return None for unreachable frame depth."""
        from spektr._core._logger import _get_source

        # Request a frame deeper than the actual call stack
        result = _get_source(9999)
        assert result is None

    def test_relpath_fallback(self):
        """Source location should handle relpath failures (e.g., Windows cross-drive)."""
        from unittest.mock import patch

        with capture() as logs:
            with patch("os.path.relpath", side_effect=ValueError("cross-drive")):
                log("test relpath fallback")

        assert len(logs) == 1
        # Source should still be set (using basename fallback)
        assert logs[0].source is not None
