"""Tests for sensitive data redaction."""

import json
import sys

from spektr import capture, configure, log
from spektr._config import get_config
from spektr._output._formatters import _redact_dict


class TestRedactDict:
    def test_redacts_matching_key(self):
        result = _redact_dict({"password": "hunter2"}, ["password"])
        assert result["password"] == "***"

    def test_substring_match(self):
        result = _redact_dict({"db_password_hash": "abc"}, ["password"])
        assert result["db_password_hash"] == "***"

    def test_case_insensitive(self):
        result = _redact_dict({"API_KEY": "sk-123"}, ["api_key"])
        assert result["API_KEY"] == "***"

    def test_non_matching_keys_pass_through(self):
        result = _redact_dict({"username": "ole", "password": "x"}, ["password"])
        assert result["username"] == "ole"
        assert result["password"] == "***"

    def test_empty_patterns(self):
        data = {"password": "secret"}
        result = _redact_dict(data, [])
        assert result["password"] == "secret"

    def test_multiple_patterns(self):
        result = _redact_dict(
            {"password": "x", "token": "y", "name": "z"},
            ["password", "token"],
        )
        assert result["password"] == "***"
        assert result["token"] == "***"
        assert result["name"] == "z"

    def test_does_not_modify_original(self):
        original = {"password": "secret"}
        _redact_dict(original, ["password"])
        assert original["password"] == "secret"


class TestRedactionDefaults:
    def test_default_redact_patterns(self):
        config = get_config()
        assert "password" in config.redact
        assert "secret" in config.redact
        assert "token" in config.redact
        assert "authorization" in config.redact
        assert "api_key" in config.redact
        assert "apikey" in config.redact


class TestRedactionInCapture:
    def test_capture_sees_raw_values(self):
        """capture() returns unredacted data for test assertions."""
        with capture() as logs:
            log("login", user="ole", password="hunter2")

        assert logs[0].data["password"] == "hunter2"

    def test_capture_with_context_raw_values(self):
        with capture() as logs:
            with log.context(auth_token="abc123"):
                log("req")

        assert logs[0].context["auth_token"] == "abc123"


class TestRedactDictEdgeCases:
    def test_nested_dict_not_deeply_redacted(self):
        """_redact_dict only redacts top-level keys, not nested ones."""
        data = {"config": {"password": "nested_secret"}}
        result = _redact_dict(data, ["password"])
        # Top-level key "config" doesn't match "password"
        assert result["config"]["password"] == "nested_secret"

    def test_non_string_values_redacted(self):
        """Redaction replaces any value type, not just strings."""
        result = _redact_dict({"token": 12345}, ["token"])
        assert result["token"] == "***"

    def test_none_value_redacted(self):
        result = _redact_dict({"api_key": None}, ["api_key"])
        assert result["api_key"] == "***"

    def test_list_value_redacted(self):
        result = _redact_dict({"secret_data": [1, 2, 3]}, ["secret"])
        assert result["secret_data"] == "***"

    def test_pattern_at_start_of_key(self):
        result = _redact_dict({"password_hash": "abc"}, ["password"])
        assert result["password_hash"] == "***"

    def test_pattern_at_end_of_key(self):
        result = _redact_dict({"db_password": "abc"}, ["password"])
        assert result["db_password"] == "***"

    def test_pattern_exact_match(self):
        result = _redact_dict({"token": "abc"}, ["token"])
        assert result["token"] == "***"

    def test_empty_dict(self):
        result = _redact_dict({}, ["password"])
        assert result == {}


class TestRedactionInOutput:
    def test_json_output_redacted(self, capsys):
        """JSON output should redact sensitive keys."""
        from spektr._output._formatters import format_record_json
        from spektr._types import LogLevel, LogRecord

        import time as _time

        record = LogRecord(
            timestamp=_time.time(),
            level=LogLevel.INFO,
            message="test",
            data={"user": "ole", "password": "hunter2"},
            context={"auth_token": "secret123"},
        )
        format_record_json(record)
        output = capsys.readouterr().err
        parsed = json.loads(output)
        assert parsed["user"] == "ole"
        assert parsed["password"] == "***"
        assert parsed["auth_token"] == "***"

    def test_custom_redact_patterns(self, capsys):
        """configure(redact=...) overrides default patterns."""
        from spektr._config import _config
        from spektr._output._formatters import format_record_json
        from spektr._types import LogLevel, LogRecord

        import time as _time

        original_redact = get_config().redact[:]
        try:
            configure(redact=["custom_secret"])

            record = LogRecord(
                timestamp=_time.time(),
                level=LogLevel.INFO,
                message="test",
                data={"custom_secret": "value", "password": "visible"},
                context={},
            )
            format_record_json(record)
            output = capsys.readouterr().err
            parsed = json.loads(output)
            assert parsed["custom_secret"] == "***"
            assert parsed["password"] == "visible"  # not in custom list
        finally:
            configure(redact=original_redact)

    def test_redaction_with_all_default_patterns(self):
        """All default patterns should redact correctly."""
        data = {
            "password": "p",
            "secret": "s",
            "token": "t",
            "authorization": "a",
            "api_key": "k",
            "apikey": "ak",
            "safe_field": "visible",
        }
        config = get_config()
        result = _redact_dict(data, config.redact)
        assert result["password"] == "***"
        assert result["secret"] == "***"
        assert result["token"] == "***"
        assert result["authorization"] == "***"
        assert result["api_key"] == "***"
        assert result["apikey"] == "***"
        assert result["safe_field"] == "visible"

    def test_redaction_in_log_pipeline(self, capsys):
        """End-to-end: log with sensitive data, verify JSON output is redacted."""
        from spektr._output._formatters import format_record_json
        from spektr._types import LogLevel, LogRecord

        import time as _time

        record = LogRecord(
            timestamp=_time.time(),
            level=LogLevel.INFO,
            message="auth",
            data={"user": "ole", "api_key": "sk-123", "authorization": "Bearer xyz"},
            context={"secret_token": "abc"},
        )
        format_record_json(record)
        output = capsys.readouterr().err
        parsed = json.loads(output)
        assert parsed["user"] == "ole"
        assert parsed["api_key"] == "***"
        assert parsed["authorization"] == "***"
        assert parsed["secret_token"] == "***"
