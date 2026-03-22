"""Shim – re-exports from _core._capture for backward compatibility."""
from ._core._capture import *  # noqa: F401, F403
from ._core._capture import CapturedLogs, capture
from ._context import _capturing_sink  # noqa: F401 – legacy import location
