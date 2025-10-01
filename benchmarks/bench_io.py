"""
I/O benchmarks for aiogzip.

Tests core read/write performance in binary and text modes.
"""

import gzip
import time

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile
from bench_common import BenchmarkBase, format_speedup


class IoBenchmarks(BenchmarkBase):
    """I/O performance benchmarks."""

    async def benchmark_binary_operations(self):
        """Benchmark binary read/write operations."""
        binary_data = self.data_gen.generate_binary(self.data_size_mb)
        aiogzip_file = self.temp_mgr.get_path("aiogzip_binary.gz")
        gzip_file = self.temp_mgr.get_path("gzip_binary.gz")

        # Benchmark aiogzip write
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
            chunk_size = 10  # Small chunks to stress the system
            for i in range(0, len(binary_data), chunk_size):
                await f.write(binary_data[i:i + chunk_size])
        aiogzip_write_time = time.perf_counter() - start

        # Benchmark aiogzip read
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "rb") as f:
            _ = await f.read()
        aiogzip_read_time = time.perf_counter() - start

        # Benchmark gzip write
        start = time.perf_counter()
        with gzip.open(gzip_file, "wb") as f:
            chunk_size = 10
            for i in range(0, len(binary_data), chunk_size):
                f.write(binary_data[i:i + chunk_size])
        gzip_write_time = time.perf_counter() - start

        # Benchmark gzip read
        start = time.perf_counter()
        with gzip.open(gzip_file, "rb") as f:
            _ = f.read()
        gzip_read_time = time.perf_counter() - start

        total_aiogzip = aiogzip_write_time + aiogzip_read_time
        total_gzip = gzip_write_time + gzip_read_time

        self.add_result(
            "Binary I/O (10-byte chunks)",
            "io",
            total_aiogzip,
            aiogzip_write=f"{aiogzip_write_time:.3f}s",
            aiogzip_read=f"{aiogzip_read_time:.3f}s",
            gzip_write=f"{gzip_write_time:.3f}s",
            gzip_read=f"{gzip_read_time:.3f}s",
            speedup=format_speedup(total_aiogzip, total_gzip)
        )

    async def benchmark_text_operations(self):
        """Benchmark text read/write operations."""
        text_data = self.data_gen.generate_text(self.data_size_mb)
        aiogzip_file = self.temp_mgr.get_path("aiogzip_text.gz")
        gzip_file = self.temp_mgr.get_path("gzip_text.gz")

        # Benchmark aiogzip write
        start = time.perf_counter()
        async with AsyncGzipTextFile(aiogzip_file, "wt") as f:
            await f.write(text_data)
        aiogzip_write_time = time.perf_counter() - start

        # Benchmark aiogzip read
        start = time.perf_counter()
        async with AsyncGzipTextFile(aiogzip_file, "rt") as f:
            _ = await f.read()
        aiogzip_read_time = time.perf_counter() - start

        # Benchmark gzip write
        start = time.perf_counter()
        with gzip.open(gzip_file, "wt") as f:
            f.write(text_data)
        gzip_write_time = time.perf_counter() - start

        # Benchmark gzip read
        start = time.perf_counter()
        with gzip.open(gzip_file, "rt") as f:
            _ = f.read()
        gzip_read_time = time.perf_counter() - start

        total_aiogzip = aiogzip_write_time + aiogzip_read_time
        total_gzip = gzip_write_time + gzip_read_time

        self.add_result(
            "Text I/O",
            "io",
            total_aiogzip,
            aiogzip_write=f"{aiogzip_write_time:.3f}s",
            aiogzip_read=f"{aiogzip_read_time:.3f}s",
            gzip_write=f"{gzip_write_time:.3f}s",
            gzip_read=f"{gzip_read_time:.3f}s",
            speedup=format_speedup(total_aiogzip, total_gzip)
        )

    async def benchmark_flush_operations(self):
        """Benchmark flush() performance."""
        test_file = self.temp_mgr.get_path("flush_test.gz")

        # Write with multiple flushes
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(test_file, "wb") as f:
            for i in range(100):
                await f.write(b"test data " * 100)
                await f.flush()
        duration = time.perf_counter() - start

        self.add_result(
            "Flush operations (100 flushes)",
            "io",
            duration,
            ops_per_sec=f"{100/duration:.0f}"
        )

    async def benchmark_readline(self):
        """Benchmark readline() performance."""
        text_file = self.temp_mgr.get_path("lines.gz")

        # Create file with 1000 lines
        async with AsyncGzipTextFile(text_file, "wt") as f:
            for i in range(1000):
                await f.write(f"This is line number {i}\n")

        # Benchmark readline
        start = time.perf_counter()
        async with AsyncGzipTextFile(text_file, "rt") as f:
            lines = []
            while True:
                line = await f.readline()
                if not line:
                    break
                lines.append(line)
        duration = time.perf_counter() - start

        self.add_result(
            "readline() (1000 lines)",
            "io",
            duration,
            lines_per_sec=f"{len(lines)/duration:.0f}"
        )

    async def run_all(self):
        """Run all I/O benchmarks."""
        await self.benchmark_binary_operations()
        await self.benchmark_text_operations()
        await self.benchmark_flush_operations()
        await self.benchmark_readline()
