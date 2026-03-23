"""stdlib logging bridge – routes Python's logging through spektr.

Installs a custom logging.Handler on the root logger so that third-party
libraries (SQLAlchemy, requests, uvicorn, boto3, etc.) get the same
beautiful formatting as native spektr logs.

Recursion guard: if the spektr formatter itself triggers a stdlib log
(e.g., via Rich internals), the bridge short-circuits to prevent infinite
recursion.  Uses a contextvars guard for async safety.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from .._config import OutputMode, get_config
from .._context import _capturing_sink, get_current_span, get_log_context
from .._output._formatters import format_record_json, format_record_rich
from .._types import LogLevel, LogRecord, SourceLocation

_in_bridge: ContextVar[bool] = ContextVar("spektr_bridge_guard", default=False)

_LEVEL_MAP: dict[int, LogLevel] = {
    logging.DEBUG: LogLevel.DEBUG,
    logging.INFO: LogLevel.INFO,
    logging.WARNING: LogLevel.WARNING,
    logging.ERROR: LogLevel.ERROR,
    logging.CRITICAL: LogLevel.ERROR,
}


def _map_level(levelno: int) -> LogLevel:
    """Map a stdlib logging level number to a spektr LogLevel."""
    if levelno >= logging.ERROR:
        return LogLevel.ERROR
    if levelno >= logging.WARNING:
        return LogLevel.WARNING
    if levelno >= logging.INFO:
        return LogLevel.INFO
    return LogLevel.DEBUG


class SpektrHandler(logging.Handler):
    """logging.Handler that converts stdlib LogRecords to spektr output."""

    def emit(self, record: logging.LogRecord) -> None:
        # Recursion guard – prevent re-entry if formatter uses stdlib logging.
        if _in_bridge.get():
            return

        token = _in_bridge.set(True)
        try:
            self._handle(record)
        finally:
            _in_bridge.reset(token)

    def _handle(self, record: logging.LogRecord) -> None:
        level = _map_level(record.levelno)
        config = get_config()

        if level < config.min_level:
            return

        span = get_current_span()
        context = get_log_context()

        # Build source location from the stdlib record.
        source = SourceLocation(
            file=record.pathname,
            line=record.lineno,
            function=record.funcName,
        )

        # Extract exc_info if present.
        exc_info = None
        if record.exc_info and record.exc_info[0] is not None:
            exc_info = record.exc_info

        spektr_record = LogRecord(
            timestamp=record.created,
            level=level,
            message=record.getMessage(),
            data={"logger": record.name},
            context=context,
            source=source,
            trace_id=span.trace_id if span else None,
            span_id=span.span_id if span else None,
            exc_info=exc_info,
        )

        # Dispatch through the same pipeline as Logger._emit().
        sink = _capturing_sink.get()
        if sink is not None:
            sink.append(spektr_record)
        elif config.output_mode == OutputMode.JSON:  # pragma: no cover
            format_record_json(spektr_record)
        else:
            format_record_rich(spektr_record)


def install_bridge() -> None:
    """Attach SpektrHandler to the root logger and remove the default handler."""
    root = logging.getLogger()

    # Avoid double-installing.
    if any(isinstance(h, SpektrHandler) for h in root.handlers):
        return

    # Remove the default StreamHandler to prevent duplicate output.
    root.handlers = [h for h in root.handlers if not isinstance(h, logging.StreamHandler)]

    handler = SpektrHandler()
    handler.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
