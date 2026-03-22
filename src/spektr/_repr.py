"""Safe object representation – protects against hostile or oversized objects.

Objects passed to log() and trace() can have broken __repr__, trigger
infinite recursion, produce enormous output, or raise exceptions.  This
module ensures none of those conditions crash or hang the logging pipeline.

Uses reprlib for depth/breadth limiting of collections and wraps everything
in exception handlers so that logging never fails due to a badly-behaved
object.

Two entry points:
    safe_repr  – for display in console output (key=value pairs).
                 Strings returned unquoted for readability.
    safe_str   – for JSON serialization and OTel attributes.
                 Prefers str() for cleaner output (datetime, Path, etc.).
"""

from __future__ import annotations

import reprlib
from typing import Any

# Pre-configured reprlib instance with conservative limits.
# reprlib handles collection truncation ({1, 2, ...}) and depth limiting
# out of the box, which protects against deeply nested or enormous objects.
_repr = reprlib.Repr()
_repr.maxstring = 200
_repr.maxother = 200
_repr.maxlist = 10
_repr.maxdict = 10
_repr.maxset = 10
_repr.maxtuple = 10
_repr.maxarray = 10
_repr.maxdeque = 10
_repr.maxlong = 50
_repr.maxlevel = 3


def safe_repr(obj: Any, *, max_length: int = 200) -> str:
    """Safely represent any object as a string for display in logs and traces.

    Guarantees:
        - Never raises an exception.
        - Output never exceeds *max_length* + 3 characters.
        - Handles circular references (via reprlib depth limiting).
        - Handles broken __repr__ (falls back to ``<ClassName at 0x...>``).

    Strings are returned unquoted since they appear as values in
    ``key=value`` display pairs where quotes add noise.
    """
    if isinstance(obj, str):
        if len(obj) <= max_length:
            return obj
        return obj[:max_length] + "..."

    try:
        result = _repr.repr(obj)
    except Exception:
        # __repr__ raised – fall back to type + identity.
        try:
            result = f"<{type(obj).__name__} at {id(obj):#x}>"
        except Exception:
            result = "<unrepresentable>"

    if len(result) > max_length:
        return result[:max_length] + "..."
    return result


def safe_str(obj: Any, *, max_length: int = 200) -> str:
    """Safely stringify any object for JSON serialization and OTel attributes.

    Prefers str() over repr() for cleaner output (no quotes on strings,
    natural formatting for datetime/Path/UUID/etc.).  Falls back to
    safe_repr() if str() raises.
    """
    if isinstance(obj, str):
        if len(obj) <= max_length:
            return obj
        return obj[:max_length] + "..."

    try:
        result = str(obj)
    except Exception:
        return safe_repr(obj, max_length=max_length)

    if len(result) > max_length:
        return result[:max_length] + "..."
    return result
