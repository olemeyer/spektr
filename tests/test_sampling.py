"""Tests for the sampling/rate-limiting subsystem."""

import threading
import time

from spektr._sampling._ratelimit import TokenBucket
from spektr._sampling._sampler import CompositeSampler, RateLimitSampler
from spektr._types import LogLevel


class TestTokenBucketBasic:
    def test_acquire_succeeds_up_to_capacity(self):
        bucket = TokenBucket(rate=0.0, capacity=3)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False

    def test_acquire_fails_when_empty(self):
        bucket = TokenBucket(rate=0.0, capacity=1)
        assert bucket.acquire() is True
        assert bucket.acquire() is False
        assert bucket.acquire() is False

    def test_capacity_of_zero_always_fails(self):
        bucket = TokenBucket(rate=0.0, capacity=0)
        assert bucket.acquire() is False


class TestTokenBucketRefill:
    def test_tokens_refill_after_waiting(self):
        bucket = TokenBucket(rate=100.0, capacity=2)
        # Drain all tokens
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False

        # Wait long enough for at least one token to refill
        time.sleep(0.05)
        assert bucket.acquire() is True

    def test_refill_does_not_exceed_capacity(self):
        bucket = TokenBucket(rate=1000.0, capacity=2)
        # Wait long enough to refill well beyond capacity
        time.sleep(0.05)

        # Should only be able to acquire up to capacity
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False


class TestTokenBucketThreadSafety:
    def test_concurrent_acquire_does_not_over_issue(self):
        capacity = 10
        bucket = TokenBucket(rate=0.0, capacity=capacity)
        results = []
        barrier = threading.Barrier(20)

        def worker():
            barrier.wait()
            results.append(bucket.acquire())

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        successful = sum(1 for result in results if result is True)
        assert successful == capacity


class TestRateLimitSampler:
    def test_allows_within_rate(self):
        sampler = RateLimitSampler(per_second=10.0)
        # First few calls should succeed (up to bucket capacity)
        results = [sampler.should_emit(LogLevel.INFO, f"message {i}") for i in range(5)]
        assert all(results)

    def test_blocks_excess(self):
        sampler = RateLimitSampler(per_second=1.0)
        # Capacity is 1, so second call should fail
        assert sampler.should_emit(LogLevel.INFO, "first") is True
        assert sampler.should_emit(LogLevel.INFO, "second") is False

    def test_error_always_passes(self):
        sampler = RateLimitSampler(per_second=1.0)
        # Drain the bucket
        sampler.should_emit(LogLevel.INFO, "drain")

        # ERROR should still pass even with empty bucket
        for _ in range(10):
            assert sampler.should_emit(LogLevel.ERROR, "error") is True

    def test_warning_is_rate_limited(self):
        sampler = RateLimitSampler(per_second=1.0)
        # Drain the bucket
        sampler.should_emit(LogLevel.WARNING, "drain")

        # WARNING should be rate limited
        assert sampler.should_emit(LogLevel.WARNING, "warning") is False

    def test_debug_is_rate_limited(self):
        sampler = RateLimitSampler(per_second=1.0)
        # Drain the bucket
        sampler.should_emit(LogLevel.DEBUG, "drain")

        # DEBUG should be rate limited
        assert sampler.should_emit(LogLevel.DEBUG, "debug") is False


class TestCompositeSampler:
    def test_all_must_pass(self):
        sampler_a = RateLimitSampler(per_second=100.0)
        sampler_b = RateLimitSampler(per_second=100.0)
        composite = CompositeSampler(sampler_a, sampler_b)

        assert composite.should_emit(LogLevel.INFO, "message") is True

    def test_any_failure_blocks(self):
        # sampler_allow has high rate, sampler_deny has capacity 1
        sampler_allow = RateLimitSampler(per_second=100.0)
        sampler_deny = RateLimitSampler(per_second=1.0)
        composite = CompositeSampler(sampler_allow, sampler_deny)

        # First call passes both
        assert composite.should_emit(LogLevel.INFO, "first") is True
        # Second call fails on sampler_deny
        assert composite.should_emit(LogLevel.INFO, "second") is False

    def test_empty_composite_passes(self):
        composite = CompositeSampler()
        assert composite.should_emit(LogLevel.INFO, "message") is True

    def test_single_sampler_passthrough(self):
        sampler = RateLimitSampler(per_second=1.0)
        composite = CompositeSampler(sampler)

        assert composite.should_emit(LogLevel.INFO, "first") is True
        assert composite.should_emit(LogLevel.INFO, "second") is False

    def test_error_passes_when_all_samplers_allow_error(self):
        sampler_a = RateLimitSampler(per_second=1.0)
        sampler_b = RateLimitSampler(per_second=1.0)
        composite = CompositeSampler(sampler_a, sampler_b)

        # Drain both buckets
        composite.should_emit(LogLevel.INFO, "drain")

        # ERROR should still pass because both RateLimitSamplers allow ERROR
        assert composite.should_emit(LogLevel.ERROR, "error") is True
