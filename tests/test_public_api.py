"""Tests for spektr public API surface — imports, types, py.typed, version."""

from __future__ import annotations

import importlib
import importlib.metadata
import pathlib


class TestPublicImports:
    """Every public symbol should be importable from the top-level package."""

    def test_import_log(self):
        from spektr import log
        assert callable(log)

    def test_import_trace(self):
        from spektr import trace
        assert callable(trace)

    def test_import_configure(self):
        from spektr import configure
        assert callable(configure)

    def test_import_install(self):
        from spektr import install
        assert callable(install)

    def test_import_capture(self):
        from spektr import capture
        assert callable(capture)

    def test_import_spektr_middleware(self):
        from spektr import SpektrMiddleware
        assert callable(SpektrMiddleware)

    def test_import_log_level(self):
        from spektr import LogLevel
        assert LogLevel.DEBUG == 10
        assert LogLevel.INFO == 20
        assert LogLevel.WARNING == 30
        assert LogLevel.ERROR == 40

    def test_import_log_record(self):
        from spektr import LogLevel, LogRecord
        record = LogRecord(
            timestamp=0.0, level=LogLevel.INFO, message="test", data={}, context={}
        )
        assert record.message == "test"
        assert record.level == LogLevel.INFO

    def test_import_span_data(self):
        from spektr import SpanData
        span = SpanData(name="test", span_id="a", trace_id="b", parent_id=None, start_time=0.0)
        assert span.name == "test"
        assert span.trace_id == "b"

    def test_import_source_location(self):
        from spektr import SourceLocation
        loc = SourceLocation(file="test.py", line=42, function="test_fn")
        assert loc.file == "test.py"
        assert loc.line == 42

    def test_import_output_mode(self):
        from spektr import OutputMode
        assert OutputMode.RICH is not None
        assert OutputMode.JSON is not None

    def test_import_sampler(self):
        from spektr import Sampler
        assert hasattr(Sampler, "should_emit")

    def test_import_sink(self):
        from spektr import Sink
        assert hasattr(Sink, "write")
        assert hasattr(Sink, "flush")

    def test_import_metric_backend(self):
        from spektr import MetricBackend
        assert hasattr(MetricBackend, "counter")

    def test_import_rate_limit_sampler(self):
        from spektr import RateLimitSampler
        sampler = RateLimitSampler(per_second=100)
        assert sampler.should_emit(20, "test") is True

    def test_import_composite_sampler(self):
        from spektr import CompositeSampler
        sampler = CompositeSampler()
        assert sampler.should_emit(20, "test") is True

    def test_import_in_memory_metrics(self):
        from spektr import InMemoryMetrics
        metrics = InMemoryMetrics()
        metrics.count("test", 1)
        assert metrics.get_counter("test") == 1
        metrics.reset()

    def test_import_version(self):
        from spektr import __version__
        assert isinstance(__version__, str)
        assert len(__version__) > 0


class TestAllExports:
    """__all__ should list every public symbol."""

    def test_all_is_complete(self):
        import spektr

        expected = {
            "__version__",
            "log",
            "trace",
            "configure",
            "install",
            "capture",
            "SpektrMiddleware",
            "LogLevel",
            "LogRecord",
            "SpanData",
            "SourceLocation",
            "OutputMode",
            "Sink",
            "Sampler",
            "MetricBackend",
            "RateLimitSampler",
            "CompositeSampler",
            "InMemoryMetrics",
        }
        assert set(spektr.__all__) == expected

    def test_all_symbols_resolve(self):
        import spektr

        for name in spektr.__all__:
            assert hasattr(spektr, name), f"spektr.{name} not found"


class TestVersion:
    def test_version_is_pep440(self):
        from spektr import __version__
        from packaging.version import Version

        # Should not raise
        Version(__version__)

    def test_version_matches_metadata(self):
        installed_version = importlib.metadata.version("spektr")
        from spektr import __version__
        assert __version__ == installed_version


class TestPyTyped:
    def test_py_typed_marker_exists(self):
        """py.typed marker should be present in the package."""
        import spektr

        package_dir = pathlib.Path(spektr.__file__).parent
        py_typed = package_dir / "py.typed"
        assert py_typed.exists(), "py.typed marker missing from package"

    def test_py_typed_in_package(self):
        """py.typed should be included when the package is built."""
        import spektr

        package_dir = pathlib.Path(spektr.__file__).parent
        assert (package_dir / "py.typed").is_file()


class TestLogLevelUsability:
    """LogLevel should work seamlessly when imported from spektr directly."""

    def test_log_level_in_capture_filter(self):
        from spektr import LogLevel, capture, log

        with capture() as logs:
            log.debug("d")
            log.error("e")

        errors = logs.filter(level=LogLevel.ERROR)
        assert len(errors) == 1
        assert errors[0].message == "e"

    def test_log_level_in_configure(self):
        from spektr import LogLevel, configure

        configure(min_level=LogLevel.WARNING)
        # Reset to default
        configure(min_level=LogLevel.DEBUG)

    def test_log_level_comparison(self):
        from spektr import LogLevel

        assert LogLevel.ERROR > LogLevel.WARNING
        assert LogLevel.WARNING > LogLevel.INFO
        assert LogLevel.INFO > LogLevel.DEBUG

    def test_log_level_label(self):
        from spektr import LogLevel

        assert LogLevel.DEBUG.label == "DEBUG"
        assert LogLevel.INFO.label == "INFO"
        assert LogLevel.WARNING.label == "WARNING"
        assert LogLevel.ERROR.label == "ERROR"

    def test_log_record_has_level(self):
        from spektr import LogLevel, LogRecord, capture, log

        with capture() as logs:
            log.warn("test")

        record = logs[0]
        assert isinstance(record.level, LogLevel)
        assert record.level == LogLevel.WARNING


class TestOutputMode:
    def test_output_mode_values(self):
        from spektr import OutputMode

        assert OutputMode.RICH.value == "rich"
        assert OutputMode.JSON.value == "json"

    def test_output_mode_in_configure(self):
        from spektr import OutputMode, configure

        configure(output_mode=OutputMode.RICH)
