from __future__ import annotations

import functools
import inspect
import os
import random
import sys
import threading
import time
import traceback
from typing import Any, Callable

from .._config import OutputMode, get_config
from .._context import _capturing_sink, get_current_span, get_log_context, merge_log_context, reset_log_context
from .._formatters import format_record_json, format_record_rich
from .._types import LogLevel, LogRecord, SourceLocation


_SPEKTR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


# ── Rate-limiting state ──────────────────────────────────────

_rate_lock = threading.Lock()
_once_seen: set[tuple] = set()
_every_counters: dict[tuple, int] = {}


def _caller_key(message: str, depth: int = 2) -> tuple:
    """Build a unique key from (message, filename, lineno) for rate limiting."""
    try:
        frame = sys._getframe(depth)
        return (message, frame.f_code.co_filename, frame.f_lineno)
    except (AttributeError, ValueError):
        return (message, "", 0)


# ── Timer Context Manager ───────────────────────────────────

class _TimerContext:
    """Context manager and decorator that measures duration and logs it."""

    def __init__(self, logger: Logger, message: str, data: dict[str, Any]) -> None:
        self._logger = logger
        self._message = message
        self._data = data
        self._start: float = 0.0

    def __call__(self, func: Callable) -> Callable:
        """Allow use as a decorator: @log.time("name")."""
        return self._logger._time_decorate(func, self._message, self._data)

    def __enter__(self) -> _TimerContext:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        duration_ms = (time.perf_counter() - self._start) * 1000
        self._logger._emit(
            LogLevel.INFO,
            self._message,
            {**self._data, "duration_ms": round(duration_ms, 2)},
        )

    async def __aenter__(self) -> _TimerContext:
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

    # ── Timing ───────────────────────────────────────────────

    def time(self, name_or_func: str | Callable | None = None, **kwargs: Any) -> Any:
        """Measure duration. Works as context manager and decorator.

        Usage::
            with log.time("db query", table="users"): ...
            @log.time
            def process(): ...
            @log.time("custom name")
            def handler(): ...
        """
        if isinstance(name_or_func, str):
            return _TimerContext(self, name_or_func, kwargs)

        if callable(name_or_func):
            return self._time_decorate(name_or_func, name_or_func.__qualname__, {})

        if name_or_func is None:
            def decorator(func: Callable) -> Callable:
                return self._time_decorate(func, func.__qualname__, kwargs)
            return decorator

        raise TypeError(f"time() got unexpected argument: {name_or_func!r}")

    def _time_decorate(self, func: Callable, name: str, extra: dict[str, Any]) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with _TimerContext(self, name, extra):
                    return await func(*args, **kwargs)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _TimerContext(self, name, extra):
                return func(*args, **kwargs)
        return wrapper

    # ── Rate-limited logging ─────────────────────────────────

    def once(self, message: str, **kwargs: Any) -> None:
        """Log only the first time this message is seen."""
        with _rate_lock:
            if message in _once_seen:
                return
            _once_seen.add(message)
        self._emit(LogLevel.INFO, message, kwargs, depth=2)

    def every(self, n: int, message: str, **kwargs: Any) -> None:
        """Log every *n*th call from this call site."""
        key = _caller_key(message, depth=2)
        with _rate_lock:
            count = _every_counters.get(key, 0)
            _every_counters[key] = count + 1
            if count % n != 0:
                return
        self._emit(LogLevel.INFO, message, kwargs, depth=2)

    def sample(self, rate: float, message: str, **kwargs: Any) -> None:
        """Log with probability *rate* (0.0–1.0)."""
        if random.random() >= rate:
            return
        self._emit(LogLevel.INFO, message, kwargs, depth=2)

    # ── Metrics ──────────────────────────────────────────────

    def count(self, name: str, value: float = 1, **labels: Any) -> None:
        """Increment a counter metric."""
        from .._metrics._api import _metrics
        _metrics.count(name, value, **labels)

    def gauge(self, name: str, value: float, **labels: Any) -> None:
        """Set a gauge metric value."""
        from .._metrics._api import _metrics
        _metrics.gauge(name, value, **labels)

    def histogram(self, name: str, value: float, **labels: Any) -> None:
        """Record a histogram metric value."""
        from .._metrics._api import _metrics
        _metrics.histogram(name, value, **labels)

    # ── Progress ─────────────────────────────────────────────

    def progress(self, name: str, total: int | None = None, *, log_interval: float = 1.0) -> Any:
        """Track progress of a batch operation.

        Usage::
            with log.progress("import", total=10000) as p:
                for item in items:
                    process(item)
                    p.advance()
        """
        from .._metrics._progress import ProgressTracker
        return ProgressTracker(self, name, total=total, log_interval=log_interval)

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

        # Check sampler (if configured).
        if config.sampler is not None:
            if not config.sampler.should_emit(level, message):
                return None

        source = _get_source(depth + 1) if config.show_source else None
        span = get_current_span()
        ctx = {**get_log_context(), **self._bound}

        # Structured exception enrichment — add error fields to data.
        if exc_info is not None and exc_info[1] is not None:
            exception = exc_info[1]
            data = {
                **data,
                "error_type": type(exception).__name__,
                "error_message": str(exception),
                "error_stacktrace": "".join(
                    traceback.format_exception(exc_info[0], exc_info[1], exc_info[2])
                ),
            }

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

        # Dispatch to capturing sink (tests), custom sinks, or default formatter.
        capturing = _capturing_sink.get()
        if capturing is not None:
            capturing.append(record)
        elif config.sinks:
            for sink in config.sinks:
                sink.write(record)
        elif config.output_mode == OutputMode.JSON:
            format_record_json(record)
        else:
            format_record_rich(record)

        return record
