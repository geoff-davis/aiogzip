#!/usr/bin/env python3
"""WP0 line-scaling baseline, with timing and work/allocation runs separated."""

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
import time
import tracemalloc
from pathlib import Path

from capture_file_state_trace import Source, git_metadata


async def sample(package, wire, expected, *, newline, encoding, hint, instrument):
    source = Source(wire)
    kwargs = {"newline": newline, "encoding": encoding, "chunk_size": 65536}
    async with package.AsyncGzipTextFile(
        None, "rt", fileobj=source, closefd=False, **kwargs
    ) as f:
        work = {"append_calls": 0, "growing_buffer_characters": 0}
        original = package.AsyncGzipTextFile._append_buffer

        def append(handle, text):
            if text:
                work["append_calls"] += 1
                work["growing_buffer_characters"] += len(handle._text_buffer) + len(
                    text
                )
            return original(handle, text)

        if instrument:
            package.AsyncGzipTextFile._append_buffer = append
            tracemalloc.start()
        try:
            started = time.perf_counter()
            if hint is None:
                output = await f.readline()
            else:
                batches = []
                while batch := await f.readlines(hint):
                    batches.extend(batch)
                output = "".join(batches)
            elapsed = time.perf_counter() - started
            peak = tracemalloc.get_traced_memory()[1] if instrument else None
        finally:
            if instrument:
                tracemalloc.stop()
                package.AsyncGzipTextFile._append_buffer = original
        assert output == expected
    return {"seconds": elapsed, "peak_python_bytes": peak, **work}


async def run(package, repeats):
    rows = []
    cases = [
        ("small-hint", n, "\n", "utf-8", hint)
        for n in (2048, 4096, 8192, 16384, 32768)
        for hint in (1, 32, -1)
    ]
    cases += [
        ("long-line", size, newline, encoding, None)
        for size in (1, 2, 4, 8, 16)
        for encoding in ("utf-8", "iso2022_jp")
        for newline in (None, "", "\n", "\r", "\r\n")
    ]
    for family, size, newline, encoding, hint in cases:
        expected = (
            "x\n" * size
            if family == "small-hint"
            else ("a" if encoding == "utf-8" else "日") * (size * 1024 * 1024)
        )
        wire = gzip.compress(expected.encode(encoding), mtime=0)
        fixture = hashlib.sha256(wire).hexdigest()
        samples = []
        for _ in range(repeats):
            samples.append(
                (
                    await sample(
                        package,
                        wire,
                        expected,
                        newline=newline,
                        encoding=encoding,
                        hint=hint,
                        instrument=False,
                    )
                )["seconds"]
            )
        instrumentation = await sample(
            package,
            wire,
            expected,
            newline=newline,
            encoding=encoding,
            hint=hint,
            instrument=True,
        )
        median = statistics.median(samples)
        row = {
            "family": family,
            "size": size,
            "newline": newline,
            "encoding": encoding,
            "hint": hint,
            "fixture_sha256": fixture,
            "compressed_bytes": len(wire),
            "logical_characters": len(expected),
            "seconds": samples,
            "median_seconds": median,
            "mad_seconds": statistics.median(abs(s - median) for s in samples),
            "instrumented": instrumentation,
        }
        rows.append(row)
        print(
            f"{family} size={size} newline={newline!r} encoding={encoding} hint={hint}: {median:.6f}s",
            flush=True,
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    root, harness = args.source_root.resolve(), Path(__file__).resolve()
    provenance = {
        "source": git_metadata(root),
        "harness": git_metadata(harness.parents[1]),
    }
    if any(meta["sha"] is None or meta["status"] != "" for meta in provenance.values()):
        raise RuntimeError(
            f"source and harness must be committed and clean: {provenance}"
        )
    os.environ["AIOGZIP_ENGINE"] = args.engine
    sys.path.insert(0, str(root / "src"))
    from importlib.metadata import version

    import aiogzip

    origin = Path(aiogzip.__file__).resolve()
    if not origin.is_relative_to(root / "src"):
        raise RuntimeError(f"wrong source import: {origin}")
    engines = dataclasses.asdict(aiogzip.engine_info())
    assert engines["decompression"] == (
        "stdlib-zlib" if args.engine == "stdlib" else "zlib-ng"
    )
    record = {
        **provenance,
        "import": str(origin),
        "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "engines": engines,
        "aiofiles": version("aiofiles"),
        "command": sys.argv,
        "repeat": args.repeat,
        "order": "size, encoding, newline; consecutive repeats, then instrumented sample",
        "limitations": "Single-host baseline, not a candidate speed claim. Fixtures/open and validation excluded from timings. Small-hint timings include result-list collection/join. Growing-buffer characters count lengths presented to concatenation, not measured allocator copies. Tracemalloc excludes native allocations. No long-line terminator; wider WP5 boundary/entropy/chunk-size matrix remains required.",
        "rows": asyncio.run(run(aiogzip, args.repeat)),
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
