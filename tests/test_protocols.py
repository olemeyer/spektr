"""Tests for protocol interfaces and their implementations."""

from __future__ import annotations

import pytest

from spektr._output._sinks import StderrSink
from spektr._protocols import MetricBackend, Sampler, Sink
from spektr._sampling._sampler import CompositeSampler, RateLimitSampler
from spektr._types import LogLevel


class TestSinkProtocol:
    def test_stderr_sink_implements_protocol(self):
        sink = StderrSink()
        assert isinstance(sink, Sink)

    def test_custom_sink_implements_protocol(self):
        class MySink:
            def write(self, record):
                pass

            def flush(self):
                pass

        assert isinstance(MySink(), Sink)

    def test_incomplete_sink_does_not_match(self):
        class BadSink:
            def write(self, record):
                pass
            # Missing flush

        assert not isinstance(BadSink(), Sink)


class TestSamplerProtocol:
    def test_rate_limit_sampler_implements_protocol(self):
        sampler = RateLimitSampler(per_second=100)
        assert isinstance(sampler, Sampler)

    def test_composite_sampler_implements_protocol(self):
        sampler = CompositeSampler(RateLimitSampler(per_second=100))
        assert isinstance(sampler, Sampler)

    def test_custom_sampler_implements_protocol(self):
        class MySampler:
            def should_emit(self, level, message):
                return True

        assert isinstance(MySampler(), Sampler)

    def test_incomplete_sampler_does_not_match(self):
        class BadSampler:
            pass

        assert not isinstance(BadSampler(), Sampler)


class TestMetricBackendProtocol:
    def test_custom_backend_implements_protocol(self):
        class MyBackend:
            def counter(self, name, value, labels):
                pass

            def gauge(self, name, value, labels):
                pass

            def histogram(self, name, value, labels):
                pass

        assert isinstance(MyBackend(), MetricBackend)


class TestRateLimitSampler:
    def test_errors_always_pass(self):
        sampler = RateLimitSampler(per_second=0.001)
        # Exhaust the bucket for normal messages
        for _ in range(100):
            sampler.should_emit(LogLevel.INFO, "spam")
        # Errors should still pass
        assert sampler.should_emit(LogLevel.ERROR, "critical") is True

    def test_rate_limiting_works(self):
        sampler = RateLimitSampler(per_second=1)
        results = [sampler.should_emit(LogLevel.INFO, "msg") for _ in range(100)]
        passed = sum(results)
        # With capacity=1, at most a few should pass immediately
        assert passed < 10

    def test_high_rate_allows_most(self):
        sampler = RateLimitSampler(per_second=10000)
        results = [sampler.should_emit(LogLevel.INFO, "msg") for _ in range(100)]
        passed = sum(results)
        # With very high rate, most should pass
        assert passed > 50


class TestCompositeSampler:
    def test_all_pass(self):
        class AlwaysPass:
            def should_emit(self, level, message):
                return True

        sampler = CompositeSampler(AlwaysPass(), AlwaysPass())
        assert sampler.should_emit(LogLevel.INFO, "test") is True

    def test_one_blocks(self):
        class AlwaysPass:
            def should_emit(self, level, message):
                return True

        class AlwaysBlock:
            def should_emit(self, level, message):
                return False

        sampler = CompositeSampler(AlwaysPass(), AlwaysBlock())
        assert sampler.should_emit(LogLevel.INFO, "test") is False

    def test_empty_composite_passes(self):
        sampler = CompositeSampler()
        assert sampler.should_emit(LogLevel.INFO, "test") is True
