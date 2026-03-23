"""Tests for rate-limited logging – once(), every(), sample()."""

import threading

from spektr import capture, log
from spektr._core._logger import _every_counters, _once_seen, _rate_lock
from spektr import LogLevel


def _reset_rate_state():
    """Clear rate-limiting state between tests."""
    with _rate_lock:
        _once_seen.clear()
        _every_counters.clear()


class TestOnce:
    def setup_method(self):
        _reset_rate_state()

    def test_logs_first_call_only(self):
        with capture() as logs:
            for _ in range(10):
                log.once("startup complete")

        assert len(logs) == 1
        assert logs[0].message == "startup complete"

    def test_different_messages_logged_independently(self):
        with capture() as logs:
            log.once("first")
            log.once("second")
            log.once("first")
            log.once("second")

        assert len(logs) == 2
        assert logs[0].message == "first"
        assert logs[1].message == "second"

    def test_kwargs_passed_through(self):
        with capture() as logs:
            log.once("cache initialized", backend="redis")

        assert logs[0].data["backend"] == "redis"

    def test_logs_at_info_level(self):
        with capture() as logs:
            log.once("msg")

        assert logs[0].level == LogLevel.INFO

    def test_thread_safe(self):
        threads = []
        for _ in range(20):
            t = threading.Thread(target=lambda: log.once("thread msg"))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        # All 20 threads called once() — message should be in the seen set
        assert "thread msg" in _once_seen

        # Calling again from main thread should be suppressed
        with capture() as logs:
            log.once("thread msg")

        assert len(logs) == 0


class TestEvery:
    def setup_method(self):
        _reset_rate_state()

    def test_first_call_logs(self):
        with capture() as logs:
            log.every(5, "batch")

        assert len(logs) == 1

    def test_logs_every_nth(self):
        with capture() as logs:
            for _ in range(9):
                log.every(3, "batch")

        assert len(logs) == 3

    def test_kwargs_passed_through(self):
        with capture() as logs:
            log.every(1, "item processed", count=42)

        assert logs[0].data["count"] == 42

    def test_every_1_logs_every_time(self):
        with capture() as logs:
            for _ in range(5):
                log.every(1, "always")

        assert len(logs) == 5

    def test_different_messages_tracked_independently(self):
        with capture() as logs:
            for _ in range(6):
                log.every(2, "alpha")
                log.every(3, "beta")

        alpha_logs = [r for r in logs if r.message == "alpha"]
        beta_logs = [r for r in logs if r.message == "beta"]
        assert len(alpha_logs) == 3  # calls 0, 2, 4
        assert len(beta_logs) == 2  # calls 0, 3


class TestOnceEdgeCases:
    def setup_method(self):
        _reset_rate_state()

    def test_once_with_kwargs_still_deduplicates(self):
        """Different kwargs on same message should still deduplicate."""
        with capture() as logs:
            log.once("init", backend="redis")
            log.once("init", backend="memcached")

        assert len(logs) == 1
        assert logs[0].data["backend"] == "redis"

    def test_once_empty_message(self):
        with capture() as logs:
            log.once("")
            log.once("")

        assert len(logs) == 1
        assert logs[0].message == ""

    def test_once_on_bound_logger(self):
        db = log.bind(component="db")
        with capture() as logs:
            db.once("connected")
            db.once("connected")

        assert len(logs) == 1
        assert logs[0].context["component"] == "db"


class TestEveryEdgeCases:
    def setup_method(self):
        _reset_rate_state()

    def test_every_large_n(self):
        with capture() as logs:
            for _ in range(100):
                log.every(50, "rare")

        assert len(logs) == 2  # calls 0 and 50

    def test_every_on_bound_logger(self):
        db = log.bind(component="db")
        with capture() as logs:
            for _ in range(6):
                db.every(3, "heartbeat")

        assert len(logs) == 2
        assert logs[0].context["component"] == "db"

    def test_every_with_n_equals_1(self):
        """every(1, ...) should log every single call."""
        with capture() as logs:
            for _ in range(3):
                log.every(1, "all")

        assert len(logs) == 3


class TestSample:
    def test_rate_zero_never_logs(self):
        with capture() as logs:
            for _ in range(100):
                log.sample(0.0, "never")

        assert len(logs) == 0

    def test_rate_one_always_logs(self):
        with capture() as logs:
            for _ in range(10):
                log.sample(1.0, "always")

        assert len(logs) == 10

    def test_probabilistic(self):
        """With rate=0.5 and 1000 calls, expect roughly 500 logs."""
        with capture() as logs:
            for _ in range(1000):
                log.sample(0.5, "half")

        # Wide tolerance to avoid flaky tests
        assert 300 < len(logs) < 700

    def test_kwargs_passed_through(self):
        with capture() as logs:
            log.sample(1.0, "req", path="/api")

        assert logs[0].data["path"] == "/api"

    def test_logs_at_info_level(self):
        with capture() as logs:
            log.sample(1.0, "msg")

        assert logs[0].level == LogLevel.INFO

    def test_sample_very_low_rate(self):
        """Rate near zero should produce very few logs."""
        with capture() as logs:
            for _ in range(100):
                log.sample(0.01, "rare")

        assert len(logs) < 20

    def test_sample_on_bound_logger(self):
        db = log.bind(component="db")
        with capture() as logs:
            db.sample(1.0, "query", table="users")

        assert logs[0].context["component"] == "db"
        assert logs[0].data["table"] == "users"


