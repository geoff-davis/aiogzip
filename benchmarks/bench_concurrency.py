"""
Concurrency benchmarks for aiogzip.

Tests async and concurrent operations with simulated I/O delays.
"""

import asyncio
import gzip
import time

from bench_common import BenchmarkBase

from aiogzip import AsyncGzipBinaryFile


class ConcurrencyBenchmarks(BenchmarkBase):
    """Concurrency performance benchmarks."""

    async def benchmark_concurrent_operations(self):
        """Benchmark concurrent file operations with simulated I/O delays."""
        num_files = 10
        test_data = self.data_gen.generate_binary(1)  # 1MB per file

        # Async concurrent processing with simulated I/O delay
        async def process_file_async(idx):
            filepath = self.temp_mgr.get_path(f"async_{idx}.gz")
            async with AsyncGzipBinaryFile(filepath, "wb") as f:
                await f.write(test_data)
            # Simulate network/disk delay (e.g., waiting for upload)
            await asyncio.sleep(0.01)
            async with AsyncGzipBinaryFile(filepath, "rb") as f:
                _ = await f.read()

        start = time.perf_counter()
        await asyncio.gather(*[process_file_async(i) for i in range(num_files)])
        async_time = time.perf_counter() - start

        # Sync sequential processing with simulated I/O delay
        def process_file_sync(idx):
            filepath = self.temp_mgr.get_path(f"sync_{idx}.gz")
            with gzip.open(filepath, "wb") as f:
                f.write(test_data)
            # Simulate network/disk delay (blocking)
            time.sleep(0.01)
            with gzip.open(filepath, "rb") as f:
                _ = f.read()

        start = time.perf_counter()
        for i in range(num_files):
            process_file_sync(i)
        sync_time = time.perf_counter() - start

        speedup = sync_time / async_time if async_time > 0 else 0

        # Calculate theoretical minimum times
        num_files * 0.01  # Sequential delays
        theoretical_async_min = 0.01  # Parallel delays

        self.add_result(
            f"Concurrent I/O ({num_files} files, 10ms delay each)",
            "concurrency",
            async_time,
            async_time=f"{async_time:.3f}s",
            sync_time=f"{sync_time:.3f}s",
            speedup=f"{speedup:.2f}x",
            delay_saved=f"{sync_time - async_time:.3f}s",
            async_efficiency=f"{theoretical_async_min / async_time * 100:.0f}%",
        )

    async def benchmark_mixed_workload(self):
        """Benchmark mixed read/write operations."""
        num_tasks = 5
        test_data = self.data_gen.generate_binary(1)

        # Create files first
        for i in range(num_tasks):
            filepath = self.temp_mgr.get_path(f"mixed_{i}.gz")
            async with AsyncGzipBinaryFile(filepath, "wb") as f:
                await f.write(test_data)

        # Mixed async operations (some read, some write)
        async def mixed_async_task(idx):
            if idx % 2 == 0:
                # Read
                filepath = self.temp_mgr.get_path(f"mixed_{idx}.gz")
                async with AsyncGzipBinaryFile(filepath, "rb") as f:
                    _ = await f.read()
            else:
                # Write
                filepath = self.temp_mgr.get_path(f"mixed_new_{idx}.gz")
                async with AsyncGzipBinaryFile(filepath, "wb") as f:
                    await f.write(test_data)

        start = time.perf_counter()
        await asyncio.gather(*[mixed_async_task(i) for i in range(num_tasks)])
        async_time = time.perf_counter() - start

        # Sequential version
        def mixed_sync_task(idx):
            if idx % 2 == 0:
                filepath = self.temp_mgr.get_path(f"mixed_{idx}.gz")
                with gzip.open(filepath, "rb") as f:
                    _ = f.read()
            else:
                filepath = self.temp_mgr.get_path(f"mixed_new_{idx}.gz")
                with gzip.open(filepath, "wb") as f:
                    f.write(test_data)

        start = time.perf_counter()
        for i in range(num_tasks):
            mixed_sync_task(i)
        sync_time = time.perf_counter() - start

        speedup = sync_time / async_time if async_time > 0 else 0

        self.add_result(
            f"Mixed operations ({num_tasks} read/write)",
            "concurrency",
            async_time,
            async_time=f"{async_time:.3f}s",
            sync_time=f"{sync_time:.3f}s",
            speedup=f"{speedup:.2f}x",
        )

    async def run_all(self):
        """Run all concurrency benchmarks."""
        await self.benchmark_concurrent_operations()
        await self.benchmark_mixed_workload()
