#!/usr/bin/env python3
"""Paired WP1 driver latency/throughput; clean source and harness required."""

import argparse
import asyncio
import dataclasses
import gzip
import hashlib
import json
import os
import platform
import statistics
import sys
import threading
import time
from pathlib import Path

from capture_file_state_trace import git_metadata


def summary(samples):
    median = statistics.median(samples)
    return {
        "seconds": samples,
        "median_seconds": median,
        "mad_seconds": statistics.median(abs(value - median) for value in samples),
    }


async def measure(package, repeats):
    from aiogzip import _codec_async as driver

    async def collect(operation, workload=b""):
        return b"".join(
            [
                part
                async for part in driver._drive_operation(operation, workload=workload)
            ]
        )

    async def encode(payload):
        encoder = package.GzipEncoder(mtime=0)
        return (
            await collect(encoder.start())
            + await collect(encoder.feed(payload), payload)
            + await collect(encoder.finish())
        )

    async def decode(wire):
        decoder = package.GzipDecoder()
        return await collect(decoder.feed(wire), wire) + await collect(decoder.finish())

    rows = []
    for size in (16 * 1024, 256 * 1024, 1024 * 1024, 4 * 1024 * 1024):
        payload = hashlib.shake_256(b"WP1 native settlement fixture").digest(size)
        wire = gzip.compress(payload, mtime=0)
        for name, function, data, expected in (
            ("encode", encode, payload, payload),
            ("decode", decode, wire, payload),
        ):
            await function(data)  # Warm executor and engine outside samples.
            samples = []
            for _ in range(repeats):
                start = time.perf_counter()
                result = await function(data)
                samples.append(time.perf_counter() - start)
                assert (
                    gzip.decompress(result) if name == "encode" else result
                ) == expected
            row = {
                "case": name,
                "payload_bytes": size,
                "fixture_sha256": hashlib.sha256(data).hexdigest(),
                **summary(samples),
            }
            row["median_mib_per_second"] = size / 1024**2 / row["median_seconds"]
            rows.append(row)

    class OneStep:
        def _advance_raw(self):
            raise StopIteration

        def close(self):
            raise AssertionError("completed operation must not be abandoned")

    # Amortize timer noise without hiding the individual batch samples.
    iterations = 200
    await collect(OneStep(), b"x" * driver._ZLIB_OFFLOAD_THRESHOLD)
    samples = []
    workload = b"x" * driver._ZLIB_OFFLOAD_THRESHOLD
    for _ in range(repeats):
        start = time.perf_counter()
        for _ in range(iterations):
            await collect(OneStep(), workload)
        samples.append((time.perf_counter() - start) / iterations)
    rows.append(
        {"case": "executor-step-latency", "iterations": iterations, **summary(samples)}
    )
    # Separate instrumented latency probe: cancel the caller and release a real
    # native encoder together. Both revisions safely settle caller-only cancel.
    payload = hashlib.shake_256(b"WP1 cancellation fixture").digest(350_000)
    samples = []
    original_advance = driver._raw_next_or_done
    loop = asyncio.get_running_loop()
    for _ in range(repeats):
        entered = asyncio.Event()
        release = threading.Event()

        def gated(operation, workload, entered=entered, release=release):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("cancellation benchmark watchdog expired")
            return original_advance(operation, workload)

        encoder = package.GzipEncoder(mtime=0)
        list(encoder.start())
        stream = driver._drive_operation(encoder.feed(payload), workload=payload)
        driver._raw_next_or_done = gated
        caller = asyncio.create_task(anext(stream))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            start = time.perf_counter()
            caller.cancel()
            release.set()
            try:
                await caller
            except asyncio.CancelledError:
                samples.append(time.perf_counter() - start)
            else:
                raise AssertionError("cancellation was lost")
        finally:
            release.set()
            await asyncio.gather(caller, return_exceptions=True)
            await stream.aclose()
            driver._raw_next_or_done = original_advance
    rows.append(
        {
            "case": "caller-cancel-to-settlement",
            "fixture_sha256": hashlib.sha256(payload).hexdigest(),
            "method": "Instrumented native entry gate; elapsed from caller cancellation and gate release through actual encode and cleanup; excludes gated waiting.",
            **summary(samples),
        }
    )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("at least three samples are required")
    source = git_metadata(args.source_root.resolve())
    harness = git_metadata(Path(__file__).resolve().parents[1])
    if not source["sha"] or not harness["sha"] or source["status"] or harness["status"]:
        parser.error("source and harness must be clean committed trees")
    os.environ["AIOGZIP_ENGINE"] = args.engine
    sys.path.insert(0, str(args.source_root.resolve() / "src"))
    import aiogzip

    record = {
        "source": source,
        "harness": harness,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "engine_request": args.engine,
        "engines": dataclasses.asdict(aiogzip.engine_info()),
        "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None,
        "method": "Warmup per case; fixture generation and validation outside timing; sequential uninstrumented samples; default compression policy unchanged; shared host, no release gate claim.",
        "rows": asyncio.run(measure(aiogzip, args.repeats)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
