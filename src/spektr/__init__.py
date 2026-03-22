"""spektr – Zero-config Python observability."""

from ._capture import capture
from ._config import configure
from ._exceptions import install
from ._logger import Logger
from ._tracer import Trace

log = Logger()
trace = Trace()

__all__ = ["log", "trace", "configure", "install", "capture"]
