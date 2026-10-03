#!/usr/bin/env python3
"""G07 small-read resource observations and separate quiet-machine latency runs.

Every matrix row runs in a fresh process. Resource mode instruments inflation
and Python allocations but records no timings. Latency mode uses no allocation
tracer or inflation wrapper. Neither mode changes the file reader's drain policy.
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
import subprocess
import sys
import threading
import time
import tracemalloc
from importlib.metadata import version
from pathlib import Path

from capture_file_state_trace import git_metadata

REQUESTS = {
    "read": 1,
    "read1": 1,
    "readinto": 7,
    "peek": 1,
    "readline": 7,
    "text-read": 1,
    "text-readline": 7,
}


class Source:
    def __init__(self, wire, seekable):
        self.buffer = io.BytesIO(wire)
        self.physically_seekable = seekable
        self.reads = []

    async def read(self, size=-1):
        data = self.buffer.read(size)
        self.reads.append({"requested": size, "returned": len(data)})
        return data

    def tell(self):
        return self.buffer.tell()

    def seekable(self):
        return self.physically_seekable

    async def seek(self, offset, whence=0):
        if not self.physically_seekable:
            raise OSError("not physically seekable")
        return self.buffer.seek(offset, whence)


def rss_bytes():
    """Linux point-in-time RSS, not a transient per-call peak."""
    path = Path("/proc/self/statm")
    if not path.exists():
        return None
    return int(path.read_text(encoding="utf-8").split()[1]) * os.sysconf("SC_PAGE_SIZE")


def host_state():
    return {
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "cpu_affinity": sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
    }


async def measure(package, case, phase):
    size = case["size"]
    payload = (
        b"x" * size
        if case["fixture"] == "repeated-x"
        else random.Random(0).randbytes(size)
    )
    wire = gzip.compress(payload, mtime=123)
    assert gzip.decompress(wire) == payload
    fault = case.get("fault")
    if fault == "crc":
        damaged = bytearray(wire)
        damaged[-8] ^= 1
        wire = bytes(damaged)
        del damaged
    fixture = {
        "payload_bytes": size,
        "compressed_bytes": len(wire),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "wire_sha256": hashlib.sha256(wire).hexdigest(),
    }
    chunk_size = package.AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE
    if case["fixture"] == "repeated-x":
        assert len(wire) < chunk_size
    elif size >= 1024 * 1024:
        assert len(wire) > chunk_size
    text = case["surface"].startswith("text-")
    cls = package.AsyncGzipTextFile if text else package.AsyncGzipBinaryFile
    sources = [Source(wire, case["seekable"]) for _ in range(case["handles"])]
    handles = [
        cls(
            None,
            "rt" if text else "rb",
            fileobj=source,
            closefd=False,
            max_decompressed_size=case.get("limit"),
            **({"encoding": "latin-1", "newline": "\n"} if text else {}),
        )
        for source in sources
    ]
    buffers = [bytearray(b"!" * REQUESTS[case["surface"]]) for _ in handles]
    stats = {"total_inflated_bytes": 0, "largest_inflate_step_bytes": 0}
    lock = threading.Lock()
    engine = sys.modules[package.__name__ + "._engine"]
    original_inflate = engine.inflate_step

    def inflate(*args, **kwargs):
        step = original_inflate(*args, **kwargs)
        with lock:
            stats["total_inflated_bytes"] += len(step.output)
            stats["largest_inflate_step_bytes"] = max(
                stats["largest_inflate_step_bytes"], len(step.output)
            )
        return step

    async def first(index):
        started = time.perf_counter() if phase == "latency" else None
        try:
            if case["surface"] == "readinto":
                count = await handles[index].readinto(buffers[index])
                result = bytes(buffers[index][:count])
            else:
                method = getattr(handles[index], case["surface"].removeprefix("text-"))
                result = await method(REQUESTS[case["surface"]])
            error = None
        except OSError as exc:
            result = None
            error = {"type": type(exc).__name__, "message": str(exc)}
        elapsed = time.perf_counter() - started if started is not None else None
        return result, error, elapsed

    done = False
    ticks = []

    async def ticker():
        while not done:
            ticks.append(time.perf_counter())
            await asyncio.sleep(0)

    try:
        for handle in handles:
            await handle.open()
        binaries = [handle.buffer if text else handle for handle in handles]
        decoders = [handle._decoder for handle in binaries]
        host_before = host_state()
        rss_before = rss_bytes()
        if phase == "resources":
            engine.inflate_step = inflate
            tracemalloc.start()
        sibling = asyncio.create_task(ticker()) if phase == "latency" else None
        started = time.perf_counter() if phase == "latency" else None
        tasks = [asyncio.create_task(first(index)) for index in range(len(handles))]
        try:
            outcomes = await asyncio.gather(*tasks)
            ended = time.perf_counter() if phase == "latency" else None
            # Stop timestamps at the measurement boundary, before cleanup yields.
            done = True
            current, peak = (
                tracemalloc.get_traced_memory()
                if phase == "resources"
                else (None, None)
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if phase == "resources":
                tracemalloc.stop()
                engine.inflate_step = original_inflate
            done = True
            if sibling is not None:
                await sibling
        rss_after = rss_bytes()
        host_after = host_state()
        rows = []
        for index, (handle, binary, decoder, source, outcome) in enumerate(
            zip(handles, binaries, decoders, sources, outcomes, strict=True)
        ):
            result, error, elapsed = outcome
            row = {
                "requested": REQUESTS[case["surface"]],
                "returned": len(result) if result is not None else 0,
                "logical_units": "characters" if text else "bytes",
                "error": error,
                "first_result_seconds": elapsed,
                "source_reads": source.reads.copy(),
                "compressed_bytes_fetched": sum(
                    read["returned"] for read in source.reads
                ),
                "compressed_bytes_accepted": decoder.compressed_size,
                "inflated_accounted_bytes": decoder.uncompressed_size,
                "codec_output_chunk_size": decoder._output_chunk_size,
                "binary_unread_bytes": len(binary._buffer) - binary._buffer_offset,
                "binary_buffer_storage_bytes": sys.getsizeof(binary._buffer),
                "text_unread_characters": len(handle._text_buffer)
                - handle._text_buffer_offset
                if text
                else 0,
                "text_buffer_storage_bytes": sys.getsizeof(handle._text_buffer)
                if text
                else 0,
                "compressed_cache_bytes": len(binary._compressed_cache),
                "compressed_cache_storage_bytes": sys.getsizeof(
                    binary._compressed_cache
                ),
                "binary_position": binary._position,
                "validated_members": decoder.member_count,
                "decoder_finished": decoder.finished,
                "binary_eof": binary._eof,
                "mtime": handle.mtime,
            }
            rows.append(row)
            if fault == "limit":
                assert error is not None and "max_decompressed_size" in error["message"]
                assert result is None
                assert decoder.uncompressed_size <= case["limit"]
                if case["surface"] == "readinto":
                    assert buffers[index] == b"!" * len(buffers[index])
                try:
                    await handle.read(1)
                except OSError:
                    pass
                else:
                    raise AssertionError("size failure became a successful read")
                row["round_trip_verified"] = False
                row["terminal_limit_verified"] = True
                continue
            if fault == "crc":
                assert error is not None and error["type"] == "BadGzipFile"
                assert result is None
            else:
                assert error is None
                raw = result.encode("latin-1") if text else result
                assert raw == payload[: len(raw)] and raw
            digest = hashlib.sha256()
            if result is not None and case["surface"] != "peek":
                digest.update(result.encode("latin-1") if text else result)
            saw_broken = False
            while True:
                try:
                    rest = await handle.read(chunk_size)
                except OSError:
                    if fault != "crc":
                        raise
                    saw_broken = True
                    break
                if not rest:
                    break
                digest.update(rest.encode("latin-1") if text else rest)
            assert digest.hexdigest() == fixture["payload_sha256"]
            assert saw_broken == (fault == "crc")
            row["round_trip_verified"] = True
            row["validation_salvage_verified"] = fault == "crc"
        gaps = []
        if phase == "latency":
            stamps = [started, *ticks, ended]
            assert all(a <= b for a, b in zip(stamps, stamps[1:], strict=False))
            gaps = sorted(b - a for a, b in zip(stamps, stamps[1:], strict=False))
        return {
            "host_before": host_before,
            "host_after": host_after,
            "case": case,
            "phase": phase,
            "fixture": fixture,
            "source_chunk_size": chunk_size,
            "handles": rows,
            "inflation": stats if phase == "resources" else None,
            "tracemalloc_current_bytes": current,
            "tracemalloc_peak_bytes": peak,
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "cohort_seconds": ended - started if started is not None else None,
            "ticker_ticks": len(ticks) if phase == "latency" else None,
            "max_gap_seconds": max(gaps) if gaps else None,
            "p99_gap_seconds": gaps[min(len(gaps) - 1, int(len(gaps) * 0.99))]
            if gaps
            else None,
        }
    finally:
        engine.inflate_step = original_inflate
        for handle in handles:
            await handle.close()


def matrix():
    cases = [
        {
            "size": mib * 1024 * 1024,
            "fixture": "repeated-x",
            "surface": surface,
            "seekable": seekable,
            "handles": handles,
        }
        for mib in (1, 16, 32)
        for surface in REQUESTS
        for seekable in (True, False)
        for handles in (1, 4)
    ]
    cases += [
        {
            "size": 16 * 1024 * 1024,
            "fixture": "random-seed-0",
            "surface": surface,
            "seekable": seekable,
            "handles": handles,
        }
        for surface in ("read", "text-read")
        for seekable in (True, False)
        for handles in (1, 4)
    ]
    cases += [
        {
            "size": 16 * 1024 * 1024,
            "fixture": "repeated-x",
            "surface": surface,
            "seekable": seekable,
            "handles": 1,
            "fault": fault,
            "limit": 1024 * 1024 if fault == "limit" else None,
        }
        for surface in ("read", "readinto", "text-read")
        for seekable in (True, False)
        for fault in ("limit", "crc")
    ]
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--phase", choices=("resources", "latency"), required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case-json", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeat < 1 or (args.output is None and args.case_json is None):
        parser.error("positive repeat and an output path are required")
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
    import aiogzip

    origin = Path(aiogzip.__file__).resolve()
    assert origin.is_relative_to(root / "src"), origin
    engines = dataclasses.asdict(aiogzip.engine_info())
    assert engines["decompression"] == (
        "stdlib-zlib" if args.engine == "stdlib" else "zlib-ng"
    )
    if args.case_json is not None:
        print(
            json.dumps(
                asyncio.run(measure(aiogzip, json.loads(args.case_json), args.phase))
            )
        )
        return
    record = {
        **provenance,
        "import": str(origin),
        "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "engines": engines,
        "aiofiles": version("aiofiles"),
        "command": sys.argv,
        "host": host_state(),
        "rows": [],
        "limitations": "Fresh process per row. Fixtures, hashes, sources, open and readinto targets excluded from measurement; full data validation follows it. Resource mode includes task/instrumentation overhead; tracemalloc misses native allocations. RSS is before/after, not peak, and includes fixture storage. Text uses Latin-1 and newline=LF so one character maps to one plaintext byte. Inflated-accounted excludes a possible limit-overflow byte; the resource-only engine wrapper counts actual returned inflate bytes across the cohort. Latency has no tracer/inflate wrapper, but does have a sibling ticker and in-memory-source bookkeeping; requires quiet-machine review. Per-handle first-result time starts when that task begins; cohort time includes scheduling all handles. Peek size is a minimum request, not a maximum returned size. Multiple-member and separated-trailer semantics are covered by test_wp5_partial_read_limits.py. No wall-clock measurements in resource mode.",
    }
    # Fail early on an existing capture; exclusively create only after success.
    if args.output.exists():
        raise FileExistsError(args.output)
    for case in matrix():
        for repeat in range(args.repeat):
            result = subprocess.run(
                [
                    sys.executable,
                    str(harness),
                    "--source-root",
                    str(root),
                    "--engine",
                    args.engine,
                    "--phase",
                    args.phase,
                    "--case-json",
                    json.dumps(case),
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=180,
                check=True,
            )
            row = json.loads(result.stdout)
            row["repeat"] = repeat
            record["rows"].append(row)
            print(f"{args.phase}: {len(record['rows'])} rows complete", flush=True)
    assert provenance == {
        "source": git_metadata(root),
        "harness": git_metadata(harness.parents[1]),
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
