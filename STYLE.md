# Code Style Guide

## Python

### Imports

```python
# Good: top-level, grouped (stdlib → third-party → local)
from __future__ import annotations

import asyncio
import time
from typing import Any

from rich.console import Console

from ._types import LogLevel, LogRecord
```

```python
# Bad: local imports, star imports
def my_func():
    from ._config import get_config  # avoid unless breaking circular import
```

### Naming

```python
# Good: full, descriptive names
message = "hello"
request_id = "abc-123"
trace_id = "def-456"
source_location = SourceLocation(...)
configuration = get_config()

# Bad: abbreviated names
msg = "hello"
rid = "abc-123"
tid = "def-456"
src = SourceLocation(...)
cfg = get_config()
```

### Type Annotations

```python
# Good: annotate public APIs and function signatures
def _emit(self, level: LogLevel, message: str, data: dict[str, Any]) -> LogRecord | None:

# Good: use `from __future__ import annotations` for modern syntax
from __future__ import annotations

def process(items: list[str]) -> dict[str, int]:
```

### Error Handling

```python
# Good: specific exceptions
try:
    frame = sys._getframe(depth)
except (AttributeError, ValueError):
    return None

# Bad: bare except
try:
    something()
except:
    pass
```

### None Checks

```python
# Good: explicit None check
if span is not None:
    record.trace_id = span.trace_id

# Bad: truthy check when None is the concern
if span:
    record.trace_id = span.trace_id
```

### Dataclasses

```python
# Good: frozen for immutable data, default_factory for mutable defaults
@dataclass(frozen=True)
class LogRecord:
    timestamp: float
    level: LogLevel
    message: str
    data: dict[str, Any]

@dataclass
class SpanData:
    children: list[SpanData] = field(default_factory=list)
```

## Tests

### Structure

```python
# Good: descriptive class grouping, one assertion focus per test
class TestBasicLogging:
    def test_log_default_is_info(self):
        with capture() as logs:
            log("hello")
        assert logs[0].level == LogLevel.INFO

    def test_log_stores_structured_data(self):
        with capture() as logs:
            log("order", order_id=42)
        assert logs[0].data["order_id"] == 42
```

```python
# Bad: multiple unrelated assertions, vague test names
def test_logging():
    with capture() as logs:
        log("hello")
        log.error("bad")
    assert len(logs) == 2
    assert logs[0].level == LogLevel.INFO
    assert logs[1].level == LogLevel.ERROR
    # too many things tested at once
```

### Patterns

- Always use `capture()` — never mock formatters or internal state
- Reset config in fixtures, not in test bodies
- Test async code with `asyncio.run()` directly
- Test edge cases: empty strings, None values, unicode, large data
