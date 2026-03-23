"""Tests for log.time() – performance measurement."""

import asyncio
import time

import pytest

from spektr import capture, log
from spektr import LogLevel


class TestTimeContextManager:
    def test_logs_duration(self):
        with capture() as logs:
            with log.time("db query"):
                time.sleep(0.02)

        assert len(logs) == 1
        assert logs[0].message == "db query"
        assert logs[0].data["duration_ms"] >= 15

    def test_includes_kwargs(self):
        with capture() as logs:
            with log.time("db query", table="users", operation="select"):
                pass

        assert logs[0].data["table"] == "users"
        assert logs[0].data["operation"] == "select"

    def test_has_duration_ms_key(self):
        with capture() as logs:
            with log.time("op"):
                pass

        assert "duration_ms" in logs[0].data

    def test_logs_at_info_level(self):
        with capture() as logs:
            with log.time("op"):
                pass

        assert logs[0].level == LogLevel.INFO

    def test_duration_is_float(self):
        with capture() as logs:
            with log.time("op"):
                pass

        assert isinstance(logs[0].data["duration_ms"], float)


class TestTimeDecorator:
    def test_bare_decorator(self):
        @log.time
        def my_function():
            return 42

        with capture() as logs:
            result = my_function()

        assert result == 42
        assert len(logs) == 1
        assert "duration_ms" in logs[0].data

    def test_decorator_uses_qualname(self):
        @log.time
        def process_order():
            pass

        with capture() as logs:
            process_order()

        assert "process_order" in logs[0].message

    def test_decorator_with_name(self):
        @log.time("custom name")
        def process():
            pass

        with capture() as logs:
            process()

        assert logs[0].message == "custom name"

    def test_decorator_with_kwargs(self):
        @log.time("work", component="db")
        def query():
            return "result"

        with capture() as logs:
            result = query()

        assert result == "result"
        assert logs[0].data["component"] == "db"

    def test_decorator_preserves_function_name(self):
        @log.time
        def my_func():
            pass

        assert my_func.__name__ == "my_func"


class TestTimeAsync:
    def test_async_context_manager(self):
        async def run():
            with capture() as logs:
                async with log.time("async op"):
                    await asyncio.sleep(0.01)
            return logs

        logs = asyncio.run(run())
        assert len(logs) == 1
        assert logs[0].data["duration_ms"] >= 5

    def test_async_decorator(self):
        @log.time
        async def async_process():
            await asyncio.sleep(0.01)
            return "done"

        async def run():
            with capture() as logs:
                result = await async_process()
            return logs, result

        logs, result = asyncio.run(run())
        assert result == "done"
        assert len(logs) == 1
        assert logs[0].data["duration_ms"] >= 5


class TestTimeEdgeCases:
    def test_time_invalid_argument_raises(self):
        with pytest.raises(TypeError, match="unexpected argument"):
            log.time(123)

    def test_time_context_manager_reuse(self):
        """Using the same timer context twice should work."""
        timer = log.time("reuse test")
        with capture() as logs:
            with timer:
                pass
        assert len(logs) == 1
        assert logs[0].message == "reuse test"

    def test_time_zero_duration(self):
        """An operation that takes near-zero time should still produce valid duration."""
        with capture() as logs:
            with log.time("instant"):
                pass
        assert logs[0].data["duration_ms"] >= 0

    def test_time_decorator_with_args(self):
        """Decorated function should pass through arguments correctly."""
        @log.time
        def add(a, b):
            return a + b

        with capture() as logs:
            result = add(3, 4)

        assert result == 7
        assert len(logs) == 1

    def test_time_decorator_with_kwargs_passthrough(self):
        """Decorated function should pass through keyword arguments."""
        @log.time
        def greet(name, greeting="hello"):
            return f"{greeting} {name}"

        with capture() as logs:
            result = greet("ole", greeting="hi")

        assert result == "hi ole"

    def test_time_none_returns_decorator(self):
        """log.time(None, key=val) should work as decorator factory."""
        @log.time(None, component="db")
        def query():
            return "result"

        with capture() as logs:
            result = query()

        assert result == "result"
        assert logs[0].data["component"] == "db"

    def test_time_named_decorator_preserves_name(self):
        @log.time("custom")
        def my_func():
            pass

        assert my_func.__name__ == "my_func"

    def test_time_async_decorator_with_name(self):
        @log.time("async custom")
        async def my_async():
            return 99

        async def run():
            with capture() as logs:
                result = await my_async()
            return logs, result

        logs, result = asyncio.run(run())
        assert result == 99
        assert logs[0].message == "async custom"

    def test_time_async_decorator_preserves_name(self):
        @log.time
        async def my_async_func():
            pass

        assert my_async_func.__name__ == "my_async_func"


class TestTimeBoundLogger:
    def test_time_on_bound_logger(self):
        db = log.bind(component="database")
        with capture() as logs:
            with db.time("query", table="users"):
                pass

        assert logs[0].context["component"] == "database"
        assert logs[0].data["table"] == "users"
        assert "duration_ms" in logs[0].data

    def test_time_decorator_on_bound_logger(self):
        db = log.bind(component="database")

        @db.time
        def query():
            return "rows"

        with capture() as logs:
            result = query()

        assert result == "rows"
        assert logs[0].context["component"] == "database"
        assert "duration_ms" in logs[0].data

    def test_time_named_decorator_on_bound_logger(self):
        db = log.bind(component="database")

        @db.time("slow query")
        def query():
            return "rows"

        with capture() as logs:
            query()

        assert logs[0].message == "slow query"
        assert logs[0].context["component"] == "database"
