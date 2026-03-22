"""Shim – re-exports from _core._tracer for backward compatibility."""
from ._core._tracer import *  # noqa: F401, F403
from ._core._tracer import Trace, _SpanContext, _extract_args, _render_trace
