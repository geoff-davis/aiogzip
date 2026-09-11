#!/usr/bin/env python3
"""Deterministic WP2 read-path timing; shared-host results are provisional."""

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
import tempfile
import time
from pathlib import Path

from capture_file_state_trace import Source, git_metadata


def summarize(samples):
    median = statistics.median(samples)
    return {
        "seconds": samples,
        "median_seconds": median,
        "minimum_seconds": min(samples),
        "mad_seconds": statistics.median(abs(sample - median) for sample in samples),
    }


async def measure(package, repeats):
    rows = []
    # ASCII text has the same byte/character counts, with deterministic gzip input.
    content = hashlib.shake_256(b"WP2 read fixture").digest(2 * 1024 * 1024).hex()
    payload = "".join(
        content[start : start + 256] + "\n" for start in range(0, len(content), 256)
    )
    fixtures = [
        ("hex-lines", payload.encode(), "utf-8"),
        (
            "random-bytes",
            hashlib.shake_256(b"WP2 incompressible fixture").digest(4 * 1024 * 1024),
            "latin-1",
        ),
    ]
    with tempfile.TemporaryDirectory(prefix="aiogzip-wp2-") as directory:
        path = Path(directory) / "fixture.gz"
        for family, raw, encoding in fixtures:
            wire = gzip.compress(raw, mtime=123)
            assert len(wire) > package.AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE
            path.write_bytes(wire)
            for source_kind in ("native", "custom"):
                for text in (False, True):
                    cls = (
                        package.AsyncGzipTextFile
                        if text
                        else package.AsyncGzipBinaryFile
                    )
                    expected = raw.decode(encoding) if text else raw
                    for surface in ("read-all", "read-sized", "readline"):
                        samples = []
                        for iteration in range(repeats + 1):
                            options = (
                                {"newline": "", "encoding": encoding} if text else {}
                            )
                            if source_kind == "custom":
                                options.update(fileobj=Source(wire), closefd=False)
                            f = cls(
                                path if source_kind == "native" else None,
                                "rt" if text else "rb",
                                **options,
                            )
                            async with f:
                                start = time.perf_counter()
                                if surface == "read-all":
                                    result = await f.read()
                                else:
                                    pieces = []
                                    while piece := await (
                                        f.read(65536)
                                        if surface == "read-sized"
                                        else f.readline()
                                    ):
                                        pieces.append(piece)
                                    result = ("" if text else b"").join(pieces)
                                elapsed = time.perf_counter() - start
                            assert result == expected
                            if iteration:
                                samples.append(elapsed)
                        rows.append(
                            {
                                "source_kind": source_kind,
                                "text": text,
                                "surface": surface,
                                "family": family,
                                "payload_bytes": len(raw),
                                "wire_bytes": len(wire),
                                "fixture_sha256": hashlib.sha256(wire).hexdigest(),
                                **summarize(samples),
                            }
                        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=11)
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
        "qualification": "Provisional unless a quiet host is independently established; G17 remains open.",
        "method": "Identical deterministic fixture; one warmup then all samples retained. Setup/open/close/validation outside timing; collection and join inside timing. No allocation measurement. Default chunk sizes. Deterministic random hex lines and incompressible bytes (Latin-1 for text); both compressed fixtures guarded above one default input chunk. Warm filesystem cache; not a storage-device throughput qualification.",
        "rows": asyncio.run(measure(aiogzip, args.repeats)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
