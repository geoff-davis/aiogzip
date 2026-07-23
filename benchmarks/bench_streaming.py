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

    def _measure_direct_codecs(self):
        """Record informational direct-codec and equivalent stdlib timings."""
        output_chunk_size = 256 * 1024

        start = time.perf_counter()
        stdlib_encoded = gzip.compress(self.payload, compresslevel=6, mtime=0)
        stdlib_encode_duration = time.perf_counter() - start
        self.add_result(
            "stdlib gzip.compress reference",
            "streaming",
            stdlib_encode_duration,
            input_bytes=len(self.payload),
            compressed_bytes=len(stdlib_encoded),
            informational=True,
        )

        encoder = aiogzip.GzipEncoder(
            compresslevel=6,
            mtime=0,
            output_chunk_size=output_chunk_size,
        )
        encoded = bytearray()
        encode_chunk_sizes = []
        start = time.perf_counter()
        for chunk in encoder.start():
            encoded.extend(chunk)
            encode_chunk_sizes.append(len(chunk))
        for chunk in encoder.feed(self.payload):
            encoded.extend(chunk)
            encode_chunk_sizes.append(len(chunk))
        for chunk in encoder.finish():
            encoded.extend(chunk)
            encode_chunk_sizes.append(len(chunk))
        codec_encode_duration = time.perf_counter() - start
        assert gzip.decompress(encoded) == self.payload
        assert max(encode_chunk_sizes, default=0) <= output_chunk_size
        self.add_result(
            "sans-I/O codec encode (informational)",
            "streaming",
            codec_encode_duration,
            input_bytes=len(self.payload),
            compressed_bytes=len(encoded),
            output_chunks=len(encode_chunk_sizes),
            stdlib_reference_seconds=stdlib_encode_duration,
            informational=True,
            engine=aiogzip.engine_info().compression,
        )

        start = time.perf_counter()
        stdlib_decoded = gzip.decompress(self.compressed)
        stdlib_decode_duration = time.perf_counter() - start
        assert stdlib_decoded == self.payload
        self.add_result(
            "stdlib gzip.decompress reference",
            "streaming",
            stdlib_decode_duration,
            input_bytes=len(self.compressed),
            output_bytes=len(stdlib_decoded),
            informational=True,
        )

        decoder = aiogzip.GzipDecoder(output_chunk_size=output_chunk_size)
        decoded = bytearray()
        decode_chunk_sizes = []
        start = time.perf_counter()
        for chunk in decoder.feed(self.compressed):
            decoded.extend(chunk)
            decode_chunk_sizes.append(len(chunk))
        for chunk in decoder.finish():
            decoded.extend(chunk)
            decode_chunk_sizes.append(len(chunk))
        codec_decode_duration = time.perf_counter() - start
        assert decoded == self.payload
        assert max(decode_chunk_sizes, default=0) <= output_chunk_size
        self.add_result(
            "sans-I/O codec decode (informational)",
            "streaming",
            codec_decode_duration,
            input_bytes=len(self.compressed),
            output_bytes=len(decoded),
            output_chunks=len(decode_chunk_sizes),
            stdlib_reference_seconds=stdlib_decode_duration,
            informational=True,
            engine=aiogzip.engine_info().decompression,
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
        self._measure_direct_codecs()
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
