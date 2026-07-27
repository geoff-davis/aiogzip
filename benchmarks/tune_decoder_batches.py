#!/usr/bin/env python3
"""Compare private decoder window and batch candidates."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import statistics
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from bench_codec_regressions import (
    _KIB,
    _MIB,
    _counting_decompressors,
    _deterministic_bytes,
    _digest_direct,
    _digest_stream,
    _fixture,
    _split_exact,
)

import aiogzip
import aiogzip.codec as codec_module

ROOT = Path(__file__).resolve().parents[1]
INPUT_CANDIDATES = (64 * _KIB, 256 * _KIB, 512 * _KIB)
OUTPUT_CANDIDATES = (64 * _KIB, 256 * _KIB, 512 * _KIB, _MIB)


def _timed(call: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = call()
    return time.perf_counter() - started, result


def _timed_async(
    runner: asyncio.Runner,
    call: Callable[[], Awaitable[Any]],
) -> tuple[float, Any]:
    started = time.perf_counter()
    result = runner.run(call())
    return time.perf_counter() - started, result


def _limit_probe(wire: bytes, expected: bytes, limit: int) -> tuple[int, str]:
    decoder = aiogzip.GzipDecoder(
        output_chunk_size=64 * _KIB,
        max_decompressed_size=limit,
    )
    digest = hashlib.sha256()
    output_bytes = 0
    try:
        for chunk in decoder.feed(wire):
            digest.update(chunk)
            output_bytes += len(chunk)
    except OSError:
        pass
    else:
        raise AssertionError("over-limit fixture did not fail")
    assert output_bytes == limit
    assert digest.digest() == hashlib.sha256(expected[:limit]).digest()
    assert decoder.uncompressed_size == limit
    return output_bytes, digest.hexdigest()


def _add_sample(
    samples: dict[tuple[int, str], list[dict[str, Any]]],
    candidate: int,
    case: str,
    duration: float,
    **metrics: Any,
) -> None:
    samples.setdefault((candidate, case), []).append({"duration": duration, **metrics})


def _run_input_tuning(repeat: int) -> list[dict[str, Any]]:
    with asyncio.Runner() as runner:
        return _run_input_tuning_with_runner(repeat, runner)


def _run_input_tuning_with_runner(
    repeat: int,
    runner: asyncio.Runner,
) -> list[dict[str, Any]]:
    fixtures = {size: _fixture(size) for size in (8, 16, 32, 64)}
    streaming_fixture = fixtures[8]
    samples: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for repetition in range(repeat):
        ordered = (
            INPUT_CANDIDATES[repetition % len(INPUT_CANDIDATES) :]
            + INPUT_CANDIDATES[: repetition % len(INPUT_CANDIDATES)]
        )
        for candidate in ordered:
            codec_module._INFLATE_INPUT_WINDOW = candidate
            codec_module._INFLATE_OUTPUT_BATCH = 256 * _KIB
            for size, fixture in fixtures.items():
                duration, result = _timed(
                    lambda fixture=fixture: _digest_direct(
                        (fixture.compressed,),
                        output_chunk_size=256 * _KIB,
                    )
                )
                output_bytes, digest, chunks, maximum = result
                assert output_bytes == len(fixture.payload)
                assert digest == fixture.payload_sha256
                _add_sample(
                    samples,
                    candidate,
                    f"direct one-feed {size}MiB",
                    duration,
                    output_chunks=chunks,
                    max_output_chunk=maximum,
                )
                if size >= 32:
                    items = _split_exact(fixture.compressed, 256 * _KIB)
                    duration, result = _timed(
                        lambda items=items: _digest_direct(
                            items,
                            output_chunk_size=256 * _KIB,
                        )
                    )
                    output_bytes, digest, chunks, maximum = result
                    assert output_bytes == len(fixture.payload)
                    assert digest == fixture.payload_sha256
                    _add_sample(
                        samples,
                        candidate,
                        f"direct 256K-feeds {size}MiB",
                        duration,
                        output_chunks=chunks,
                        max_output_chunk=maximum,
                    )

            items = _split_exact(streaming_fixture.compressed, 512 * _KIB)
            duration, result = _timed_async(
                runner,
                lambda items=items: _digest_stream(items, output_chunk_size=256 * _KIB),
            )
            output_bytes, digest, chunks, maximum = result
            assert output_bytes == len(streaming_fixture.payload)
            assert digest == streaming_fixture.payload_sha256
            _add_sample(
                samples,
                candidate,
                "decompress_chunks 512K-in 256K-out",
                duration,
                output_chunks=chunks,
                max_output_chunk=maximum,
            )
    return _aggregate(samples)


def _run_output_tuning(repeat: int) -> list[dict[str, Any]]:
    direct = _fixture(8)
    tiny_payload = _deterministic_bytes(128 * _KIB, label=b"output-tuning")
    tiny_wire = gzip.compress(tiny_payload, compresslevel=6, mtime=0)
    limit_payload = _deterministic_bytes(_MIB, label=b"limit-tuning")
    limit_wire = gzip.compress(limit_payload, compresslevel=6, mtime=0)
    limit = len(limit_payload) // 2
    samples: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for repetition in range(repeat):
        ordered = (
            OUTPUT_CANDIDATES[repetition % len(OUTPUT_CANDIDATES) :]
            + OUTPUT_CANDIDATES[: repetition % len(OUTPUT_CANDIDATES)]
        )
        for candidate in ordered:
            codec_module._INFLATE_INPUT_WINDOW = 256 * _KIB
            codec_module._INFLATE_OUTPUT_BATCH = candidate

            duration, result = _timed(
                lambda: _digest_direct(
                    (direct.compressed,),
                    output_chunk_size=256 * _KIB,
                )
            )
            output_bytes, digest, chunks, maximum = result
            assert output_bytes == len(direct.payload)
            assert digest == direct.payload_sha256
            _add_sample(
                samples,
                candidate,
                "direct one-feed 8MiB",
                duration,
                output_chunks=chunks,
                max_output_chunk=maximum,
            )

            with _counting_decompressors() as engines:
                duration, result = _timed(
                    lambda: _digest_direct((tiny_wire,), output_chunk_size=1)
                )
            output_bytes, digest, chunks, maximum = result
            assert output_bytes == len(tiny_payload)
            assert digest == hashlib.sha256(tiny_payload).hexdigest()
            _add_sample(
                samples,
                candidate,
                "tiny public output 128KiB",
                duration,
                engine_calls=sum(engine.decompress_calls for engine in engines),
                output_chunks=chunks,
                max_output_chunk=maximum,
            )

            duration, result = _timed(
                lambda: _limit_probe(limit_wire, limit_payload, limit)
            )
            _add_sample(
                samples,
                candidate,
                "exact-limit then overflow 1MiB",
                duration,
                output_bytes=result[0],
                output_sha256=result[1],
            )
    return _aggregate(samples)


def _aggregate(
    samples: dict[tuple[int, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    results = []
    for (candidate, case), runs in sorted(samples.items()):
        durations = [run["duration"] for run in runs]
        median = statistics.median(durations)
        representative = min(runs, key=lambda run: abs(run["duration"] - median))
        metrics = {
            key: value for key, value in representative.items() if key != "duration"
        }
        results.append(
            {
                "candidate_bytes": candidate,
                "case": case,
                "duration_samples": durations,
                "median_seconds": median,
                "median_absolute_deviation": statistics.median(
                    abs(duration - median) for duration in durations
                ),
                "metrics": metrics,
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("input", "output"), required=True)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be positive")

    results = (
        _run_input_tuning(args.repeat)
        if args.kind == "input"
        else _run_output_tuning(args.repeat)
    )
    record = {
        "kind": args.kind,
        "repeat": args.repeat,
        "engine": aiogzip.engine_info().decompression,
        "python": __import__("sys").version,
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
        "file_sha256": {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in (
                "benchmarks/tune_decoder_batches.py",
                "src/aiogzip/_codec_buffer.py",
                "src/aiogzip/_engine.py",
                "src/aiogzip/codec.py",
            )
        },
        "environment_label": (
            "Apple M3 MacBook Air (provisional; rerun release gates on "
            "Framework Desktop)"
        ),
        "results": results,
    }
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
