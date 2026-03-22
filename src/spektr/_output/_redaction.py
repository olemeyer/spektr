"""Redaction logic for sensitive data in log records."""

from __future__ import annotations

import json

_REDACTED = "***"


def redact_dict(data: dict, patterns: list[str]) -> dict:
    """Replace values whose keys match any redaction pattern."""
    if not patterns:
        return data
    redacted = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(pattern in key_lower for pattern in patterns):
            redacted[key] = _REDACTED
        else:
            redacted[key] = value
    return redacted


def redact_body(body: str, patterns: list[str], max_length: int = 10240) -> str:
    """Redact sensitive values in a request/response body string.

    If the body exceeds *max_length*, it is truncated before redaction
    is attempted. JSON bodies with top-level dict structure have their
    keys checked against the redaction patterns.
    """
    if len(body) > max_length:
        body = body[:max_length] + "...[truncated]"
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            redacted = redact_dict(parsed, patterns)
            return json.dumps(redacted)
    except (json.JSONDecodeError, ValueError):
        pass
    return body
