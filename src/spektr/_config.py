from __future__ import annotations

import enum
import os
import threading
from dataclasses import dataclass

from ._types import LogLevel


class OutputMode(enum.Enum):
    RICH = "rich"
    JSON = "json"


@dataclass
class Config:
    service: str = "default"
    output_mode: OutputMode = OutputMode.RICH
    min_level: LogLevel = LogLevel.DEBUG
    endpoint: str | None = None
    show_source: bool = True

    @staticmethod
    def from_env() -> Config:
        cfg = Config()

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("SPEKTR_ENDPOINT")
        if endpoint:
            cfg.endpoint = endpoint
            cfg.output_mode = OutputMode.JSON

        if os.environ.get("SPEKTR_JSON", "").strip() in ("1", "true"):
            cfg.output_mode = OutputMode.JSON

        if os.environ.get("NO_COLOR"):
            cfg.output_mode = OutputMode.JSON

        level = os.environ.get("SPEKTR_LOG_LEVEL", "").upper()
        if level and level in LogLevel.__members__:
            cfg.min_level = LogLevel[level]

        service = os.environ.get("SPEKTR_SERVICE") or os.environ.get("OTEL_SERVICE_NAME")
        if service:
            cfg.service = service

        return cfg


_lock = threading.Lock()
_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        with _lock:
            if _config is None:
                _config = Config.from_env()
    return _config


def configure(**kwargs) -> None:
    global _config
    # ensure config exists first (outside lock to avoid deadlock)
    cfg = get_config()
    with _lock:
        for key, value in kwargs.items():
            if not hasattr(cfg, key):
                raise ValueError(f"Unknown config option: {key}")
            setattr(cfg, key, value)

        if "endpoint" in kwargs and kwargs["endpoint"] and "output_mode" not in kwargs:
            cfg.output_mode = OutputMode.JSON

        _config = cfg
