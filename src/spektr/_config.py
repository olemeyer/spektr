"""Configuration – auto-detected from environment, overridable at runtime.

Environment variables (checked in order):
    OTEL_EXPORTER_OTLP_ENDPOINT  →  sets endpoint + switches to JSON mode
    SPEKTR_ENDPOINT              →  same as above (spektr-specific alias)
    SPEKTR_JSON=1|true           →  force JSON output (no endpoint needed)
    NO_COLOR                     →  respects the no-color.org convention
    SPEKTR_LOG_LEVEL             →  minimum log level (DEBUG/INFO/WARNING/ERROR)
    SPEKTR_SERVICE               →  service name for OTel resource
    OTEL_SERVICE_NAME            →  same, standard OTel env var

The config singleton is lazily created on first access via get_config().
Thread-safe through double-checked locking.
"""

from __future__ import annotations

import enum
import os
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ._types import LogLevel

if TYPE_CHECKING:
    pass


class OutputMode(enum.Enum):
    """Determines how log records and traces are rendered."""

    RICH = "rich"  # Colored console output with trace trees (development).
    JSON = "json"  # Structured JSON to stderr (production / collectors).


@dataclass
class Config:
    """Runtime configuration – mutable, modified through configure()."""

    service: str = "default"
    output_mode: OutputMode = OutputMode.RICH
    min_level: LogLevel = LogLevel.DEBUG
    endpoint: str | None = None
    show_source: bool = True
    redact: list[str] = field(
        default_factory=lambda: [
            "password",
            "secret",
            "token",
            "authorization",
            "api_key",
            "apikey",
        ]
    )
    sinks: list[Any] = field(default_factory=list)
    sampler: Any | None = None
    health_path: str | None = None

    @staticmethod
    def from_env() -> Config:
        """Build a Config by reading environment variables."""
        cfg = Config()

        # Endpoint detection – OTEL standard var takes precedence.
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("SPEKTR_ENDPOINT")
        if endpoint:
            cfg.endpoint = endpoint
            cfg.output_mode = OutputMode.JSON

        # Explicit JSON mode (no endpoint required).
        if os.environ.get("SPEKTR_JSON", "").strip() in ("1", "true"):
            cfg.output_mode = OutputMode.JSON

        # Respect the NO_COLOR convention (https://no-color.org/).
        if os.environ.get("NO_COLOR"):
            cfg.output_mode = OutputMode.JSON

        # Log level filter.
        level = os.environ.get("SPEKTR_LOG_LEVEL", "").upper()
        if level and level in LogLevel.__members__:
            cfg.min_level = LogLevel[level]

        # Service name – SPEKTR_SERVICE takes precedence over OTEL_SERVICE_NAME.
        service = os.environ.get("SPEKTR_SERVICE") or os.environ.get("OTEL_SERVICE_NAME")
        if service:
            cfg.service = service

        return cfg


# ── Singleton ──────────────────────────────────────────────────

_lock = threading.Lock()
_config: Config | None = None


def get_config() -> Config:
    """Return the global config, creating it from env vars on first call."""
    global _config
    if _config is None:
        with _lock:
            if _config is None:
                _config = Config.from_env()
    return _config


def configure(**kwargs) -> None:
    """Override config values at runtime.

    Example::

        configure(output_mode=OutputMode.JSON, min_level=LogLevel.WARNING)
        configure(endpoint="http://collector:4318")  # auto-switches to JSON

    Raises:
        ValueError: If an unknown config key is passed.
    """
    global _config

    # Ensure config exists first – called OUTSIDE the lock to avoid deadlock
    # (get_config also acquires _lock internally).
    cfg = get_config()

    with _lock:
        for key, value in kwargs.items():
            if not hasattr(cfg, key):
                raise ValueError(f"Unknown config option: {key}")
            setattr(cfg, key, value)

        # Setting an endpoint implies JSON output (unless explicitly overridden).
        if "endpoint" in kwargs and kwargs["endpoint"] and "output_mode" not in kwargs:
            cfg.output_mode = OutputMode.JSON

        _config = cfg

    # Re-initialize OTel when service name or endpoint changes so the
    # TracerProvider picks up the new resource / exporter.
    if "endpoint" in kwargs or "service" in kwargs:
        from . import _otel

        _otel.setup(service_name=cfg.service, endpoint=cfg.endpoint)
