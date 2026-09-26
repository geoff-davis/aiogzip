#!/usr/bin/env python3
"""G08 throughput and scheduling observations; run in interleaved clean checkouts.

Throughput excludes the ticker and fixture construction. Latency runs include a
sleep(0) sibling and report the final gap even when the source starves it entirely.
Neither observed wall-clock gaps nor these fixtures establish a preemption bound.
"""

import argparse
import asyncio
import dataclasses
import gzip
import hashlib
import json
import os
import platform
import random
import statistics
import sys
import time
from importlib.metadata import version
from pathlib import Path

from capture_file_state_trace import git_metadata


async def sample(package, items, payload, *, compress, fast, ticker):
    fetched = 0
    observations = []
    done = False

    async def source():
        nonlocal fetched
        for item in items:
            fetched += 1
            yield item

    async def sibling():
        while not done:
            observations.append((time.perf_counter(), fetched))
            await asyncio.sleep(0)

    wrapper = (
        package.compress_chunks(source(), mtime=0, fast_compress=fast)
        if compress
        else package.decompress_chunks(source())
    )
    task = asyncio.create_task(sibling()) if ticker else None
    started = time.perf_counter()
    try:
        chunks = [chunk async for chunk in wrapper]
        ended = time.perf_counter()
    finally:
        done = True
        if task is not None:
            await task
    # Joining and complete content validation are outside the timed region.
    result = b"".join(chunks)
    assert (gzip.decompress(result) if compress else result) == payload
    stamps = [started, *(stamp for stamp, _ in observations), ended]
    gaps = sorted(b - a for a, b in zip(stamps, stamps[1:], strict=False))
    return {
        "seconds": ended - started,
        "source_items": fetched,
        "ticks": len(observations),
        "ticks_before_final_item": sum(n < len(items) for _, n in observations),
        "max_gap_seconds": max(gaps) if ticker else None,
        "p99_gap_seconds": gaps[min(len(gaps) - 1, int(len(gaps) * 0.99))]
        if ticker
        else None,
        "max_items_between_ticks": max(
            b - a
            for a, b in zip(
                [0, *(n for _, n in observations)],
                [*(n for _, n in observations), fetched],
                strict=True,
            )
        )
        if ticker
        else None,
        "output_chunks": len(chunks),
        "output_bytes": len(result),
    }


async def run(package, *, repeat, fast, size, fixture):
    line = b'{"id":123,"message":"representative repeated JSONL text","ok":true}\n'
    payload = (
        random.Random(20260927).randbytes(size)
        if fixture == "random"
        else (line * (size // len(line) + 1))[:size]
    )
    wire = gzip.compress(payload, mtime=0)
    cases = []
    for compress in (True, False):
        data = payload if compress else wire
        for chunk_size in (64, 4096, 65536, 1024 * 1024):
            items = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
            cases.append((f"throughput-{chunk_size}", compress, items, payload, False))
        small = b"x" * 4096
        small_wire = gzip.compress(small, mtime=0)
        cases.append(
            (
                "latency-empty",
                compress,
                [b""] * 20000 + [small if compress else small_wire],
                small,
                True,
            )
        )
        tiny_payload = small if compress else bytes(range(256)) * 32
        tiny_data = tiny_payload if compress else gzip.compress(tiny_payload, mtime=0)
        cases.append(
            (
                "latency-tiny",
                compress,
                [tiny_data[i : i + 1] for i in range(len(tiny_data))],
                tiny_payload,
                True,
            )
        )
        cases.append(("latency-large", compress, [data], payload, True))
    cases.append(
        (
            "latency-empty-members",
            False,
            [gzip.compress(b"", mtime=0)] * 20000 + [gzip.compress(b"x", mtime=0)],
            b"x",
            True,
        )
    )
    rows = []
    for name, compress, items, expected, ticker in cases:
        samples = [
            await sample(
                package, items, expected, compress=compress, fast=fast, ticker=ticker
            )
            for _ in range(repeat)
        ]
        seconds = [s["seconds"] for s in samples]
        row = {
            "case": name,
            "fixture": fixture,
            "direction": "compress" if compress else "decompress",
            "payload_sha256": hashlib.sha256(expected).hexdigest(),
            "input_sha256": hashlib.sha256(b"".join(items)).hexdigest(),
            "samples": samples,
            "min_seconds": min(seconds),
            "median_seconds": statistics.median(seconds),
        }
        rows.append(row)
        print(f"{name} {row['direction']}: {row['min_seconds']:.6f}s", flush=True)
    return rows


async def run_all(package, **kwargs):
    rows = []
    for fixture in ("random", "text"):
        rows.extend(await run(package, fixture=fixture, **kwargs))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1 or args.size < 1:
        parser.error("repeat and size must be positive")
    root, harness = args.source_root.resolve(), Path(__file__).resolve()
    provenance = {
        "source": git_metadata(root),
        "harness": git_metadata(harness.parents[1]),
    }
    if any(m["sha"] is None or m["status"] != "" for m in provenance.values()):
        raise RuntimeError(
            f"source and harness must be committed and clean: {provenance}"
        )
    os.environ["AIOGZIP_ENGINE"] = args.engine
    sys.path.insert(0, str(root / "src"))
    import aiogzip

    origin = Path(aiogzip.__file__).resolve()
    assert origin.is_relative_to(root / "src"), origin
    engines = dataclasses.asdict(aiogzip.engine_info())
    assert engines["decompression"] == (
        "stdlib-zlib" if args.engine == "stdlib" else "zlib-ng"
    )
    encoder = aiogzip.GzipEncoder(fast_compress=args.engine == "zlib-ng")
    compression_module = type(encoder._engine).__module__
    encoder.discard()
    assert compression_module == (
        "zlib" if args.engine == "stdlib" else "zlib_ng.zlib_ng"
    ), compression_module
    record = {
        **provenance,
        "import": str(origin),
        "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "aiofiles": version("aiofiles"),
        "engines": engines,
        "compression_engine_module": compression_module,
        "fast_compress": args.engine == "zlib-ng",
        "affinity": sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        "load_start": os.getloadavg() if hasattr(os, "getloadavg") else None,
        "command": sys.argv,
        "limitations": "Fixture/open-loop construction and output join/validation excluded. Output chunks retained during timing. Ticker only in latency cases. Consecutive repeats; compare interleaved process captures including baseline drift. Observations are not scheduling guarantees or G17 qualification.",
        "rows": asyncio.run(
            run_all(
                aiogzip,
                repeat=args.repeat,
                fast=args.engine == "zlib-ng",
                size=args.size,
            )
        ),
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
