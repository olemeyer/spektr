"""Exception handling – global hooks with Rich tracebacks, and framework integration.

install() sets up:
    1. Rich tracebacks for uncaught exceptions (sys.excepthook)
    2. Rich tracebacks for uncaught exceptions in threads (threading.excepthook)
    3. stdlib logging bridge – routes third-party library logs through spektr
    4. Optional: ASGI middleware for FastAPI/Starlette apps
"""

from __future__ import annotations

import sys
import threading
from types import TracebackType

from rich.traceback import Traceback

from .._output._formatters import _get_console


def _excepthook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None) -> None:
    console = _get_console()
    tb = Traceback.from_exception(exc_type, exc_value, exc_tb, show_locals=True, width=console.width)
    console.print(tb)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is not None and args.exc_value is not None:
        _excepthook(args.exc_type, args.exc_value, args.exc_traceback)


_installed = False


def install(app: object | None = None) -> None:
    """Install spektr globally.

    Sets up rich exception hooks and the stdlib logging bridge.
    Optionally pass a FastAPI/Starlette app to auto-add ASGI middleware.
    """
    global _installed
    if not _installed:
        sys.excepthook = _excepthook
        threading.excepthook = _threading_excepthook

        # Activate the stdlib logging bridge.
        from ._bridge import install_bridge

        install_bridge()

        _installed = True

    if app is not None:
        _install_framework(app)


def _install_framework(app: object) -> None:
    cls_name = type(app).__name__
    if cls_name in ("FastAPI", "Starlette"):
        _install_asgi(app)
        return


def _install_asgi(app: object) -> None:
    """Add SpektrMiddleware to a FastAPI/Starlette app."""
    from ._middleware import SpektrMiddleware

    app.add_middleware(SpektrMiddleware)  # type: ignore[attr-defined]
