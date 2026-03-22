"""Tests for spektr exception handling – @log.catch, install(), local variables."""

from __future__ import annotations

import asyncio
import sys

import pytest

from spektr import capture, install, log
from spektr._types import LogLevel


# ── @log.catch Decorator ─────────────────────────────────────


class TestCatchDecorator:
    def test_catch_logs_exception(self):
        @log.catch(reraise=False)
        def failing():
            raise ValueError("test error")

        with capture() as logs:
            failing()
        assert len(logs) == 1
        assert logs[0].level == LogLevel.ERROR
        assert "ValueError" in logs[0].message
        assert "test error" in logs[0].message

    def test_catch_reraise_true_by_default(self):
        @log.catch
        def failing():
            raise ValueError("should propagate")

        with capture():
            with pytest.raises(ValueError, match="should propagate"):
                failing()

    def test_catch_reraise_false_suppresses(self):
        @log.catch(reraise=False)
        def failing():
            raise ValueError("suppressed")

        with capture() as logs:
            result = failing()
        assert result is None
        assert len(logs) == 1

    def test_catch_returns_value_on_success(self):
        @log.catch
        def succeeding():
            return 42

        with capture() as logs:
            result = succeeding()
        assert result == 42
        assert len(logs) == 0

    def test_catch_preserves_function_name(self):
        @log.catch
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_catch_with_args(self):
        @log.catch(reraise=False)
        def process(x: int, y: str):
            raise RuntimeError(f"{x} {y}")

        with capture() as logs:
            process(42, "hello")
        assert "RuntimeError" in logs[0].message

    def test_catch_captures_exc_info(self):
        @log.catch(reraise=False)
        def failing():
            raise TypeError("bad type")

        with capture() as logs:
            failing()
        assert logs[0].exc_info is not None
        assert logs[0].exc_info[0] is TypeError

    def test_catch_async_function(self):
        @log.catch(reraise=False)
        async def async_failing():
            raise ValueError("async boom")

        async def run():
            with capture() as logs:
                await async_failing()
            return logs

        logs = asyncio.run(run())
        assert len(logs) == 1
        assert "ValueError" in logs[0].message

    def test_catch_async_reraise(self):
        @log.catch
        async def async_failing():
            raise RuntimeError("async propagate")

        async def run():
            with capture():
                with pytest.raises(RuntimeError):
                    await async_failing()

        asyncio.run(run())

    def test_catch_async_returns_value(self):
        @log.catch
        async def async_ok():
            return "result"

        async def run():
            with capture():
                return await async_ok()

        result = asyncio.run(run())
        assert result == "result"

    def test_catch_multiple_exceptions(self):
        call_count = 0

        @log.catch(reraise=False)
        def multi_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"fail #{call_count}")

        with capture() as logs:
            multi_fail()
            multi_fail()
            multi_fail()
        assert len(logs) == 3
        assert "fail #1" in logs[0].message
        assert "fail #2" in logs[1].message
        assert "fail #3" in logs[2].message

    def test_catch_nested_calls(self):
        @log.catch(reraise=False)
        def outer():
            return inner()

        @log.catch(reraise=False)
        def inner():
            raise ValueError("inner error")

        with capture() as logs:
            outer()
        # inner catches and suppresses, outer succeeds
        assert len(logs) == 1
        assert "inner error" in logs[0].message


# ── install() ────────────────────────────────────────────────


class TestInstall:
    def test_install_sets_excepthook(self):
        old_hook = sys.excepthook
        try:
            install()
            assert sys.excepthook is not old_hook
        finally:
            sys.excepthook = old_hook

    def test_install_idempotent(self):
        import spektr._exceptions as exc_module

        old_hook = sys.excepthook
        try:
            exc_module._installed = False
            install()
            hook1 = sys.excepthook
            install()
            hook2 = sys.excepthook
            assert hook1 is hook2
        finally:
            sys.excepthook = old_hook
            exc_module._installed = False

    def test_install_with_none_app(self):
        old_hook = sys.excepthook
        try:
            import spektr._exceptions as exc_module
            exc_module._installed = False
            install(app=None)
            assert sys.excepthook is not old_hook
        finally:
            sys.excepthook = old_hook
            exc_module._installed = False
