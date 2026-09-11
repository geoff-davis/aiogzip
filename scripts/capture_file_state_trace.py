#!/usr/bin/env python3
"""Capture small semantic scenarios separately from transport diagnostics.

Run each source root in its own process. Opaque cookies never leave that process.
The source-root check is mandatory so a baseline cannot silently import a candidate.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import gzip
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


class Source:
    def __init__(self, wire: bytes) -> None:
        self.buffer = io.BytesIO(wire)
        self.reads: list[dict[str, int]] = []

    async def read(self, size: int = -1) -> bytes:
        data = self.buffer.read(size)
        self.reads.append({"requested": size, "returned": len(data)})
        return data

    async def seek(self, offset: int, whence: int = 0) -> int:
        return self.buffer.seek(offset, whence)

    async def seekable(self) -> bool:
        return True


async def capture(package):
    semantic = {}
    diagnostics = {}
    payload = "α\r\nbeta\rgamma\nlast"
    wire = gzip.compress(payload.encode(), mtime=123)
    for newline in (None, "", "\n", "\r", "\r\n"):
        sources = [Source(wire), Source(wire)]
        handles = [
            package.AsyncGzipTextFile(
                None, "rt", fileobj=source, closefd=False, newline=newline
            )
            for source in sources
        ]
        events = []
        cookies = {}
        try:
            for handle in handles:
                await handle.open()
            first, second = handles
            events.append(["H1.read", 2, await first.read(2)])
            cookies["H1:C1"] = await first.tell()
            events.append(["H1.tell", "H1:C1"])
            expected = await first.read(5)
            events.append(["H1.read", 5, expected])
            assert await first.seek(cookies["H1:C1"]) == cookies["H1:C1"]
            events.append(["H1.seek", "H1:C1", "H1:C1"])
            actual = await first.read(5)
            assert actual == expected
            events.append(["H1.read", 5, actual])
            try:
                await second.seek(cookies["H1:C1"])
            except OSError as error:
                events.append(["H2.seek", "foreign:H1:C1", type(error).__name__])
            else:
                raise AssertionError("foreign cookie accepted")
            events.append(["H1.seek", 0, await first.seek(0)])
            result = await first.read()
            assert result == (
                payload.replace("\r\n", "\n").replace("\r", "\n")
                if newline is None
                else payload
            )
            events.append(["H1.read", -1, result])
            events.append(["H1.newlines", first.newlines])
            events.append(["H1.mtime", first.mtime])
        finally:
            for handle in handles:
                await handle.close()
        events.append(["closed", [handle.closed for handle in handles]])
        key = f"text-cookie-newline={newline!r}"
        semantic[key] = events
        diagnostics[key] = {
            f"H{i + 1}": source.reads for i, source in enumerate(sources)
        }

    source = Source(wire)
    async with package.AsyncGzipBinaryFile(
        None, "rb", fileobj=source, closefd=False
    ) as f:
        prefix = await f.read(3)
        position = await f.tell()
        peeked = await f.peek(1)
        assert await f.tell() == position
        rest = await f.read()
        assert prefix + rest == payload.encode()
        assert rest.startswith(peeked)
        semantic["binary-position"] = [
            ["read", 3, prefix.hex()],
            ["tell", position],
            ["peek-preserves-position", True],
            ["read", -1, rest.hex()],
            ["eof", (await f.read()).hex()],
        ]
    diagnostics["binary-position"] = source.reads
    return semantic, diagnostics, hashlib.sha256(wire).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve()
    os.environ["AIOGZIP_ENGINE"] = args.engine
    sys.path.insert(0, str(root / "src"))
    import aiogzip

    origin = Path(aiogzip.__file__).resolve()
    if not origin.is_relative_to(root / "src"):
        raise RuntimeError(f"wrong import origin: {origin}")
    engines = dataclasses.asdict(aiogzip.engine_info())
    if args.engine == "stdlib":
        assert set(engines.values()) == {"stdlib-zlib"}, engines
    else:
        assert engines["decompression"] == "zlib-ng", engines

    def git(*arguments: str) -> str | None:
        if not (root / ".git").exists():
            return None  # An unpacked sdist has no Git provenance.
        return subprocess.check_output(
            ["git", "-C", str(root), *arguments], text=True
        ).strip()

    dependencies = {}
    for name in ("aiofiles", "zlib-ng"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None

    semantic, diagnostics, fixture_hash = asyncio.run(capture(aiogzip))
    record = {
        "schema": 1,
        "source": {
            "sha": git("rev-parse", "HEAD"),
            "tree": git("rev-parse", "HEAD^{tree}"),
            "status": git("status", "--short"),
            "import": str(origin),
        },
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "engines": engines,
        "dependencies": dependencies,
        "fixture_sha256": fixture_hash,
        "command": sys.argv,
        "semantic": semantic,
        "diagnostic": diagnostics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(record, output, indent=2, ensure_ascii=False)
        output.write("\n")


if __name__ == "__main__":
    main()
