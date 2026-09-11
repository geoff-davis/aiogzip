#!/usr/bin/env python3
"""Named WP3 opening scenarios; semantic corrections require exact BC3 pairs."""

import argparse
import asyncio
import dataclasses
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from capture_file_state_trace import git_metadata


def exception(error):
    return {
        "type": type(error).__name__,
        "message": str(error),
        "cause": exception(error.__cause__) if error.__cause__ is not None else None,
        "notes": getattr(error, "__notes__", []),
    }


async def outcome(awaitable):
    try:
        await awaitable
    except BaseException as error:
        return exception(error)
    return "ok"


async def capture(package):
    import aiofiles
    import aiofiles.threadpool

    semantic = {}
    original_open = aiofiles.open
    original_sync = aiofiles.threadpool.sync_open
    original_wrap = aiofiles.threadpool.wrap
    for text in (False, True):
        cls = package.AsyncGzipTextFile if text else package.AsyncGzipBinaryFile
        for writing in (False, True):
            label = ("text" if text else "binary") + ("-write" if writing else "-read")
            for operation in ("normal", "open", "close", "clean-exit", "body-exit"):
                entered, release = asyncio.Event(), asyncio.Event()
                resources = []

                class Resource:
                    closes = 0

                    async def write(self, data):
                        return len(data)

                    async def close(self):
                        self.closes += 1

                async def acquire(
                    *args,
                    resources=resources,
                    entered=entered,
                    release=release,
                    **kwargs,
                ):
                    resource = Resource()
                    resources.append(resource)
                    entered.set()
                    await release.wait()
                    return resource

                aiofiles.open = acquire
                f = cls("trace.gz", ("w" if writing else "r") + ("t" if text else "b"))
                opener = asyncio.create_task(f.open())
                other = None
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    if operation == "open":
                        other = asyncio.create_task(outcome(f.open()))
                    elif operation == "close":
                        other = asyncio.create_task(outcome(f.close()))
                    elif operation in ("clean-exit", "body-exit"):
                        error = (
                            ValueError("body failure")
                            if operation == "body-exit"
                            else None
                        )
                        other = asyncio.create_task(
                            outcome(
                                f.__aexit__(type(error) if error else None, error, None)
                            )
                        )
                    # All tested contenders reach their acquisition/rejection
                    # boundary in this turn; no time-based sleep is required.
                    await asyncio.sleep(0)
                    release.set()
                    events = {"opener": await outcome(opener)}
                    if other is not None:
                        events["contender"] = await other
                    events["closed_after_open"] = f.closed
                    events["close"] = await outcome(f.close())
                    events["closed"] = f.closed
                    events["resource_closes"] = [r.closes for r in resources]
                    semantic[f"{label}-{operation}"] = events
                finally:
                    release.set()
                    await asyncio.gather(
                        opener, *([other] if other else []), return_exceptions=True
                    )
                    await outcome(f.close())
                    for resource in resources:
                        if not resource.closes:
                            await resource.close()
                    aiofiles.open = original_open

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "native.gz"
                path.write_bytes(b"")
                loop = asyncio.get_running_loop()
                entered = asyncio.Event()
                release, settled = threading.Event(), threading.Event()
                acquired = []

                def acquire_native(
                    *args,
                    acquired=acquired,
                    loop=loop,
                    entered=entered,
                    release=release,
                    settled=settled,
                ):
                    raw = original_sync(*args)
                    acquired.append(raw)
                    loop.call_soon_threadsafe(entered.set)
                    try:
                        if not release.wait(5):
                            raise RuntimeError("open trace watchdog expired")
                        return raw
                    finally:
                        settled.set()

                aiofiles.threadpool.sync_open = acquire_native
                f = cls(path, ("w" if writing else "r") + ("t" if text else "b"))
                opener = asyncio.create_task(f.open())
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    opener.cancel("cancel open")
                    for _ in range(4):
                        await asyncio.sleep(0)
                    release.set()
                    assert await asyncio.to_thread(settled.wait, 5)
                    events = {
                        "opener": await outcome(opener),
                        "close": await outcome(f.close()),
                    }
                    events["acquired_closed"] = [raw.closed for raw in acquired]
                    events["closed"] = f.closed
                    semantic[f"{label}-native-cancel"] = events
                finally:
                    release.set()
                    await asyncio.gather(opener, return_exceptions=True)
                    for raw in acquired:
                        if not raw.closed:
                            raw.close()
                    aiofiles.threadpool.sync_open = original_sync

        for existing_cause in (False, True):

            class BadSink:
                closes = 0

                async def write(self, data, existing_cause=existing_cause):
                    error = OSError("header failure")
                    if existing_cause:
                        raise error from ValueError("original sink cause")
                    raise error

                async def close(self):
                    self.closes += 1
                    raise RuntimeError("cleanup failure")

            sink = BadSink()

            async def acquire_bad(*args, sink=sink, **kwargs):
                return sink

            aiofiles.open = acquire_bad
            f = cls("trace.gz", "wt" if text else "wb")
            try:
                semantic[
                    f"{'text' if text else 'binary'}-header-cleanup-cause-{existing_cause}"
                ] = {
                    "open": await outcome(f.open()),
                    "close": await outcome(f.close()),
                    "resource_closes": sink.closes,
                }
            finally:
                aiofiles.open = original_open

        with tempfile.TemporaryDirectory() as directory:
            acquired = []

            class File(io.FileIO):
                closes = 0

                def close(self):
                    self.closes += 1
                    super().close()
                    raise OSError("raw close failure")

            def acquire_raw(*args, acquired=acquired):
                raw = File(*args)
                acquired.append(raw)
                return raw

            def fail_wrap(*args, **kwargs):
                raise RuntimeError("wrap failure") from ValueError(
                    "original wrap cause"
                )

            aiofiles.threadpool.sync_open = acquire_raw
            aiofiles.threadpool.wrap = fail_wrap
            f = cls(Path(directory) / "wrap.gz", "wt" if text else "wb")
            try:
                events = {
                    "open": await outcome(f.open()),
                    "close": await outcome(f.close()),
                }
                events["acquired_closed"] = [raw.closed for raw in acquired]
                events["resource_closes"] = [raw.closes for raw in acquired]
                semantic[f"{'text' if text else 'binary'}-wrap-cleanup-cause"] = events
            finally:
                aiofiles.threadpool.sync_open = original_sync
                aiofiles.threadpool.wrap = original_wrap
                for raw in acquired:
                    if not raw.closed:
                        try:
                            raw.close()
                        except OSError:
                            pass
    return semantic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    script = Path(__file__).resolve()
    source, harness = git_metadata(root), git_metadata(script.parents[1])
    if args.require_clean and any(
        not m["sha"] or m["status"] for m in (source, harness)
    ):
        parser.error("clean committed source and harness required")
    os.environ["AIOGZIP_ENGINE"] = args.engine
    sys.path.insert(0, str(root / "src"))
    import aiogzip

    if not Path(aiogzip.__file__).resolve().is_relative_to(root / "src"):
        raise RuntimeError("wrong source import")
    semantic = asyncio.run(capture(aiogzip))
    record = dict(
        source=source,
        harness=harness,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        python=sys.version,
        engines=dataclasses.asdict(aiogzip.engine_info()),
        fixture_sha256=hashlib.sha256(b"WP3 named opening scenarios v1").hexdigest(),
        semantic=semantic,
        diagnostic={},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
