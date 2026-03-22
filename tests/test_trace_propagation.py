"""Tests for trace.inject() / trace.extract() and W3C propagation."""

from __future__ import annotations

from spektr import trace
from spektr._otel._propagation import (
    TraceContext,
    extract_context,
    format_traceparent,
    inject_context,
    parse_traceparent,
)


class TestParseTraceparent:
    def test_valid_traceparent(self):
        header = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ctx = parse_traceparent(header)
        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.parent_id == "00f067aa0ba902b7"
        assert ctx.trace_flags == "01"

    def test_unsampled_trace(self):
        header = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"
        ctx = parse_traceparent(header)
        assert ctx is not None
        assert ctx.trace_flags == "00"

    def test_invalid_version(self):
        header = "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        assert parse_traceparent(header) is None

    def test_malformed_header(self):
        assert parse_traceparent("not-a-traceparent") is None

    def test_empty_string(self):
        assert parse_traceparent("") is None

    def test_all_zero_trace_id(self):
        header = "00-00000000000000000000000000000000-00f067aa0ba902b7-01"
        assert parse_traceparent(header) is None

    def test_all_zero_parent_id(self):
        header = "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01"
        assert parse_traceparent(header) is None

    def test_uppercase_normalized(self):
        header = "00-4BF92F3577B34DA6A3CE929D0E0E4736-00F067AA0BA902B7-01"
        ctx = parse_traceparent(header)
        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"

    def test_whitespace_stripped(self):
        header = "  00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01  "
        ctx = parse_traceparent(header)
        assert ctx is not None

    def test_wrong_length_trace_id(self):
        header = "00-4bf92f3577b34da6-00f067aa0ba902b7-01"
        assert parse_traceparent(header) is None


class TestFormatTraceparent:
    def test_sampled(self):
        result = format_traceparent(
            "4bf92f3577b34da6a3ce929d0e0e4736",
            "00f067aa0ba902b7",
            sampled=True,
        )
        assert result == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    def test_not_sampled(self):
        result = format_traceparent(
            "4bf92f3577b34da6a3ce929d0e0e4736",
            "00f067aa0ba902b7",
            sampled=False,
        )
        assert result == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"

    def test_roundtrip(self):
        original = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ctx = parse_traceparent(original)
        assert ctx is not None
        reconstructed = format_traceparent(ctx.trace_id, ctx.parent_id, ctx.trace_flags == "01")
        assert reconstructed == original


class TestExtractContext:
    def test_extracts_traceparent(self):
        headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        ctx = extract_context(headers)
        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"

    def test_case_insensitive(self):
        headers = {"Traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        ctx = extract_context(headers)
        assert ctx is not None

    def test_missing_header_returns_none(self):
        headers = {"content-type": "application/json"}
        assert extract_context(headers) is None

    def test_empty_headers_returns_none(self):
        assert extract_context({}) is None


class TestTraceInjectExtract:
    def test_inject_creates_headers(self):
        with trace("test-span"):
            headers = trace.inject()
        assert "traceparent" in headers

    def test_inject_with_existing_headers(self):
        with trace("test-span"):
            headers = trace.inject({"x-custom": "value"})
        assert "traceparent" in headers
        assert headers["x-custom"] == "value"

    def test_inject_without_span_returns_empty(self):
        headers = trace.inject()
        # No active span, so no traceparent should be added
        assert "traceparent" not in headers

    def test_extract_valid_context(self):
        headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        ctx = trace.extract(headers)
        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"

    def test_extract_invalid_returns_none(self):
        headers = {"traceparent": "invalid"}
        assert trace.extract(headers) is None

    def test_inject_extract_roundtrip(self):
        with trace("roundtrip"):
            injected = trace.inject()

        ctx = trace.extract(injected)
        assert ctx is not None
        assert len(ctx.trace_id) == 32
        assert len(ctx.parent_id) == 16
