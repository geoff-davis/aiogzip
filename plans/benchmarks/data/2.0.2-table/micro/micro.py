"""Pinned micro-test for the two cases flagged in the 2.0.2 table refresh.

Run with PYTHONPATH=<source root>/src. Prints one JSON line of timings in ms.
Fixtures are the ones benchmarks/bench_io.py builds at --size 8.
"""

import asyncio
import gzip
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

import aiogzip
from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

N = 8 * 1024 * 1024
ITER = int(sys.argv[1]) if len(sys.argv) > 1 else 300


def summary(times):
    times = sorted(times)
    return {
        "min": times[0] * 1e3,
        "p10": times[len(times) // 10] * 1e3,
        "median": statistics.median(times) * 1e3,
    }


async def main():
    out = {"file": aiogzip.__file__, "version": aiogzip.__version__}
    info = getattr(aiogzip, "engine_info", None)
    out["engine"] = str(info()) if info else "n/a"
    with tempfile.TemporaryDirectory() as tmp:
        payload = b"A" * N
        fixture = Path(tmp) / "readall.gz"
        fixture.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))
        text_path = Path(tmp) / "text.gz"
        async with AsyncGzipTextFile(text_path, "wt") as f:
            await f.write("x" * N)
        for _ in range(20):  # warm-up
            async with AsyncGzipBinaryFile(fixture, "rb", chunk_size=512 * 1024) as f:
                await f.read()
        t = []
        for _ in range(ITER):
            start = time.perf_counter()
            async with AsyncGzipBinaryFile(fixture, "rb", chunk_size=512 * 1024) as f:
                result = await f.read()
            t.append(time.perf_counter() - start)
        assert result == payload
        out["read_all"] = summary(t)
        t = []
        for _ in range(ITER):
            start = time.perf_counter()
            async with AsyncGzipTextFile(text_path, "rt", chunk_size=64 * 1024) as f:
                result = await f.read(N)
            t.append(time.perf_counter() - start)
        assert len(result) == N
        out["text_sized_read"] = summary(t)
        t = []
        for _ in range(ITER):
            start = time.perf_counter()
            async with AsyncGzipTextFile(text_path, "rt", chunk_size=64 * 1024) as f:
                result = await f.readline()
            t.append(time.perf_counter() - start)
        assert len(result) == N
        out["text_long_line"] = summary(t)
    print(json.dumps(out))


asyncio.run(main())
