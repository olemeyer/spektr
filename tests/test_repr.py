"""Tests for safe object representation (_repr module).

Covers edge cases that can crash logging pipelines: broken __repr__,
enormous objects, circular references, and hostile __str__.
"""

import json

import pytest

from spektr._repr import safe_repr, safe_str


# ── Helpers ───────────────────────────────────────────────────────


class BrokenRepr:
    """__repr__ raises."""

    def __repr__(self):
        raise RuntimeError("boom")


class BrokenStr:
    """__str__ raises, __repr__ also raises."""

    def __str__(self):
        raise RuntimeError("str boom")

    def __repr__(self):
        raise RuntimeError("repr boom")


class HugeRepr:
    """__repr__ returns an enormous string."""

    def __repr__(self):
        return "x" * 10_000


class SlowRepr:
    """Simulates a repr that produces a moderately large but safe string."""

    def __repr__(self):
        return f"SlowRepr(data={'a' * 500})"


class NiceObject:
    def __repr__(self):
        return "NiceObject(value=42)"

    def __str__(self):
        return "NiceObject: 42"


# ── safe_repr ─────────────────────────────────────────────────────


class TestSafeRepr:
    def test_string_passthrough(self):
        assert safe_repr("hello") == "hello"

    def test_string_truncation(self):
        long_string = "a" * 300
        result = safe_repr(long_string, max_length=100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    def test_short_string_no_truncation(self):
        assert safe_repr("short", max_length=100) == "short"

    def test_integer(self):
        assert safe_repr(42) == "42"

    def test_float(self):
        assert safe_repr(3.14) == "3.14"

    def test_none(self):
        assert safe_repr(None) == "None"

    def test_bool(self):
        assert safe_repr(True) == "True"

    def test_list(self):
        result = safe_repr([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_dict(self):
        result = safe_repr({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_broken_repr_does_not_raise(self):
        obj = BrokenRepr()
        result = safe_repr(obj)
        assert "BrokenRepr" in result
        assert "0x" in result  # fallback includes memory address

    def test_broken_repr_and_str(self):
        obj = BrokenStr()
        result = safe_repr(obj)
        assert "BrokenStr" in result

    def test_huge_repr_truncated(self):
        obj = HugeRepr()
        result = safe_repr(obj, max_length=200)
        assert len(result) <= 203  # max_length + "..."
        assert "..." in result  # reprlib or our truncation inserted ellipsis

    def test_large_list_truncated(self):
        """reprlib limits collection size – a 1000-element list should be truncated."""
        big_list = list(range(1000))
        result = safe_repr(big_list)
        assert "..." in result
        assert len(result) < 500  # much smaller than full repr

    def test_deeply_nested(self):
        """reprlib limits nesting depth."""
        nested = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        result = safe_repr(nested)
        assert "..." in result  # depth limit hit

    def test_circular_reference(self):
        """Circular references should not cause infinite recursion."""
        circular: list = [1, 2]
        circular.append(circular)
        result = safe_repr(circular)
        # reprlib handles this with depth limiting
        assert isinstance(result, str)
        assert len(result) < 500

    def test_nice_object(self):
        obj = NiceObject()
        result = safe_repr(obj)
        assert "NiceObject" in result
        assert "42" in result

    def test_custom_max_length(self):
        result = safe_repr("a" * 50, max_length=20)
        assert len(result) == 23  # 20 + "..."
        assert result == "a" * 20 + "..."

    def test_bytes(self):
        result = safe_repr(b"hello")
        assert result == "b'hello'"

    def test_set(self):
        result = safe_repr({1})
        assert "1" in result

    def test_large_string_inside_dict(self):
        """Strings inside collections are truncated by reprlib."""
        data = {"key": "x" * 10_000}
        result = safe_repr(data)
        assert len(result) <= 203


# ── safe_str ──────────────────────────────────────────────────────


class TestSafeStr:
    def test_string_passthrough(self):
        assert safe_str("hello") == "hello"

    def test_string_truncation(self):
        long_string = "a" * 300
        result = safe_str(long_string, max_length=100)
        assert len(result) == 103
        assert result.endswith("...")

    def test_integer(self):
        assert safe_str(42) == "42"

    def test_float(self):
        assert safe_str(3.14) == "3.14"

    def test_nice_object_uses_str(self):
        """safe_str prefers str() over repr() for cleaner output."""
        obj = NiceObject()
        result = safe_str(obj)
        assert result == "NiceObject: 42"  # str(), not repr()

    def test_broken_str_falls_back_to_safe_repr(self):
        obj = BrokenStr()
        result = safe_str(obj)
        assert "BrokenStr" in result  # fell back to safe_repr

    def test_huge_str_truncated(self):
        class HugeStr:
            def __str__(self):
                return "y" * 10_000

        result = safe_str(HugeStr(), max_length=200)
        assert len(result) <= 203
        assert result.endswith("...")

    def test_none(self):
        assert safe_str(None) == "None"

    def test_list(self):
        assert safe_str([1, 2, 3]) == "[1, 2, 3]"

    def test_path_like_object(self):
        """pathlib.Path uses str() for clean output."""
        from pathlib import Path

        result = safe_str(Path("/tmp/test.txt"))
        assert result == "/tmp/test.txt"  # str(), not PosixPath(...)


# ── Integration: verify safe_repr is used in formatters ───────────


class TestSafeReprBoundaries:
    def test_string_exactly_at_max_length(self):
        """String with len == max_length should not be truncated."""
        string = "a" * 200
        result = safe_repr(string, max_length=200)
        assert result == string
        assert "..." not in result

    def test_string_one_over_max_length(self):
        string = "a" * 201
        result = safe_repr(string, max_length=200)
        assert len(result) == 203
        assert result.endswith("...")

    def test_max_length_1(self):
        result = safe_repr("hello", max_length=1)
        assert result == "h..."

    def test_empty_string(self):
        assert safe_repr("") == ""

    def test_unicode_string(self):
        result = safe_repr("こんにちは世界")
        assert result == "こんにちは世界"

    def test_unicode_truncation(self):
        """Unicode strings should truncate by character count, not bytes."""
        string = "こ" * 300
        result = safe_repr(string, max_length=100)
        assert len(result) == 103

    def test_tuple(self):
        result = safe_repr((1, 2, 3))
        assert result == "(1, 2, 3)"

    def test_large_tuple_truncated(self):
        big_tuple = tuple(range(100))
        result = safe_repr(big_tuple)
        assert "..." in result

    def test_frozenset(self):
        result = safe_repr(frozenset([1]))
        assert "1" in result

    def test_empty_collections(self):
        assert safe_repr([]) == "[]"
        assert safe_repr({}) == "{}"
        assert safe_repr(()) == "()"
        assert safe_repr(set()) == "set()"


class TestSafeReprExceptionChain:
    def test_type_name_raises(self):
        """Object where type().__name__ raises should return '<unrepresentable>'."""
        class EvilMeta(type):
            @property
            def __name__(cls):
                raise RuntimeError("evil meta")

        class Evil(metaclass=EvilMeta):
            def __repr__(self):
                raise RuntimeError("repr fails")

        obj = object.__new__(Evil)
        result = safe_repr(obj)
        assert result == "<unrepresentable>"


class TestSafeStrBoundaries:
    def test_string_exactly_at_max_length(self):
        string = "b" * 200
        result = safe_str(string, max_length=200)
        assert result == string
        assert "..." not in result

    def test_string_one_over_max_length(self):
        string = "b" * 201
        result = safe_str(string, max_length=200)
        assert len(result) == 203

    def test_empty_string(self):
        assert safe_str("") == ""

    def test_str_raises_repr_also_raises(self):
        """When both str() and repr() fail, should still return something."""
        obj = BrokenStr()
        result = safe_str(obj)
        assert isinstance(result, str)
        assert "BrokenStr" in result

    def test_datetime_uses_str(self):
        """datetime objects should use str() for clean ISO format."""
        from datetime import datetime, timezone
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        result = safe_str(dt)
        assert "2024" in result
        assert "12:30" in result

    def test_uuid_uses_str(self):
        import uuid
        uid = uuid.uuid4()
        result = safe_str(uid)
        # str(uuid) returns the hex string, not UUID('...')
        assert "UUID" not in result
        assert "-" in result


class TestFormatterIntegration:
    def test_broken_repr_in_log_data(self):
        """Logging an object with broken __repr__ should not crash."""
        from spektr import capture, log

        obj = BrokenRepr()
        with capture() as logs:
            log("test", value=obj)

        assert len(logs) == 1
        assert logs[0].data["value"] is obj

    def test_huge_object_in_log_data(self):
        """Logging an object with huge repr should not produce unbounded output."""
        from spektr import capture, log

        obj = HugeRepr()
        with capture() as logs:
            log("test", value=obj)

        assert len(logs) == 1

    def test_broken_repr_in_json_output(self, capsys):
        """JSON formatter should handle broken repr without crashing."""
        from spektr._output._formatters import format_record_json
        from spektr._types import LogLevel, LogRecord
        import time as _time

        obj = BrokenRepr()
        record = LogRecord(
            timestamp=_time.time(),
            level=LogLevel.INFO,
            message="test",
            data={"value": obj},
            context={},
        )
        format_record_json(record)
        output = capsys.readouterr().err
        parsed = json.loads(output)
        assert "BrokenRepr" in parsed["value"]

    def test_broken_repr_in_rich_output(self, capsys):
        """Rich formatter should handle broken repr without crashing."""
        from spektr._output._formatters import format_record_rich
        from spektr._types import LogLevel, LogRecord
        import time as _time

        obj = BrokenRepr()
        record = LogRecord(
            timestamp=_time.time(),
            level=LogLevel.INFO,
            message="test",
            data={"value": obj},
            context={},
        )
        # Should not raise
        format_record_rich(record)

    def test_circular_ref_in_log_data(self):
        """Logging an object with circular reference should not hang."""
        from spektr import capture, log

        circular = {"key": "value"}
        circular["self"] = circular

        with capture() as logs:
            log("test", data=circular)

        assert len(logs) == 1
