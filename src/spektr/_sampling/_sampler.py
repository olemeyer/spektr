"""Sampling strategies implementing the Sampler protocol."""

from __future__ import annotations

from .._protocols import Sampler
from .._types import LogLevel
from ._ratelimit import TokenBucket


class RateLimitSampler:
    """Sampler that limits emissions to a maximum per-second rate.

    Uses a token bucket internally. ERROR-level messages always pass
    regardless of the rate limit.
    """

    def __init__(self, per_second: float) -> None:
        """
        Args:
            per_second: Maximum number of log records emitted per second.
        """
        self._bucket = TokenBucket(rate=per_second, capacity=max(1, int(per_second)))

    def should_emit(self, level: int, message: str) -> bool:
        """Return True if the record should be emitted.

        ERROR-level records always pass. All others are rate-limited.
        """
        if level >= LogLevel.ERROR:
            return True
        return self._bucket.acquire()


class CompositeSampler:
    """Chains multiple samplers — all must pass for a record to be emitted."""

    def __init__(self, *samplers: Sampler) -> None:
        """
        Args:
            *samplers: One or more Sampler instances to chain.
        """
        self._samplers = samplers

    def should_emit(self, level: int, message: str) -> bool:
        """Return True only if every sampler in the chain allows emission."""
        return all(sampler.should_emit(level, message) for sampler in self._samplers)
