#!/usr/bin/env python3
"""WP2 public source-failure outcomes for exact, scoped BC2 comparison."""

import argparse
import asyncio
import dataclasses
import gzip
import hashlib
import io
import json
import os
import sys
import threading
from pathlib import Path

from capture_file_state_trace import git_metadata


async def capture(package):
    import aiofiles.threadpool

    a, b = b"member A\n", b"member B\n"
    wire_a = gzip.compress(a, mtime=0)
    wire = wire_a + gzip.compress(b, mtime=0)
    semantic, diagnostic = {}, {}

    async def finish_trace(file, caller, events):
        try:
            await caller
        except asyncio.CancelledError:
            events.append(["initial", "CancelledError"])
        except OSError as error:
            events.append(["initial", "OSError", str(error)])
        else:
            raise AssertionError("injected cancellation/error was not observed")
        for label in ("retry", "next"):
            try:
                data = await file.read()
            except OSError as error:
                if not str(error).startswith("read stream is broken"):
                    raise
                events.append([label, "OSError", "read stream is broken"])
            else:
                events.append(
                    [label, {"bytes": data.hex()} if isinstance(data, bytes) else data]
                )

    for text in (False, True):
        cls = package.AsyncGzipTextFile if text else package.AsyncGzipBinaryFile
        for consumed in (False, True):
            for checkpoint in (False, True):
                for failure in ("cancel", "error"):
                    entered, release = asyncio.Event(), asyncio.Event()

                    class Source:
                        first = True

                        def __init__(self, checkpoint=checkpoint):
                            self.buffer = io.BytesIO(wire)
                            self.tell = self.buffer.tell if checkpoint else None

                        async def read(
                            self,
                            size=-1,
                            *,
                            consumed=consumed,
                            failure=failure,
                            entered=entered,
                            release=release,
                        ):
                            if self.first:
                                self.first = False
                                data = (
                                    self.buffer.read(len(wire_a)) if consumed else None
                                )
                                entered.set()
                                if failure == "error":
                                    raise OSError("injected source failure")
                                await release.wait()
                                if data is not None:
                                    return data
                            return self.buffer.read(size)

                    source, events = Source(), []
                    async with cls(
                        None, "rt" if text else "rb", fileobj=source, closefd=False
                    ) as f:
                        caller = asyncio.create_task(f.read())
                        try:
                            await asyncio.wait_for(entered.wait(), 5)
                            if failure == "cancel":
                                caller.cancel()
                            await finish_trace(f, caller, events)
                        finally:
                            release.set()
                            await asyncio.gather(caller, return_exceptions=True)
                    name = f"{'text' if text else 'binary'}-custom-{failure}-consumed-{consumed}-checkpoint-{checkpoint}"
                    semantic[name] = events
                    diagnostic[name] = {"physical_position": source.buffer.tell()}

        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release, settled = threading.Event(), threading.Event()

        class Reader(io.BufferedReader):
            first = True

            def read(
                self,
                size=-1,
                *,
                loop=loop,
                entered=entered,
                release=release,
                settled=settled,
            ):
                if self.first:
                    self.first = False
                    data = super().read(len(wire_a))
                    loop.call_soon_threadsafe(entered.set)
                    try:
                        if not release.wait(5):
                            raise RuntimeError("native trace watchdog expired")
                        return data
                    finally:
                        settled.set()
                return super().read(size)

        raw = Reader(io.BytesIO(wire))
        source = aiofiles.threadpool.wrap(raw, loop=loop)
        events = []
        caller = None
        try:
            async with cls(
                None, "rt" if text else "rb", fileobj=source, closefd=False
            ) as f:
                caller = asyncio.create_task(f.read())
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    caller.cancel()
                    for _ in range(4):
                        await asyncio.sleep(0)
                    release.set()
                    assert await asyncio.to_thread(settled.wait, 5)
                    await finish_trace(f, caller, events)
                finally:
                    release.set()
                    await asyncio.gather(caller, return_exceptions=True)
            name = f"{'text' if text else 'binary'}-native-consumed-cancel"
            semantic[name] = events
            diagnostic[name] = {"physical_position": raw.tell()}
        finally:
            release.set()
            if caller is not None:
                await asyncio.gather(caller, return_exceptions=True)
            raw.close()
    return semantic, diagnostic, hashlib.sha256(wire).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    source = git_metadata(root)
    harness_path = Path(__file__).resolve()
    harness = git_metadata(harness_path.parents[1])
    if args.require_clean and any(
        not m["sha"] or m["status"] for m in (source, harness)
    ):
        parser.error("clean committed source and harness trees are required")
    os.environ["AIOGZIP_ENGINE"] = args.engine
    sys.path.insert(0, str(root / "src"))
    import aiogzip

    if not Path(aiogzip.__file__).resolve().is_relative_to(root / "src"):
        raise RuntimeError("wrong source import")
    semantic, diagnostic, fixture = asyncio.run(capture(aiogzip))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "source": source,
                "harness": harness,
                "harness_sha256": hashlib.sha256(harness_path.read_bytes()).hexdigest(),
                "python": sys.version,
                "engines": dataclasses.asdict(aiogzip.engine_info()),
                "fixture_sha256": fixture,
                "semantic": semantic,
                "diagnostic": diagnostic,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
