#!/usr/bin/env python3
"""Record F6 read-ahead diagnostics without freezing current buffer behavior.

Use a committed harness and clean source checkout. These are single-run resource
observations, not paired performance evidence or timing gates. The compressible
fixture exercises inflation amplification; the random fixture spans source reads.
"""

import argparse
import asyncio
import dataclasses
import gzip
import hashlib
import io
import json
import os
import platform
import random
import sys
import time
import tracemalloc
from importlib.metadata import version
from pathlib import Path

from capture_file_state_trace import git_metadata


async def measure(package, compressible):
    size = 16 * 1024 * 1024
    payload = b"x" * size if compressible else random.Random(0).randbytes(size)
    wire = gzip.compress(payload, mtime=0)
    fixture_hash = hashlib.sha256(wire).hexdigest()
    payload_hash = hashlib.sha256(payload).hexdigest()
    chunk_size = package.AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE
    assert (len(wire) < chunk_size) if compressible else (len(wire) > chunk_size)

    class Source:
        def __init__(self):
            self.buffer = io.BytesIO(wire)
            self.reads = []

        async def read(self, size=-1):
            data = self.buffer.read(size)
            self.reads.append({"requested": size, "returned": len(data)})
            return data

    source = Source()
    async with package.AsyncGzipBinaryFile(
        None, "rb", fileobj=source, closefd=False
    ) as f:
        # Fixtures, compression, hashes, source buffer and open are outside measurement.
        tracemalloc.start()
        try:
            started = time.perf_counter()
            first = await f.read(1)
            elapsed = time.perf_counter() - started
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # Private state is diagnostic only, deliberately absent from test assertions.
        retained = len(f._buffer) - f._buffer_offset
        reads = list(source.reads)
        assert first == payload[:1]
        digest = hashlib.sha256(first)
        while chunk := await f.read(chunk_size):
            digest.update(chunk)
        assert digest.hexdigest() == payload_hash
    return {
        "fixture": "repeated-x" if compressible else "random-seed-0",
        "payload_bytes": size,
        "compressed_bytes": len(wire),
        "payload_sha256": payload_hash,
        "fixture_sha256": fixture_hash,
        "source_chunk_size": chunk_size,
        "requested": 1,
        "returned": len(first),
        "source_reads_during_call": reads,
        "compressed_bytes_fetched": sum(read["returned"] for read in reads),
        "retained_plaintext": retained,
        "tracemalloc_current": current,
        "tracemalloc_peak": peak,
        "first_result_seconds": elapsed,
        "round_trip_sha256_verified": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve()
    harness = Path(__file__).resolve()
    provenance = {
        "source": git_metadata(root),
        "harness": git_metadata(harness.parents[1]),
    }
    for label, metadata in provenance.items():
        if metadata["sha"] is None or metadata["status"] != "":
            raise RuntimeError(f"{label} must be committed and clean: {metadata}")
    os.environ["AIOGZIP_ENGINE"] = "stdlib"
    sys.path.insert(0, str(root / "src"))
    import aiogzip

    origin = Path(aiogzip.__file__).resolve()
    if not origin.is_relative_to(root / "src"):
        raise RuntimeError(f"wrong source import: {origin}")
    engines = dataclasses.asdict(aiogzip.engine_info())
    assert set(engines.values()) == {"stdlib-zlib"}

    async def run():
        return [await measure(aiogzip, mode) for mode in (True, False)]

    record = {
        **provenance,
        "import": str(origin),
        "harness_path": str(harness),
        "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "aiofiles": version("aiofiles"),
        "engines": engines,
        "command": sys.argv,
        "limitations": "One sample per fixture; tracemalloc misses native allocations; excludes fixture generation and open; no RSS or scheduler measurement; correctness hashing follows measured call. This is not a performance comparison.",
        "rows": asyncio.run(run()),
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
