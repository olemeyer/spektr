from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from .._context import _capturing_sink
from .._types import LogLevel, LogRecord


class CapturedLogs:
    def __init__(self) -> None:
        self.records: list[LogRecord] = []

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> LogRecord:
        return self.records[index]

    def __contains__(self, substring: str) -> bool:
        return any(substring in r.message for r in self.records)

    def __iter__(self):
        return iter(self.records)

    def filter(self, level: LogLevel | None = None, **kwargs: Any) -> list[LogRecord]:
        results = self.records
        if level is not None:
            results = [r for r in results if r.level == level]
        for key, value in kwargs.items():
            results = [r for r in results if r.data.get(key) == value or r.context.get(key) == value]
        return results

    @property
    def messages(self) -> list[str]:
        return [r.message for r in self.records]


@contextmanager
def capture() -> Generator[CapturedLogs, None, None]:
    captured = CapturedLogs()
    token = _capturing_sink.set(captured.records)
    try:
        yield captured
    finally:
        _capturing_sink.reset(token)
