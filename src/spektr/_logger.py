from __future__ import annotations

import functools
import inspect
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Generator

from ._config import OutputMode, get_config
from ._context import get_current_span, get_log_context, merge_log_context, reset_log_context
from ._formatters import format_record_json, format_record_rich
from ._types import LogLevel, LogRecord, SourceLocation


_SPEKTR_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_source(depth: int) -> SourceLocation | None:
    try:
        frame = sys._getframe(depth)
    except (AttributeError, ValueError):
        return None
    # walk up to find first frame outside spektr internals
    while frame is not None:
        filename = os.path.abspath(frame.f_code.co_filename)
        if not filename.startswith(_SPEKTR_DIR):
            break
        frame = frame.f_back
    if frame is None:
        return None
    filename = frame.f_code.co_filename
    try:
        filename = os.path.relpath(filename)
    except ValueError:
        filename = os.path.basename(filename)
    return SourceLocation(
        file=filename,
        line=frame.f_lineno,
        function=frame.f_code.co_name,
    )


class _CatchDecorator:
    def __init__(self, logger: Logger) -> None:
        self._logger = logger

    def __call__(self, func: Callable | None = None, *, reraise: bool = True) -> Any:
        if func is not None and callable(func):
            return self._wrap(func, reraise=True)
        # called as @log.catch(reraise=False)
        def decorator(fn: Callable) -> Callable:
            return self._wrap(fn, reraise=reraise)
        return decorator

    def _wrap(self, func: Callable, reraise: bool) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    self._logger._emit(LogLevel.ERROR, f"{type(exc).__name__}: {exc}", {}, exc_info=sys.exc_info(), depth=1)
                    if reraise:
                        raise
                    return None
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                self._logger._emit(LogLevel.ERROR, f"{type(exc).__name__}: {exc}", {}, exc_info=sys.exc_info(), depth=1)
                if reraise:
                    raise
                return None
        return wrapper


class _ContextManager:
    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._token = None

    def __enter__(self) -> _ContextManager:
        self._token = merge_log_context(**self._kwargs)
        return self

    def __exit__(self, *_: Any) -> None:
        if self._token is not None:
            reset_log_context(self._token)

    async def __aenter__(self) -> _ContextManager:
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        self.__exit__(*args)


class Logger:
    def __init__(self, bound_context: dict[str, Any] | None = None) -> None:
        self._bound = bound_context or {}
        self.catch = _CatchDecorator(self)

    # ── Main call: log("msg", key=val) ──────────────────────

    def __call__(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.INFO, message, kwargs, depth=2)

    # ── Levels ──────────────────────────────────────────────

    def debug(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.DEBUG, message, kwargs, depth=2)

    def info(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.INFO, message, kwargs, depth=2)

    def warn(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.WARNING, message, kwargs, depth=2)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.WARNING, message, kwargs, depth=2)

    def error(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.ERROR, message, kwargs, depth=2)

    def exception(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.ERROR, message, kwargs, exc_info=sys.exc_info(), depth=2)

    # ── Context ─────────────────────────────────────────────

    def context(self, **kwargs: Any) -> _ContextManager:
        return _ContextManager(**kwargs)

    def bind(self, **kwargs: Any) -> Logger:
        return Logger(bound_context={**self._bound, **kwargs})

    # ── Internal ────────────────────────────────────────────

    def _emit(
        self,
        level: LogLevel,
        message: str,
        data: dict[str, Any],
        *,
        exc_info: tuple | None = None,
        depth: int = 2,
    ) -> LogRecord | None:
        config = get_config()
        if level < config.min_level:
            return None

        source = _get_source(depth + 1) if config.show_source else None
        span = get_current_span()
        ctx = {**get_log_context(), **self._bound}

        record = LogRecord(
            timestamp=time.time(),
            level=level,
            message=message,
            data=data,
            context=ctx,
            source=source,
            trace_id=span.trace_id if span else None,
            span_id=span.span_id if span else None,
            exc_info=exc_info,
        )

        # dispatch to active formatter
        from ._capture import _capturing_sink
        if _capturing_sink.get() is not None:
            _capturing_sink.get().append(record)  # type: ignore
        elif config.output_mode == OutputMode.JSON:
            format_record_json(record)
        else:
            format_record_rich(record)

        return record
