"""Token bucket rate limiter for sampling."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Thread-safe token bucket for rate limiting.

    Tokens are added at a fixed rate and consumed one at a time.
    When the bucket is empty, acquisition fails until tokens refill.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        """
        Args:
            rate: Tokens added per second.
            capacity: Maximum tokens in bucket.
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """Try to consume one token. Returns True if successful."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False
