"""Tests for spektr configuration – configure(), env vars, auto-detection."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from spektr._config import Config, OutputMode, configure, get_config
from spektr import LogLevel
import spektr._config as config_module


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config before each test."""
    config_module._config = None
    yield
    config_module._config = None


class TestConfigDefaults:
    def test_default_service(self):
        cfg = Config()
        assert cfg.service == "default"

    def test_default_output_mode_is_rich(self):
        cfg = Config()
        assert cfg.output_mode == OutputMode.RICH

    def test_default_min_level_is_debug(self):
        cfg = Config()
        assert cfg.min_level == LogLevel.DEBUG

    def test_default_no_endpoint(self):
        cfg = Config()
        assert cfg.endpoint is None


class TestConfigFromEnv:
    def test_otel_endpoint_switches_to_json(self):
        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}):
            cfg = Config.from_env()
        assert cfg.output_mode == OutputMode.JSON
        assert cfg.endpoint == "http://collector:4318"

    def test_spektr_endpoint(self):
        with patch.dict(os.environ, {"SPEKTR_ENDPOINT": "http://my-backend:4318"}):
            cfg = Config.from_env()
        assert cfg.endpoint == "http://my-backend:4318"
        assert cfg.output_mode == OutputMode.JSON

    def test_spektr_json_flag(self):
        with patch.dict(os.environ, {"SPEKTR_JSON": "1"}):
            cfg = Config.from_env()
        assert cfg.output_mode == OutputMode.JSON

    def test_spektr_json_true(self):
        with patch.dict(os.environ, {"SPEKTR_JSON": "true"}):
            cfg = Config.from_env()
        assert cfg.output_mode == OutputMode.JSON

    def test_no_color_switches_to_json(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            cfg = Config.from_env()
        assert cfg.output_mode == OutputMode.JSON

    def test_log_level_from_env(self):
        with patch.dict(os.environ, {"SPEKTR_LOG_LEVEL": "WARNING"}):
            cfg = Config.from_env()
        assert cfg.min_level == LogLevel.WARNING

    def test_log_level_case_insensitive(self):
        with patch.dict(os.environ, {"SPEKTR_LOG_LEVEL": "error"}):
            cfg = Config.from_env()
        assert cfg.min_level == LogLevel.ERROR

    def test_invalid_log_level_ignored(self):
        with patch.dict(os.environ, {"SPEKTR_LOG_LEVEL": "INVALID"}):
            cfg = Config.from_env()
        assert cfg.min_level == LogLevel.DEBUG

    def test_service_from_spektr_env(self):
        with patch.dict(os.environ, {"SPEKTR_SERVICE": "my-api"}):
            cfg = Config.from_env()
        assert cfg.service == "my-api"

    def test_service_from_otel_env(self):
        with patch.dict(os.environ, {"OTEL_SERVICE_NAME": "otel-svc"}):
            cfg = Config.from_env()
        assert cfg.service == "otel-svc"

    def test_spektr_service_takes_precedence(self):
        with patch.dict(os.environ, {"SPEKTR_SERVICE": "spektr-svc", "OTEL_SERVICE_NAME": "otel-svc"}):
            cfg = Config.from_env()
        assert cfg.service == "spektr-svc"


class TestConfigure:
    def test_configure_sets_service(self):
        configure(service="my-app")
        assert get_config().service == "my-app"

    def test_configure_sets_endpoint_and_switches_mode(self):
        configure(endpoint="http://collector:4318")
        cfg = get_config()
        assert cfg.endpoint == "http://collector:4318"
        assert cfg.output_mode == OutputMode.JSON

    def test_configure_explicit_output_mode(self):
        configure(endpoint="http://collector:4318", output_mode=OutputMode.RICH)
        assert get_config().output_mode == OutputMode.RICH

    def test_configure_min_level(self):
        configure(min_level=LogLevel.WARNING)
        assert get_config().min_level == LogLevel.WARNING

    def test_configure_unknown_option_raises(self):
        with pytest.raises(ValueError, match="Unknown config option"):
            configure(nonexistent="value")

    def test_configure_multiple_options(self):
        configure(service="test", min_level=LogLevel.ERROR, show_source=False)
        cfg = get_config()
        assert cfg.service == "test"
        assert cfg.min_level == LogLevel.ERROR
        assert cfg.show_source is False


class TestMinLevel:
    def test_debug_filtered_when_min_is_info(self):
        from spektr import capture, log

        configure(min_level=LogLevel.INFO)
        with capture() as logs:
            log.debug("should be filtered")
            log.info("should appear")
        assert len(logs) == 1
        assert logs[0].message == "should appear"

    def test_all_levels_when_min_is_debug(self):
        from spektr import capture, log

        configure(min_level=LogLevel.DEBUG)
        with capture() as logs:
            log.debug("d")
            log.info("i")
            log.warn("w")
            log.error("e")
        assert len(logs) == 4

    def test_only_error_when_min_is_error(self):
        from spektr import capture, log

        configure(min_level=LogLevel.ERROR)
        with capture() as logs:
            log.debug("d")
            log.info("i")
            log.warn("w")
            log.error("e")
        assert len(logs) == 1
        assert logs[0].level == LogLevel.ERROR
