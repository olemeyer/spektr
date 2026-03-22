"""Tests for spektr output formatting – Rich and JSON."""

from __future__ import annotations

import json
import sys
import time
from io import StringIO
from unittest.mock import patch

import pytest

from spektr._config import OutputMode, configure
from spektr._formatters import (
    _format_duration,
    _format_value,
    format_record_json,
    format_trace_json,
)
from spektr._types import LogLevel, LogRecord, SourceLocation, SpanData
import spektr._config as config_module


@pytest.fixture(autouse=True)
def reset_config():
    config_module._config = None
    yield
    config_module._config = None


def _make_record(**kwargs) -> LogRecord:
    defaults = dict(
        timestamp=time.time(),
        level=LogLevel.INFO,
        message="test message",
        data={},
        context={},
        source=SourceLocation(file="test.py", line=42, function="test_func"),
        trace_id=None,
        span_id=None,
        exc_info=None,
    )
    defaults.update(kwargs)
    return LogRecord(**defaults)


def _make_span(**kwargs) -> SpanData:
    defaults = dict(
        name="test-span",
        span_id="abcd1234abcd1234",
        trace_id="1234abcd1234abcd1234abcd1234abcd",
        parent_id=None,
        start_time=100.0,
        end_time=100.05,
        data={},
    )
    defaults.update(kwargs)
    return SpanData(**defaults)


# ── Format Helpers ───────────────────────────────────────────


class TestFormatHelpers:
    def test_format_duration_microseconds(self):
        assert _format_duration(0.5) == "500us"

    def test_format_duration_milliseconds(self):
        assert _format_duration(42.3) == "42.3ms"

    def test_format_duration_seconds(self):
        assert _format_duration(1500) == "1.50s"

    def test_format_value_string(self):
        assert _format_value("hello") == "hello"

    def test_format_value_int(self):
        assert _format_value(42) == "42"

    def test_format_value_none(self):
        assert _format_value(None) == "None"

    def test_format_value_list(self):
        assert _format_value([1, 2]) == "[1, 2]"


# ── JSON Record Formatting ──────────────────────────────────


class TestJSONRecordFormat:
    def test_basic_json_output(self):
        record = _make_record(message="hello", data={"key": "val"})
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert output["msg"] == "hello"
        assert output["level"] == "info"
        assert output["key"] == "val"

    def test_json_includes_trace_ids(self):
        record = _make_record(trace_id="t123", span_id="s456")
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert output["trace_id"] == "t123"
        assert output["span_id"] == "s456"

    def test_json_no_trace_ids_when_absent(self):
        record = _make_record()
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert "trace_id" not in output
        assert "span_id" not in output

    def test_json_includes_source(self):
        record = _make_record(source=SourceLocation("app.py", 10, "main"))
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert output["source"] == "app.py:10"

    def test_json_includes_error_info(self):
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()
        record = _make_record(exc_info=exc_info)
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert output["error"]["type"] == "ValueError"
        assert output["error"]["message"] == "test error"

    def test_json_flattens_context_and_data(self):
        record = _make_record(context={"ctx_key": "ctx_val"}, data={"data_key": "data_val"})
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert output["ctx_key"] == "ctx_val"
        assert output["data_key"] == "data_val"

    def test_json_data_overrides_context_on_collision(self):
        record = _make_record(context={"key": "from_context"}, data={"key": "from_data"})
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert output["key"] == "from_data"

    def test_json_handles_non_serializable_values(self):
        record = _make_record(data={"obj": object()})
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_record_json(record)
        output = json.loads(buf.getvalue())
        assert "object" in output["obj"].lower()

    def test_json_levels(self):
        for level in LogLevel:
            record = _make_record(level=level)
            buf = StringIO()
            with patch.object(sys, "stderr", buf):
                format_record_json(record)
            output = json.loads(buf.getvalue())
            assert output["level"] == level.name.lower()


# ── JSON Trace Formatting ────────────────────────────────────


class TestJSONTraceFormat:
    def test_basic_trace_json(self):
        span = _make_span(name="root")
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_trace_json(span)
        output = json.loads(buf.getvalue())
        assert output["name"] == "root"
        assert output["status"] == "ok"
        assert output["duration_ms"] is not None

    def test_trace_json_with_children(self):
        child = _make_span(
            name="child",
            span_id="child123",
            parent_id="parent123",
            start_time=100.01,
            end_time=100.02,
        )
        parent = _make_span(name="parent", span_id="parent123", children=[child])
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_trace_json(parent)
        output = json.loads(buf.getvalue())
        assert len(output["children"]) == 1
        assert output["children"][0]["name"] == "child"

    def test_trace_json_with_error(self):
        span = _make_span(status="error", error=ValueError("boom"))
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_trace_json(span)
        output = json.loads(buf.getvalue())
        assert output["status"] == "error"
        assert output["error"]["type"] == "ValueError"

    def test_trace_json_with_attributes(self):
        span = _make_span(data={"table": "users", "rows": 42})
        buf = StringIO()
        with patch.object(sys, "stderr", buf):
            format_trace_json(span)
        output = json.loads(buf.getvalue())
        assert output["attributes"]["table"] == "users"
        assert output["attributes"]["rows"] == 42


# ── Rich Formatting (smoke tests) ───────────────────────────


class TestRichFormat:
    def test_rich_does_not_crash_on_basic_record(self):
        from spektr._formatters import format_record_rich

        record = _make_record(message="hello", data={"key": "val"})
        # Should not raise
        format_record_rich(record)

    def test_rich_does_not_crash_on_exception(self):
        from spektr._formatters import format_record_rich

        try:
            raise ValueError("test")
        except ValueError:
            exc_info = sys.exc_info()
        record = _make_record(exc_info=exc_info)
        format_record_rich(record)

    def test_rich_does_not_crash_on_no_source(self):
        from spektr._formatters import format_record_rich

        record = _make_record(source=None)
        format_record_rich(record)

    def test_rich_trace_tree_does_not_crash(self):
        from spektr._formatters import format_trace_rich

        child = _make_span(name="child", parent_id="p", start_time=100.01, end_time=100.02)
        root = _make_span(name="root", children=[child])
        format_trace_rich(root)

    def test_rich_trace_tree_with_error(self):
        from spektr._formatters import format_trace_rich

        span = _make_span(name="fail", status="error", error=RuntimeError("boom"))
        format_trace_rich(span)
