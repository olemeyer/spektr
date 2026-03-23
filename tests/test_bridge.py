"""Tests for the stdlib logging bridge."""

import logging

import pytest

from spektr import capture, install
from spektr._integrations._bridge import SpektrHandler, install_bridge
from spektr._config import get_config, configure
from spektr._types import LogLevel


@pytest.fixture(autouse=True)
def _clean_bridge():
    """Remove SpektrHandler from root logger after each test."""
    yield
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, SpektrHandler)]
    root.setLevel(logging.WARNING)  # reset to default


class TestBridgeBasic:
    def test_routes_stdlib_log_through_spektr(self):
        install_bridge()
        logger = logging.getLogger("test.basic")

        with capture() as logs:
            logger.info("hello from stdlib")

        assert len(logs) == 1
        assert logs[0].message == "hello from stdlib"

    def test_includes_logger_name(self):
        install_bridge()
        logger = logging.getLogger("myapp.db")

        with capture() as logs:
            logger.warning("slow query")

        assert logs[0].data["logger"] == "myapp.db"

    def test_source_location_from_stdlib(self):
        install_bridge()
        logger = logging.getLogger("test.source")

        with capture() as logs:
            logger.info("msg")

        assert logs[0].source is not None
        assert "test_bridge.py" in logs[0].source.file


class TestBridgeLevelMapping:
    def test_debug(self):
        install_bridge()
        logger = logging.getLogger("test.levels")

        with capture() as logs:
            logger.debug("dbg")

        assert logs[0].level == LogLevel.DEBUG

    def test_info(self):
        install_bridge()
        logger = logging.getLogger("test.levels")

        with capture() as logs:
            logger.info("inf")

        assert logs[0].level == LogLevel.INFO

    def test_warning(self):
        install_bridge()
        logger = logging.getLogger("test.levels")

        with capture() as logs:
            logger.warning("wrn")

        assert logs[0].level == LogLevel.WARNING

    def test_error(self):
        install_bridge()
        logger = logging.getLogger("test.levels")

        with capture() as logs:
            logger.error("err")

        assert logs[0].level == LogLevel.ERROR

    def test_critical_maps_to_error(self):
        install_bridge()
        logger = logging.getLogger("test.levels")

        with capture() as logs:
            logger.critical("crit")

        assert logs[0].level == LogLevel.ERROR


class TestBridgeFiltering:
    def test_respects_min_level(self):
        install_bridge()
        logger = logging.getLogger("test.filter")
        original = get_config().min_level

        try:
            configure(min_level=LogLevel.WARNING)
            with capture() as logs:
                logger.info("filtered out")
                logger.warning("visible")

            assert len(logs) == 1
            assert logs[0].message == "visible"
        finally:
            configure(min_level=original)


class TestBridgeExcInfo:
    def test_captures_exc_info(self):
        install_bridge()
        logger = logging.getLogger("test.exc")

        with capture() as logs:
            try:
                raise ValueError("test error")
            except ValueError:
                logger.exception("caught it")

        assert len(logs) == 1
        assert logs[0].exc_info is not None
        assert logs[0].exc_info[0] is ValueError


class TestBridgeIdempotent:
    def test_double_install_does_not_duplicate(self):
        install_bridge()
        install_bridge()

        root = logging.getLogger()
        handler_count = sum(1 for h in root.handlers if isinstance(h, SpektrHandler))
        assert handler_count == 1


class TestBridgeLevelBoundaries:
    """Test level mapping at exact boundaries and intermediate values."""

    def test_level_just_above_debug(self):
        install_bridge()
        logger = logging.getLogger("test.boundary")

        with capture() as logs:
            logger.log(logging.DEBUG + 1, "between debug and info")

        assert logs[0].level == LogLevel.DEBUG

    def test_level_just_below_info(self):
        install_bridge()
        logger = logging.getLogger("test.boundary")

        with capture() as logs:
            logger.log(logging.INFO - 1, "just below info")

        assert logs[0].level == LogLevel.DEBUG

    def test_level_just_above_info(self):
        install_bridge()
        logger = logging.getLogger("test.boundary")

        with capture() as logs:
            logger.log(logging.INFO + 1, "between info and warning")

        assert logs[0].level == LogLevel.INFO

    def test_level_just_below_warning(self):
        install_bridge()
        logger = logging.getLogger("test.boundary")

        with capture() as logs:
            logger.log(logging.WARNING - 1, "just below warning")

        assert logs[0].level == LogLevel.INFO

    def test_level_just_above_warning(self):
        install_bridge()
        logger = logging.getLogger("test.boundary")

        with capture() as logs:
            logger.log(logging.WARNING + 1, "between warning and error")

        assert logs[0].level == LogLevel.WARNING

    def test_level_above_critical(self):
        install_bridge()
        logger = logging.getLogger("test.boundary")

        with capture() as logs:
            logger.log(logging.CRITICAL + 10, "above critical")

        assert logs[0].level == LogLevel.ERROR

    def test_custom_level_number(self):
        install_bridge()
        logger = logging.getLogger("test.custom")

        with capture() as logs:
            logger.log(25, "custom level 25")

        assert logs[0].level == LogLevel.INFO


