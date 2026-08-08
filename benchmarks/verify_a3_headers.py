#!/usr/bin/env python3
"""Release-only structural verification for 2.0.0a3 header processing.

This complements ``bench_a3_regressions.py`` without changing the locked
exact-a2 comparison harness. It measures ownership-specific allocation,
path-backed behavior, text parity, and the real 128 MiB parser boundary.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from bench_a3_regressions import (
    _MIB,
    _file_sha256,
    collect_environment,
    combined_header_fixture,
    configure_source_root,
    optional_header_fixture,
)


class SeekableMemorySource:
    """Bounded asynchronous source that never activates rewind caching."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.read_calls = 0
        self.max_requested = 0
        self.max_returned = 0

    def seekable(self) -> bool:
        return True

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        self.max_requested = max(self.max_requested, size)
        if size < 0:
            size = len(self.data) - self.position
        end = min(len(self.data), self.position + size)
        result = self.data[self.position : end]
        self.position = end
        self.max_returned = max(self.max_returned, len(result))
        return result

    async def seek(self, offset: int, whence: int = 0) -> int:
        if whence != 0 or offset < 0:
            raise OSError("verification source only supports absolute seeks")
        self.position = offset
        return offset


class NonSeekableMemorySource:
    """Bounded source whose file wrapper intentionally owns a rewind cache."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.read_calls = 0
        self.max_returned = 0

    def seekable(self) -> bool:
        return False

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if size < 0:
            size = len(self.data) - self.position
        end = min(len(self.data), self.position + size)
        result = self.data[self.position : end]
        self.position = end
        self.max_returned = max(self.max_returned, len(result))
        return result


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


async def _expected_failure(
    aiogzip: Any,
    source: SeekableMemorySource | NonSeekableMemorySource,
    *,
    chunk_size: int,
    error_fragment: str,
    measure_memory: bool,
) -> dict[str, Any]:
    reader = aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=chunk_size,
    )
    await reader.open()
    if measure_memory:
        gc.collect()
        tracemalloc.start()
    started = time.perf_counter()
    try:
        try:
            await reader.read()
        except (EOFError, OSError) as error:
            failure = f"{type(error).__name__}: {error}"
        else:
            raise AssertionError("expected header failure was not raised")
        duration = time.perf_counter() - started
        if error_fragment not in failure:
            raise AssertionError(
                f"expected {error_fragment!r} in failure, observed {failure!r}"
            )
        cache_bytes = len(reader._compressed_cache)
        cache_enabled = reader._cache_rewindable_reads
        observed_mtime = reader.mtime
        if measure_memory:
            current_before_close, peak = tracemalloc.get_traced_memory()
        else:
            current_before_close = peak = None
    finally:
        await reader.close()

    del reader
    gc.collect()
    if measure_memory:
        current_after_close_gc, final_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if final_peak != peak:
            peak = final_peak
    else:
        current_after_close_gc = None

    if source.max_returned > chunk_size:
        raise AssertionError("source returned more bytes than requested")
    return {
        "duration_seconds": duration,
        "failure": failure,
        "mtime": observed_mtime,
        "source_read_calls": source.read_calls,
        "source_position": source.position,
        "source_max_returned_bytes": source.max_returned,
        "compressed_rewind_cache_bytes": cache_bytes,
        "compressed_rewind_cache_enabled": cache_enabled,
        "peak_python_bytes": peak,
        "current_python_bytes_before_close": current_before_close,
        "current_python_bytes_after_close_gc": current_after_close_gc,
        "measurement_mode": "tracemalloc" if measure_memory else "wall_time",
    }


async def _path_backed_samples(
    aiogzip: Any, wire: bytes, *, chunk_size: int, repeat: int
) -> dict[str, Any]:
    samples = []
    with tempfile.TemporaryDirectory(prefix="aiogzip-a3-header-") as directory:
        path = Path(directory) / "incomplete-fname.gz"
        path.write_bytes(wire)
        for _ in range(repeat):
            reader = aiogzip.open(path, "rb", chunk_size=chunk_size)
            await reader.open()
            started = time.perf_counter()
            try:
                try:
                    await reader.read()
                except (EOFError, OSError) as error:
                    failure = f"{type(error).__name__}: {error}"
                else:
                    raise AssertionError("path-backed incomplete header was accepted")
                samples.append(time.perf_counter() - started)
                if "truncated gzip member header" not in failure:
                    raise AssertionError(f"unexpected path-backed failure: {failure}")
            finally:
                await reader.close()
    median = float(statistics.median(samples))
    return {
        "duration_samples_seconds": samples,
        "median_seconds": median,
        "median_absolute_deviation_seconds": float(
            statistics.median(abs(sample - median) for sample in samples)
        ),
        "sample_count": len(samples),
        "fixture_bytes": len(wire),
        "fixture_sha256": hashlib.sha256(wire).hexdigest(),
        "filesystem": "temporary path (described in environment)",
    }


async def _text_smoke(aiogzip: Any, chunk_size: int) -> dict[str, Any]:
    wire, payload, _ = combined_header_fixture(
        extra_size=4096,
        fname_size=4097,
        fcomment_size=4099,
        mtime=123456789,
        fhcrc=True,
    )
    source = SeekableMemorySource(wire)
    async with aiogzip.open(
        None,
        "rt",
        fileobj=source,
        closefd=False,
        chunk_size=chunk_size,
    ) as reader:
        output = await reader.read()
        observed_mtime = reader.mtime
    if output.encode() != payload or observed_mtime != 123456789:
        raise AssertionError("text optional-header smoke mismatch")
    return {
        "fixture_bytes": len(wire),
        "output_bytes": len(payload),
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "mtime": observed_mtime,
        "source_read_calls": source.read_calls,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    runner_root = Path(__file__).resolve().parents[1]
    aiogzip, identity = configure_source_root(args.source_root, args.engine)
    chunk_size = args.source_chunk_mib * _MIB
    results: dict[str, Any] = {}

    for field in ("fname", "fcomment"):
        wire, _ = optional_header_fixture(
            field, args.retention_mib * _MIB, complete=False, mtime=101
        )
        source = SeekableMemorySource(wire)
        result = await _expected_failure(
            aiogzip,
            source,
            chunk_size=chunk_size,
            error_fragment="truncated gzip member header",
            measure_memory=True,
        )
        if result["compressed_rewind_cache_bytes"] != 0:
            raise AssertionError("seekable source unexpectedly activated rewind cache")
        results[f"seekable-{field}-{args.retention_mib}MiB-retention"] = result
        del source, wire
        gc.collect()

    wire, _ = optional_header_fixture(
        "fname", args.cache_control_mib * _MIB, complete=False, mtime=102
    )
    source = NonSeekableMemorySource(wire)
    cache_result = await _expected_failure(
        aiogzip,
        source,
        chunk_size=chunk_size,
        error_fragment="truncated gzip member header",
        measure_memory=True,
    )
    if cache_result["compressed_rewind_cache_bytes"] != len(wire):
        raise AssertionError("non-seekable control did not retain its rewind cache")
    results[f"nonseekable-fname-{args.cache_control_mib}MiB-cache-control"] = (
        cache_result
    )
    del source, wire
    gc.collect()

    path_wire, _ = optional_header_fixture(
        "fname", args.path_mib * _MIB, complete=False, mtime=103
    )
    results[f"path-fname-{args.path_mib}MiB"] = await _path_backed_samples(
        aiogzip,
        path_wire,
        chunk_size=chunk_size,
        repeat=args.repeat,
    )
    del path_wire
    gc.collect()

    results["text-combined-fields-smoke"] = await _text_smoke(aiogzip, chunk_size)

    boundary_mib = 128
    limit = boundary_mib * _MIB
    exact_wire, _ = optional_header_fixture(
        "fname", limit - 10, complete=False, mtime=104
    )
    exact_source = SeekableMemorySource(exact_wire)
    exact = await _expected_failure(
        aiogzip,
        exact_source,
        chunk_size=chunk_size,
        error_fragment="truncated gzip member header",
        measure_memory=False,
    )
    if exact["source_position"] != limit or exact["mtime"] is not None:
        raise AssertionError("exact header boundary semantics changed")
    results[f"exact-{boundary_mib}MiB-boundary"] = exact
    del exact_source, exact_wire
    gc.collect()

    over_wire, _ = optional_header_fixture(
        "fname", limit - 9, complete=False, mtime=105
    )
    over_source = SeekableMemorySource(over_wire)
    over = await _expected_failure(
        aiogzip,
        over_source,
        chunk_size=chunk_size,
        error_fragment=f"exceeds the {boundary_mib} MiB safety limit",
        measure_memory=False,
    )
    if over["source_position"] != limit + 1 or over["mtime"] is not None:
        raise AssertionError("over-limit header semantics changed")
    results[f"over-{boundary_mib}MiB-boundary"] = over

    environment = collect_environment(args.source_root.resolve(), identity, runner_root)
    return {
        "schema_version": 1,
        "verification": "aiogzip-2.0.0a3-release-header-structure",
        "created_at_unix": time.time(),
        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        "configuration": {
            "boundary_mib": boundary_mib,
            "retention_mib": args.retention_mib,
            "cache_control_mib": args.cache_control_mib,
            "path_mib": args.path_mib,
            "source_chunk_mib": args.source_chunk_mib,
            "repeat": args.repeat,
            "allocation_fixture_policy": "fixture and reader opened before tracemalloc",
            "nonseekable_policy": "reported separately and excluded from parser gates",
        },
        "source": identity,
        "environment": environment,
        "script_sha256": _file_sha256(Path(__file__)),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--retention-mib", type=_positive_int, default=64)
    parser.add_argument("--cache-control-mib", type=_positive_int, default=32)
    parser.add_argument("--path-mib", type=_positive_int, default=16)
    parser.add_argument("--source-chunk-mib", type=_positive_int, default=1)
    parser.add_argument("--repeat", type=_positive_int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.repeat < 5 or args.repeat % 2 == 0:
        parser.error("--repeat must be an odd integer of at least 5")
    try:
        document = asyncio.run(run(args))
    except (AssertionError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
