"""
Memory benchmarks for aiogzip.

Tests memory usage and efficiency.
"""

import time

from aiogzip import AsyncGzipBinaryFile
from bench_common import BenchmarkBase

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class MemoryBenchmarks(BenchmarkBase):
    """Memory usage benchmarks."""

    async def benchmark_memory_efficiency(self):
        """Benchmark memory usage during operations."""
        if not PSUTIL_AVAILABLE:
            print("  Skipping: psutil not available")
            self.add_result(
                "Memory efficiency",
                "memory",
                0.0,
                status="skipped (psutil not installed)"
            )
            return

        import psutil
        process = psutil.Process()

        # Generate 5MB of data
        test_data = self.data_gen.generate_binary(5)
        test_file = self.temp_mgr.get_path("memory_test.gz")

        # Get baseline memory
        baseline_memory = process.memory_info().rss / (1024 * 1024)  # MB

        # Write data
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(test_file, "wb") as f:
            await f.write(test_data)

        # Read data
        async with AsyncGzipBinaryFile(test_file, "rb") as f:
            _ = await f.read()

        duration = time.perf_counter() - start

        # Get peak memory
        peak_memory = process.memory_info().rss / (1024 * 1024)  # MB
        memory_increase = peak_memory - baseline_memory
        memory_ratio = memory_increase / 5.0  # Ratio to data size

        self.add_result(
            "Memory efficiency (5MB)",
            "memory",
            duration,
            memory_increase_mb=f"{memory_increase:.1f}",
            memory_ratio=f"{memory_ratio:.2f}x",
            status="OK" if memory_ratio < 5.0 else "HIGH"
        )

    async def run_all(self):
        """Run all memory benchmarks."""
        await self.benchmark_memory_efficiency()
