"""Tests for W3C Trace Context propagation (traceparent header)."""

from __future__ import annotations

import pytest

from spektr import capture, trace
from spektr._otel._propagation import (
    TraceContext,
    extract_context,
    format_traceparent,
    inject_context,
    parse_traceparent,
)
import spektr._otel as otel_bridge


@pytest.fixture(autouse=True)
def otel_env():
    """Ensure a clean OTel provider for each test."""
    otel_bridge.setup(service_name="propagation-test")
    yield
    otel_bridge.shutdown()


# ── parse_traceparent ─────────────────────────────────────────


class TestParseTraceparent:
    def test_valid_traceparent(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        result = parse_traceparent(header)

        assert result is not None
        assert result.trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert result.parent_id == "b7ad6b7169203331"
        assert result.trace_flags == "01"

    def test_valid_traceparent_not_sampled(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-00"
        result = parse_traceparent(header)

        assert result is not None
        assert result.trace_flags == "00"

    def test_wrong_version_returns_none(self):
        header = "01-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        assert parse_traceparent(header) is None

    def test_version_ff_returns_none(self):
        header = "ff-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        assert parse_traceparent(header) is None

    def test_trace_id_too_short(self):
        header = "00-0af7651916cd43dd8448eb211c8031-b7ad6b7169203331-01"
        assert parse_traceparent(header) is None

    def test_trace_id_too_long(self):
        header = "00-0af7651916cd43dd8448eb211c80319cab-b7ad6b7169203331-01"
        assert parse_traceparent(header) is None

    def test_parent_id_too_short(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b71692033-01"
        assert parse_traceparent(header) is None

    def test_parent_id_too_long(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b716920333100-01"
        assert parse_traceparent(header) is None

    def test_non_hex_trace_id(self):
        header = "00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-b7ad6b7169203331-01"
        assert parse_traceparent(header) is None

    def test_non_hex_parent_id(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-zzzzzzzzzzzzzzzz-01"
        assert parse_traceparent(header) is None

    def test_non_hex_trace_flags(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-zz"
        assert parse_traceparent(header) is None

    def test_empty_string(self):
        assert parse_traceparent("") is None

    def test_garbage_input(self):
        assert parse_traceparent("not-a-valid-header-at-all") is None

    def test_missing_fields(self):
        assert parse_traceparent("00-0af7651916cd43dd8448eb211c80319c") is None

    def test_all_zero_trace_id_invalid(self):
        header = "00-00000000000000000000000000000000-b7ad6b7169203331-01"
        assert parse_traceparent(header) is None

    def test_all_zero_parent_id_invalid(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-0000000000000000-01"
        assert parse_traceparent(header) is None

    def test_uppercase_is_normalized(self):
        header = "00-0AF7651916CD43DD8448EB211C80319C-B7AD6B7169203331-01"
        result = parse_traceparent(header)

        assert result is not None
        assert result.trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert result.parent_id == "b7ad6b7169203331"

    def test_whitespace_stripped(self):
        header = "  00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01  "
        result = parse_traceparent(header)

        assert result is not None
        assert result.trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_returns_frozen_dataclass(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        result = parse_traceparent(header)

        assert isinstance(result, TraceContext)
        with pytest.raises(AttributeError):
            result.trace_id = "something_else"


# ── format_traceparent ────────────────────────────────────────


class TestFormatTraceparent:
    def test_format_sampled(self):
        result = format_traceparent(
            trace_id="0af7651916cd43dd8448eb211c80319c",
            span_id="b7ad6b7169203331",
            sampled=True,
        )
        assert result == "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"

    def test_format_not_sampled(self):
        result = format_traceparent(
            trace_id="0af7651916cd43dd8448eb211c80319c",
            span_id="b7ad6b7169203331",
            sampled=False,
        )
        assert result == "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-00"

    def test_default_sampled_is_true(self):
        result = format_traceparent(
            trace_id="0af7651916cd43dd8448eb211c80319c",
            span_id="b7ad6b7169203331",
        )
        assert result.endswith("-01")

    def test_round_trip_with_parse(self):
        trace_id = "0af7651916cd43dd8448eb211c80319c"
        span_id = "b7ad6b7169203331"

        header = format_traceparent(trace_id, span_id, sampled=True)
        parsed = parse_traceparent(header)

        assert parsed is not None
        assert parsed.trace_id == trace_id
        assert parsed.parent_id == span_id
        assert parsed.trace_flags == "01"

    def test_round_trip_not_sampled(self):
        trace_id = "abcdef0123456789abcdef0123456789"
        span_id = "0123456789abcdef"

        header = format_traceparent(trace_id, span_id, sampled=False)
        parsed = parse_traceparent(header)

        assert parsed is not None
        assert parsed.trace_id == trace_id
        assert parsed.parent_id == span_id
        assert parsed.trace_flags == "00"


# ── inject_context ────────────────────────────────────────────


class TestInjectContext:
    def test_inject_with_active_span(self):
        with trace("test-span"):
            headers: dict[str, str] = {}
            inject_context(headers)

        assert "traceparent" in headers
        parsed = parse_traceparent(headers["traceparent"])
        assert parsed is not None
        assert len(parsed.trace_id) == 32
        assert len(parsed.parent_id) == 16

    def test_inject_without_active_span(self):
        headers: dict[str, str] = {}
        inject_context(headers)

        assert "traceparent" not in headers

    def test_inject_returns_same_dict(self):
        headers: dict[str, str] = {"existing": "value"}
        result = inject_context(headers)

        assert result is headers
        assert result["existing"] == "value"

    def test_inject_preserves_existing_headers(self):
        with trace("test"):
            headers = {"Authorization": "Bearer token", "Content-Type": "application/json"}
            inject_context(headers)

        assert headers["Authorization"] == "Bearer token"
        assert headers["Content-Type"] == "application/json"
        assert "traceparent" in headers

    def test_inject_span_ids_match_current_span(self):
        with trace("test") as span:
            headers: dict[str, str] = {}
            inject_context(headers)
            parsed = parse_traceparent(headers["traceparent"])

        assert parsed is not None
        assert parsed.trace_id == span.trace_id
        assert parsed.parent_id == span.span_id

    def test_inject_nested_span_uses_inner(self):
        with trace("outer") as outer_span:
            with trace("inner") as inner_span:
                headers: dict[str, str] = {}
                inject_context(headers)
                parsed = parse_traceparent(headers["traceparent"])

        assert parsed is not None
        assert parsed.trace_id == inner_span.trace_id
        assert parsed.parent_id == inner_span.span_id
        assert parsed.trace_id == outer_span.trace_id  # same trace


# ── extract_context ───────────────────────────────────────────


class TestExtractContext:
    def test_extract_valid_header(self):
        headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        result = extract_context(headers)

        assert result is not None
        assert result.trace_id == "0af7651916cd43dd8448eb211c80319c"
        assert result.parent_id == "b7ad6b7169203331"
        assert result.trace_flags == "01"

    def test_extract_missing_header(self):
        headers = {"Content-Type": "application/json"}
        assert extract_context(headers) is None

    def test_extract_empty_headers(self):
        assert extract_context({}) is None

    def test_extract_invalid_header_value(self):
        headers = {"traceparent": "invalid-garbage"}
        assert extract_context(headers) is None

    def test_extract_case_insensitive_lowercase(self):
        headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        result = extract_context(headers)
        assert result is not None

    def test_extract_case_insensitive_uppercase(self):
        headers = {
            "TRACEPARENT": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        result = extract_context(headers)
        assert result is not None
        assert result.trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_extract_case_insensitive_mixed(self):
        headers = {
            "TraceParent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        result = extract_context(headers)
        assert result is not None
        assert result.trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_extract_case_insensitive_title_case(self):
        headers = {
            "Traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        result = extract_context(headers)
        assert result is not None


# ── Full Round-Trip ───────────────────────────────────────────


class TestRoundTrip:
    def test_inject_then_extract(self):
        with trace("outgoing-request"):
            outgoing_headers: dict[str, str] = {}
            inject_context(outgoing_headers)

        # Simulate receiving these headers on the other side.
        received = extract_context(outgoing_headers)

        assert received is not None
        assert len(received.trace_id) == 32
        assert len(received.parent_id) == 16
        assert received.trace_flags == "01"

    def test_round_trip_preserves_trace_id(self):
        with trace("service-a") as span:
            headers: dict[str, str] = {}
            inject_context(headers)

        context = extract_context(headers)

        assert context is not None
        assert context.trace_id == span.trace_id

    def test_round_trip_parent_id_is_span_id(self):
        with trace("service-a") as span:
            headers: dict[str, str] = {}
            inject_context(headers)

        context = extract_context(headers)

        assert context is not None
        assert context.parent_id == span.span_id

    def test_round_trip_nested_spans(self):
        with trace("root"):
            with trace("child") as child_span:
                headers: dict[str, str] = {}
                inject_context(headers)

        context = extract_context(headers)

        assert context is not None
        assert context.trace_id == child_span.trace_id
        assert context.parent_id == child_span.span_id

    def test_multiple_inject_extract_cycles(self):
        """Simulate propagation across three services."""
        # Service A creates a span and injects context.
        with trace("service-a") as service_a_span:
            headers_a_to_b: dict[str, str] = {}
            inject_context(headers_a_to_b)

        context_at_b = extract_context(headers_a_to_b)
        assert context_at_b is not None
        assert context_at_b.trace_id == service_a_span.trace_id

        # Service B creates its own span and injects context for Service C.
        with trace("service-b") as service_b_span:
            headers_b_to_c: dict[str, str] = {}
            inject_context(headers_b_to_c)

        context_at_c = extract_context(headers_b_to_c)
        assert context_at_c is not None
        assert context_at_c.parent_id == service_b_span.span_id
