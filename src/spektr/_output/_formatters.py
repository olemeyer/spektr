from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.console import Console
from rich.text import Text
from rich.traceback import Traceback
from rich.tree import Tree

_SPEKTR_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from .._config import get_config
from .._repr import safe_repr, safe_str
from .._types import LogLevel, LogRecord, SpanData

_LEVEL_STYLES = {
    LogLevel.DEBUG: ("DEBUG", "dim blue"),
    LogLevel.INFO: ("INFO ", "green"),
    LogLevel.WARNING: ("WARN ", "yellow"),
    LogLevel.ERROR: ("ERROR", "bold red"),
}

_console_lock = threading.Lock()
_console: Console | None = None


def _get_console() -> Console:
    global _console
    if _console is None:
        with _console_lock:
            if _console is None:
                _console = Console(stderr=True)
    return _console


_REDACTED = "***"


def _redact_dict(data: dict, patterns: list[str]) -> dict:
    """Replace values whose keys match any redaction pattern with '***'."""
    if not patterns:
        return data
    redacted = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(pattern in key_lower for pattern in patterns):
            redacted[key] = _REDACTED
        else:
            redacted[key] = value
    return redacted


def _format_value(value: object) -> str:
    return safe_repr(value)


def _format_duration(ms: float) -> str:
    if ms < 1:
        return f"{ms * 1000:.0f}us"
    if ms < 1000:
        return f"{ms:.1f}ms"
    return f"{ms / 1000:.2f}s"


# ── Rich Formatter (Dev) ───────────────────────────────────────


def format_record_rich(record: LogRecord) -> None:
    console = _get_console()
    line = Text()

    # timestamp
    ts = datetime.fromtimestamp(record.timestamp, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    line.append(f" {ts} ", style="dim")

    # level
    label, style = _LEVEL_STYLES.get(record.level, ("?????", ""))
    line.append(f"{label}", style=style)

    # message
    line.append(f"  {record.message}")

    # structured data (context + call-site), with sensitive keys redacted
    config = get_config()
    merged = _redact_dict({**record.context, **record.data}, config.redact)
    if merged:
        line.append("  ")
        for key, value in merged.items():
            line.append(f"{key}", style="cyan")
            line.append("=", style="dim")
            line.append(f"{_format_value(value)}", style="magenta")
            line.append(" ")

    # source location
    if record.source:
        line.append(f" {record.source.file}:{record.source.line}", style="dim")

    console.print(line)

    # exception with local variables
    if record.exc_info and record.exc_info[0] is not None:
        # filter out spektr internal frames for cleaner output
        exc_type, exc_val, exc_tb = record.exc_info
        # walk to first non-spektr frame
        tb = exc_tb
        while tb is not None:
            frame_file = os.path.abspath(tb.tb_frame.f_code.co_filename)
            if not frame_file.startswith(_SPEKTR_PKG):
                break
            tb = tb.tb_next
        rich_tb = Traceback.from_exception(
            exc_type,
            exc_val,
            tb or exc_tb,
            show_locals=True,
            width=console.width,
        )
        console.print(rich_tb)


# ── Rich Trace Tree ───────────────────────────────────────────


def format_trace_rich(root: SpanData) -> None:
    console = _get_console()

    def _build_tree(span: SpanData, tree: Tree | None = None) -> Tree:
        duration = _format_duration(span.duration_ms) if span.duration_ms is not None else "..."
        label = Text()
        label.append(f"{span.name}", style="bold")
        label.append(f"  {duration}", style="cyan" if span.status == "ok" else "bold red")

        if span.data:
            redacted_data = _redact_dict(span.data, get_config().redact)
            label.append("  ")
            for key, value in redacted_data.items():
                label.append(f"{key}", style="dim cyan")
                label.append("=", style="dim")
                label.append(f"{_format_value(value)}", style="dim magenta")
                label.append(" ")

        if span.status == "error":
            error_msg = str(span.error) if span.error else "error"
            label.append(f"  {error_msg}", style="bold red")

        if tree is None:
            node = Tree(label, guide_style="dim")
        else:
            node = tree.add(label)

        for child in span.children:
            _build_tree(child, node)

        return node

    tree = _build_tree(root)
    console.print()
    console.print(tree)
    console.print()


# ── JSON Formatter (Prod) ─────────────────────────────────────


def format_record_json(record: LogRecord) -> None:
    ts = datetime.fromtimestamp(record.timestamp, tz=timezone.utc).isoformat()
    entry: dict = {
        "ts": ts,
        "level": record.level.name.lower(),
        "msg": record.message,
    }

    # flatten context + data, with sensitive keys redacted
    config = get_config()
    merged = _redact_dict({**record.context, **record.data}, config.redact)
    entry.update(merged)

    if record.trace_id:
        entry["trace_id"] = record.trace_id
    if record.span_id:
        entry["span_id"] = record.span_id
    if record.source:
        entry["source"] = f"{record.source.file}:{record.source.line}"

    if record.exc_info and record.exc_info[1] is not None:
        exc = record.exc_info[1]
        entry["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }

    sys.stderr.write(json.dumps(entry, default=safe_str) + "\n")
    sys.stderr.flush()


def format_trace_json(root: SpanData) -> None:
    def _serialize(span: SpanData) -> dict:
        d: dict = {
            "name": span.name,
            "span_id": span.span_id,
            "trace_id": span.trace_id,
            "duration_ms": round(span.duration_ms, 2) if span.duration_ms else None,
            "status": span.status,
        }
        if span.parent_id:
            d["parent_id"] = span.parent_id
        if span.data:
            redacted = _redact_dict(span.data, get_config().redact)
            d["attributes"] = {k: safe_str(v) if not isinstance(v, (int, float, bool)) else v for k, v in redacted.items()}
        if span.error:
            d["error"] = {"type": type(span.error).__name__, "message": str(span.error)}
        if span.children:
            d["children"] = [_serialize(c) for c in span.children]
        return d

    sys.stderr.write(json.dumps(_serialize(root), default=str) + "\n")
    sys.stderr.flush()
