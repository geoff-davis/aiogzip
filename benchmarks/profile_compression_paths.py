#!/usr/bin/env python3
"""Profile representative and diagnostic compression paths for WP6."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import gzip
import hashlib
import json
import pstats
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from bench_codec_regressions import _fixture, _split_exact

import aiogzip
from aiogzip import _engine

ROOT = Path(__file__).resolve().parents[1]
_KIB = 1024


async def _source(items: tuple[bytes, ...]):
    for item in items:
        yield item


def _direct_compress(
    items: tuple[bytes, ...],
    *,
    output_chunk_size: int,
    fast_compress: bool,
) -> bytes:
    encoder = aiogzip.GzipEncoder(
        mtime=0,
        output_chunk_size=output_chunk_size,
        fast_compress=fast_compress,
    )
    output = bytearray()
    output.extend(b"".join(encoder.start()))
    for item in items:
        output.extend(b"".join(encoder.feed(item)))
    output.extend(b"".join(encoder.finish()))
    return bytes(output)


async def _stream_compress(
    items: tuple[bytes, ...],
    *,
    output_chunk_size: int,
    fast_compress: bool,
) -> bytes:
    output = bytearray()
    async for chunk in aiogzip.compress_chunks(
        _source(items),
        mtime=0,
        output_chunk_size=output_chunk_size,
        fast_compress=fast_compress,
    ):
        output.extend(chunk)
    return bytes(output)


async def _tiny_file_write(payload: bytes, path: Path) -> bytes:
    async with aiogzip.open(path, "wb", mtime=0) as stream:
        for offset in range(0, len(payload), 10):
            await stream.write(payload[offset : offset + 10])
    return path.read_bytes()


def _profile_sync(method: Callable[[], bytes]) -> tuple[float, bytes, cProfile.Profile]:
    profile = cProfile.Profile()
    started = time.perf_counter()
    result = profile.runcall(method)
    return time.perf_counter() - started, result, profile


def _profile_async(
    runner: asyncio.Runner,
    method: Callable[[], Awaitable[bytes]],
) -> tuple[float, bytes, cProfile.Profile]:
    profile = cProfile.Profile()
    started = time.perf_counter()
    result = profile.runcall(runner.run, method())
    return time.perf_counter() - started, result, profile


def _matches(filename: str, function: str, category: str) -> bool:
    basename = Path(filename).name
    if category == "input_normalization":
        return function in {"_snapshot_bytes_input", "_coerce_byteslike"}
    if category == "operation_allocation":
        return basename == "codec.py" and function == "_reserve"
    if category == "operation_next":
        return basename == "codec.py" and function == "__next__"
    if category == "engine_compression":
        return "compress" in function and (
            filename == "~" or "zlib" in filename.lower()
        )
    if category == "crc":
        return "crc32" in function
    if category == "output_slicing":
        return basename == "codec.py" and function in {"_feed", "_output_chunks"}
    if category == "async_driver":
        return basename == "_codec_async.py" and function in {
            "_drive_operation",
            "_offloaded_next",
            "_raw_next_or_done",
            "_run_in_thread",
        }
    if category == "sink_writes":
        return basename == "_binary.py" and function == "_write_all"
    if category == "event_loop":
        return basename in {"base_events.py", "events.py"} and function in {
            "_run_once",
            "_run",
            "run_forever",
            "run_until_complete",
        }
    return False


def _profile_summary(profile: cProfile.Profile) -> dict[str, Any]:
    stats = pstats.Stats(profile).stats
    rows = []
    for (filename, line, function), values in stats.items():
        primitive_calls, total_calls, self_time, cumulative_time, _callers = values
        rows.append(
            {
                "file": filename,
                "line": line,
                "function": function,
                "primitive_calls": primitive_calls,
                "total_calls": total_calls,
                "self_seconds": self_time,
                "cumulative_seconds": cumulative_time,
            }
        )

    categories = {}
    for category in (
        "input_normalization",
        "operation_allocation",
        "operation_next",
        "engine_compression",
        "crc",
        "output_slicing",
        "async_driver",
        "sink_writes",
        "event_loop",
    ):
        matching = [
            row for row in rows if _matches(row["file"], row["function"], category)
        ]
        categories[category] = {
            "primitive_calls": sum(row["primitive_calls"] for row in matching),
            "total_calls": sum(row["total_calls"] for row in matching),
            "self_seconds": sum(row["self_seconds"] for row in matching),
            "cumulative_seconds": sum(row["cumulative_seconds"] for row in matching),
            "matches": [
                f"{Path(row['file']).name}:{row['line']}:{row['function']}"
                for row in matching
            ],
        }

    return {
        "categories": categories,
        "top_by_cumulative": sorted(
            rows,
            key=lambda row: row["cumulative_seconds"],
            reverse=True,
        )[:40],
        "top_by_self": sorted(
            rows,
            key=lambda row: row["self_seconds"],
            reverse=True,
        )[:40],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_case(
    name: str,
    duration: float,
    compressed: bytes,
    payload: bytes,
    profile: cProfile.Profile,
) -> dict[str, Any]:
    assert gzip.decompress(compressed) == payload
    return {
        "name": name,
        "duration_seconds": duration,
        "compressed_bytes": len(compressed),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "profile": _profile_summary(profile),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-fast", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.include_fast and not _engine.have_fast_engine():
        parser.error("--include-fast requires the zlib-ng engine")

    fixture = _fixture(8)
    cases = []
    direct_cases = (
        ("64K-in 64K-out", 64 * _KIB, 64 * _KIB),
        ("512K-in 256K-out", 512 * _KIB, 256 * _KIB),
    )
    for label, input_size, output_size in direct_cases:
        items = _split_exact(fixture.payload, input_size)
        duration, compressed, profile = _profile_sync(
            lambda items=items, output_size=output_size: _direct_compress(
                items,
                output_chunk_size=output_size,
                fast_compress=False,
            )
        )
        cases.append(
            _record_case(
                f"direct stdlib {label}",
                duration,
                compressed,
                fixture.payload,
                profile,
            )
        )

    with asyncio.Runner() as runner:
        for label, input_size, output_size in direct_cases:
            items = _split_exact(fixture.payload, input_size)
            duration, compressed, profile = _profile_async(
                runner,
                lambda items=items, output_size=output_size: _stream_compress(
                    items,
                    output_chunk_size=output_size,
                    fast_compress=False,
                ),
            )
            cases.append(
                _record_case(
                    f"async stdlib {label}",
                    duration,
                    compressed,
                    fixture.payload,
                    profile,
                )
            )

        if args.include_fast:
            items = _split_exact(fixture.payload, 512 * _KIB)
            duration, compressed, profile = _profile_sync(
                lambda: _direct_compress(
                    items,
                    output_chunk_size=256 * _KIB,
                    fast_compress=True,
                )
            )
            cases.append(
                _record_case(
                    "direct zlib-ng 512K-in 256K-out",
                    duration,
                    compressed,
                    fixture.payload,
                    profile,
                )
            )
            duration, compressed, profile = _profile_async(
                runner,
                lambda: _stream_compress(
                    items,
                    output_chunk_size=256 * _KIB,
                    fast_compress=True,
                ),
            )
            cases.append(
                _record_case(
                    "async zlib-ng 512K-in 256K-out",
                    duration,
                    compressed,
                    fixture.payload,
                    profile,
                )
            )

        with TemporaryDirectory(prefix="aiogzip-wp6-") as directory:
            path = Path(directory) / "tiny-writes.gz"
            duration, compressed, profile = _profile_async(
                runner,
                lambda: _tiny_file_write(fixture.payload, path),
            )
            cases.append(
                _record_case(
                    "binary writer 10-byte chunks",
                    duration,
                    compressed,
                    fixture.payload,
                    profile,
                )
            )

    record = {
        "kind": "compression-profile",
        "engine_info": asdict(aiogzip.engine_info()),
        "python": sys.version,
        "target_commit": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "target_dirty": bool(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
        "environment_label": (
            "Apple M3 MacBook Air (provisional; rerun release gates on "
            "Framework Desktop)"
        ),
        "fixture": {
            "bytes": len(fixture.payload),
            "sha256": fixture.payload_sha256,
            "tiny_write_bytes": 10,
        },
        "file_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in (
                "benchmarks/profile_compression_paths.py",
                "src/aiogzip/_binary.py",
                "src/aiogzip/_codec_async.py",
                "src/aiogzip/codec.py",
            )
        },
        "profile_notes": (
            "Category times are cProfile aggregates and are not additive. "
            "Direct cases capture engine work; executor work is outside the "
            "main-thread async profile."
        ),
        "cases": cases,
    }
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
