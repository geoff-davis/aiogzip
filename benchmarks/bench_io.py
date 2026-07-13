"""
I/O benchmarks for aiogzip.

Tests core read/write performance in binary and text modes.
"""

import gzip
import time

from bench_common import (
    COMPARISON_COMPRESSLEVEL,
    BenchmarkBase,
    format_speedup,
    write_comparison_fixture,
)

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
        async with AsyncGzipBinaryFile(
            aiogzip_file, "wb", compresslevel=COMPARISON_COMPRESSLEVEL
        ) as f:
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
        with gzip.open(gzip_file, "wb", compresslevel=COMPARISON_COMPRESSLEVEL) as f:
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
        async with AsyncGzipBinaryFile(
            aiogzip_file, "wb", compresslevel=COMPARISON_COMPRESSLEVEL
        ) as f:
            await f.write(binary_data)
        aiogzip_write_time = time.perf_counter() - start

        # Benchmark aiogzip bulk read
        start = time.perf_counter()
        async with AsyncGzipBinaryFile(aiogzip_file, "rb") as f:
            await f.read()
        aiogzip_read_time = time.perf_counter() - start

        # Benchmark gzip bulk write
        start = time.perf_counter()
        with gzip.open(gzip_file, "wb", compresslevel=COMPARISON_COMPRESSLEVEL) as f:
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
        async with AsyncGzipBinaryFile(
            aiogzip_file, "wb", compresslevel=COMPARISON_COMPRESSLEVEL
        ) as f:
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
        with gzip.open(gzip_file, "wb", compresslevel=COMPARISON_COMPRESSLEVEL) as f:
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
        """Benchmark bulk text reads and writes as separate operations."""
        text_data = self.data_gen.generate_text(self.data_size_mb)
        encoded = text_data.encode("utf-8")
        fixture = self.temp_mgr.get_path("text_read_fixture.gz")
        aiogzip_output = self.temp_mgr.get_path("aiogzip_text_write.gz")
        gzip_output = self.temp_mgr.get_path("gzip_text_write.gz")
        write_comparison_fixture(fixture, encoded)

        # Benchmark aiogzip write
        start = time.perf_counter()
        async with AsyncGzipTextFile(
            aiogzip_output,
            "wt",
            compresslevel=COMPARISON_COMPRESSLEVEL,
            mtime=0,
        ) as f:
            await f.write(text_data)
        aiogzip_write_time = time.perf_counter() - start

        # Benchmark gzip write
        start = time.perf_counter()
        with gzip.open(
            gzip_output,
            "wt",
            encoding="utf-8",
            compresslevel=COMPARISON_COMPRESSLEVEL,
        ) as f:
            f.write(text_data)
        gzip_write_time = time.perf_counter() - start

        # Benchmark both readers against the exact same gzip bytes.
        start = time.perf_counter()
        async with AsyncGzipTextFile(fixture, "rt", encoding="utf-8") as f:
            aiogzip_text = await f.read()
        aiogzip_read_time = time.perf_counter() - start

        start = time.perf_counter()
        with gzip.open(fixture, "rt", encoding="utf-8") as f:
            gzip_text = f.read()
        gzip_read_time = time.perf_counter() - start

        assert aiogzip_text == text_data
        assert gzip_text == text_data

        text_size_mb = len(encoded) / (1024 * 1024)

        self.add_result(
            f"Text write (bulk, compression level {COMPARISON_COMPRESSLEVEL})",
            "io",
            aiogzip_write_time,
            aiogzip_time=f"{aiogzip_write_time:.4f}s",
            gzip_time=f"{gzip_write_time:.4f}s",
            speedup=format_speedup(aiogzip_write_time, gzip_write_time),
            aiogzip_throughput=f"{text_size_mb / aiogzip_write_time:.1f} MB/s",
            gzip_throughput=f"{text_size_mb / gzip_write_time:.1f} MB/s",
        )
        self.add_result(
            "Text read (bulk, identical fixture)",
            "io",
            aiogzip_read_time,
            aiogzip_time=f"{aiogzip_read_time:.4f}s",
            gzip_time=f"{gzip_read_time:.4f}s",
            speedup=format_speedup(aiogzip_read_time, gzip_read_time),
            aiogzip_throughput=f"{text_size_mb / aiogzip_read_time:.1f} MB/s",
            gzip_throughput=f"{text_size_mb / gzip_read_time:.1f} MB/s",
        )

    async def benchmark_line_iteration(self):
        """Compare line iteration against gzip using one read-only fixture."""
        text_data = self.data_gen.generate_jsonl(self.data_size_mb)
        encoded = text_data.encode("utf-8")
        text_file = self.temp_mgr.get_path("line_iteration_fixture.gz")
        write_comparison_fixture(text_file, encoded)
        expected = (
            text_data.count("\n") + (1 if text_data else 0),
            len(text_data),
        )

        start = time.perf_counter()
        default_count = 0
        default_chars = 0
        async with AsyncGzipTextFile(text_file, "rt", encoding="utf-8") as f:
            async for line in f:
                default_count += 1
                default_chars += len(line)
        default_time = time.perf_counter() - start

        start = time.perf_counter()
        tuned_count = 0
        tuned_chars = 0
        async with AsyncGzipTextFile(
            text_file,
            "rt",
            encoding="utf-8",
            newline="\n",
            chunk_size=512 * 1024,
        ) as f:
            async for line in f:
                tuned_count += 1
                tuned_chars += len(line)
        tuned_time = time.perf_counter() - start

        start = time.perf_counter()
        gzip_count = 0
        gzip_chars = 0
        with gzip.open(text_file, "rt", encoding="utf-8", newline="\n") as f:
            for line in f:
                gzip_count += 1
                gzip_chars += len(line)
        gzip_time = time.perf_counter() - start

        assert (default_count, default_chars) == expected
        assert (tuned_count, tuned_chars) == expected
        assert (gzip_count, gzip_chars) == expected

        self.add_result(
            "Text line iteration (default, identical fixture)",
            "io",
            default_time,
            aiogzip_time=f"{default_time:.4f}s",
            gzip_time=f"{gzip_time:.4f}s",
            speedup=format_speedup(default_time, gzip_time),
            aiogzip_lines_per_sec=f"{default_count / default_time:.0f}",
            gzip_lines_per_sec=f"{gzip_count / gzip_time:.0f}",
            lines=default_count,
        )
        self.add_result(
            "Text line iteration (tuned, identical fixture)",
            "io",
            tuned_time,
            aiogzip_time=f"{tuned_time:.4f}s",
            gzip_time=f"{gzip_time:.4f}s",
            speedup=format_speedup(tuned_time, gzip_time),
            aiogzip_lines_per_sec=f"{tuned_count / tuned_time:.0f}",
            gzip_lines_per_sec=f"{gzip_count / gzip_time:.0f}",
            lines=tuned_count,
            tuning='newline="\\n", chunk_size=512 KiB',
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

    async def benchmark_read_all_isolated(self):
        """Full-read throughput with the write excluded from the timed region.

        Isolates ``read(-1)`` so the cost of copying decompressed output shows
        up directly (the bulk benchmark folds write+compression into its
        totals). Uses highly compressible data, where decompression is cheap
        and the output copy is the dominant cost; larger ``--size`` makes the
        signal cleaner.
        """
        payload = self.data_gen.generate_compressible(self.data_size_mb)
        fixture = self.temp_mgr.get_path("readall_isolated.gz")
        write_comparison_fixture(fixture, payload)

        chunk_size = 512 * 1024
        aiogzip_times = []
        for _ in range(5):
            start = time.perf_counter()
            async with AsyncGzipBinaryFile(fixture, "rb", chunk_size=chunk_size) as f:
                result = await f.read()
            assert result == payload
            aiogzip_times.append(time.perf_counter() - start)
        aiogzip_best = min(aiogzip_times)

        gzip_times = []
        for _ in range(5):
            start = time.perf_counter()
            with gzip.open(fixture, "rb") as f:
                result = f.read()
            assert result == payload
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
        await self.benchmark_read_all_isolated()
        await self.benchmark_text_large_reads()
