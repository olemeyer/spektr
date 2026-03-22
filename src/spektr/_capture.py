from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Generator

from ._types import LogLevel, LogRecord

_capturing_sink: ContextVar[list[LogRecord] | None] = ContextVar("spektr_capturing_sink", default=None)


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
