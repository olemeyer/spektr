from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from ._types import LogRecord, SpanData

_log_context: ContextVar[dict[str, Any]] = ContextVar("spektr_log_context", default={})
_current_span: ContextVar[SpanData | None] = ContextVar("spektr_current_span", default=None)
_capturing_sink: ContextVar[list[LogRecord] | None] = ContextVar("spektr_capturing_sink", default=None)


def get_log_context() -> dict[str, Any]:
    return _log_context.get().copy()


def merge_log_context(**kwargs: Any) -> Token:
    current = _log_context.get()
    return _log_context.set({**current, **kwargs})


def reset_log_context(token: Token) -> None:
    _log_context.reset(token)


def get_current_span() -> SpanData | None:
    return _current_span.get()


def set_current_span(span: SpanData | None) -> Token:
    return _current_span.set(span)
