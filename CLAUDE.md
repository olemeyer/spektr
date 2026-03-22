# spektr development guidelines

Read CONTRIBUTING.md for guidelines on how to contribute.

## Code Style

- ALWAYS attempt to add a test case for changed behavior
- PREFER integration tests in `tests/test_integration.py` over unit tests
- ALWAYS read and copy the style of similar tests when adding new cases
- PREFER top-level imports over local imports or fully qualified names
- AVOID shortening variable names, e.g., use `message` instead of `msg`, and `request_id` instead of `rid`
- NEVER use `# type: ignore` without a specific error code and justification
- PREFER `if x is not None` over `if x` when checking for None specifically
- AVOID bare `except:` clauses; always catch specific exceptions

## Architecture

- The public API surface is intentionally tiny: `log`, `trace`, `configure`, `install`, `capture`
- Internal modules are prefixed with `_` and should not be imported by users
- All async context propagation uses `contextvars` — never thread-locals
- The `log` object is a callable instance of `Logger`, not a module
- The `trace` object is a callable instance of `Trace`, not a module
- Output formatting is separate from logging logic (formatters are pluggable)

## Testing

- Run tests: `uv run python -m pytest tests/ -v`
- Run specific test file: `uv run python -m pytest tests/test_logging.py -v`
- PREFER running specific tests over the entire suite during development
- ALWAYS use `spektr.capture()` in tests to capture log output instead of mocking
- NEVER mock internal spektr components in tests — test the public API

## Dependencies

- Runtime: `rich`, `opentelemetry-api`, `opentelemetry-sdk` — keep the dependency footprint minimal
- OTLP exporter is optional (`spektr[otlp]`)
- NEVER add runtime dependencies without discussion
- Dev dependencies (pytest) are not included in the package

## Common patterns

```python
# Testing pattern
from spektr import capture, log

def test_something():
    with capture() as logs:
        log("test", key="value")
    assert logs[0].data["key"] == "value"

# Config reset in tests (use fixture)
import spektr._config as config_module
config_module._config = None
```
