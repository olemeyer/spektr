"""Progress tracking for batch operations.

Usage::

    with log.progress("import users", total=10000) as progress:
        for user in users:
            process(user)
            progress.advance()

When ``tqdm`` is installed and output is RICH mode on a TTY, a live
progress bar is shown instead of periodic log lines.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Any

try:
    from tqdm.auto import tqdm as _tqdm
except ImportError:  # pragma: no cover
    _tqdm = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from .._core._logger import Logger


def _use_tqdm() -> bool:
    """Decide whether to use tqdm for progress display."""
    if _tqdm is None:
        return False
    from .._config import OutputMode, get_config

    config = get_config()
    if config.output_mode != OutputMode.RICH:
        return False
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


class ProgressTracker:
    """Tracks and logs progress of long-running batch operations.

    Automatically rate-limits log output to avoid flooding (max 1 log per
    ``log_interval`` seconds).  On exit, always logs a final summary.

    When ``tqdm`` is installed and output is in RICH mode on a TTY, displays
    a live progress bar instead of periodic log lines.
    """

    def __init__(
        self,
        logger: Logger,
        name: str,
        total: int | None = None,
        log_interval: float = 1.0,
        *,
        use_tqdm: bool | None = None,
    ) -> None:
        self._logger = logger
        self._name = name
        self._total = total
        self._log_interval = log_interval
        self._current = 0
        self._start: float = 0.0
        self._last_log: float = 0.0
        self._tqdm_bar: Any = None
        self._use_tqdm = use_tqdm if use_tqdm is not None else _use_tqdm()

    def __enter__(self) -> ProgressTracker:
        self._start = time.monotonic()
        self._last_log = self._start
        self._current = 0

        if self._use_tqdm:
            self._tqdm_bar = _tqdm(
                total=self._total,
                desc=self._name,
                unit="it",
                file=sys.stderr,
            )
        else:
            self._log_progress()

        return self

    def __exit__(self, *_: Any) -> None:
        if self._tqdm_bar is not None:
            self._tqdm_bar.close()
            self._tqdm_bar = None

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

        if self._tqdm_bar is not None:
            self._tqdm_bar.update(n)
            return

        now = time.monotonic()
        if now - self._last_log >= self._log_interval:
            self._log_progress()
            self._last_log = now

    def set(self, current: int) -> None:
        """Set absolute progress value."""
        previous = self._current
        self._current = current

        if self._tqdm_bar is not None:
            self._tqdm_bar.update(current - previous)
            return

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
