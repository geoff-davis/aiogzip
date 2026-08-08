#!/usr/bin/env python3
"""Release evidence for concurrent, path-backed, and allocation write surfaces."""

from __future__ import annotations

import argparse
import asyncio
import gc
import gzip
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
    SCHEMA_VERSION,
    CountingMemorySink,
    _csv_positive_ints,
    _file_sha256,
    _payload_for_write,
    _positive_int,
    _records,
    collect_environment,
    configure_source_root,
)


async def _write_stream(writer: Any, record: bytes, total_bytes: int) -> int:
    for item in _records(record, total_bytes):
        if await writer.write(item) != len(item):
            raise AssertionError("write returned an unexpected byte count")
    position = await writer.tell()
    await writer.close()
    if position != total_bytes:
        raise AssertionError(f"position {position} != {total_bytes}")
    return position


async def _concurrent_once(
    aiogzip: Any,
    *,
    writer_count: int,
    write_size: int,
    aggregate_bytes: int,
    fast_compress: bool,
) -> dict[str, Any]:
    per_writer_bytes = aggregate_bytes // writer_count
    record, expected = _payload_for_write(write_size, per_writer_bytes)
    sinks = [CountingMemorySink() for _ in range(writer_count)]
    writers = [
        aiogzip.open(
            None,
            "wb",
            fileobj=sink,
            closefd=False,
            mtime=0,
            original_filename=f"writer-{index}.bin",
            fast_compress=fast_compress,
        )
        for index, sink in enumerate(sinks)
    ]
    for writer in writers:
        await writer.open()

    started = time.perf_counter()
    positions = await asyncio.gather(
        *(_write_stream(writer, record, per_writer_bytes) for writer in writers)
    )
    duration = time.perf_counter() - started

    compressed_hashes = []
    for sink in sinks:
        compressed = bytes(sink.output)
        if gzip.decompress(compressed) != expected:
            raise AssertionError("concurrent writer output mismatch")
        compressed_hashes.append(hashlib.sha256(compressed).hexdigest())
    return {
        "duration_seconds": duration,
        "writer_count": writer_count,
        "write_size_bytes": write_size,
        "aggregate_payload_bytes": per_writer_bytes * writer_count,
        "per_writer_payload_bytes": per_writer_bytes,
        "per_writer_payload_sha256": hashlib.sha256(expected).hexdigest(),
        "positions": positions,
        "sink_write_calls": sum(sink.write_calls for sink in sinks),
        "compressed_sha256": compressed_hashes,
    }


async def _path_once(
    aiogzip: Any,
    *,
    write_size: int,
    total_bytes: int,
    fast_compress: bool,
) -> dict[str, Any]:
    record, expected = _payload_for_write(write_size, total_bytes)
    with tempfile.TemporaryDirectory(prefix="aiogzip-a3-writes-") as directory:
        path = Path(directory) / "payload.gz"
        writer = aiogzip.open(
            path,
            "wb",
            mtime=0,
            original_filename="payload.bin",
            fast_compress=fast_compress,
        )
        await writer.open()
        started = time.perf_counter()
        position = await _write_stream(writer, record, total_bytes)
        duration = time.perf_counter() - started
        compressed = path.read_bytes()
    decoded = gzip.decompress(compressed)
    if decoded != expected:
        raise AssertionError("path-backed writer output mismatch")
    return {
        "duration_seconds": duration,
        "write_size_bytes": write_size,
        "payload_bytes": len(expected),
        "payload_sha256": hashlib.sha256(expected).hexdigest(),
        "compressed_bytes": len(compressed),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "position": position,
    }


async def _allocation_once(
    aiogzip: Any,
    *,
    write_size: int,
    total_bytes: int,
    fast_compress: bool,
) -> dict[str, Any]:
    record, expected = _payload_for_write(write_size, total_bytes)
    sink = CountingMemorySink()
    writer = aiogzip.open(
        None,
        "wb",
        fileobj=sink,
        closefd=False,
        mtime=0,
        original_filename="allocation.bin",
        fast_compress=fast_compress,
    )
    await writer.open()
    gc.collect()
    tracemalloc.start()
    position = await _write_stream(writer, record, total_bytes)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    compressed = bytes(sink.output)
    if gzip.decompress(compressed) != expected:
        raise AssertionError("allocation writer output mismatch")
    return {
        "write_size_bytes": write_size,
        "payload_bytes": len(expected),
        "payload_sha256": hashlib.sha256(expected).hexdigest(),
        "position": position,
        "sink_write_calls": sink.write_calls,
        "peak_python_bytes": peak,
        "current_python_bytes": current,
        "measurement_mode": "tracemalloc (not a timing claim)",
    }


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(sample["duration_seconds"]) for sample in samples]
    median = float(statistics.median(durations))
    return {
        "duration_samples_seconds": durations,
        "median_seconds": median,
        "median_absolute_deviation_seconds": float(
            statistics.median(abs(sample - median) for sample in durations)
        ),
        "sample_count": len(samples),
        "sample_metrics": samples,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    runner_root = Path(__file__).resolve().parents[1]
    aiogzip, identity = configure_source_root(args.source_root, args.engine)
    fast_compress = args.engine == "zlib-ng"
    results: dict[str, Any] = {}

    for write_size in args.concurrent_write_sizes:
        for writer_count in args.writer_counts:
            samples = [
                await _concurrent_once(
                    aiogzip,
                    writer_count=writer_count,
                    write_size=write_size,
                    aggregate_bytes=args.total_write_bytes,
                    fast_compress=fast_compress,
                )
                for _ in range(args.repeat)
            ]
            results[f"memory-{writer_count}-writers-{write_size}B"] = _aggregate(
                samples
            )

    for write_size in args.path_write_sizes:
        samples = [
            await _path_once(
                aiogzip,
                write_size=write_size,
                total_bytes=args.total_write_bytes,
                fast_compress=fast_compress,
            )
            for _ in range(args.repeat)
        ]
        results[f"path-1-writer-{write_size}B"] = _aggregate(samples)

    for write_size in args.concurrent_write_sizes:
        results[f"allocation-1-writer-{write_size}B"] = await _allocation_once(
            aiogzip,
            write_size=write_size,
            total_bytes=args.total_write_bytes,
            fast_compress=fast_compress,
        )

    environment = collect_environment(args.source_root.resolve(), identity, runner_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "verification": "aiogzip-2.0.0a3-write-surfaces",
        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        "source": identity,
        "environment": environment,
        "verification_harness_sha256": _file_sha256(Path(__file__)),
        "configuration": {
            "writer_counts": args.writer_counts,
            "concurrent_write_sizes": args.concurrent_write_sizes,
            "path_write_sizes": args.path_write_sizes,
            "total_write_bytes": args.total_write_bytes,
            "repeat": args.repeat,
            "concurrent_total_policy": "fixed aggregate bytes divided across writers",
            "correctness_policy": "position, decompressed bytes, and SHA-256 checked outside timing",
        },
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--writer-counts", type=_csv_positive_ints, default=(1, 4, 10))
    parser.add_argument(
        "--concurrent-write-sizes",
        type=_csv_positive_ints,
        default=(10, 1024, 65536),
    )
    parser.add_argument(
        "--path-write-sizes",
        type=_csv_positive_ints,
        default=(10, 100, 1024, 4096, 16384, 65536, 262144),
    )
    parser.add_argument(
        "--total-write-bytes", type=_positive_int, default=8 * 1024 * 1024
    )
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
