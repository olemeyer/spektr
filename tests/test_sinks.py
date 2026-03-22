"""Tests for custom sinks."""

import time

from spektr._config import OutputMode
from spektr._output._sinks import StderrSink
from spektr._protocols import Sink
from spektr._types import LogLevel, LogRecord
import spektr._config as config_module


def _make_record(message: str = "test message", level: LogLevel = LogLevel.INFO) -> LogRecord:
    """Create a minimal LogRecord for testing."""
    return LogRecord(
        timestamp=time.time(),
        level=level,
        message=message,
        data={"key": "value"},
        context={},
    )


class TestStderrSink:
    def setup_method(self):
        config_module._config = None

    def teardown_method(self):
        config_module._config = None

    def test_implements_sink_protocol(self):
        sink = StderrSink()
        assert isinstance(sink, Sink)

    def test_writes_to_stderr_json_mode(self, capsys):
        from spektr._config import configure

        configure(output_mode=OutputMode.JSON)
        sink = StderrSink()
        record = _make_record()

        sink.write(record)

        captured = capsys.readouterr()
        assert "test message" in captured.err

    def test_writes_to_stderr_rich_mode(self, capsys):
        from spektr._config import configure

        configure(output_mode=OutputMode.RICH)
        sink = StderrSink()
        record = _make_record()

        sink.write(record)

        captured = capsys.readouterr()
        assert "test message" in captured.err

    def test_flush_does_not_raise(self):
        sink = StderrSink()
        sink.flush()


class TestCustomSink:
    def test_custom_sink_receives_records(self):
        received = []

        class CollectorSink:
            def write(self, record: LogRecord) -> None:
                received.append(record)

            def flush(self) -> None:
                pass

        sink = CollectorSink()
        record = _make_record("custom sink test")
        sink.write(record)

        assert len(received) == 1
        assert received[0].message == "custom sink test"

    def test_custom_sink_implements_protocol(self):
        class MinimalSink:
            def write(self, record: LogRecord) -> None:
                pass

            def flush(self) -> None:
                pass

        sink = MinimalSink()
        assert isinstance(sink, Sink)

    def test_multiple_sinks_receive_same_record(self):
        received_a = []
        received_b = []

        class SinkA:
            def write(self, record: LogRecord) -> None:
                received_a.append(record)

            def flush(self) -> None:
                pass

        class SinkB:
            def write(self, record: LogRecord) -> None:
                received_b.append(record)

            def flush(self) -> None:
                pass

        record = _make_record("broadcast test")
        sinks = [SinkA(), SinkB()]
        for sink in sinks:
            sink.write(record)

        assert len(received_a) == 1
        assert len(received_b) == 1
        assert received_a[0] is received_b[0]
        assert received_a[0].message == "broadcast test"

    def test_custom_sink_receives_all_record_fields(self):
        received = []

        class DetailSink:
            def write(self, record: LogRecord) -> None:
                received.append(record)

            def flush(self) -> None:
                pass

        record = LogRecord(
            timestamp=time.time(),
            level=LogLevel.WARNING,
            message="detailed record",
            data={"request_path": "/api/users"},
            context={"request_id": "req-123"},
            trace_id="trace-abc",
            span_id="span-def",
        )

        sink = DetailSink()
        sink.write(record)

        captured = received[0]
        assert captured.level == LogLevel.WARNING
        assert captured.message == "detailed record"
        assert captured.data["request_path"] == "/api/users"
        assert captured.context["request_id"] == "req-123"
        assert captured.trace_id == "trace-abc"
        assert captured.span_id == "span-def"
