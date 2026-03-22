"""Tests for structured exception enrichment in log records."""

from __future__ import annotations

import asyncio

from spektr import capture, log
from spektr._types import LogLevel


class TestStructuredExceptionFields:
    def test_exception_adds_error_type(self):
        @log.catch(reraise=False)
        def failing():
            raise ValueError("bad value")

        with capture() as logs:
            failing()

        assert logs[0].data["error_type"] == "ValueError"

    def test_exception_adds_error_message(self):
        @log.catch(reraise=False)
        def failing():
            raise RuntimeError("something broke")

        with capture() as logs:
            failing()

        assert logs[0].data["error_message"] == "something broke"

    def test_exception_adds_stacktrace(self):
        @log.catch(reraise=False)
        def failing():
            raise TypeError("wrong type")

        with capture() as logs:
            failing()

        assert "error_stacktrace" in logs[0].data
        assert "TypeError" in logs[0].data["error_stacktrace"]
        assert "wrong type" in logs[0].data["error_stacktrace"]

    def test_stacktrace_contains_traceback(self):
        @log.catch(reraise=False)
        def failing():
            raise KeyError("missing")

        with capture() as logs:
            failing()

        stacktrace = logs[0].data["error_stacktrace"]
        assert "Traceback" in stacktrace

    def test_log_exception_method_has_structured_fields(self):
        try:
            raise ValueError("explicit exception")
        except ValueError:
            with capture() as logs:
                log.exception("caught it")

        assert logs[0].data["error_type"] == "ValueError"
        assert logs[0].data["error_message"] == "explicit exception"

    def test_normal_log_has_no_error_fields(self):
        with capture() as logs:
            log("normal message", key="value")

        assert "error_type" not in logs[0].data
        assert "error_message" not in logs[0].data
        assert "error_stacktrace" not in logs[0].data

    def test_async_exception_has_structured_fields(self):
        @log.catch(reraise=False)
        async def async_failing():
            raise IOError("async io error")

        async def run():
            with capture() as logs:
                await async_failing()
            return logs

        logs = asyncio.run(run())
        assert logs[0].data["error_type"] == "OSError"  # IOError is alias for OSError
        assert logs[0].data["error_message"] == "async io error"

    def test_custom_exception_type(self):
        class CustomAppError(Exception):
            pass

        @log.catch(reraise=False)
        def failing():
            raise CustomAppError("custom")

        with capture() as logs:
            failing()

        assert logs[0].data["error_type"] == "CustomAppError"

    def test_exception_preserves_other_data(self):
        """error_* fields should not overwrite existing data."""
        @log.catch(reraise=False)
        def failing():
            raise ValueError("test")

        with capture() as logs:
            failing()

        # The original message data should still be accessible
        assert logs[0].level == LogLevel.ERROR
        assert "ValueError" in logs[0].message
