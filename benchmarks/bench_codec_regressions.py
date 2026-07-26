"""Regression benchmarks for the 2.0.0a2 decoder repair."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import struct
import time
import tracemalloc
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator

from bench_common import BenchmarkBase

import aiogzip
from aiogzip import _engine

_MIB = 1024 * 1024
_KIB = 1024
_OUTPUT_BOUND = 256 * _KIB
_STREAM_INPUT_BOUND = 256 * _KIB


@dataclass(frozen=True, slots=True)
class _Fixture:
    payload: bytes
    compressed: bytes
    payload_sha256: str
    compressed_sha256: str


@dataclass(frozen=True, slots=True)
class _Profile:
    direct_sizes_mib: tuple[int, ...]
    compressible_sizes_mib: tuple[int, ...]
    ticker_sizes_mib: tuple[int, ...]
    header_sizes_mib: tuple[int, ...]
    high_level_size_mib: int
    empty_blocks: int


_PROFILES = {
    "quick": _Profile(
        direct_sizes_mib=(1, 2),
        compressible_sizes_mib=(1,),
        ticker_sizes_mib=(1, 2),
        header_sizes_mib=(0,),
        high_level_size_mib=1,
        empty_blocks=2_000,
    ),
    "release": _Profile(
        direct_sizes_mib=(8, 16, 32, 64),
        compressible_sizes_mib=(8, 32),
        ticker_sizes_mib=(8, 16, 32, 64),
        header_sizes_mib=(1, 4, 16, 32, 64),
        high_level_size_mib=8,
        empty_blocks=100_000,
    ),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _deterministic_bytes(size: int, *, label: bytes) -> bytes:
    return hashlib.shake_256(b"aiogzip-a2-regressions:" + label).digest(size)


def _fixture(size_mib: int, *, compressible: bool = False) -> _Fixture:
    size = size_mib * _MIB
    if compressible:
        pattern = b"aiogzip-2.0.0a2-regression-fixture\n"
        payload = (pattern * ((size + len(pattern) - 1) // len(pattern)))[:size]
    else:
        payload = _deterministic_bytes(size, label=f"incompressible:{size}".encode())
    compressed = gzip.compress(payload, compresslevel=6, mtime=0)
    return _Fixture(
        payload=payload,
        compressed=compressed,
        payload_sha256=_sha256(payload),
        compressed_sha256=_sha256(compressed),
    )


def _split_exact(data: bytes, size: int) -> tuple[bytes, ...]:
    return tuple(data[offset : offset + size] for offset in range(0, len(data), size))


def _source_metrics(items: tuple[bytes, ...]) -> dict[str, int]:
    sizes = [len(item) for item in items]
    return {
        "source_items": len(items),
        "source_min_bytes": min(sizes, default=0),
        "source_max_bytes": max(sizes, default=0),
        "source_total_bytes": sum(sizes),
    }


def _percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction)))
    return ordered[index]


def _digest_direct(
    compressed_items: tuple[bytes, ...], *, output_chunk_size: int
) -> tuple[int, str, int, int]:
    decoder = aiogzip.GzipDecoder(output_chunk_size=output_chunk_size)
    digest = hashlib.sha256()
    output_bytes = 0
    output_chunks = 0
    maximum_chunk = 0
    for item in compressed_items:
        for output in decoder.feed(item):
            digest.update(output)
            output_bytes += len(output)
            output_chunks += 1
            maximum_chunk = max(maximum_chunk, len(output))
    for output in decoder.finish():
        digest.update(output)
        output_bytes += len(output)
        output_chunks += 1
        maximum_chunk = max(maximum_chunk, len(output))
    return output_bytes, digest.hexdigest(), output_chunks, maximum_chunk


async def _source(items: tuple[bytes, ...]) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def _digest_stream(
    compressed_items: tuple[bytes, ...], *, output_chunk_size: int
) -> tuple[int, str, int, int]:
    digest = hashlib.sha256()
    output_bytes = 0
    output_chunks = 0
    maximum_chunk = 0
    async for output in aiogzip.decompress_chunks(
        _source(compressed_items), output_chunk_size=output_chunk_size
    ):
        digest.update(output)
        output_bytes += len(output)
        output_chunks += 1
        maximum_chunk = max(maximum_chunk, len(output))
    return output_bytes, digest.hexdigest(), output_chunks, maximum_chunk


async def _compress_stream(
    payload_items: tuple[bytes, ...], *, output_chunk_size: int
) -> tuple[bytes, int]:
    compressed = bytearray()
    chunks = 0
    async for output in aiogzip.compress_chunks(
        _source(payload_items),
        compresslevel=6,
        mtime=0,
        output_chunk_size=output_chunk_size,
    ):
        compressed.extend(output)
        chunks += 1
    return bytes(compressed), chunks


class _CountingEngine:
    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.decompress_calls = 0

    def decompress(self, *args: Any, **kwargs: Any) -> bytes:
        self.decompress_calls += 1
        return self._wrapped.decompress(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


@contextmanager
def _counting_decompressors() -> Iterator[list[_CountingEngine]]:
    original = _engine.decompressobj
    engines: list[_CountingEngine] = []

    def create(wbits: int) -> _CountingEngine:
        engine = _CountingEngine(original(wbits))
        engines.append(engine)
        return engine

    _engine.decompressobj = create
    try:
        yield engines
    finally:
        _engine.decompressobj = original


def _custom_gzip(
    payload: bytes = b"header benchmark payload",
    *,
    filename: bytes | None = None,
    comment: bytes | None = None,
    extra: bytes | None = None,
    header_crc: bool = False,
) -> bytes:
    flags = 0
    if extra is not None:
        flags |= 0x04
    if filename is not None:
        flags |= 0x08
    if comment is not None:
        flags |= 0x10
    if header_crc:
        flags |= 0x02
    header = bytearray(b"\x1f\x8b\x08")
    header.append(flags)
    header.extend(struct.pack("<I", 0))
    header.extend(b"\x00\xff")
    if extra is not None:
        header.extend(struct.pack("<H", len(extra)))
        header.extend(extra)
    if filename is not None:
        header.extend(filename)
        header.append(0)
    if comment is not None:
        header.extend(comment)
        header.append(0)
    if header_crc:
        header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))
    engine = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
    body = engine.compress(payload) + engine.flush()
    trailer = struct.pack("<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload))
    return bytes(header) + body + trailer


def _empty_block_gzip(empty_blocks: int) -> tuple[bytes, bytes]:
    payload = b"aiogzip-empty-block-prefix"
    length = len(payload)
    raw = bytearray(b"\x00")
    raw.extend(struct.pack("<H", length))
    raw.extend(struct.pack("<H", length ^ 0xFFFF))
    raw.extend(payload)
    raw.extend(b"\x00\x00\x00\xff\xff" * empty_blocks)
    raw.extend(b"\x01\x00\x00\xff\xff")
    trailer = struct.pack("<II", zlib.crc32(payload) & 0xFFFFFFFF, length)
    wire = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff" + bytes(raw) + trailer
    assert gzip.decompress(wire) == payload
    return wire, payload


class RegressionsBenchmarks(BenchmarkBase):
    """Run deterministic throughput, allocation, and scheduler matrices."""

    def __init__(
        self,
        data_size_mb: int = 1,
        *,
        regression_profile: str = "quick",
        regression_mode: str = "throughput",
    ) -> None:
        super().__init__(data_size_mb=data_size_mb)
        self.profile_name = regression_profile
        self.profile = _PROFILES[regression_profile]
        self.mode = regression_mode
        self.has_public_codec = hasattr(aiogzip, "GzipDecoder")

    def _skip_codec(self, name: str, mode: str) -> None:
        self.add_result(
            name,
            "regressions",
            0.0,
            status="skipped",
            reason="target does not expose the 2.0 public codec",
            benchmark_mode=mode,
            package_version=aiogzip.__version__,
        )

    def _direct_scaling(self) -> None:
        for compressible in (False, True):
            sizes = (
                self.profile.compressible_sizes_mib
                if compressible
                else self.profile.direct_sizes_mib
            )
            fixture_kind = "compressible" if compressible else "incompressible"
            for size_mib in sizes:
                for boundary, item_size in (
                    ("one-feed", max(1, 2 * size_mib * _MIB)),
                    ("256K-feeds", _STREAM_INPUT_BOUND),
                ):
                    name = (
                        f"direct decode {fixture_kind} {size_mib}MiB "
                        f"{boundary} 256K-output"
                    )
                    if not self.has_public_codec:
                        self._skip_codec(name, "throughput")
                        continue
                    fixture = _fixture(size_mib, compressible=compressible)
                    items = _split_exact(fixture.compressed, item_size)
                    start = time.perf_counter()
                    output_bytes, digest, chunks, maximum = _digest_direct(
                        items, output_chunk_size=_OUTPUT_BOUND
                    )
                    duration = time.perf_counter() - start
                    assert output_bytes == len(fixture.payload)
                    assert digest == fixture.payload_sha256
                    assert maximum <= _OUTPUT_BOUND
                    self.add_result(
                        name,
                        "regressions",
                        duration,
                        benchmark_mode="throughput",
                        fixture_kind=fixture_kind,
                        fixture_bytes=len(fixture.payload),
                        fixture_sha256=fixture.payload_sha256,
                        compressed_bytes=len(fixture.compressed),
                        compressed_sha256=fixture.compressed_sha256,
                        output_bytes=output_bytes,
                        output_sha256=digest,
                        output_chunks=chunks,
                        max_output_chunk=maximum,
                        throughput_mib_s=size_mib / duration,
                        engine=aiogzip.engine_info().decompression,
                        **_source_metrics(items),
                    )

    async def _high_level_streaming(self) -> None:
        fixture = _fixture(self.profile.high_level_size_mib)
        for input_size, output_size in (
            (64 * _KIB, 64 * _KIB),
            (512 * _KIB, 256 * _KIB),
        ):
            items = _split_exact(fixture.compressed, input_size)
            start = time.perf_counter()
            output_bytes, digest, chunks, maximum = await _digest_stream(
                items, output_chunk_size=output_size
            )
            duration = time.perf_counter() - start
            assert output_bytes == len(fixture.payload)
            assert digest == fixture.payload_sha256
            assert maximum <= output_size
            self.add_result(
                f"decompress_chunks {input_size // _KIB}K-in "
                f"{output_size // _KIB}K-out",
                "regressions",
                duration,
                benchmark_mode="throughput",
                fixture_bytes=len(fixture.payload),
                fixture_sha256=fixture.payload_sha256,
                compressed_sha256=fixture.compressed_sha256,
                output_bytes=output_bytes,
                output_sha256=digest,
                output_chunks=chunks,
                max_output_chunk=maximum,
                engine=aiogzip.engine_info().decompression,
                **_source_metrics(items),
            )

        payload_items = _split_exact(fixture.payload, 64 * _KIB)
        for input_size, output_size in (
            (64 * _KIB, 64 * _KIB),
            (512 * _KIB, 256 * _KIB),
        ):
            payload_items = _split_exact(fixture.payload, input_size)
            start = time.perf_counter()
            compressed, chunks = await _compress_stream(
                payload_items, output_chunk_size=output_size
            )
            duration = time.perf_counter() - start
            decoded = gzip.decompress(compressed)
            assert _sha256(decoded) == fixture.payload_sha256
            self.add_result(
                f"compress_chunks {input_size // _KIB}K-in {output_size // _KIB}K-out",
                "regressions",
                duration,
                benchmark_mode="throughput",
                fixture_bytes=len(fixture.payload),
                fixture_sha256=fixture.payload_sha256,
                compressed_bytes=len(compressed),
                compressed_sha256=_sha256(compressed),
                output_chunks=chunks,
                engine=aiogzip.engine_info().compression,
                **_source_metrics(payload_items),
            )

    def _output_bound_matrix(self) -> None:
        fixture = _Fixture(
            payload=_deterministic_bytes(128 * _KIB, label=b"output-bound"),
            compressed=b"",
            payload_sha256="",
            compressed_sha256="",
        )
        compressed = gzip.compress(fixture.payload, compresslevel=6, mtime=0)
        fixture = _Fixture(
            payload=fixture.payload,
            compressed=compressed,
            payload_sha256=_sha256(fixture.payload),
            compressed_sha256=_sha256(compressed),
        )
        for output_bound in (1, _KIB, 64 * _KIB, 256 * _KIB):
            name = f"direct output bound {output_bound} bytes"
            if not self.has_public_codec:
                self._skip_codec(name, "throughput")
                continue
            items = (fixture.compressed,)
            with _counting_decompressors() as engines:
                start = time.perf_counter()
                output_bytes, digest, chunks, maximum = _digest_direct(
                    items, output_chunk_size=output_bound
                )
                duration = time.perf_counter() - start
            calls = sum(engine.decompress_calls for engine in engines)
            assert output_bytes == len(fixture.payload)
            assert digest == fixture.payload_sha256
            assert maximum <= output_bound
            self.add_result(
                name,
                "regressions",
                duration,
                benchmark_mode="throughput",
                fixture_bytes=len(fixture.payload),
                fixture_sha256=fixture.payload_sha256,
                compressed_bytes=len(fixture.compressed),
                compressed_sha256=fixture.compressed_sha256,
                output_bytes=output_bytes,
                output_sha256=digest,
                output_chunks=chunks,
                max_output_chunk=maximum,
                output_chunk_size=output_bound,
                engine_decompress_calls=calls,
                engine=aiogzip.engine_info().decompression,
                **_source_metrics(items),
            )

    def _header_throughput(self) -> None:
        for size_mib in self.profile.header_sizes_mib:
            field_size = 64 * _KIB if self.profile_name == "quick" else size_mib * _MIB
            for field_name in ("filename", "comment"):
                field = _deterministic_bytes(
                    field_size, label=f"header:{field_name}:{field_size}".encode()
                ).replace(b"\x00", b"x")
                kwargs = {field_name: field}
                wire = _custom_gzip(header_crc=True, **kwargs)
                expected = _sha256(b"header benchmark payload")
                for boundary in (len(wire) + 1, 64 * _KIB):
                    name = (
                        f"header {field_name} {field_size} bytes "
                        f"{'one-feed' if boundary > len(wire) else '64K-feeds'}"
                    )
                    if not self.has_public_codec:
                        self._skip_codec(name, "throughput")
                        continue
                    items = _split_exact(wire, boundary)
                    start = time.perf_counter()
                    output_bytes, digest, _, maximum = _digest_direct(
                        items, output_chunk_size=_OUTPUT_BOUND
                    )
                    duration = time.perf_counter() - start
                    assert output_bytes == len(b"header benchmark payload")
                    assert digest == expected
                    assert maximum <= _OUTPUT_BOUND
                    self.add_result(
                        name,
                        "regressions",
                        duration,
                        benchmark_mode="throughput",
                        header_field=field_name,
                        header_field_bytes=field_size,
                        header_crc=True,
                        collect_member_info=False,
                        output_bytes=output_bytes,
                        output_sha256=digest,
                        engine=aiogzip.engine_info().decompression,
                        **_source_metrics(items),
                    )

    def _memory_matrix(self) -> None:
        for size_mib in self.profile.direct_sizes_mib:
            name = f"direct decode memory {size_mib}MiB one-feed"
            if not self.has_public_codec:
                self._skip_codec(name, "memory")
                continue
            fixture = _fixture(size_mib)
            tracemalloc.start()
            start = time.perf_counter()
            output_bytes, digest, chunks, maximum = _digest_direct(
                (fixture.compressed,), output_chunk_size=_OUTPUT_BOUND
            )
            duration = time.perf_counter() - start
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert output_bytes == len(fixture.payload)
            assert digest == fixture.payload_sha256
            assert maximum <= _OUTPUT_BOUND
            self.add_result(
                name,
                "regressions",
                duration,
                benchmark_mode="memory",
                fixture_bytes=len(fixture.payload),
                fixture_sha256=fixture.payload_sha256,
                compressed_sha256=fixture.compressed_sha256,
                output_bytes=output_bytes,
                output_sha256=digest,
                output_chunks=chunks,
                max_output_chunk=maximum,
                peak_python_bytes=peak,
                engine=aiogzip.engine_info().decompression,
                **_source_metrics((fixture.compressed,)),
            )

        field_size = 64 * _KIB if self.profile_name == "quick" else 32 * _MIB
        for field_name, flag in (("filename", 0x08), ("comment", 0x10)):
            field = b"x" * field_size
            incomplete = b"\x1f\x8b\x08" + bytes([flag]) + b"\x00" * 6 + field
            items = _split_exact(incomplete, 64 * _KIB)
            for collect_metadata in (False, True):
                name = (
                    f"incomplete {field_name} memory {field_size} bytes "
                    f"metadata-{'on' if collect_metadata else 'off'}"
                )
                if not self.has_public_codec:
                    self._skip_codec(name, "memory")
                    continue
                decoder = aiogzip.GzipDecoder(
                    output_chunk_size=_OUTPUT_BOUND,
                    collect_member_info=collect_metadata,
                )
                tracemalloc.start()
                start = time.perf_counter()
                try:
                    for item in items:
                        list(decoder.feed(item))
                    try:
                        list(decoder.finish())
                    except (EOFError, OSError):
                        pass
                    else:
                        raise AssertionError("incomplete gzip header was accepted")
                finally:
                    decoder.discard()
                duration = time.perf_counter() - start
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                self.add_result(
                    name,
                    "regressions",
                    duration,
                    benchmark_mode="memory",
                    header_field=field_name,
                    header_field_bytes=field_size,
                    collect_member_info=collect_metadata,
                    peak_python_bytes=peak,
                    engine=aiogzip.engine_info().decompression,
                    **_source_metrics(items),
                )

    async def _ticker_measure(
        self, items: tuple[bytes, ...], expected: _Fixture
    ) -> tuple[float, dict[str, Any]]:
        stop = False
        primed = asyncio.Event()
        ticks: list[float] = []

        async def ticker() -> None:
            while not stop:
                ticks.append(time.perf_counter())
                primed.set()
                await asyncio.sleep(0)

        task = asyncio.create_task(ticker())
        await primed.wait()
        started = time.perf_counter()
        first_output_at: float | None = None
        digest = hashlib.sha256()
        output_bytes = 0
        output_chunks = 0
        maximum = 0
        async for output in aiogzip.decompress_chunks(
            _source(items), output_chunk_size=_OUTPUT_BOUND
        ):
            if first_output_at is None:
                first_output_at = time.perf_counter()
            digest.update(output)
            output_bytes += len(output)
            output_chunks += 1
            maximum = max(maximum, len(output))
        duration = time.perf_counter() - started
        stop = True
        await task
        gaps = [
            later - earlier for earlier, later in zip(ticks, ticks[1:], strict=False)
        ]
        output_digest = digest.hexdigest()
        assert output_bytes == len(expected.payload)
        assert output_digest == expected.payload_sha256
        assert maximum <= _OUTPUT_BOUND
        return duration, {
            "ticker_count": len(ticks),
            "ticker_gap_p50_seconds": _percentile(gaps, 0.50),
            "ticker_gap_p95_seconds": _percentile(gaps, 0.95),
            "ticker_gap_p99_seconds": _percentile(gaps, 0.99),
            "ticker_gap_max_seconds": max(gaps, default=0.0),
            "first_output_seconds": (
                first_output_at - started if first_output_at is not None else duration
            ),
            "output_bytes": output_bytes,
            "output_sha256": output_digest,
            "output_chunks": output_chunks,
            "max_output_chunk": maximum,
        }

    async def _ticker_baseline(self) -> None:
        gaps: list[float] = []
        previous = time.perf_counter()
        for _ in range(10_000):
            await asyncio.sleep(0)
            current = time.perf_counter()
            gaps.append(current - previous)
            previous = current
        self.add_result(
            "async ticker baseline",
            "regressions",
            sum(gaps),
            benchmark_mode="ticker",
            ticker_count=len(gaps),
            ticker_gap_p50_seconds=_percentile(gaps, 0.50),
            ticker_gap_p95_seconds=_percentile(gaps, 0.95),
            ticker_gap_p99_seconds=_percentile(gaps, 0.99),
            ticker_gap_max_seconds=max(gaps, default=0.0),
        )

    async def _ticker_matrix(self) -> None:
        await self._ticker_baseline()
        for size_mib in self.profile.ticker_sizes_mib:
            fixture = _fixture(size_mib)
            for boundary, item_size in (
                ("one-item", len(fixture.compressed) + 1),
                ("256K-items", _STREAM_INPUT_BOUND),
            ):
                items = _split_exact(fixture.compressed, item_size)
                duration, metrics = await self._ticker_measure(items, fixture)
                self.add_result(
                    f"async decode ticker {size_mib}MiB {boundary}",
                    "regressions",
                    duration,
                    benchmark_mode="ticker",
                    fixture_bytes=len(fixture.payload),
                    fixture_sha256=fixture.payload_sha256,
                    compressed_sha256=fixture.compressed_sha256,
                    engine=aiogzip.engine_info().decompression,
                    **metrics,
                    **_source_metrics(items),
                )

        wire, payload = _empty_block_gzip(self.profile.empty_blocks)
        fixture = _Fixture(
            payload=payload,
            compressed=wire,
            payload_sha256=_sha256(payload),
            compressed_sha256=_sha256(wire),
        )
        items = (wire,)
        with _counting_decompressors() as engines:
            duration, metrics = await self._ticker_measure(items, fixture)
        self.add_result(
            f"async decode ticker empty-blocks {self.profile.empty_blocks}",
            "regressions",
            duration,
            benchmark_mode="ticker",
            fixture_bytes=len(payload),
            fixture_sha256=fixture.payload_sha256,
            compressed_sha256=fixture.compressed_sha256,
            empty_blocks=self.profile.empty_blocks,
            engine_decompress_calls=sum(engine.decompress_calls for engine in engines),
            progress_events="unavailable through public API",
            engine=aiogzip.engine_info().decompression,
            **metrics,
            **_source_metrics(items),
        )

    async def run_all(self) -> None:
        """Run the selected matrix without mixing measurement modes."""
        modes = (
            ("throughput", "memory", "ticker") if self.mode == "all" else (self.mode,)
        )
        for mode in modes:
            if mode == "throughput":
                self._direct_scaling()
                await self._high_level_streaming()
                self._output_bound_matrix()
                self._header_throughput()
            elif mode == "memory":
                self._memory_matrix()
            elif mode == "ticker":
                await self._ticker_matrix()
            else:  # pragma: no cover - argparse owns public validation.
                raise ValueError(f"unknown regression mode: {mode}")
