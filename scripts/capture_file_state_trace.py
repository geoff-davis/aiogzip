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


def git_metadata(root: Path) -> dict[str, str | None]:
    """Identify an exact checkout, including untracked files; sdists have no Git."""

    def git(*arguments: str) -> str | None:
        if not (root / ".git").exists():
            return None
        return subprocess.check_output(
            ["git", "-C", str(root), *arguments], text=True, encoding="utf-8"
        ).strip()

    return {
        "sha": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--short"),
    }


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


async def capture_extended(package):
    """Small named public scenarios; failure boundaries are fixed by each source."""
    semantic, diagnostic = {}, {}
    payload = b"alpha\nbeta\ngamma\nlast"
    wire = gzip.compress(payload, mtime=123)

    def value(result):
        if isinstance(result, bytes):
            return {"bytes": result.hex()}
        if isinstance(result, list):
            return [value(item) for item in result]
        return result

    async def observe(events, name, awaitable, *, error=None):
        try:
            result = await awaitable
        except (OSError, ValueError) as caught:
            if error is None or not str(caught).startswith(error):
                raise
            events.append([name, {"error": type(caught).__name__, "prefix": error}])
            return None
        if error is not None:
            raise AssertionError(f"{name} did not raise {error}")
        events.append([name, value(result)])
        return result

    source = Source(wire)
    events = []
    async with package.AsyncGzipBinaryFile(
        None, "rb", fileobj=source, closefd=False
    ) as f:
        parts = [await observe(events, "read1(3)", f.read1(3))]
        for method in ("readinto", "readinto1"):
            buffer = bytearray(2)
            count = await observe(events, f"{method}(2)", getattr(f, method)(buffer))
            parts.append(bytes(buffer[:count]))
            events.append(["destination", value(parts[-1])])
        peeked = await f.peek(1)
        assert payload[len(b"".join(parts)) :].startswith(peeked)
        events.append(["peek(1) prefix matches unread", True])
        await observe(events, "tell", f.tell())
        parts.append(await observe(events, "readline(5)", f.readline(5)))
        parts.extend(await observe(events, "readlines(1)", f.readlines(1)))
        parts.extend(await observe(events, "readlines(-1)", f.readlines()))
        assert b"".join(parts) == payload
        await observe(events, "seek(0)", f.seek(0))
        await observe(events, "seek(5)", f.seek(5))
        assert await observe(events, "read(2)", f.read(2)) == payload[5:7]
    semantic["binary-surfaces-and-seek"] = events
    diagnostic["binary-surfaces-and-seek"] = source.reads

    for text in (False, True):
        cls = package.AsyncGzipTextFile if text else package.AsyncGzipBinaryFile
        mode = "rt" if text else "rb"
        expected = payload.decode() if text else payload
        for failure in ("crc", "limit"):
            damaged = bytearray(wire)
            if failure == "crc":
                damaged[-8] ^= 1
            source = Source(bytes(damaged))
            options = {"max_decompressed_size": 4} if failure == "limit" else {}
            events = []
            async with cls(None, mode, fileobj=source, closefd=False, **options) as f:
                await observe(
                    events,
                    "read over failure",
                    f.read(100),
                    error=(
                        "Error decompressing gzip data:"
                        if failure == "crc"
                        else "decompressed output exceeded max_decompressed_size"
                    ),
                )
                if failure == "crc":
                    assert await observe(events, "salvage", f.read(100)) == expected
                else:
                    # No forbidden bytes may be emitted by any permitted salvage.
                    try:
                        salvage = await f.read(100)
                    except OSError:
                        salvage = "" if text else b""
                    assert len(salvage) <= 4
                    events.append(["limit salvage", value(salvage)])
                await observe(
                    events,
                    "exhausted salvage",
                    f.read(1),
                    error="read stream is broken",
                )
                if failure == "crc":
                    source.buffer = io.BytesIO(wire)
                    await observe(events, "rewind recovery", f.seek(0))
                    assert await observe(events, "recovered read", f.read()) == expected
            key = f"{'text' if text else 'binary'}-{failure}-salvage"
            semantic[key], diagnostic[key] = events, source.reads

        class TransientSource(Source):
            fail = True

            async def read(self, size=-1):
                if self.fail and self.buffer.tell() > 0:
                    self.fail = False
                    raise OSError("transient source failure")
                return await super().read(min(size, 12))

        source = TransientSource(wire)
        events = []
        async with cls(None, mode, fileobj=source, closefd=False) as f:
            await observe(
                events,
                "readlines transient",
                f.readlines(),
                error="transient source failure",
            )
            lines = await observe(events, "readlines retry", f.readlines())
            assert ("" if text else b"").join(lines) == expected
            if text:
                await f.buffer.close()
                events.append(["buffer.close closes text", f.closed])
                assert f.closed
        semantic[f"{'text' if text else 'binary'}-transient-rollback"] = events
        diagnostic[f"{'text' if text else 'binary'}-transient-rollback"] = source.reads

        class ParkedSource(Source):
            first = True

            def __init__(self, wire, entered, release):
                super().__init__(wire)
                self.entered, self.release = entered, release

            async def read(self, size=-1):
                if self.first:
                    self.first = False
                    self.entered.set()
                    await self.release.wait()
                return await super().read(size)

        entered, release = asyncio.Event(), asyncio.Event()
        source, events = ParkedSource(wire, entered, release), []
        async with cls(None, mode, fileobj=source, closefd=False) as f:
            caller = asyncio.create_task(f.read())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                try:
                    await f.read(1)
                except package.ConcurrentOperationError:
                    events.append(["overlap", "ConcurrentOperationError"])
                else:
                    raise AssertionError("overlapping read accepted")
                caller.cancel()
                try:
                    await caller
                except asyncio.CancelledError:
                    events.append(["caller", "CancelledError"])
                else:
                    raise AssertionError("cancellation was swallowed")
            finally:
                release.set()
                await asyncio.gather(caller, return_exceptions=True)
            assert (
                await observe(events, "no-effect cancellation retry", f.read())
                == expected
            )
        semantic[f"{'text' if text else 'binary'}-cancel-no-effect"] = events
        diagnostic[f"{'text' if text else 'binary'}-cancel-no-effect"] = source.reads

    class ReplaySource(Source):
        async def seekable(self):
            return False

    for cap in (None, 1):
        source, events = ReplaySource(wire), []
        async with package.AsyncGzipBinaryFile(
            None, "rb", fileobj=source, closefd=False, max_rewind_cache_size=cap
        ) as f:
            assert await observe(events, "read(2)", f.read(2)) == payload[:2]
            if cap is None:
                await observe(events, "cache rewind", f.seek(0))
                assert await observe(events, "replay", f.read()) == payload
            else:
                await observe(
                    events,
                    "cache exhausted rewind",
                    f.seek(0),
                    error="Underlying file is not seekable",
                )
        semantic[f"nonseekable-cache-{cap}"] = events
        diagnostic[f"nonseekable-cache-{cap}"] = source.reads

    class FailedSeekSource(Source):
        async def seek(self, offset, whence=0):
            raise OSError("injected no-effect seek failure")

    source, events = FailedSeekSource(wire), []
    async with package.AsyncGzipBinaryFile(
        None, "rb", fileobj=source, closefd=False
    ) as f:
        prefix = await observe(events, "read(2)", f.read(2))
        await observe(
            events, "failed rewind", f.seek(0), error="injected no-effect seek failure"
        )
        assert (
            prefix + await observe(events, "read after failed rewind", f.read())
            == payload
        )
    semantic["failed-no-effect-rewind"], diagnostic["failed-no-effect-rewind"] = (
        events,
        source.reads,
    )

    for encoding in ("utf-8", "utf-16", "iso2022_jp"):
        content = "日本語\r\nabc\r終\n"
        source = Source(gzip.compress(content.encode(encoding), mtime=123))
        events = []
        async with package.AsyncGzipTextFile(
            None,
            "rt",
            fileobj=source,
            closefd=False,
            encoding=encoding,
            newline="",
            chunk_size=3,
        ) as f:
            prefix = await observe(events, "read(2)", f.read(2))
            cookie = await f.tell()
            events.append(["tell", "H1:C1"])
            remainder = await observe(events, "read remainder", f.read())
            assert prefix + remainder == content
            assert await f.seek(cookie) == cookie
            events.append(["seek", "H1:C1"])
            assert await observe(events, "replay remainder", f.read()) == remainder
            await observe(
                events,
                "invalid cookie",
                f.seek(-1),
                error="Cannot seek to invalid text cookie",
            )
        semantic[f"cookie-encoding-{encoding}"] = events
        diagnostic[f"cookie-encoding-{encoding}"] = source.reads

    for closefd in (False, True):

        class Sink:
            def __init__(self):
                self.data = bytearray()
                self.writes = []
                self.closes = 0
                self.fail = False

            async def write(self, data):
                if self.fail:
                    raise OSError("injected sink failure")
                self.data.extend(data)
                self.writes.append(len(data))
                return len(data)

            async def close(self):
                self.closes += 1

        sink, events = Sink(), []
        async with package.AsyncGzipBinaryFile(
            None, "wb", fileobj=sink, closefd=closefd, mtime=0
        ) as f:
            await observe(events, "write", f.write(payload))
            await observe(events, "tell", f.tell())
        assert gzip.decompress(sink.data) == payload
        assert sink.closes == int(closefd)
        events.append(["sink closed", bool(sink.closes)])
        semantic[f"write-closefd-{closefd}"] = events
        diagnostic[f"write-closefd-{closefd}"] = sink.writes

        sink, events = Sink(), []
        async with package.AsyncGzipBinaryFile(
            None, "wb", fileobj=sink, closefd=closefd, mtime=0
        ) as f:
            sink.fail = True
            await observe(
                events,
                "write fails in same call",
                f.write(hashlib.shake_256(b"sink-failure").digest(65536)),
                error="injected sink failure",
            )
            assert await observe(events, "position uncommitted", f.tell()) == 0
            await observe(
                events, "later write", f.write(payload), error="write stream is broken"
            )
        semantic[f"sink-failure-closefd-{closefd}"] = events
        diagnostic[f"sink-failure-closefd-{closefd}"] = sink.writes
    return semantic, diagnostic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Include WP0 failure/ownership/encoding scenarios.",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="Require committed, clean source and harness checkouts for retained evidence.",
    )
    args = parser.parse_args()
    root = args.source_root.resolve()
    harness_path = Path(__file__).resolve()
    source_metadata = git_metadata(root)
    harness_metadata = git_metadata(harness_path.parents[1])
    if args.require_clean:
        for label, metadata in (
            ("source", source_metadata),
            ("harness", harness_metadata),
        ):
            if metadata["sha"] is None or metadata["status"] != "":
                raise RuntimeError(f"{label} must be a clean Git checkout: {metadata}")
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

    dependencies = {}
    for name in ("aiofiles", "zlib-ng"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None

    semantic, diagnostics, fixture_hash = asyncio.run(capture(aiogzip))
    if args.extended:
        extended_semantic, extended_diagnostics = asyncio.run(capture_extended(aiogzip))
        semantic.update(extended_semantic)
        diagnostics.update(extended_diagnostics)
    record = {
        "schema": 2,
        "extended": args.extended,
        "source": {
            **source_metadata,
            "import": str(origin),
        },
        "harness": {**harness_metadata, "path": str(harness_path)},
        "harness_sha256": hashlib.sha256(harness_path.read_bytes()).hexdigest(),
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
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2, ensure_ascii=False)
        output.write("\n")


if __name__ == "__main__":
    main()
