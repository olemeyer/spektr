"""Tests for sink integration with the logging pipeline."""

from __future__ import annotations

import pytest

import spektr._config as config_module
from spektr import capture, configure, log
from spektr._config import Config
from spektr._types import LogLevel, LogRecord


@pytest.fixture(autouse=True)
def reset_config():
    old = config_module._config
    yield
    config_module._config = old


class TestSinkIntegration:
    def test_custom_sink_receives_records(self):
        records = []

        class ListSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        configure(sinks=[ListSink()])
        log("hello from sink")

        assert len(records) == 1
        assert records[0].message == "hello from sink"

    def test_multiple_sinks_receive_same_record(self):
        records_a = []
        records_b = []

        class SinkA:
            def write(self, record):
                records_a.append(record)

            def flush(self):
                pass

        class SinkB:
            def write(self, record):
                records_b.append(record)

            def flush(self):
                pass

        configure(sinks=[SinkA(), SinkB()])
        log("multi-sink test")

        assert len(records_a) == 1
        assert len(records_b) == 1
        assert records_a[0].message == records_b[0].message

    def test_capture_takes_priority_over_sinks(self):
        """capture() should intercept even when sinks are configured."""
        sink_records = []

        class MySink:
            def write(self, record):
                sink_records.append(record)

            def flush(self):
                pass

        configure(sinks=[MySink()])
        with capture() as logs:
            log("captured")

        assert len(logs) == 1
        assert len(sink_records) == 0

    def test_sink_receives_all_record_fields(self):
        records = []

        class DetailSink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        configure(sinks=[DetailSink()])
        log.error("fail", code=500)

        record = records[0]
        assert record.level == LogLevel.ERROR
        assert record.message == "fail"
        assert record.data["code"] == 500
        assert record.timestamp > 0

    def test_empty_sinks_falls_through_to_formatter(self, capsys):
        """When sinks list is empty, use default formatter."""
        config_module._config = Config(sinks=[])
        log("should use default")
        # No crash = success (formatter writes to stderr)

    def test_sink_with_bound_logger(self):
        records = []

        class MySink:
            def write(self, record):
                records.append(record)

            def flush(self):
                pass

        configure(sinks=[MySink()])
        bound = log.bind(service="api")
        bound("bound message")

        assert records[0].context["service"] == "api"
