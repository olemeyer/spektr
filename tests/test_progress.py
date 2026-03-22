"""Tests for progress tracking – log.progress() context manager."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from spektr import capture, log
from spektr._metrics._progress import ProgressTracker, _use_tqdm
from spektr._types import LogLevel


class TestProgressBasic:
    def test_progress_logs_start_and_end(self):
        with capture() as logs:
            with log.progress("import", total=100) as progress:
                pass
        # Should have at least start progress + completed
        assert len(logs) >= 2
        assert "progress" in logs[0].message
        assert "completed" in logs[-1].message

    def test_progress_completed_has_duration(self):
        with capture() as logs:
            with log.progress("batch", total=10) as progress:
                for _ in range(10):
                    progress.advance()
        completed = logs[-1]
        assert "duration_ms" in completed.data
        assert completed.data["duration_ms"] >= 0

    def test_progress_completed_has_status(self):
        with capture() as logs:
            with log.progress("task") as progress:
                pass
        completed = logs[-1]
        assert completed.data["status"] == "completed"

    def test_progress_tracks_current(self):
        with capture() as logs:
            with log.progress("items", total=5) as progress:
                for _ in range(5):
                    progress.advance()
        completed = logs[-1]
        assert completed.data["current"] == 5

    def test_progress_with_total_shows_percent(self):
        with capture() as logs:
            with log.progress("upload", total=100) as progress:
                for _ in range(100):
                    progress.advance()
        completed = logs[-1]
        assert completed.data["percent"] == 100.0

    def test_progress_without_total(self):
        with capture() as logs:
            with log.progress("stream") as progress:
                progress.advance(50)
        completed = logs[-1]
        assert completed.data["current"] == 50
        assert "total" not in completed.data

    def test_progress_advance_by_n(self):
        with capture() as logs:
            with log.progress("bulk", total=1000) as progress:
                progress.advance(500)
                progress.advance(500)
        completed = logs[-1]
        assert completed.data["current"] == 1000

    def test_progress_set_absolute(self):
        with capture() as logs:
            with log.progress("download", total=100) as progress:
                progress.set(75)
        completed = logs[-1]
        assert completed.data["current"] == 75


class TestProgressRateLimiting:
    def test_progress_rate_limits_logs(self):
        """Should not log every single advance, only at intervals."""
        with capture() as logs:
            with log.progress("fast", total=10000, log_interval=10.0) as progress:
                for _ in range(10000):
                    progress.advance()
        # With a huge interval, only start + completed should be logged
        assert len(logs) == 2

    def test_progress_logs_on_interval(self):
        """Logs should appear at the configured interval."""
        with capture() as logs:
            with log.progress("timed", total=100, log_interval=0.01) as progress:
                for i in range(100):
                    progress.advance()
                    if i % 20 == 0:
                        time.sleep(0.015)
        # Should have more than just start + completed
        assert len(logs) > 2


class TestProgressEdgeCases:
    def test_progress_zero_total(self):
        with capture() as logs:
            with log.progress("empty", total=0) as progress:
                pass
        completed = logs[-1]
        assert completed.data["percent"] == 100.0

    def test_progress_name_in_messages(self):
        with capture() as logs:
            with log.progress("my-task", total=10) as progress:
                progress.advance()
        for record in logs:
            assert "my-task" in record.message or "my-task" in record.data.get("name", "")

    def test_progress_logs_at_info_level(self):
        with capture() as logs:
            with log.progress("task") as progress:
                pass
        for record in logs:
            assert record.level == LogLevel.INFO


class TestProgressTqdm:
    """Tests for tqdm integration in ProgressTracker."""

    def test_use_tqdm_false_when_not_installed(self):
        with patch("spektr._metrics._progress._tqdm", None):
            assert _use_tqdm() is False

    def test_tqdm_bar_created_when_enabled(self):
        """When use_tqdm=True, a tqdm bar is created and updated."""
        mock_bar = MagicMock()
        with patch("spektr._metrics._progress._tqdm", return_value=mock_bar) as mock_tqdm_cls:
            tracker = ProgressTracker(log, "test", total=100, use_tqdm=True)
            with capture() as logs:
                with tracker:
                    tracker.advance(50)
                    tracker.advance(50)

            mock_tqdm_cls.assert_called_once()
            assert mock_bar.update.call_count == 2
            mock_bar.update.assert_any_call(50)
            mock_bar.close.assert_called_once()

            # Completed summary still logged
            assert "completed" in logs[-1].message
            assert logs[-1].data["current"] == 100

    def test_tqdm_bar_set_updates_delta(self):
        """set() should update tqdm with the delta, not the absolute value."""
        mock_bar = MagicMock()
        with patch("spektr._metrics._progress._tqdm", return_value=mock_bar):
            tracker = ProgressTracker(log, "test", total=100, use_tqdm=True)
            with capture() as logs:
                with tracker:
                    tracker.advance(20)
                    tracker.set(75)

            # set(75) from current=20 should update by 55
            mock_bar.update.assert_any_call(20)
            mock_bar.update.assert_any_call(55)

    def test_tqdm_suppresses_interval_logs(self):
        """When tqdm is active, no interval progress logs should be emitted."""
        mock_bar = MagicMock()
        with patch("spektr._metrics._progress._tqdm", return_value=mock_bar):
            tracker = ProgressTracker(log, "test", total=100, log_interval=0.0, use_tqdm=True)
            with capture() as logs:
                with tracker:
                    for _ in range(100):
                        tracker.advance()

            # Only the final "completed" log, no interval progress logs
            assert len(logs) == 1
            assert "completed" in logs[0].message

    def test_no_tqdm_falls_back_to_log(self):
        """When use_tqdm=False, falls back to log-based progress."""
        tracker = ProgressTracker(log, "fallback", total=10, use_tqdm=False)
        with capture() as logs:
            with tracker:
                for _ in range(10):
                    tracker.advance()

        # Should have at least start + completed
        assert len(logs) >= 2
        assert "progress" in logs[0].message
        assert "completed" in logs[-1].message

    def test_tqdm_without_total(self):
        """tqdm should work with indeterminate progress (no total)."""
        mock_bar = MagicMock()
        with patch("spektr._metrics._progress._tqdm", return_value=mock_bar) as mock_cls:
            tracker = ProgressTracker(log, "stream", use_tqdm=True)
            with capture():
                with tracker:
                    tracker.advance(10)

            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args
            assert call_kwargs[1]["total"] is None or call_kwargs[0][0] is None


class TestProgressAsync:
    def test_async_progress(self):
        async def run():
            with capture() as logs:
                async with log.progress("async-task", total=10) as progress:
                    for _ in range(10):
                        progress.advance()
            return logs

        logs = asyncio.run(run())
        completed = logs[-1]
        assert "completed" in completed.message
        assert completed.data["current"] == 10
