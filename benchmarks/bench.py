"""
Benchmark: spektr vs loguru vs structlog vs stdlib logging.

Run:
    pip install spektr loguru structlog
    python benchmarks/bench.py

Measures wall-clock time for structured log calls with output suppressed.
"""

import io
import logging
import sys
import time

ITERATIONS = 100_000


def bench(name, setup, run):
    """Run a benchmark and return ops/sec."""
    ctx = setup()
    # Warmup
    for _ in range(1000):
        run(ctx)
    # Timed run
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        run(ctx)
    elapsed = time.perf_counter() - start
    ops = ITERATIONS / elapsed
    print(f"  {name:20s}  {ops:>12,.0f} ops/sec  ({elapsed:.2f}s)")
    return ops


def main():
    print(f"Benchmark: {ITERATIONS:,} structured log calls each\n")
    results = {}

    # ── stdlib logging ───────────────────────────────────────
    def setup_stdlib():
        logger = logging.getLogger("bench_stdlib")
        logger.setLevel(logging.DEBUG)
        logger.handlers = [logging.StreamHandler(io.StringIO())]
        logger.propagate = False
        return logger

    results["stdlib"] = bench(
        "stdlib logging",
        setup_stdlib,
        lambda logger: logger.info("order created", extra={"order_id": 42, "amount": 99.99}),
    )

    # ── spektr ───────────────────────────────────────────────
    def setup_spektr():
        from spektr import capture

        ctx = capture()
        ctx.__enter__()
        return ctx

    def run_spektr(ctx):
        from spektr import log

        log("order created", order_id=42, amount=99.99)

    results["spektr"] = bench("spektr", setup_spektr, run_spektr)

    # ── loguru ───────────────────────────────────────────────
    try:
        import loguru

        def setup_loguru():
            loguru.logger.remove()
            loguru.logger.add(io.StringIO(), format="{message}")
            return loguru.logger

        results["loguru"] = bench(
            "loguru",
            setup_loguru,
            lambda logger: logger.info("order created", order_id=42, amount=99.99),
        )
    except ImportError:
        print("  loguru               (not installed, skipping)")

    # ── structlog ────────────────────────────────────────────
    try:
        import structlog

        def setup_structlog():
            structlog.configure(
                processors=[structlog.dev.ConsoleRenderer()],
                wrapper_class=structlog.BoundLogger,
                logger_factory=structlog.PrintLoggerFactory(io.StringIO()),
                cache_logger_on_first_use=True,
            )
            return structlog.get_logger()

        results["structlog"] = bench(
            "structlog",
            setup_structlog,
            lambda logger: logger.info("order created", order_id=42, amount=99.99),
        )
    except ImportError:
        print("  structlog            (not installed, skipping)")

    # ── Summary ──────────────────────────────────────────────
    print()
    if "spektr" in results:
        baseline = results["spektr"]
        print("Relative to spektr:")
        for name, ops in sorted(results.items(), key=lambda x: -x[1]):
            ratio = ops / baseline
            bar = "#" * int(ratio * 20)
            print(f"  {name:20s}  {ratio:.2f}x  {bar}")


if __name__ == "__main__":
    main()
