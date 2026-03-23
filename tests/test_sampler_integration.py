"""Tests for sampler integration with the logging pipeline."""

from __future__ import annotations

import pytest

import spektr._config as config_module
from spektr import capture, configure, log
from spektr._sampling._sampler import CompositeSampler, RateLimitSampler
from spektr import LogLevel


@pytest.fixture(autouse=True)
def reset_config():
    old = config_module._config
    yield
    config_module._config = old


class TestSamplerIntegration:
    def test_sampler_blocks_messages(self):
        class BlockAll:
            def should_emit(self, level, message):
                return False

        configure(sampler=BlockAll())
        with capture() as logs:
            log("should be blocked")

        assert len(logs) == 0

    def test_sampler_passes_messages(self):
        class PassAll:
            def should_emit(self, level, message):
                return True

        configure(sampler=PassAll())
        with capture() as logs:
            log("should pass")

        assert len(logs) == 1

    def test_sampler_receives_level_and_message(self):
        received = []

        class SpySampler:
            def should_emit(self, level, message):
                received.append((level, message))
                return True

        configure(sampler=SpySampler())
        with capture():
            log.error("boom")

        assert received[0] == (LogLevel.ERROR, "boom")

    def test_no_sampler_by_default(self):
        """Without a sampler, all messages pass."""
        configure(sampler=None)
        with capture() as logs:
            log("no sampler")

        assert len(logs) == 1

    def test_rate_limit_sampler_allows_errors(self):
        sampler = RateLimitSampler(per_second=0.001)
        configure(sampler=sampler)
        with capture() as logs:
            for _ in range(10):
                log.error("critical")

        # All errors should pass the rate limiter
        assert len(logs) == 10

    def test_rate_limit_sampler_limits_info(self):
        sampler = RateLimitSampler(per_second=1)
        configure(sampler=sampler)
        with capture() as logs:
            for _ in range(100):
                log.info("spam")

        # With rate=1/s, very few should pass in a tight loop
        assert len(logs) < 10

    def test_composite_sampler_chains(self):
        class LevelFilter:
            def should_emit(self, level, message):
                return level >= LogLevel.WARNING

        class MessageFilter:
            def should_emit(self, level, message):
                return "important" in message

        sampler = CompositeSampler(LevelFilter(), MessageFilter())
        configure(sampler=sampler)

        with capture() as logs:
            log.warning("important alert")
            log.warning("minor alert")
            log.info("important note")
            log.info("nothing")

        # Only "important alert" passes both filters
        assert len(logs) == 1
        assert logs[0].message == "important alert"

    def test_sampler_does_not_affect_min_level(self):
        """min_level check happens before sampler."""

        class PassAll:
            def should_emit(self, level, message):
                return True

        configure(sampler=PassAll(), min_level=LogLevel.WARNING)
        with capture() as logs:
            log.debug("should be filtered by level")

        assert len(logs) == 0
