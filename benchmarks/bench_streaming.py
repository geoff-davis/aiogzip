"""Benchmarks for async-iterable gzip compression and decompression."""

import asyncio
import gzip
import time
import tracemalloc

from bench_common import BenchmarkBase

import aiogzip
from aiogzip import _engine


class StreamingBenchmarks(BenchmarkBase):
    """Compare iterable chunk sizes, file APIs, responsiveness, and memory."""

    def setup(self):
        super().setup()
        size = max(self.data_size_bytes, 1)
        self.payload = self.data_gen.generate_binary(self.data_size_mb)
        self.compressed = gzip.compress(self.payload, mtime=0)
        self.path = self.temp_mgr.get_path("streaming.gz")
        self.path.write_bytes(self.compressed)
        self.compressible_size = size
        self.compressible_payload = b"A" * size
        self.compressible = gzip.compress(self.compressible_payload, mtime=0)
        self.compressible_path = self.temp_mgr.get_path("compressible.gz")
        self.compressible_path.write_bytes(self.compressible)
        self.output_path = self.temp_mgr.get_path("streaming-output.gz")

    async def _source(self, data, chunk_size):
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    async def _consume_stream(self, data, input_size, output_size):
        total = 0
        async for chunk in aiogzip.decompress_chunks(
            self._source(data, input_size), output_chunk_size=output_size
        ):
            total += len(chunk)
        return total

    async def _measure_stream(self, input_size, output_size):
        stop = asyncio.Event()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0)

        ticker_task = asyncio.create_task(ticker())
        start = time.perf_counter()
        total = await self._consume_stream(self.compressed, input_size, output_size)
        duration = time.perf_counter() - start
        stop.set()
        await ticker_task
        assert total == len(self.payload)
        self.add_result(
            f"decompress_chunks ({input_size // 1024}K in, {output_size // 1024}K out)",
            "streaming",
            duration,
            event_loop_ticks=ticks,
            engine=aiogzip.engine_info().decompression,
        )

    async def _measure_file_reader(self):
        start = time.perf_counter()
        total = 0
        async with aiogzip.open(self.path, "rb") as stream:
            while chunk := await stream.read(64 * 1024):
                total += len(chunk)
        duration = time.perf_counter() - start
        assert total == len(self.payload)
        self.add_result(
            "file reader (64K output)",
            "streaming",
            duration,
            engine=aiogzip.engine_info().decompression,
        )

    async def _consume_compression(self, data, input_size, output_size, *, fast=False):
        total = 0
        async for chunk in aiogzip.compress_chunks(
            self._source(data, input_size),
            mtime=0,
            fast_compress=fast,
            output_chunk_size=output_size,
        ):
            total += len(chunk)
        return total

    async def _measure_compression(self, input_size, output_size, *, fast=False):
        stop = asyncio.Event()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0)

        ticker_task = asyncio.create_task(ticker())
        start = time.perf_counter()
        total = await self._consume_compression(
            self.payload, input_size, output_size, fast=fast
        )
        duration = time.perf_counter() - start
        stop.set()
        await ticker_task
        assert total > 0
        engine = "zlib-ng" if fast and _have_fast_compression() else "stdlib-zlib"
        label = " fast" if fast else ""
        self.add_result(
            f"compress_chunks{label} ({input_size // 1024}K in, "
            f"{output_size // 1024}K out)",
            "streaming",
            duration,
            compressed_bytes=total,
            event_loop_ticks=ticks,
            engine=engine,
        )

    async def _measure_file_writer(self):
        start = time.perf_counter()
        async with aiogzip.open(self.output_path, "wb", mtime=0) as stream:
            async for chunk in self._source(self.payload, 64 * 1024):
                await stream.write(chunk)
        duration = time.perf_counter() - start
        self.add_result(
            "file writer (64K input)",
            "streaming",
            duration,
            compressed_bytes=self.output_path.stat().st_size,
            engine=aiogzip.engine_info().compression,
        )

    async def _measure_memory(self, name, operation):
        tracemalloc.start()
        start = time.perf_counter()
        total = await operation()
        duration = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert total == self.compressible_size
        self.add_result(
            name,
            "streaming",
            duration,
            peak_python_mb=peak / (1024 * 1024),
            engine=aiogzip.engine_info().decompression,
        )

    async def _stream_compressible(self):
        return await self._consume_stream(self.compressible, 4096, 64 * 1024)

    async def _read_compressible(self):
        return len(await aiogzip.read(self.compressible_path))

    async def _compress_compressible(self):
        return await self._consume_compression(
            self.compressible_payload, 64 * 1024, 64 * 1024
        )

    async def _measure_compression_memory(self):
        tracemalloc.start()
        start = time.perf_counter()
        total = await self._compress_compressible()
        duration = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert total > 0
        self.add_result(
            "compress_chunks compressible peak",
            "streaming",
            duration,
            peak_python_mb=peak / (1024 * 1024),
            compressed_bytes=total,
            engine=aiogzip.engine_info().compression,
        )

    async def run_all(self):
        """Benchmark both iterable codecs and their file-API baselines."""
        await self._measure_stream(64 * 1024, 64 * 1024)
        await self._measure_stream(512 * 1024, 256 * 1024)
        await self._measure_file_reader()
        await self._measure_memory(
            "decompress_chunks compressible peak", self._stream_compressible
        )
        await self._measure_memory(
            "full read compressible peak", self._read_compressible
        )
        await self._measure_compression(64 * 1024, 64 * 1024)
        await self._measure_compression(512 * 1024, 256 * 1024)
        if _have_fast_compression():
            await self._measure_compression(512 * 1024, 256 * 1024, fast=True)
        await self._measure_file_writer()
        await self._measure_compression_memory()


def _have_fast_compression():
    """Return whether the optional compression engine is active."""
    return _engine.have_fast_engine()
