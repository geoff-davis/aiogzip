#!/usr/bin/env python3
"""G06 long-line resource observations, separate from quiet-machine timing."""

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

from capture_file_state_trace import Source, git_metadata
from measure_b2_read_resources import host_state, rss_bytes


def matrix():
    core = [
        dict(
            size=mib * 1024 * 1024,
            newline=newline,
            encoding=encoding,
            chunk_size=65536,
            content="repeated",
            ending="absent",
            family="long",
        )
        for mib in (1, 2, 4, 8, 16)
        for newline in (None, "", "\n", "\r", "\r\n")
        for encoding in ("utf-8", "iso2022_jp")
    ]
    controls = [
        dict(
            size=1024 * 1024,
            newline=newline,
            encoding=encoding,
            chunk_size=chunk,
            content=content,
            ending=ending,
            family="long",
        )
        for newline in (None, "", "\n", "\r", "\r\n")
        for encoding in ("utf-8", "iso2022_jp")
        for chunk in (4096, 262144)
        for content in ("repeated", "seeded-ascii")
        for ending in ("crlf", "trailing-cr")
    ]
    short = [
        dict(
            size=32768,
            newline=newline,
            encoding=encoding,
            chunk_size=262144,
            content="repeated",
            ending="crlf",
            family="short",
        )
        for newline in (None, "", "\n", "\r", "\r\n")
        for encoding in ("utf-8", "iso2022_jp")
    ]
    split = [
        dict(
            size=1024 * 1024 - 1,
            newline=newline,
            encoding=encoding,
            chunk_size=65536,
            content="seeded-ascii",
            ending="crlf",
            family="split",
        )
        for newline in (None, "", "\n", "\r", "\r\n")
        for encoding in ("utf-8", "iso2022_jp")
    ]
    incompressible = [
        dict(
            size=mib * 1024 * 1024,
            newline=newline,
            encoding="latin-1",
            chunk_size=65536,
            content="seeded-bytes",
            ending="absent",
            family="long",
        )
        for mib in (1, 2, 4, 8, 16)
        for newline in (None, "", "\n", "\r", "\r\n")
    ]
    return core + controls + split + short + incompressible


def fixture(case):
    size = case["size"]
    unit = "日" if case["encoding"] == "iso2022_jp" else "x"
    if case["family"] == "short":
        text = (unit * 30 + "\r\n") * size
    else:
        if case["content"] == "seeded-bytes":
            # Latin-1 preserves random byte entropy while excluding only CR/LF.
            data = (
                random.Random(0)
                .randbytes(size)
                .replace(b"\r", b"\xff")
                .replace(b"\n", b"\xfe")
            )
            text = data.decode("latin-1")
        elif case["content"] == "seeded-ascii":
            # Newline-free higher-entropy control; printable ASCII is not a
            # claim of incompressibility or a stateful-encoding stress fixture.
            data = random.Random(0).randbytes(size)
            text = data.translate(bytes(33 + i % 94 for i in range(256))).decode(
                "ascii"
            )
        else:
            text = unit * size
        text += {"absent": "", "crlf": "\r\n", "trailing-cr": "\r"}[case["ending"]]
    raw = text.encode(case["encoding"])
    wire = gzip.compress(raw, mtime=0)
    if case["content"] == "seeded-bytes":
        assert len(wire) >= 0.99 * len(raw), (
            "incompressible control compressed too well"
        )
    with io.TextIOWrapper(
        io.BytesIO(raw), encoding=case["encoding"], newline=case["newline"]
    ) as reference:
        expected = list(reference)
    return (
        wire,
        expected,
        {
            "wire_sha256": hashlib.sha256(wire).hexdigest(),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "compressed_bytes": len(wire),
            "compressed_to_encoded_ratio": len(wire) / len(raw),
            "encoded_bytes": len(raw),
            "size_units": "lines"
            if case["family"] == "short"
            else "characters before ending",
            "input_characters": len(text),
            "returned_characters": sum(map(len, expected)),
            "returned_lines": len(expected),
        },
    )


async def sample(package, case, wire, expected, phase):
    work = {"append_calls": 0, "growing_buffer_characters": 0}
    cls = package.AsyncGzipTextFile
    original = cls._append_buffer

    def append(handle, text):
        if text:
            work["append_calls"] += 1
            work["growing_buffer_characters"] += len(handle._text_buffer) + len(text)
        return original(handle, text)

    async with cls(
        None,
        "rt",
        fileobj=Source(wire),
        closefd=False,
        newline=case["newline"],
        encoding=case["encoding"],
        chunk_size=case["chunk_size"],
    ) as stream:
        binary_chunk_size = stream.buffer._chunk_size
        assert binary_chunk_size == case["chunk_size"]
        before = host_state()
        rss_before = rss_bytes()
        if phase == "resources":
            cls._append_buffer = append
            tracemalloc.start()
        output = []
        started = time.perf_counter() if phase == "timing" else None
        try:
            async for line in stream:
                output.append(line)
            elapsed = time.perf_counter() - started if started is not None else None
            current, peak = (
                tracemalloc.get_traced_memory()
                if phase == "resources"
                else (None, None)
            )
        finally:
            if phase == "resources":
                tracemalloc.stop()
                cls._append_buffer = original
        rss_after = rss_bytes()
        after = host_state()
        # Validate outside instrumentation/timing, using stdlib's independent
        # decoding and newline handling rather than candidate-generated output.
        assert output == expected
    return {
        "binary_chunk_size": binary_chunk_size,
        "seconds": elapsed,
        "work": work if phase == "resources" else None,
        "python_current_bytes": current,
        "python_peak_bytes": peak,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "host_before": before,
        "host_after": after,
        "verified": True,
    }


async def run(package, cases, phase, repeat):
    rows = []
    for case in cases:
        wire, expected, metadata = fixture(case)
        samples = [
            await sample(package, case, wire, expected, phase) for _ in range(repeat)
        ]
        rows.append({"case": case, "fixture": metadata, "samples": samples})
        print(f"{phase}: {len(rows)} rows complete", flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--phase", choices=("resources", "timing"), required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat must be positive")
    if args.output.exists():
        raise FileExistsError(args.output)
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
    record = {
        **provenance,
        "import": str(origin),
        "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "engines": engines,
        "dependencies": {"aiofiles": version("aiofiles")},
        "command": sys.argv,
        "phase": args.phase,
        "limitations": "Fixtures, stdlib reference output, hashes and open precede measurement. Output-list collection is included. Append lengths are a structural string-building proxy, not actual allocator copies; final joins/slices are excluded from that proxy but included in Python allocation peaks. Zero append counts on fast paths mean this hook is bypassed, not zero copying. No scanning-work claim: baseline generic search_from avoids rescanning prefixes, and candidate scans new chunks plus a carried CR. Only unlimited line iteration is measured; bounded readline is separately tested. Doubling ratios must be derived in the evidence record. Tracemalloc misses native allocations. RSS is before/after, not peak; rows share a process and allocator history. Resource phase records no times. Timing phase has no instrumentation and requires quiet interleaved baseline/candidate runs. Seeded printable ASCII is higher entropy, not incompressible; repeated Japanese exercises stateful decoding. Latin-1 random-byte controls exclude CR/LF and assert compressed size is at least 99% of encoded size. Boundary-split, rollback, cookie and salvage contracts are covered separately in pytest.",
        "rows": asyncio.run(run(aiogzip, matrix(), args.phase, args.repeat)),
    }
    assert provenance == {
        "source": git_metadata(root),
        "harness": git_metadata(harness.parents[1]),
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
