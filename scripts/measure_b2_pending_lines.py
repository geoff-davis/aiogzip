"""Measure WP4 public pending-line scaling and batching on an explicit checkout."""

import argparse
import asyncio
import dataclasses
import gzip
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8"
    ).strip()


async def measure(args):
    root = args.source_root.resolve()
    if git(root, "status", "--porcelain"):
        raise RuntimeError("source checkout must be clean")
    sys.path.insert(0, str(root / "src"))
    os.environ["AIOGZIP_ENGINE"] = args.engine
    import aiogzip
    from aiogzip import AsyncGzipTextFile, engine_info

    if not Path(aiogzip.__file__).resolve().is_relative_to(root / "src"):
        raise RuntimeError("wrong source import")
    engines = dataclasses.asdict(engine_info())
    expected_engine = "stdlib-zlib" if args.engine == "stdlib" else "zlib-ng"
    if engines["decompression"] != expected_engine:
        raise RuntimeError("requested engine unavailable")
    harness = Path(__file__).resolve().parents[1]
    if git(harness, "status", "--porcelain"):
        raise RuntimeError("harness checkout must be clean")

    rows = []
    cases = (
        [(n, hint, False) for n in (2048, 4096, 8192, 16384, 32768) for hint in (1, 17)]
        if args.category == "scaling"
        else [
            (200000, hint, batch)
            for hint, batch in (
                (1 << 20, True),
                (1 << 20, False),
                (8192, False),
                (-1, False),
            )
        ]
    )
    with tempfile.TemporaryDirectory(prefix="aiogzip-wp4-bench-") as directory:
        path = Path(directory) / "input.gz"
        for count, hint, batching in cases:
            lines = (
                ["x\n"] * count
                if args.category == "scaling"
                else [
                    json.dumps(
                        {
                            "id": i if args.payload == "varied" else 0,
                            "message": "αβ" * 32,
                        }
                    )
                    + "\n"
                    for i in range(count)
                ]
            )
            payload = "".join(lines)
            path.write_bytes(gzip.compress(payload.encode(), mtime=0))
            durations = []
            for _ in range(args.repeat):
                output = []
                async with AsyncGzipTextFile(
                    path, "rt", newline="\n", chunk_size=args.chunk_size
                ) as reader:
                    started = time.perf_counter()
                    if batching:
                        async for batch in reader.iter_batches():
                            output.extend(batch)
                    else:
                        while batch := await reader.readlines(hint):
                            output.extend(batch)
                    durations.append(time.perf_counter() - started)
                if output != lines:
                    raise AssertionError("public results differ")
            rows.append(
                dict(
                    lines=count,
                    chunk_size=args.chunk_size,
                    payload=args.payload,
                    hint=hint,
                    iter_batches=batching,
                    seconds=durations,
                    minimum=min(durations),
                    median=statistics.median(durations),
                    sha256=hashlib.sha256(payload.encode()).hexdigest(),
                )
            )
    return dict(
        source=str(root),
        commit=git(root, "rev-parse", "HEAD"),
        harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        python=sys.version,
        engine=engines,
        harness_commit=git(harness, "rev-parse", "HEAD"),
        load=os.getloadavg(),
        affinity=sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        rows=rows,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--category", choices=("scaling", "bulk"), required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=256 * 1024)
    parser.add_argument("--payload", choices=("varied", "repetitive"), default="varied")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(measure(args))
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, ensure_ascii=False)
        output.write("\n")