# ── Rate-Limit Chaining ────────────────────────────────────


class TestRateLimitChaining:
    def setup_method(self):
        _reset_rate_state()

    def test_once_chained_warn(self):
        with capture() as logs:
            log.once().warn("deprecated API called")
            log.once().warn("deprecated API called")

        assert len(logs) == 1
        assert logs[0].level == LogLevel.WARNING
        assert logs[0].message == "deprecated API called"

    def test_once_chained_debug(self):
        with capture() as logs:
            log.once().debug("one-time debug info")

        assert logs[0].level == LogLevel.DEBUG

    def test_once_chained_error(self):
        with capture() as logs:
            log.once().error("critical config missing")

        assert logs[0].level == LogLevel.ERROR

    def test_once_chained_warning_alias(self):
        with capture() as logs:
            log.once().warning("alias test")

        assert logs[0].level == LogLevel.WARNING

    def test_once_chained_with_kwargs(self):
        with capture() as logs:
            log.once().warn("stale cache", backend="redis")

        assert logs[0].data["backend"] == "redis"

    def test_once_chained_with_formatting(self):
        with capture() as logs:
            log.once().info("started {service}", service="api")

        assert logs[0].message == "started api"

    def test_once_chained_deduplicates(self):
        with capture() as logs:
            log.once().warn("msg")
            log.once().error("msg")  # same message, should be dropped

        assert len(logs) == 1
        assert logs[0].level == LogLevel.WARNING

    def test_once_direct_still_works(self):
        with capture() as logs:
            log.once("msg", key="val")

        assert len(logs) == 1
        assert logs[0].level == LogLevel.INFO
        assert logs[0].data["key"] == "val"

    def test_every_chained_warn(self):
        with capture() as logs:
            for _ in range(6):
                log.every(3).warn("slow query")

        assert len(logs) == 2
        assert all(r.level == LogLevel.WARNING for r in logs)

    def test_every_chained_debug(self):
        with capture() as logs:
            for _ in range(3):
                log.every(3).debug("heartbeat")

        assert len(logs) == 1
        assert logs[0].level == LogLevel.DEBUG

    def test_every_chained_with_kwargs(self):
        with capture() as logs:
            log.every(1).warn("query", table="orders")

        assert logs[0].data["table"] == "orders"

    def test_every_direct_still_works(self):
        with capture() as logs:
            for _ in range(6):
                log.every(3, "batch")

        assert len(logs) == 2
        assert all(r.level == LogLevel.INFO for r in logs)

    def test_every_chained_formatting(self):
        with capture() as logs:
            for i in range(6):
                log.every(3).info("batch {i}", i=i)

        assert len(logs) == 2
        assert logs[0].message == "batch 0"
        assert logs[1].message == "batch 3"

    def test_sample_chained_debug(self):
        with capture() as logs:
            for _ in range(100):
                log.sample(1.0).debug("verbose trace")

        assert len(logs) == 100
        assert all(r.level == LogLevel.DEBUG for r in logs)

    def test_sample_chained_warn(self):
        with capture() as logs:
            log.sample(1.0).warn("retrying", attempt=3)

        assert logs[0].level == LogLevel.WARNING
        assert logs[0].data["attempt"] == 3

    def test_sample_chained_zero_rate(self):
        with capture() as logs:
            for _ in range(100):
                log.sample(0.0).error("never")

        assert len(logs) == 0

    def test_sample_direct_still_works(self):
        with capture() as logs:
            log.sample(1.0, "msg", key="val")

        assert logs[0].level == LogLevel.INFO
        assert logs[0].data["key"] == "val"

    def test_chained_callable(self):
        """log.once()("msg") should work like log.once().info("msg")."""
        with capture() as logs:
            log.once()("shorthand")

        assert len(logs) == 1
        assert logs[0].level == LogLevel.INFO

    def test_chained_on_bound_logger(self):
        db = log.bind(component="db")
        with capture() as logs:
            db.once().warn("connection pool exhausted")

        assert logs[0].level == LogLevel.WARNING
        assert logs[0].context["component"] == "db"

    def test_reusable_rate_limited_logger(self):
        """Storing the rate-limited logger should work."""
        sampled = log.sample(1.0)
        with capture() as logs:
            sampled.debug("a")
            sampled.debug("b")
            sampled.debug("c")

        assert len(logs) == 3
        assert all(r.level == LogLevel.DEBUG for r in logs)


# ── Caller Key ──────────────────────────────────────────────


class TestCallerKey:
    def test_caller_key_fallback_on_deep_depth(self):
        """_caller_key should return fallback on frame error."""
        from spektr._core._logger import _caller_key

        key = _caller_key("test", depth=9999)
        assert key == ("test", "", 0)

    def test_user_caller_key_walks_past_spektr_frames(self):
        """_user_caller_key should walk up past spektr frames."""
        from spektr._core._logger import _user_caller_key

        key = _user_caller_key("test")
        assert key[0] == "test"
        assert key[1] != ""  # should have a real filename
        assert key[2] > 0  # should have a real line number
