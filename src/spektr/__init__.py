"""
spektr – Zero-config Python observability.

Combines logging, tracing, and error tracking into a single, ergonomic API.
No configuration required – just import and go.

Usage::

    from spektr import log, trace

    log("hello world", user="ole")

    with trace("db-query", table="users"):
        ...

    @trace
    def process(order_id: int):
        log("processing", order_id=order_id)

Public API:
    log       – Logger instance. Call directly or use .debug/.info/.warn/.error.
    trace     – Trace instance. Use as context manager or decorator.
    configure – Override auto-detected settings (output mode, log level, etc.).
    install   – Install global exception handlers with rich tracebacks.
    capture   – Context manager to intercept log records in tests.
"""

from ._capture import capture
from ._config import configure
from ._exceptions import install
from ._logger import Logger
from ._tracer import Trace

# Module-level singletons – the primary user-facing API.
# Using instances (not classes) allows `log("msg")` instead of `Logger.info("msg")`.
log = Logger()
trace = Trace()

__all__ = ["log", "trace", "configure", "install", "capture"]
