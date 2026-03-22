"""Custom sink support for log record output."""

from __future__ import annotations

import sys

from .._types import LogRecord


class StderrSink:
    """Default sink that routes to Rich or JSON formatter."""

    def write(self, record: LogRecord) -> None:
        from .._config import OutputMode, get_config
        from ._formatters import format_record_json, format_record_rich

        config = get_config()
        if config.output_mode == OutputMode.JSON:
            format_record_json(record)
        else:
            format_record_rich(record)

    def flush(self) -> None:
        sys.stderr.flush()
