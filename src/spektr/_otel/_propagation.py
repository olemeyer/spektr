"""W3C Trace Context propagation (traceparent header).

Implements parsing and formatting of the W3C ``traceparent`` header as
defined in https://www.w3.org/TR/trace-context/. This allows spektr to
participate in distributed traces across service boundaries.

Functions:
    parse_traceparent   – Parse a traceparent header string.
    format_traceparent  – Build a traceparent header string.
    inject_context      – Add traceparent header from the current OTel span.
    extract_context     – Read traceparent header from an incoming dict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opentelemetry import trace as otel_trace
from opentelemetry.trace import get_current_span

# Pre-compiled pattern for the traceparent header value.
# Format: {version}-{trace_id}-{parent_id}-{trace_flags}
_TRACEPARENT_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

_TRACEPARENT_KEY = "traceparent"


@dataclass(frozen=True)
class TraceContext:
    """Parsed W3C trace context extracted from a traceparent header."""

    trace_id: str
    parent_id: str
    trace_flags: str


def parse_traceparent(header: str) -> TraceContext | None:
    """Parse a W3C traceparent header string.

    Expected format::

        {version}-{trace_id}-{parent_id}-{trace_flags}

    Where:
        - version is ``"00"``
        - trace_id is 32 lowercase hex characters
        - parent_id is 16 lowercase hex characters
        - trace_flags is 2 lowercase hex characters

    Returns ``None`` if the header is malformed or uses an unsupported version.
    """
    match = _TRACEPARENT_RE.match(header.strip().lower())
    if match is None:
        return None

    version, trace_id, parent_id, trace_flags = match.groups()

    if version != "00":
        return None

    # All-zero trace_id or parent_id are explicitly invalid per the spec.
    if trace_id == "0" * 32 or parent_id == "0" * 16:
        return None

    return TraceContext(
        trace_id=trace_id,
        parent_id=parent_id,
        trace_flags=trace_flags,
    )


def format_traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    """Format a W3C traceparent header string.

    Args:
        trace_id: 32-character hex trace identifier.
        span_id: 16-character hex span identifier.
        sampled: Whether the trace is sampled (sets trace-flags bit 0).

    Returns:
        A traceparent header value like ``00-{trace_id}-{span_id}-{flags}``.
    """
    trace_flags = "01" if sampled else "00"
    return f"00-{trace_id}-{span_id}-{trace_flags}"


def inject_context(headers: dict[str, str]) -> dict[str, str]:
    """Add a ``traceparent`` header from the current OTel span context.

    If there is no active span (or the span context is invalid), the
    headers dict is returned unchanged.

    Args:
        headers: Mutable mapping of HTTP headers.

    Returns:
        The same *headers* dict, potentially with a ``traceparent`` key added.
    """
    span = get_current_span()
    context = span.get_span_context()

    if context is None or not context.is_valid:
        return headers

    trace_id = format(context.trace_id, "032x")
    span_id = format(context.span_id, "016x")
    sampled = bool(context.trace_flags & otel_trace.TraceFlags.SAMPLED)

    headers[_TRACEPARENT_KEY] = format_traceparent(trace_id, span_id, sampled=sampled)
    return headers


def extract_context(headers: dict[str, str]) -> TraceContext | None:
    """Extract trace context from HTTP headers (case-insensitive key lookup).

    Looks for the ``traceparent`` header in the provided mapping using a
    case-insensitive search, then parses it.

    Args:
        headers: Mapping of HTTP header names to values.

    Returns:
        A :class:`TraceContext` if a valid traceparent header is found,
        otherwise ``None``.
    """
    for key, value in headers.items():
        if key.lower() == _TRACEPARENT_KEY:
            return parse_traceparent(value)
    return None
