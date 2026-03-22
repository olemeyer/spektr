"""ASGI middleware – auto-instruments HTTP requests with logging and tracing.

Adds to every HTTP request:
    - A unique request_id (UUID4) in the log context
    - A trace span covering the full request lifecycle
    - Start/completion log messages with method, path, status, duration
    - W3C Trace Context propagation (reads incoming traceparent header)
    - Optional health check endpoint (configurable via health_path)
    - Automatic metrics recording (request count, latency histogram)

Works with any ASGI framework (FastAPI, Starlette, Litestar, etc.).
No framework-specific imports required.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from .._context import merge_log_context, reset_log_context
from .._logger import Logger
from .._tracer import _SpanContext
from .._types import LogLevel

_logger = Logger()


def _extract_headers(scope: dict) -> dict[str, str]:
    """Extract HTTP headers from ASGI scope as a plain dict."""
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin-1") if isinstance(raw_name, bytes) else raw_name
        value = raw_value.decode("latin-1") if isinstance(raw_value, bytes) else raw_value
        headers[name.lower()] = value
    return headers


class SpektrMiddleware:
    """ASGI middleware that instruments HTTP requests.

    Usage::

        # FastAPI / Starlette
        app.add_middleware(SpektrMiddleware)

        # Any ASGI app
        app = SpektrMiddleware(app)
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Health check endpoint.
        from .._config import get_config

        config = get_config()
        path = scope.get("path", "")
        if config.health_path and path == config.health_path:
            from ._health import health_check

            await health_check(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        method = scope.get("method", "")

        # Extract W3C trace context from incoming headers.
        request_headers = _extract_headers(scope)
        trace_context = None
        try:
            from .._otel._propagation import extract_context

            trace_context = extract_context(request_headers)
        except Exception:
            pass

        status_code = 0

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        span_data = {"method": method, "path": path, "request_id": request_id}
        if trace_context is not None:
            span_data["trace_parent_id"] = trace_context.parent_id

        token = merge_log_context(request_id=request_id)
        start = time.perf_counter()
        try:
            async with _SpanContext(f"{method} {path}", span_data):
                await self.app(scope, receive, send_wrapper)

            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            _logger._emit(
                LogLevel.INFO,
                "request completed",
                {"method": method, "path": path, "status_code": status_code, "duration_ms": duration_ms},
            )

            # Record metrics.
            self._record_metrics(method, path, status_code, duration_ms)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            _logger._emit(
                LogLevel.ERROR,
                "request failed",
                {"method": method, "path": path, "duration_ms": duration_ms},
            )

            # Record error metrics.
            self._record_metrics(method, path, 500, duration_ms)
            raise
        finally:
            reset_log_context(token)

    def _record_metrics(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        """Record request metrics (count + latency histogram)."""
        try:
            from .._metrics._api import _metrics

            _metrics.count("http.requests.total", method=method, path=path, status=str(status_code))
            _metrics.histogram("http.request.duration_ms", duration_ms, method=method, path=path)
        except Exception:
            pass
