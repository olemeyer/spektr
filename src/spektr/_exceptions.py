from __future__ import annotations

import sys
import threading
from types import TracebackType

from rich.console import Console
from rich.traceback import Traceback

from ._formatters import _get_console


def _excepthook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None) -> None:
    console = _get_console()
    tb = Traceback.from_exception(exc_type, exc_value, exc_tb, show_locals=True, width=console.width)
    console.print(tb)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is not None and args.exc_value is not None:
        _excepthook(args.exc_type, args.exc_value, args.exc_traceback)


_installed = False


def install(app: object | None = None) -> None:
    global _installed
    if not _installed:
        sys.excepthook = _excepthook
        threading.excepthook = _threading_excepthook
        _installed = True

    if app is not None:
        _install_framework(app)


def _install_framework(app: object) -> None:
    # FastAPI / Starlette
    cls_name = type(app).__name__
    if cls_name in ("FastAPI", "Starlette"):
        _install_asgi(app)
        return


def _install_asgi(app: object) -> None:
    # placeholder for v0.2 – auto-instrument ASGI apps
    pass
