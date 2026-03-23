from __future__ import annotations

import functools
import inspect
import os
import random
import sys
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from .._config import OutputMode, get_config
from .._context import _capturing_sink, _log_context, get_current_span, merge_log_context, reset_log_context
from .._output._formatters import format_record_json, format_record_rich
from .._types import LogLevel, LogRecord, SourceLocation

_SPEKTR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Cache abspath and relpath lookups — filenames don't change at runtime.
_abspath_cache: dict[str, str] = {}
_relpath_cache: dict[str, str] = {}


def _get_source(depth: int) -> SourceLocation | None:
    try:
        frame = sys._getframe(depth)
    except (AttributeError, ValueError):
        return None
    # walk up to find first frame outside spektr internals
    while frame is not None:
        co_filename = frame.f_code.co_filename
        abspath = _abspath_cache.get(co_filename)
        if abspath is None:
            abspath = os.path.abspath(co_filename)
            _abspath_cache[co_filename] = abspath
        if not abspath.startswith(_SPEKTR_DIR):
            break
        frame = frame.f_back
    if frame is None:  # pragma: no cover – all frames inside spektr
        return None
    co_filename = frame.f_code.co_filename
    display = _relpath_cache.get(co_filename)
    if display is None:
        try:
            display = os.path.relpath(co_filename)
        except ValueError:
            display = os.path.basename(co_filename)
        _relpath_cache[co_filename] = display
    return SourceLocation(
        file=display,
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
                    self._logger._emit(
                        LogLevel.ERROR,
                        f"{type(exc).__name__}: {exc}",
                        {},
                        exc_info=sys.exc_info(),
                        depth=1,
                    )
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
_once_seen: set[str] = set()
_every_counters: dict[tuple, int] = {}


def _caller_key(message: str, depth: int = 2) -> tuple:
    """Build a unique key from (message, filename, lineno) for rate limiting."""
    try:
        frame = sys._getframe(depth)
        return (message, frame.f_code.co_filename, frame.f_lineno)
    except (AttributeError, ValueError):
        return (message, "", 0)


def _user_caller_key(message: str) -> tuple:
    """Walk up the stack to find the first non-spektr frame for call site ID."""
    try:
        frame = sys._getframe(1)
        while frame is not None:
            filename = os.path.abspath(frame.f_code.co_filename)
            if not filename.startswith(_SPEKTR_DIR):
                return (message, frame.f_code.co_filename, frame.f_lineno)
            frame = frame.f_back
    except (AttributeError, ValueError):  # pragma: no cover
        pass
    return (message, "", 0)  # pragma: no cover


# ── Rate-Limited Logger (for chaining) ──────────────────────


class _RateLimitedLogger:
    """Logger proxy returned by log.once() / log.every(n) / log.sample(rate).

    Allows chaining a severity level onto rate-limited calls::

        log.sample(0.01).debug("verbose trace", payload=data)
        log.every(1000).warn("slow query", table="orders")
        log.once().error("critical config missing")
    """

    def __init__(self, logger: Logger, gate: Callable[[str], bool]) -> None:
        self._logger = logger
        self._gate = gate

    def __call__(self, message: str, **kwargs: Any) -> None:
        """Shorthand for .info()."""
        self._log(LogLevel.INFO, message, kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.DEBUG, message, kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.INFO, message, kwargs)

    def warn(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.WARNING, message, kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.WARNING, message, kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log(LogLevel.ERROR, message, kwargs)

    def _log(self, level: LogLevel, message: str, kwargs: dict[str, Any]) -> None:
        if self._gate(message):
            self._logger._emit(
                level,
                self._logger._format_message(message, kwargs),
                kwargs,
                depth=2,
            )


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
        self._emit(LogLevel.INFO, self._format_message(message, kwargs), kwargs, depth=2)

    # ── Levels ──────────────────────────────────────────────

    def debug(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.DEBUG, self._format_message(message, kwargs), kwargs, depth=2)

    def info(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.INFO, self._format_message(message, kwargs), kwargs, depth=2)

    def warn(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.WARNING, self._format_message(message, kwargs), kwargs, depth=2)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.WARNING, self._format_message(message, kwargs), kwargs, depth=2)

    def error(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.ERROR, self._format_message(message, kwargs), kwargs, depth=2)

    def exception(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.ERROR, self._format_message(message, kwargs), kwargs, exc_info=sys.exc_info(), depth=2)

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

    def once(self, message: str | None = None, **kwargs: Any) -> _RateLimitedLogger | None:
        """Log only the first time this message is seen.

        Direct form (INFO)::
            log.once("cache ready")

        Chained form (any level)::
            log.once().warn("deprecated API called")
        """
        if message is None:

            def gate(msg: str) -> bool:
                with _rate_lock:
                    if msg in _once_seen:
                        return False
                    _once_seen.add(msg)
                return True

            return _RateLimitedLogger(self, gate)
        with _rate_lock:
            if message in _once_seen:
                return None
            _once_seen.add(message)
        self._emit(LogLevel.INFO, self._format_message(message, kwargs), kwargs, depth=2)
        return None

    def every(self, n: int, message: str | None = None, **kwargs: Any) -> _RateLimitedLogger | None:
        """Log every *n*th call from this call site.

        Direct form (INFO)::
            log.every(1000, "processing", current=i)

        Chained form (any level)::
            log.every(1000).warn("slow query", table="orders")
        """
        if message is None:

            def gate(msg: str) -> bool:
                key = _user_caller_key(msg)
                with _rate_lock:
                    count = _every_counters.get(key, 0)
                    _every_counters[key] = count + 1
                    return count % n == 0

            return _RateLimitedLogger(self, gate)
        key = _caller_key(message, depth=2)
        with _rate_lock:
            count = _every_counters.get(key, 0)
            _every_counters[key] = count + 1
            if count % n != 0:
                return None
        self._emit(LogLevel.INFO, self._format_message(message, kwargs), kwargs, depth=2)
        return None

    def sample(self, rate: float, message: str | None = None, **kwargs: Any) -> _RateLimitedLogger | None:
        """Log with probability *rate* (0.0–1.0).

        Direct form (INFO)::
            log.sample(0.01, "request detail", method="GET")

        Chained form (any level)::
            log.sample(0.01).debug("verbose trace", payload=data)
        """
        if message is None:

            def gate(msg: str) -> bool:
                return random.random() < rate

            return _RateLimitedLogger(self, gate)
        if random.random() >= rate:
            return None
        self._emit(LogLevel.INFO, self._format_message(message, kwargs), kwargs, depth=2)
        return None

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

    # ── Metrics Reporting ────────────────────────────────────

    def emit_metrics(
        self,
        message: str = "metrics",
        *,
        include: list[str] | None = None,
        prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Log current metric values as a single INFO log record.

        Args:
            message: Log message (supports {placeholder} formatting).
            include: Only include metrics with these exact names.
            prefix: Only include metrics whose names start with this prefix.
            **kwargs: Extra structured data merged into the log record.

        If both *include* and *prefix* are given, a metric matches if it
        satisfies either condition.  With neither, all metrics are included.

        Usage::
            log.emit_metrics()                                # all metrics
            log.emit_metrics("health", prefix="http")         # http.* metrics
            log.emit_metrics(include=["queue.depth", "cpu"])   # specific names
        """
        from .._metrics._api import _metrics

        def _match(name: str) -> bool:
            if include is None and prefix is None:
                return True
            if include is not None and name in include:
                return True
            return prefix is not None and name.startswith(prefix)

        data: dict[str, Any] = {}

        with _metrics._lock:
            for (name, _labels), value in _metrics._counters.items():
                if _match(name):
                    data[name] = value
            for (name, _labels), value in _metrics._gauges.items():
                if _match(name):
                    data[name] = value
            for (name, _labels), values in _metrics._histograms.items():
                if _match(name) and values:
                    data[name] = values[-1]

        data.update(kwargs)
        self._emit(LogLevel.INFO, self._format_message(message, data), data, depth=2)

    # ── Message Formatting ────────────────────────────────────

    @staticmethod
    def _format_message(message: str, kwargs: dict[str, Any]) -> str:
        """Format message with kwargs if it contains {placeholders}."""
        if "{" not in message:
            return message
        try:
            return message.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return message

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
        if config.sampler is not None and not config.sampler.should_emit(level, message):
            return None

        source = _get_source(depth + 1) if config.show_source else None
        span = get_current_span()

        # Fast path: avoid dict copies when no context is set.
        log_ctx = _log_context.get()
        if log_ctx and self._bound:
            ctx = {**log_ctx, **self._bound}
        elif log_ctx:
            ctx = log_ctx.copy()
        elif self._bound:
            ctx = self._bound
        else:
            ctx = {}

        # Structured exception enrichment — add error fields to data.
        if exc_info is not None and exc_info[1] is not None:
            exception = exc_info[1]
            data = {
                **data,
                "error_type": type(exception).__name__,
                "error_message": str(exception),
                "error_stacktrace": "".join(traceback.format_exception(exc_info[0], exc_info[1], exc_info[2])),
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
