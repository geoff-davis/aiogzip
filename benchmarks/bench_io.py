"""
I/O benchmarks for aiogzip.

Tests core read/write performance in binary and text modes.
"""

import gzip
import time

from bench_common import BenchmarkBase, format_speedup

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class IoBenchmarks(BenchmarkBase):
    """I/O performance benchmarks."""

    async def benchmark_binary_small_chunks(self):
        """Benchmark binary I/O with small chunks (stress test)."""
        binary_data = self.data_gen.generate_binary(self.data_size_mb)
        aiogzip_file = self.temp_mgr.get_path("aiogzip_binary_small.gz")
        gzip_file = self.temp_mgr.get_path("gzip_binary_small.gz")

        chunk_size = 10  # Tiny chunks to stress the system

        # Benchmark aiogzip write
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
            for i in range(0, len(binary_data), chunk_size):
                await f.write(binary_data[i : i + chunk_size])
        aiogzip_write_time = time.perf_counter() - start

        # Benchmark aiogzip read
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "rb") as f:
            _ = await f.read()
        aiogzip_read_time = time.perf_counter() - start

        # Benchmark gzip write
        start = time.perf_counter()
        with gzip.open(gzip_file, "wb") as f:
            for i in range(0, len(binary_data), chunk_size):
                f.write(binary_data[i : i + chunk_size])
        gzip_write_time = time.perf_counter() - start

        # Benchmark gzip read
        start = time.perf_counter()
        with gzip.open(gzip_file, "rb") as f:
            _ = f.read()
        gzip_read_time = time.perf_counter() - start

        total_aiogzip = aiogzip_write_time + aiogzip_read_time
        total_gzip = gzip_write_time + gzip_read_time

        num_chunks = len(binary_data) // chunk_size
        aiogzip_chunks_per_sec = (
            num_chunks / aiogzip_write_time if aiogzip_write_time > 0 else 0
        )

        self.add_result(
            "Binary I/O (10-byte chunks, stress test)",
            "io",
            total_aiogzip,
            aiogzip_write=f"{aiogzip_write_time:.3f}s",
            aiogzip_read=f"{aiogzip_read_time:.3f}s",
            gzip_write=f"{gzip_write_time:.3f}s",
            gzip_read=f"{gzip_read_time:.3f}s",
            speedup=format_speedup(total_aiogzip, total_gzip),
            chunks_written=num_chunks,
            chunks_per_sec=f"{aiogzip_chunks_per_sec:.0f}",
        )

    async def benchmark_binary_bulk(self):
        """Benchmark binary I/O with bulk operations (typical use case)."""
        binary_data = self.data_gen.generate_binary(self.data_size_mb)
        aiogzip_file = self.temp_mgr.get_path("aiogzip_binary_bulk.gz")
        gzip_file = self.temp_mgr.get_path("gzip_binary_bulk.gz")

        # Benchmark aiogzip bulk write
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
            await f.write(binary_data)
        aiogzip_write_time = time.perf_counter() - start

        # Benchmark aiogzip bulk read
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "rb") as f:
            await f.read()
        aiogzip_read_time = time.perf_counter() - start

        # Benchmark gzip bulk write
        start = time.perf_counter()
        with gzip.open(gzip_file, "wb") as f:
            f.write(binary_data)
        gzip_write_time = time.perf_counter() - start

        # Benchmark gzip bulk read
        start = time.perf_counter()
        with gzip.open(gzip_file, "rb") as f:
            _ = f.read()
        gzip_read_time = time.perf_counter() - start

        total_aiogzip = aiogzip_write_time + aiogzip_read_time
        total_gzip = gzip_write_time + gzip_read_time

        # Calculate throughput
        data_size_mb = len(binary_data) / (1024 * 1024)
        aiogzip_throughput = data_size_mb / total_aiogzip if total_aiogzip > 0 else 0
        gzip_throughput = data_size_mb / total_gzip if total_gzip > 0 else 0

        self.add_result(
            "Binary I/O (bulk, single write/read)",
            "io",
            total_aiogzip,
            aiogzip_write=f"{aiogzip_write_time:.3f}s",
            aiogzip_read=f"{aiogzip_read_time:.3f}s",
            gzip_write=f"{gzip_write_time:.3f}s",
            gzip_read=f"{gzip_read_time:.3f}s",
            speedup=format_speedup(total_aiogzip, total_gzip),
            aiogzip_throughput=f"{aiogzip_throughput:.1f} MB/s",
            gzip_throughput=f"{gzip_throughput:.1f} MB/s",
        )

    async def benchmark_binary_chunked(self):
        """Benchmark binary I/O with realistic chunk sizes."""
        binary_data = self.data_gen.generate_binary(self.data_size_mb)
        aiogzip_file = self.temp_mgr.get_path("aiogzip_binary_chunked.gz")
        gzip_file = self.temp_mgr.get_path("gzip_binary_chunked.gz")

        chunk_size = 64 * 1024  # 64KB chunks (typical)

        # Benchmark aiogzip chunked write
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
            for i in range(0, len(binary_data), chunk_size):
                await f.write(binary_data[i : i + chunk_size])
        aiogzip_write_time = time.perf_counter() - start

        # Benchmark aiogzip chunked read
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "rb") as f:
            chunks = []
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
        aiogzip_read_time = time.perf_counter() - start

        # Benchmark gzip chunked write
        start = time.perf_counter()
        with gzip.open(gzip_file, "wb") as f:
            for i in range(0, len(binary_data), chunk_size):
                f.write(binary_data[i : i + chunk_size])
        gzip_write_time = time.perf_counter() - start

        # Benchmark gzip chunked read
        start = time.perf_counter()
        with gzip.open(gzip_file, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
        gzip_read_time = time.perf_counter() - start

        total_aiogzip = aiogzip_write_time + aiogzip_read_time
        total_gzip = gzip_write_time + gzip_read_time

        num_chunks = (len(binary_data) + chunk_size - 1) // chunk_size

        self.add_result(
            f"Binary I/O (64KB chunks, {num_chunks} chunks)",
            "io",
            total_aiogzip,
            aiogzip_write=f"{aiogzip_write_time:.3f}s",
            aiogzip_read=f"{aiogzip_read_time:.3f}s",
            gzip_write=f"{gzip_write_time:.3f}s",
            gzip_read=f"{gzip_read_time:.3f}s",
            speedup=format_speedup(total_aiogzip, total_gzip),
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

        # Calculate throughput
        text_size_mb = len(text_data.encode("utf-8")) / (1024 * 1024)
        aiogzip_throughput = text_size_mb / total_aiogzip if total_aiogzip > 0 else 0
        gzip_throughput = text_size_mb / total_gzip if total_gzip > 0 else 0

        self.add_result(
            "Text I/O (bulk read/write)",
            "io",
            total_aiogzip,
            aiogzip_write=f"{aiogzip_write_time:.3f}s",
            aiogzip_read=f"{aiogzip_read_time:.3f}s",
            gzip_write=f"{gzip_write_time:.3f}s",
            gzip_read=f"{gzip_read_time:.3f}s",
            speedup=format_speedup(total_aiogzip, total_gzip),
            aiogzip_throughput=f"{aiogzip_throughput:.1f} MB/s",
            gzip_throughput=f"{gzip_throughput:.1f} MB/s",
        )

    async def benchmark_line_iteration(self):
        """Benchmark line-by-line iteration vs readline()."""
        text_file = self.temp_mgr.get_path("lines_iter.gz")

        # Create file with varying line lengths
        lines = []
        for i in range(1000):
            if i % 10 == 0:
                # Long line every 10th line
                lines.append(f"Long line {i}: " + "x" * 200 + "\n")
            else:
                # Short lines
                lines.append(f"Short line {i}\n")

        async with AsyncGzipTextFile(text_file, "wt") as f:
            await f.write("".join(lines))

        # Benchmark async for iteration
        start = time.perf_counter()
        async with AsyncGzipTextFile(text_file, "rt") as f:
            iter_lines = []
            async for line in f:
                iter_lines.append(line)
        iteration_time = time.perf_counter() - start

        # Benchmark readline() loop
        start = time.perf_counter()
        async with AsyncGzipTextFile(text_file, "rt") as f:
            readline_lines = []
            while True:
                line = await f.readline()
                if not line:
                    break
                readline_lines.append(line)
        readline_time = time.perf_counter() - start

        # Compare with gzip
        gzip_file = self.temp_mgr.get_path("lines_gzip.gz")
        with gzip.open(gzip_file, "wt") as f:
            f.write("".join(lines))

        start = time.perf_counter()
        with gzip.open(gzip_file, "rt") as f:
            list(f)
        gzip_time = time.perf_counter() - start

        self.add_result(
            "Line iteration (1000 mixed-length lines)",
            "io",
            iteration_time,
            async_for_time=f"{iteration_time:.3f}s",
            readline_time=f"{readline_time:.3f}s",
            gzip_iteration=f"{gzip_time:.3f}s",
            async_for_vs_readline=f"{readline_time / iteration_time:.2f}x"
            if iteration_time > 0
            else "N/A",
            lines_per_sec=f"{len(iter_lines) / iteration_time:.0f}",
        )

    async def benchmark_flush_operations(self):
        """Benchmark flush() performance."""
        test_file = self.temp_mgr.get_path("flush_test.gz")

        # Write with multiple flushes
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(test_file, "wb") as f:
            for _i in range(100):
                await f.write(b"test data " * 100)
                await f.flush()
        duration = time.perf_counter() - start

        self.add_result(
            "Flush operations (100 flushes)",
            "io",
            duration,
            ops_per_sec=f"{100 / duration:.0f}",
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
            lines_per_sec=f"{len(lines) / duration:.0f}",
        )

    async def benchmark_read_all_isolated(self):
        """Full-read throughput with the write excluded from the timed region.

        Isolates ``read(-1)`` so the cost of copying decompressed output shows
        up directly (the bulk benchmark folds write+compression into its
        totals). Uses highly compressible data, where decompression is cheap
        and the output copy is the dominant cost; larger ``--size`` makes the
        signal cleaner.
        """
        payload = self.data_gen.generate_compressible(self.data_size_mb)
        aiogzip_file = self.temp_mgr.get_path("readall_isolated.gz")
        gzip_file = self.temp_mgr.get_path("readall_isolated_gzip.gz")

        # Write outside the timed region.
        async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
            await f.write(payload)
        with gzip.open(gzip_file, "wb") as f:
            f.write(payload)

        chunk_size = 512 * 1024
        aiogzip_times = []
        for _ in range(5):
            start = time.perf_counter()
            async with AsyncGzipBinaryFile(
                aiogzip_file, "rb", chunk_size=chunk_size
            ) as f:
                await f.read()
            aiogzip_times.append(time.perf_counter() - start)
        aiogzip_best = min(aiogzip_times)

        gzip_times = []
        for _ in range(5):
            start = time.perf_counter()
            with gzip.open(gzip_file, "rb") as f:
                f.read()
            gzip_times.append(time.perf_counter() - start)
        gzip_best = min(gzip_times)

        mb = len(payload) / (1024 * 1024)
        self.add_result(
            "Read-all isolated (compressible, read-only timing)",
            "io",
            aiogzip_best,
            aiogzip_read_best=f"{aiogzip_best * 1000:.2f}ms",
            gzip_read_best=f"{gzip_best * 1000:.2f}ms",
            aiogzip_throughput=f"{mb / aiogzip_best:.1f} MB/s"
            if aiogzip_best > 0
            else "N/A",
            speedup=format_speedup(aiogzip_best, gzip_best),
        )

    async def benchmark_text_large_reads(self):
        """Large single ``read(size)`` and a single very long line.

        Both paths previously accumulated text via repeated ``str +=`` (O(n^2));
        this records their throughput so a regression to quadratic scaling is
        visible. Uses a no-newline blob so ``read(size)`` and ``readline()``
        must accumulate across many chunks.
        """
        n = self.data_size_mb * 1024 * 1024
        blob = "x" * n
        path = self.temp_mgr.get_path("text_large_reads.gz")
        async with AsyncGzipTextFile(path, "wt") as f:
            await f.write(blob)

        chunk_size = 64 * 1024

        sized_times = []
        for _ in range(5):
            start = time.perf_counter()
            async with AsyncGzipTextFile(path, "rt", chunk_size=chunk_size) as f:
                _ = await f.read(n)
            sized_times.append(time.perf_counter() - start)
        sized_best = min(sized_times)

        line_times = []
        for _ in range(5):
            start = time.perf_counter()
            async with AsyncGzipTextFile(path, "rt", chunk_size=chunk_size) as f:
                _ = await f.readline()
            line_times.append(time.perf_counter() - start)
        line_best = min(line_times)

        mchars = n / (1024 * 1024)
        self.add_result(
            "Text large reads (sized read + long line, O(n) accumulation)",
            "io",
            sized_best,
            read_size_best=f"{sized_best * 1000:.2f}ms",
            readline_long_best=f"{line_best * 1000:.2f}ms",
            read_size_throughput=f"{mchars / sized_best:.1f} Mchar/s"
            if sized_best > 0
            else "N/A",
        )

    async def run_all(self):
        """Run all I/O benchmarks."""
        await self.benchmark_binary_small_chunks()
        await self.benchmark_binary_bulk()
        await self.benchmark_binary_chunked()
        await self.benchmark_text_operations()
        await self.benchmark_line_iteration()
        await self.benchmark_flush_operations()
        await self.benchmark_readline()
        await self.benchmark_read_all_isolated()
        await self.benchmark_text_large_reads()
