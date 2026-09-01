#!/usr/bin/env python3
"""High-level integration supplement for the aiogzip 2.0.0a4 release.

The established a3 and codec-regression harnesses retain codec, scheduler,
header, member, streaming, and write-path rows. This supplement adds only the
three high-level rows absent from those harnesses: bounded JSONL batches, full
binary-read peak allocation, and concurrent independent-file throughput.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from bench_a3_regressions import (
    Sample,
    _aggregate,
    _positive_int,
    _sha256,
    collect_environment,
    configure_source_root,
)
from bench_common import ENGINE_CHOICES

SCHEMA_VERSION = 1
FIXTURE_GENERATOR_VERSION = "a4-supplement-fixtures-v1"
_KIB = 1024
_MIB = 1024 * 1024


def _deterministic_bytes(size: int, *, label: bytes) -> bytes:
    return hashlib.shake_256(b"aiogzip-a4:" + label).digest(size)


def _jsonl_fixture(target_bytes: int) -> bytes:
    rows: list[bytes] = []
    size = 0
    index = 0
    while size < target_bytes:
        row = (
            json.dumps(
                {
                    "id": index,
                    "kind": f"event-{index % 97:02d}",
                    "value": (index * 37) % 100_003,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        rows.append(row)
        size += len(row)
        index += 1
    return b"".join(rows)


async def _bounded_jsonl_once(
    aiogzip: Any,
    compressed_path: Path,
    *,
    batch_hint: int,
) -> Sample:
    digest = hashlib.sha256()
    output_bytes = 0
    line_count = 0
    batch_count = 0
    maximum_batch_chars = 0
    started = time.perf_counter()
    async with aiogzip.open(
        compressed_path,
        "rt",
        encoding="utf-8",
        errors="strict",
        newline="\n",
    ) as stream:
        async for batch in stream.iter_batches(hint=batch_hint):
            batch_count += 1
            batch_chars = sum(len(line) for line in batch)
            maximum_batch_chars = max(maximum_batch_chars, batch_chars)
            for line in batch:
                encoded = line.encode("utf-8")
                digest.update(encoded)
                output_bytes += len(encoded)
                line_count += 1
    duration = time.perf_counter() - started
    return Sample(
        duration,
        {
            "output_bytes": output_bytes,
            "output_sha256": digest.hexdigest(),
            "line_count": line_count,
            "batch_count": batch_count,
            "batch_hint_chars": batch_hint,
            "maximum_batch_chars": maximum_batch_chars,
            "source_read_count": "not instrumented: path-backed aiofiles source",
        },
    )


async def _full_binary_read_once(
    aiogzip: Any,
    compressed_path: Path,
    *,
    measure_memory: bool,
) -> Sample:
    if measure_memory:
        tracemalloc.start()
    try:
        started = time.perf_counter()
        async with aiogzip.open(compressed_path, "rb") as stream:
            output = await stream.read()
        duration = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1] if measure_memory else None
    finally:
        if measure_memory:
            tracemalloc.stop()
    return Sample(
        duration,
        {
            "output_bytes": len(output),
            "output_sha256": _sha256(output),
            "peak_python_bytes": peak,
            "source_read_count": "not instrumented: path-backed aiofiles source",
        },
    )


async def _concurrent_reads_once(
    aiogzip: Any,
    compressed_paths: tuple[Path, ...],
) -> Sample:
    active = 0
    maximum_active = 0

    async def read_one(path: Path) -> tuple[int, str]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            async with aiogzip.open(path, "rb") as stream:
                output = await stream.read()
            return len(output), _sha256(output)
        finally:
            active -= 1

    started = time.perf_counter()
    outputs = await asyncio.gather(*(read_one(path) for path in compressed_paths))
    duration = time.perf_counter() - started
    return Sample(
        duration,
        {
            "stream_count": len(compressed_paths),
            "maximum_active_handles": maximum_active,
            "output_bytes": sum(size for size, _ in outputs),
            "output_sha256_by_stream": [digest for _, digest in outputs],
            "source_read_count": "not instrumented: path-backed aiofiles sources",
        },
    )


async def run_benchmarks(args: argparse.Namespace) -> dict[str, Any]:
    runner_root = Path(__file__).resolve().parents[1]
    aiogzip, identity = configure_source_root(args.source_root, args.engine)
    results: list[dict[str, Any]] = []

    jsonl = _jsonl_fixture(args.jsonl_mib * _MIB)
    binary = _deterministic_bytes(
        args.binary_mib * _MIB,
        label=f"binary:{args.binary_mib}".encode(),
    )
    concurrent_payloads = tuple(
        _deterministic_bytes(
            args.concurrent_mib * _MIB,
            label=f"concurrent:{index}:{args.concurrent_mib}".encode(),
        )
        for index in range(args.concurrent_streams)
    )

    fixtures = {
        "jsonl": {
            "generator_version": FIXTURE_GENERATOR_VERSION,
            "payload_bytes": len(jsonl),
            "payload_sha256": _sha256(jsonl),
            "line_count": jsonl.count(b"\n"),
        },
        "binary": {
            "generator_version": FIXTURE_GENERATOR_VERSION,
            "payload_bytes": len(binary),
            "payload_sha256": _sha256(binary),
        },
        "concurrent": [
            {
                "generator_version": FIXTURE_GENERATOR_VERSION,
                "stream": index,
                "payload_bytes": len(payload),
                "payload_sha256": _sha256(payload),
            }
            for index, payload in enumerate(concurrent_payloads)
        ],
    }

    with tempfile.TemporaryDirectory(prefix="aiogzip-a4-bench-") as raw_temp:
        temp = Path(raw_temp)
        jsonl_path = temp / "events.jsonl.gz"
        jsonl_path.write_bytes(gzip.compress(jsonl, compresslevel=6, mtime=0))
        binary_path = temp / "binary.gz"
        binary_path.write_bytes(gzip.compress(binary, compresslevel=6, mtime=0))
        concurrent_paths = tuple(
            temp / f"stream-{index}.gz" for index in range(len(concurrent_payloads))
        )
        for path, payload in zip(concurrent_paths, concurrent_payloads, strict=True):
            path.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))

        jsonl_warm_up = await _bounded_jsonl_once(
            aiogzip,
            jsonl_path,
            batch_hint=args.batch_hint,
        )
        if (
            jsonl_warm_up.metrics["output_sha256"]
            != fixtures["jsonl"]["payload_sha256"]
        ):
            raise AssertionError("bounded JSONL warm-up output mismatch")
        print("  START bounded JSONL iter_batches", flush=True)
        jsonl_samples = [
            await _bounded_jsonl_once(
                aiogzip,
                jsonl_path,
                batch_hint=args.batch_hint,
            )
            for _ in range(args.repeat)
        ]
        for sample in jsonl_samples:
            if sample.metrics["output_sha256"] != fixtures["jsonl"]["payload_sha256"]:
                raise AssertionError("bounded JSONL output mismatch")
            if sample.metrics["line_count"] != fixtures["jsonl"]["line_count"]:
                raise AssertionError("bounded JSONL line-count mismatch")
        results.append(
            _aggregate("bounded JSONL iter_batches", "integration-jsonl", jsonl_samples)
        )

        binary_warm_up = await _full_binary_read_once(
            aiogzip,
            binary_path,
            measure_memory=False,
        )
        if (
            binary_warm_up.metrics["output_sha256"]
            != fixtures["binary"]["payload_sha256"]
        ):
            raise AssertionError("full binary-read warm-up output mismatch")
        print("  START full binary read throughput", flush=True)
        binary_samples = [
            await _full_binary_read_once(
                aiogzip,
                binary_path,
                measure_memory=False,
            )
            for _ in range(args.repeat)
        ]
        for sample in binary_samples:
            if sample.metrics["output_sha256"] != fixtures["binary"]["payload_sha256"]:
                raise AssertionError("full binary-read output mismatch")
        results.append(
            _aggregate(
                "full binary read throughput", "integration-memory", binary_samples
            )
        )
        print("  START full binary read peak allocation", flush=True)
        memory_sample = await _full_binary_read_once(
            aiogzip,
            binary_path,
            measure_memory=True,
        )
        if (
            memory_sample.metrics["output_sha256"]
            != fixtures["binary"]["payload_sha256"]
        ):
            raise AssertionError("full binary-read allocation output mismatch")
        results.append(
            _aggregate(
                "full binary read peak allocation",
                "integration-memory",
                [memory_sample],
            )
        )

        concurrent_warm_up = await _concurrent_reads_once(aiogzip, concurrent_paths)
        expected_digests = [item["payload_sha256"] for item in fixtures["concurrent"]]
        if concurrent_warm_up.metrics["output_sha256_by_stream"] != expected_digests:
            raise AssertionError("concurrent-read warm-up output mismatch")
        print("  START concurrent independent-file reads", flush=True)
        concurrent_samples = [
            await _concurrent_reads_once(aiogzip, concurrent_paths)
            for _ in range(args.repeat)
        ]
        for sample in concurrent_samples:
            if sample.metrics["output_sha256_by_stream"] != expected_digests:
                raise AssertionError("concurrent-read output mismatch")
            if sample.metrics["maximum_active_handles"] > args.concurrent_streams:
                raise AssertionError(
                    "concurrent handle accounting exceeded fixture count"
                )
        results.append(
            _aggregate(
                "concurrent independent-file reads",
                "integration-concurrency",
                concurrent_samples,
            )
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "aiogzip-2.0.0a4-integration-supplement",
        "created_at_unix": time.time(),
        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        "configuration": {
            "jsonl_mib": args.jsonl_mib,
            "binary_mib": args.binary_mib,
            "concurrent_mib": args.concurrent_mib,
            "concurrent_streams": args.concurrent_streams,
            "batch_hint": args.batch_hint,
            "repeat": args.repeat,
            "warm_up_policy": "one untimed verified run per throughput row",
            "ordering_policy": "fixed category order; no randomization",
            "garbage_collection_policy": "normal interpreter policy",
            "digest_policy": "incremental JSONL digest inside timed region; other digests after read",
        },
        "source": identity,
        "environment": collect_environment(
            args.source_root.resolve(), identity, runner_root
        ),
        "fixtures": fixtures,
        "results": results,
        "discarded_or_excluded_runs": [],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=ENGINE_CHOICES, required=True)
    parser.add_argument("--jsonl-mib", type=_positive_int, default=8)
    parser.add_argument("--binary-mib", type=_positive_int, default=16)
    parser.add_argument("--concurrent-mib", type=_positive_int, default=4)
    parser.add_argument("--concurrent-streams", type=_positive_int, default=4)
    parser.add_argument("--batch-hint", type=_positive_int, default=_MIB)
    parser.add_argument("--repeat", type=_positive_int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.repeat < 5 or args.repeat % 2 == 0:
        parser.error("--repeat must be an odd integer of at least 5")
    try:
        document = asyncio.run(run_benchmarks(args))
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
