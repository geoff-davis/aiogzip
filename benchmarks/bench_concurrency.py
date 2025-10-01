"""
Concurrency benchmarks for aiogzip.

Tests async and concurrent operations.
"""

import asyncio
import gzip
import time

from aiogzip import AsyncGzipBinaryFile
from bench_common import BenchmarkBase


class ConcurrencyBenchmarks(BenchmarkBase):
    """Concurrency performance benchmarks."""

    async def benchmark_concurrent_operations(self):
        """Benchmark concurrent file operations."""
        num_files = 50
        test_data = self.data_gen.generate_binary(self.data_size_mb // 50)  # Small files

        # Async concurrent processing
        async def process_file_async(idx):
            filepath = self.temp_mgr.get_path(f"async_{idx}.gz")
            async with AsyncGzipBinaryFile(filepath, "wb") as f:
                await f.write(test_data)
            async with AsyncGzipBinaryFile(filepath, "rb") as f:
                _ = await f.read()

        start = time.perf_counter()
        await asyncio.gather(*[process_file_async(i) for i in range(num_files)])
        async_time = time.perf_counter() - start

        # Sync sequential processing
        def process_file_sync(idx):
            filepath = self.temp_mgr.get_path(f"sync_{idx}.gz")
            with gzip.open(filepath, "wb") as f:
                f.write(test_data)
            with gzip.open(filepath, "rb") as f:
                _ = f.read()

        start = time.perf_counter()
        for i in range(num_files):
            process_file_sync(i)
        sync_time = time.perf_counter() - start

        speedup = sync_time / async_time if async_time > 0 else 0

        self.add_result(
            f"Concurrent operations ({num_files} files)",
            "concurrency",
            async_time,
            async_time=f"{async_time:.3f}s",
            sync_time=f"{sync_time:.3f}s",
            speedup=f"{speedup:.2f}x"
        )

    async def run_all(self):
        """Run all concurrency benchmarks."""
        await self.benchmark_concurrent_operations()
