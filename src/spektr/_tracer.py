from __future__ import annotations

import functools
import inspect
import secrets
import time
from typing import Any, Callable

from ._config import OutputMode, get_config
from ._context import get_current_span, set_current_span
from ._formatters import format_trace_json, format_trace_rich
from ._types import SpanData


class _SpanContext:
    def __init__(self, name: str, data: dict[str, Any]) -> None:
        self.name = name
        self.data = data
        self._span: SpanData | None = None
        self._token = None

    def __enter__(self) -> SpanData:
        parent = get_current_span()
        self._span = SpanData(
            name=self.name,
            span_id=secrets.token_hex(8),
            trace_id=parent.trace_id if parent else secrets.token_hex(16),
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
        self._token.var.reset(self._token)

        # root span → render trace tree
        if self._span.parent_id is None:
            _render_trace(self._span)

        return False

    async def __aenter__(self) -> SpanData:
        return self.__enter__()

    async def __aexit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        return self.__exit__(exc_type, exc_val, exc_tb)


def _render_trace(span: SpanData) -> None:
    config = get_config()
    if config.output_mode == OutputMode.JSON:
        format_trace_json(span)
    else:
        format_trace_rich(span)


def _extract_args(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        params = dict(bound.arguments)
        # drop self/cls
        params.pop("self", None)
        params.pop("cls", None)
        return params
    except (ValueError, TypeError):
        return {}


class Trace:
    def __call__(self, name_or_func: str | Callable | None = None, **kwargs: Any) -> Any:
        # trace("name", key=val) → context manager
        if isinstance(name_or_func, str):
            return _SpanContext(name_or_func, kwargs)

        # @trace → bare decorator
        if callable(name_or_func):
            return self._decorate(name_or_func, name_or_func.__qualname__, {})

        # @trace(key=val) → decorator factory
        if name_or_func is None:
            def decorator(func: Callable) -> Callable:
                return self._decorate(func, func.__qualname__, kwargs)
            return decorator

        raise TypeError(f"trace() got unexpected argument: {name_or_func!r}")

    def _decorate(self, func: Callable, name: str, extra: dict[str, Any]) -> Callable:
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
