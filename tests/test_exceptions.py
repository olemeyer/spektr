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
        import spektr._integrations._exceptions as exc_module
        from spektr._integrations._exceptions import _excepthook

        exc_module._installed = False
        sys.excepthook = sys.__excepthook__  # reset to Python default
        try:
            install()
            assert sys.excepthook is _excepthook
        finally:
            sys.excepthook = sys.__excepthook__
            exc_module._installed = False

    def test_install_idempotent(self):
        import spektr._integrations._exceptions as exc_module

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
        import spektr._integrations._exceptions as exc_module
        from spektr._integrations._exceptions import _excepthook

        exc_module._installed = False
        sys.excepthook = sys.__excepthook__  # reset to Python default
        try:
            install(app=None)
            assert sys.excepthook is _excepthook
        finally:
            sys.excepthook = sys.__excepthook__
            exc_module._installed = False

    def test_install_sets_threading_excepthook(self):
        import threading
        import spektr._integrations._exceptions as exc_module
        from spektr._integrations._exceptions import _threading_excepthook

        old_hook = sys.excepthook
        try:
            exc_module._installed = False
            install()
            assert threading.excepthook is _threading_excepthook
        finally:
            sys.excepthook = old_hook
            exc_module._installed = False

    def test_install_activates_bridge(self):
        """install() should add SpektrHandler to root logger."""
        import logging
        import spektr._integrations._exceptions as exc_module
        from spektr._integrations._bridge import SpektrHandler

        old_hook = sys.excepthook
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            exc_module._installed = False
            install()
            assert any(isinstance(h, SpektrHandler) for h in root.handlers)
        finally:
            sys.excepthook = old_hook
            root.handlers = original_handlers
            exc_module._installed = False

    def test_install_with_fastapi_app(self):
        """install(app) with FastAPI-like app adds middleware."""
        import spektr._integrations._exceptions as exc_module

        added = []

        class FakeApp:
            def add_middleware(self, cls):
                added.append(cls)

        app = FakeApp()
        app.__class__.__name__ = "FastAPI"

        old_hook = sys.excepthook
        try:
            exc_module._installed = False
            install(app=app)
            assert len(added) == 1
        finally:
            sys.excepthook = old_hook
            exc_module._installed = False


class TestInstallFramework:
    def test_unknown_class_name_no_error(self):
        from spektr._integrations._exceptions import _install_framework

        class Flask:
            pass

        app = Flask()
        _install_framework(app)  # Should not raise

    def test_starlette_adds_middleware(self):
        from spektr._integrations._exceptions import _install_framework
        from spektr._integrations._middleware import SpektrMiddleware

        added = []

        class FakeStarlette:
            def add_middleware(self, cls):
                added.append(cls)

        app = FakeStarlette()
        app.__class__.__name__ = "Starlette"
        _install_framework(app)

        assert added == [SpektrMiddleware]


class TestCatchEdgeCases:
    def test_catch_with_none_argument(self):
        """log.catch() with no arguments should work as decorator factory."""
        @log.catch()
        def failing():
            raise ValueError("test")

        with capture() as logs:
            with pytest.raises(ValueError):
                failing()

        assert len(logs) == 1

    def test_catch_async_suppressed_returns_none(self):
        @log.catch(reraise=False)
        async def async_failing():
            raise ValueError("async suppressed")

        async def run():
            with capture() as logs:
                result = await async_failing()
            return logs, result

        logs, result = asyncio.run(run())
        assert result is None
        assert len(logs) == 1

    def test_catch_preserves_async_function_name(self):
        @log.catch
        async def my_async_func():
            pass

        assert my_async_func.__name__ == "my_async_func"

    def test_catch_with_generator_function(self):
        """catch should work with functions that have various signatures."""
        @log.catch(reraise=False)
        def variadic(*args, **kwargs):
            raise RuntimeError(f"args={len(args)}")

        with capture() as logs:
            variadic(1, 2, 3, key="val")

        assert "args=3" in logs[0].message


# ── Exception Hooks ─────────────────────────────────────────


class TestExceptHook:
    def test_excepthook_runs_without_crash(self):
        """_excepthook should render without crashing."""
        import io
        import threading
        from unittest.mock import patch

        from spektr._integrations._exceptions import _excepthook

        try:
            raise ValueError("test hook")
        except ValueError:
            exc_type, exc_val, exc_tb = sys.exc_info()

            with patch("spektr._output._formatters._get_console") as mock_console:
                mock_console.return_value = __import__("rich.console", fromlist=["Console"]).Console(
                    file=io.StringIO(), width=80
                )
                _excepthook(exc_type, exc_val, exc_tb)

    def test_threading_excepthook_runs(self):
        """_threading_excepthook should call _excepthook."""
        import io
        import threading
        from unittest.mock import patch

        from spektr._integrations._exceptions import _threading_excepthook

        try:
            raise RuntimeError("thread error")
        except RuntimeError:
            exc_type, exc_val, exc_tb = sys.exc_info()

            args = threading.ExceptHookArgs((exc_type, exc_val, exc_tb, None))

            with patch("spektr._output._formatters._get_console") as mock_console:
                mock_console.return_value = __import__("rich.console", fromlist=["Console"]).Console(
                    file=io.StringIO(), width=80
                )
                _threading_excepthook(args)

    def test_threading_excepthook_skips_none(self):
        """_threading_excepthook should skip if exc_type is None."""
        import threading

        from spektr._integrations._exceptions import _threading_excepthook

        args = threading.ExceptHookArgs((None, None, None, None))
        _threading_excepthook(args)  # should not crash
