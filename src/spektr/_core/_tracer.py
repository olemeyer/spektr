"""Distributed tracing – spans, trace trees, and decorator instrumentation.

Architecture:
    Trace       – User-facing callable (context manager + decorator).
    _SpanContext – Internal context manager that creates an OTel span and
                   a parallel SpanData (used for rich console trace trees).
    _extract_args – Introspects function signatures to auto-capture arguments.

Every span is backed by a real OTel span (IDs, context propagation, export).
SpanData is a lightweight mirror used solely for rendering trace trees to
the console – it is NOT a second tracing system.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable
from typing import Any

from .. import _otel
from .._config import OutputMode, get_config
from .._context import get_current_span, set_current_span
from .._output._formatters import format_trace_json, format_trace_rich
from .._types import SpanData


class _SpanContext:
    """Context manager that wraps a single span's lifecycle.

    On enter: creates an OTel span, mirrors it as SpanData, links parent/child.
    On exit:  records timing/errors, ends the OTel span, renders trace tree
              for root spans.
    """

    def __init__(self, name: str, data: dict[str, Any]) -> None:
        self.name = name
        self.data = data
        self._span: SpanData | None = None
        self._token: object | None = None
        self._otel_span: object | None = None
        self._otel_token: object | None = None

    def __enter__(self) -> SpanData:
        parent = get_current_span()

        # Create OTel span (auto-parents via OTel context propagation).
        self._otel_span = _otel.start_span(self.name, self.data)
        trace_id, span_id = _otel.get_span_ids(self._otel_span)
        self._otel_token = _otel.activate_span(self._otel_span)

        # Mirror as SpanData for trace tree rendering.
        self._span = SpanData(
            name=self.name,
            span_id=span_id,
            trace_id=trace_id,
            parent_id=parent.span_id if parent else None,
            start_time=time.perf_counter(),
            data=self.data,
        )
        if parent:
            parent.children.append(self._span)

        self._token = set_current_span(self._span)
        return self._span

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        assert self._span is not None
        self._span.end_time = time.perf_counter()

        if exc_type:
            self._span.status = "error"
            self._span.error = exc_val

        # Finalize OTel span (status + optional exception event).
        _otel.end_span(self._otel_span, exc_val if exc_type else None)
        _otel.deactivate_span(self._otel_token)

        # Restore previous spektr span in context.
        self._token.var.reset(self._token)

        # Root span → render trace tree to console/JSON.
        if self._span.parent_id is None:
            _render_trace(self._span)

        return False  # Never suppress exceptions.

    async def __aenter__(self) -> SpanData:
        return self.__enter__()

    async def __aexit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        return self.__exit__(exc_type, exc_val, exc_tb)


def _render_trace(span: SpanData) -> None:
    """Dispatch trace tree rendering to the configured formatter."""
    config = get_config()
    if config.output_mode == OutputMode.JSON:
        format_trace_json(span)
    else:
        format_trace_rich(span)


def _extract_args(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Introspect a function call and return its arguments as a dict.

    Uses ``inspect.signature`` to bind positional and keyword arguments,
    then drops ``self``/``cls`` for clean span attributes.
    """
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        params = dict(bound.arguments)
        params.pop("self", None)
        params.pop("cls", None)
        return params
    except (ValueError, TypeError):  # pragma: no cover
        return {}  # pragma: no cover


class Trace:
    """User-facing tracing API – works as context manager and decorator.

    Three calling conventions::

        # Context manager with explicit name
        with trace("db-query", table="users"):
            ...

        # Bare decorator – span name is the function's qualname
        @trace
        def process(order_id: int):
            ...

        # Decorator factory with extra span attributes
        @trace(version="2.0")
        def handler():
            ...
    """

    def __call__(self, name_or_func: str | Callable | None = None, **kwargs: Any) -> Any:
        # trace("name", key=val) → context manager
        if isinstance(name_or_func, str):
            return _SpanContext(name_or_func, kwargs)

        # @trace → bare decorator (function passed directly)
        if callable(name_or_func):
            return self._decorate(name_or_func, name_or_func.__qualname__, {})

        # @trace(key=val) → decorator factory (name_or_func is None)
        if name_or_func is None:

            def decorator(func: Callable) -> Callable:
                return self._decorate(func, func.__qualname__, kwargs)

            return decorator

        raise TypeError(f"trace() got unexpected argument: {name_or_func!r}")

    def inject(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Inject W3C traceparent header from the current span context.

        Args:
            headers: Optional existing headers dict. If None, a new dict is created.

        Returns:
            The headers dict with traceparent added (if a valid span is active).
        """
        from .._otel._propagation import inject_context

        if headers is None:
            headers = {}
        return inject_context(headers)

    def extract(self, headers: dict[str, str]) -> Any:
        """Extract W3C trace context from HTTP headers.

        Args:
            headers: Mapping of HTTP header names to values.

        Returns:
            A TraceContext dataclass if a valid traceparent header is found,
            otherwise None.
        """
        from .._otel._propagation import extract_context

        return extract_context(headers)

    def _decorate(self, func: Callable, name: str, extra: dict[str, Any]) -> Callable:
        """Wrap a sync or async function with automatic span creation."""
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                span_data = {**extra, **_extract_args(func, args, kwargs)}
                async with _SpanContext(name, span_data):
                    return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            span_data = {**extra, **_extract_args(func, args, kwargs)}
            with _SpanContext(name, span_data):
                return func(*args, **kwargs)

        return wrapper
