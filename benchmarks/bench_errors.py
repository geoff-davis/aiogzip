"""
Error handling benchmarks for aiogzip.

Tests error handling and edge cases.
"""

import gzip
import time

from bench_common import BenchmarkBase

from aiogzip import AsyncGzipBinaryFile


class ErrorsBenchmarks(BenchmarkBase):
    """Error handling benchmarks."""

    async def benchmark_invalid_operations(self):
        """Benchmark error handling for invalid operations."""
        test_file = self.temp_mgr.get_path("error_test.gz")

        # Write some data
        async with AsyncGzipBinaryFile(test_file, "wb") as f:
            await f.write(b"test data")

        # Test error scenarios
        errors_caught = 0
        start = time.perf_counter()

        # Try to read from write-mode file
        try:
            async with AsyncGzipBinaryFile(test_file, "wb") as f:
                await f.read()
        except OSError:
            errors_caught += 1

        # Try to write to read-mode file
        try:
            async with AsyncGzipBinaryFile(test_file, "rb") as f:
                await f.write(b"data")
        except OSError:
            errors_caught += 1

        # Try operations on closed file
        try:
            f = AsyncGzipBinaryFile(test_file, "rb")
            async with f:
                pass
            await f.read()
        except ValueError:
            errors_caught += 1

        duration = time.perf_counter() - start

        self.add_result(
            "Error handling",
            "errors",
            duration,
            errors_caught=errors_caught,
            avg_time_per_error=f"{duration / errors_caught * 1000:.2f}ms",
        )

    async def benchmark_corrupted_data(self):
        """Benchmark handling of corrupted gzip data."""
        test_file = self.temp_mgr.get_path("corrupted.gz")

        # Write clearly invalid gzip bytes to deterministically trigger BadGzipFile.
        test_file.write_bytes(b"This is not gzip data")

        # Try to read it
        start = time.perf_counter()
        error_type = "none"
        try:
            async with AsyncGzipBinaryFile(test_file, "rb") as f:
                await f.read()
            caught_error = False
        except gzip.BadGzipFile:
            caught_error = True
            error_type = "BadGzipFile"
        except Exception as exc:  # pragma: no cover - diagnostic metric only
            caught_error = True
            error_type = type(exc).__name__
        duration = time.perf_counter() - start

        self.add_result(
            "Corrupted data handling",
            "errors",
            duration,
            error_detected=caught_error,
            error_type=error_type,
        )

    async def run_all(self):
        """Run all error benchmarks."""
        await self.benchmark_invalid_operations()
        await self.benchmark_corrupted_data()
