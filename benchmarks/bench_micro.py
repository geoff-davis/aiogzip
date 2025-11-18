"""
Micro-benchmarks for aiogzip.

Tests specific optimizations and low-level operations.
"""

import time

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile
from bench_common import BenchmarkBase


class MicroBenchmarks(BenchmarkBase):
    """Micro-benchmarks for specific optimizations."""

    async def benchmark_read_all(self):
        """Benchmark read(-1) performance."""
        binary_file = self.temp_mgr.get_path("micro_binary.gz")

        # Write 1MB of binary data
        test_data = b"x" * (1024 * 1024)
        async with AsyncGzipBinaryFile(binary_file, "wb") as f:
            await f.write(test_data)

        # Benchmark read(-1) - 100 iterations
        iterations = 100
        total_time = 0
        for _ in range(iterations):
            start = time.perf_counter()
            async with AsyncGzipBinaryFile(binary_file, "rb") as f:
                _ = await f.read(-1)
            total_time += time.perf_counter() - start

        avg_time = total_time / iterations

        self.add_result(
            "read(-1) - 1MB file",
            "micro",
            avg_time,
            iterations=iterations,
            avg_time_ms=f"{avg_time * 1000:.3f}ms",
        )

    async def benchmark_line_iteration(self):
        """Benchmark line-by-line iteration."""
        text_file = self.temp_mgr.get_path("micro_text.gz")

        # Write text data with 10,000 lines
        lines = [f"This is line number {i}\n" for i in range(10000)]
        async with AsyncGzipTextFile(text_file, "wt") as f:
            await f.write("".join(lines))

        # Benchmark line iteration - 100 iterations
        iterations = 100
        total_time = 0
        for _ in range(iterations):
            start = time.perf_counter()
            async with AsyncGzipTextFile(text_file, "rt") as f:
                line_list = []
                async for line in f:
                    line_list.append(line)
            total_time += time.perf_counter() - start

        avg_time = total_time / iterations

        self.add_result(
            "Line iteration - 10K lines",
            "micro",
            avg_time,
            iterations=iterations,
            avg_time_ms=f"{avg_time * 1000:.3f}ms",
        )

    async def benchmark_readline_loop(self):
        """Benchmark readline() in a loop."""
        text_file = self.temp_mgr.get_path("micro_readline.gz")

        # Write text data with 10,000 lines
        lines = [f"This is line number {i}\n" for i in range(10000)]
        async with AsyncGzipTextFile(text_file, "wt") as f:
            await f.write("".join(lines))

        # Benchmark readline loop - 100 iterations
        iterations = 100
        total_time = 0
        for _ in range(iterations):
            start = time.perf_counter()
            async with AsyncGzipTextFile(text_file, "rt") as f:
                line_list = []
                while True:
                    line = await f.readline()
                    if not line:
                        break
                    line_list.append(line)
            total_time += time.perf_counter() - start

        avg_time = total_time / iterations

        self.add_result(
            "readline() loop - 10K lines",
            "micro",
            avg_time,
            iterations=iterations,
            avg_time_ms=f"{avg_time * 1000:.3f}ms",
        )

    async def benchmark_small_writes(self):
        """Benchmark many small write operations."""
        test_file = self.temp_mgr.get_path("micro_small_writes.gz")

        # Write 1000 small chunks
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(test_file, "wb") as f:
            for _ in range(1000):
                await f.write(b"small chunk " * 10)
        duration = time.perf_counter() - start

        self.add_result(
            "Small writes (1000 x 120 bytes)",
            "micro",
            duration,
            ops_per_sec=f"{1000 / duration:.0f}",
        )

    async def run_all(self):
        """Run all micro-benchmarks."""
        await self.benchmark_read_all()
        await self.benchmark_line_iteration()
        await self.benchmark_readline_loop()
        await self.benchmark_small_writes()
