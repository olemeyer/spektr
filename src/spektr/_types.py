from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class LogLevel(enum.IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    function: str


@dataclass(frozen=True)
class LogRecord:
    timestamp: float
    level: LogLevel
    message: str
    data: dict[str, Any]
    context: dict[str, Any]
    source: SourceLocation | None = None
    trace_id: str | None = None
    span_id: str | None = None
    exc_info: tuple | None = None


@dataclass
class SpanData:
    name: str
    span_id: str
    trace_id: str
    parent_id: str | None
    start_time: float
    wall_start: float = field(default_factory=time.time)
    end_time: float | None = None
    data: dict[str, Any] = field(default_factory=dict)
    children: list[SpanData] = field(default_factory=list)
    status: str = "ok"
    error: BaseException | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000
