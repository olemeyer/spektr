"""Progress tracking for batch operations.

Usage::

    with log.progress("import users", total=10000) as progress:
        for user in users:
            process(user)
            progress.advance()
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .._core._logger import Logger


class ProgressTracker:
    """Tracks and logs progress of long-running batch operations.

    Automatically rate-limits log output to avoid flooding (max 1 log per
    ``log_interval`` seconds).  On exit, always logs a final summary.
    """

    def __init__(
        self,
        logger: Logger,
        name: str,
        total: int | None = None,
        log_interval: float = 1.0,
    ) -> None:
        self._logger = logger
        self._name = name
        self._total = total
        self._log_interval = log_interval
        self._current = 0
        self._start: float = 0.0
        self._last_log: float = 0.0

    def __enter__(self) -> ProgressTracker:
        self._start = time.monotonic()
        self._last_log = self._start
        self._current = 0
        self._log_progress()
        return self

    def __exit__(self, *_: Any) -> None:
        duration_ms = (time.monotonic() - self._start) * 1000
        data: dict[str, Any] = {
            "name": self._name,
            "current": self._current,
            "duration_ms": round(duration_ms, 2),
            "status": "completed",
        }
        if self._total is not None:
            data["total"] = self._total
            data["percent"] = round(self._current / self._total * 100, 1) if self._total > 0 else 100.0
        from .._types import LogLevel
        self._logger._emit(LogLevel.INFO, f"{self._name} completed", data)

    async def __aenter__(self) -> ProgressTracker:
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        self.__exit__(*args)

    def advance(self, n: int = 1) -> None:
        """Advance progress by *n* items."""
        self._current += n
        now = time.monotonic()
        if now - self._last_log >= self._log_interval:
            self._log_progress()
            self._last_log = now

    def set(self, current: int) -> None:
        """Set absolute progress value."""
        self._current = current
        now = time.monotonic()
        if now - self._last_log >= self._log_interval:
            self._log_progress()
            self._last_log = now

    def _log_progress(self) -> None:
        data: dict[str, Any] = {
            "name": self._name,
            "current": self._current,
        }
        if self._total is not None:
            data["total"] = self._total
            data["percent"] = round(self._current / self._total * 100, 1) if self._total > 0 else 0.0
        elapsed = time.monotonic() - self._start
        if elapsed > 0 and self._current > 0:
            data["rate"] = round(self._current / elapsed, 1)
        from .._types import LogLevel
        self._logger._emit(LogLevel.INFO, f"{self._name} progress", data)
