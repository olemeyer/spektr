"""Shim – re-exports from _core._logger for backward compatibility."""
from ._core._logger import *  # noqa: F401, F403
from ._core._logger import (
    Logger,
    _CatchDecorator,
    _ContextManager,
    _TimerContext,
    _caller_key,
    _every_counters,
    _get_source,
    _once_seen,
    _rate_lock,
)
