# Contributing to spektr

Thanks for your interest in contributing to spektr! This document covers everything you need to get started.

## Setup

```bash
git clone https://github.com/olemeyer/spektr.git
cd spektr
uv sync
uv pip install -e .
uv pip install pytest
```

## Running Tests

```bash
# All tests
uv run python -m pytest tests/ -v

# Specific test file
uv run python -m pytest tests/test_logging.py -v

# Specific test
uv run python -m pytest tests/test_logging.py::TestBasicLogging::test_log_default_is_info -v
```

## Code Style

### General

- Keep the public API surface **tiny**. Think twice before adding a new public method.
- Use full variable names: `message` not `msg`, `request_id` not `rid`, `configuration` not `cfg`.
- Prefer `if x is not None` over `if x` when checking for None specifically.
- Avoid bare `except:` — always catch specific exceptions.
- No `# type: ignore` without a specific error code and justification.
- Top-level imports only — no local imports unless avoiding circular dependencies.

### Architecture Rules

- **Public API** lives in `__init__.py` and is exposed via `__all__`.
- **Internal modules** are prefixed with `_` (e.g., `_logger.py`, `_tracer.py`). Users should never import from these.
- **Context propagation** always uses `contextvars` — never thread-locals.
- **Formatting** is separate from logging logic. Formatters receive a `LogRecord` and produce output.

### Testing

- Every behavioral change **must** have a test.
- Use `spektr.capture()` to capture logs in tests — never mock internal components.
- Integration tests (full end-to-end scenarios) go in `tests/test_integration.py`.
- Read existing tests and match their style before writing new ones.
- Prefer specific assertions (`assert logs[0].data["key"] == "value"`) over vague ones (`assert len(logs) > 0`).

## Pull Request Process

1. Fork the repo and create a branch from `main`.
2. Add tests for any new behavior.
3. Make sure all tests pass: `uv run python -m pytest tests/ -v`
4. Keep your PR focused — one feature or fix per PR.
5. Write a clear PR description explaining **why**, not just **what**.

## Design Principles

These guide every decision in spektr:

1. **Zero config by default.** `from spektr import log; log("hello")` must work with zero setup.
2. **10 concepts, not 50.** Every new public API method must justify its existence.
3. **Beautiful output.** If the terminal output doesn't make you smile, it's not done.
4. **OTel under the hood, not in your face.** Users should never see `TracerProvider` or `BatchSpanProcessor`.
5. **Async-safe always.** Everything must work correctly across async boundaries, threads, and concurrent tasks.
6. **One dependency.** `rich` is the only runtime dependency. Adding another requires strong justification.

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests.
- Include a minimal reproducible example when reporting bugs.
- Include your Python version and spektr version.

## Security

See [SECURITY.md](SECURITY.md) for reporting security vulnerabilities.