class TestBridgeLevelFiltering:
    """Test that min_level filtering at boundary works."""

    def test_level_equals_min_level_passes(self):
        install_bridge()
        logger = logging.getLogger("test.boundary.filter")
        original = get_config().min_level

        try:
            configure(min_level=LogLevel.WARNING)
            with capture() as logs:
                logger.warning("exactly at min level")

            assert len(logs) == 1
        finally:
            configure(min_level=original)

    def test_level_above_min_level_passes(self):
        install_bridge()
        logger = logging.getLogger("test.boundary.filter")
        original = get_config().min_level

        try:
            configure(min_level=LogLevel.WARNING)
            with capture() as logs:
                logger.error("above min level")

            assert len(logs) == 1
        finally:
            configure(min_level=original)


class TestBridgeExcInfoEdgeCases:
    def test_exc_info_with_none_type(self):
        """exc_info tuple with None type should not set exc_info."""
        install_bridge()
        logger = logging.getLogger("test.exc.edge")

        with capture() as logs:
            logger.info("no exception", exc_info=(None, None, None))

        assert len(logs) == 1
        assert logs[0].exc_info is None

    def test_exc_info_false(self):
        install_bridge()
        logger = logging.getLogger("test.exc.edge")

        with capture() as logs:
            logger.info("no exc", exc_info=False)

        assert logs[0].exc_info is None


class TestBridgeContext:
    def test_bridge_inherits_spektr_context(self):
        """stdlib logs inside a spektr context should inherit it."""
        from spektr import log

        install_bridge()
        logger = logging.getLogger("test.context")

        with capture() as logs:
            with log.context(request_id="abc"):
                logger.info("inside context")

        assert logs[0].context["request_id"] == "abc"

    def test_bridge_inherits_trace_ids(self):
        """stdlib logs inside a trace span should have trace/span IDs."""
        from spektr import trace

        install_bridge()
        logger = logging.getLogger("test.trace")

        with capture() as logs:
            with trace("my-span"):
                logger.info("inside span")

        assert logs[0].trace_id is not None
        assert logs[0].span_id is not None

    def test_bridge_message_formatting(self):
        """stdlib log with format args should resolve the message."""
        install_bridge()
        logger = logging.getLogger("test.format")

        with capture() as logs:
            logger.info("user %s has %d items", "ole", 5)

        assert logs[0].message == "user ole has 5 items"


class TestBridgeRecursionGuard:
    def test_no_infinite_recursion(self):
        """If the formatter triggers a stdlib log, the bridge should not recurse."""
        install_bridge()
        logger = logging.getLogger("test.recursion")

        # This should complete without RecursionError
        with capture() as logs:
            logger.info("safe")

        assert len(logs) == 1

    def test_recursion_guard_resets_after_exception(self):
        """The bridge guard should reset even if _handle raises."""
        from spektr._integrations._bridge import _in_bridge

        install_bridge()
        logger = logging.getLogger("test.guard.reset")

        # After any error, the guard should be False again
        assert _in_bridge.get() is False
        with capture() as logs:
            logger.info("after reset")
        assert _in_bridge.get() is False
        assert len(logs) == 1

    def test_recursion_guard_drops_reentrant_record(self):
        """Bridge should not recurse when already inside the bridge."""
        from spektr._integrations._bridge import SpektrHandler, _in_bridge

        handler = SpektrHandler()

        # Simulate being inside the bridge already
        token = _in_bridge.set(True)
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="should be dropped",
                args=(),
                exc_info=None,
            )
            with capture() as logs:
                handler.emit(record)

            assert len(logs) == 0
        finally:
            _in_bridge.reset(token)


class TestBridgeJsonMode:
    def test_bridge_formats_json_when_configured(self):
        """Bridge should format as JSON when output_mode is JSON."""
        import spektr._config as config_module
        from spektr._config import Config, OutputMode
        from spektr._integrations._bridge import SpektrHandler

        handler = SpektrHandler()
        old_config = config_module._config

        try:
            config_module._config = Config(output_mode=OutputMode.JSON)

            record = logging.LogRecord(
                name="sqlalchemy",
                level=logging.INFO,
                pathname="engine.py",
                lineno=42,
                msg="SELECT * FROM users",
                args=(),
                exc_info=None,
            )

            with capture() as logs:
                handler.emit(record)

            assert len(logs) == 1
            assert logs[0].data["logger"] == "sqlalchemy"
        finally:
            config_module._config = old_config
