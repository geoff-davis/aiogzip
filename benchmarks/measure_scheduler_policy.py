#!/usr/bin/env python3
"""Record private scheduler progress for the adversarial DEFLATE fixture."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from bench_codec_regressions import (
    _counting_decompressors,
    _digest_stream,
    _empty_block_gzip,
    _fixture,
    _percentile,
    _split_exact,
)

import aiogzip
from aiogzip import _codec_async
from aiogzip._codec_async import _drive_operation
from aiogzip.codec import _CodecProgress

ROOT = Path(__file__).resolve().parents[1]
_KIB = 1024


class _CountingOperation:
    """Count private progress while preserving the operation protocol."""

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.progress_events = 0
        self.progress_bytes = 0

    def __iter__(self) -> _CountingOperation:
        return self

    def __next__(self) -> bytes:
        return next(self._wrapped)

    def _advance_raw(self) -> bytes | _CodecProgress:
        result = self._wrapped._advance_raw()
        if isinstance(result, _CodecProgress):
            self.progress_events += 1
            self.progress_bytes += result.compressed_bytes
        return result

    def close(self) -> None:
        self._wrapped.close()


async def _measure(wire: bytes, expected: bytes) -> dict[str, Any]:
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
    decoder = aiogzip.GzipDecoder()
    operation = _CountingOperation(decoder.feed(wire))
    digest = hashlib.sha256()
    output_bytes = 0
    output_chunks = 0
    empty_output_chunks = 0
    with _counting_decompressors() as engines:
        started = time.perf_counter()
        async for output in _drive_operation(operation, workload=wire):
            output_chunks += 1
            empty_output_chunks += not output
            output_bytes += len(output)
            digest.update(output)
        finish = _CountingOperation(decoder.finish())
        async for output in _drive_operation(finish):
            output_chunks += 1
            empty_output_chunks += not output
            output_bytes += len(output)
            digest.update(output)
        duration = time.perf_counter() - started
    stop = True
    await task
    gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:], strict=False)]
    assert output_bytes == len(expected)
    assert digest.digest() == hashlib.sha256(expected).digest()
    assert empty_output_chunks == 0
    return {
        "duration_seconds": duration,
        "ticker_count": len(ticks),
        "ticker_gap_p50_seconds": _percentile(gaps, 0.50),
        "ticker_gap_p95_seconds": _percentile(gaps, 0.95),
        "ticker_gap_p99_seconds": _percentile(gaps, 0.99),
        "ticker_gap_max_seconds": max(gaps, default=0.0),
        "engine_calls": sum(engine.decompress_calls for engine in engines),
        "progress_events": operation.progress_events + finish.progress_events,
        "progress_bytes": operation.progress_bytes + finish.progress_bytes,
        "output_bytes": output_bytes,
        "output_chunks": output_chunks,
        "empty_output_chunks": empty_output_chunks,
        "output_sha256": digest.hexdigest(),
    }


async def _measure_checkpoint_cost(
    items: tuple[bytes, ...],
    *,
    checkpoint: Any,
    output_chunk_size: int,
) -> float:
    original = _codec_async._cooperative_checkpoint
    _codec_async._cooperative_checkpoint = checkpoint
    try:
        started = time.perf_counter()
        await _digest_stream(items, output_chunk_size=output_chunk_size)
        return time.perf_counter() - started
    finally:
        _codec_async._cooperative_checkpoint = original


def _duration_summary(samples: list[float]) -> dict[str, Any]:
    median = statistics.median(samples)
    return {
        "duration_median_seconds": median,
        "duration_mad_seconds": statistics.median(
            abs(duration - median) for duration in samples
        ),
        "duration_samples_seconds": samples,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=9)
    parser.add_argument("--empty-blocks", type=int, default=100_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    if args.empty_blocks <= 0:
        parser.error("--empty-blocks must be positive")

    wire, expected = _empty_block_gzip(args.empty_blocks)
    assert __import__("gzip").decompress(wire) == expected
    throughput_fixture = _fixture(8)
    throughput_cases = {
        "64K-in 64K-out": (
            _split_exact(throughput_fixture.compressed, 64 * _KIB),
            64 * _KIB,
        ),
        "512K-in 256K-out": (
            _split_exact(throughput_fixture.compressed, 512 * _KIB),
            256 * _KIB,
        ),
    }

    async def no_checkpoint() -> None:
        return None

    with asyncio.Runner() as runner:
        samples = [runner.run(_measure(wire, expected)) for _ in range(args.repeat)]
        checkpoint_samples: dict[str, dict[str, list[float]]] = {
            name: {"enabled": [], "disabled": []} for name in throughput_cases
        }
        for name, (throughput_items, output_chunk_size) in throughput_cases.items():
            for repetition in range(args.repeat * 2):
                key = "enabled" if repetition % 2 == 0 else "disabled"
                checkpoint = (
                    _codec_async._cooperative_checkpoint
                    if key == "enabled"
                    else no_checkpoint
                )
                checkpoint_samples[name][key].append(
                    runner.run(
                        _measure_checkpoint_cost(
                            throughput_items,
                            checkpoint=checkpoint,
                            output_chunk_size=output_chunk_size,
                        )
                    )
                )
    durations = [sample["duration_seconds"] for sample in samples]
    record = {
        "kind": "scheduler-policy",
        "repeat": args.repeat,
        "engine": aiogzip.engine_info().decompression,
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
            "empty_blocks": args.empty_blocks,
            "compressed_bytes": len(wire),
            "compressed_sha256": hashlib.sha256(wire).hexdigest(),
            "output_bytes": len(expected),
            "output_sha256": hashlib.sha256(expected).hexdigest(),
        },
        "thresholds": {
            "inline_output_bytes": 1024 * 1024,
            "inline_output_chunks": 4096,
            "no_output_bytes": 1024 * 1024,
            "no_output_steps": 8,
            "offload_bytes": 256 * 1024,
        },
        "file_sha256": {
            relative: _sha256(ROOT / relative)
            for relative in (
                "benchmarks/measure_scheduler_policy.py",
                "src/aiogzip/_codec_async.py",
                "src/aiogzip/_engine.py",
                "src/aiogzip/codec.py",
            )
        },
        "duration_median_seconds": statistics.median(durations),
        "duration_mad_seconds": statistics.median(
            abs(duration - statistics.median(durations)) for duration in durations
        ),
        "samples": samples,
        "checkpoint_cost": {
            "fixture_bytes": len(throughput_fixture.payload),
            "fixture_sha256": throughput_fixture.payload_sha256,
            "compressed_bytes": len(throughput_fixture.compressed),
            "compressed_sha256": throughput_fixture.compressed_sha256,
            "cases": {
                name: {
                    "source_items": len(throughput_items),
                    "source_item_bytes": len(throughput_items[0]),
                    "output_chunk_size": output_chunk_size,
                    "enabled": _duration_summary(checkpoint_samples[name]["enabled"]),
                    "disabled": _duration_summary(checkpoint_samples[name]["disabled"]),
                }
                for name, (throughput_items, output_chunk_size) in (
                    throughput_cases.items()
                )
            },
        },
    }
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
