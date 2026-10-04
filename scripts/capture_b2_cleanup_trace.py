#!/usr/bin/env python3
"""Failed-open cleanup cancellation must retain b1 control-flow outcomes."""

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

from capture_b2_open_trace import outcome
from capture_file_state_trace import git_metadata


async def capture(package):
    import aiofiles
    import aiofiles.threadpool

    original_open = aiofiles.open
    original_sync = aiofiles.threadpool.sync_open
    semantic = {}
    for text in (False, True):
        for native in (False, True):
            for control in ("cancel", "timeout"):
                loop = asyncio.get_running_loop()
                entered = asyncio.Event()
                release, settled = threading.Event(), threading.Event()
                closes = []
                timeout = None
                primary = OSError("header failed")

                class File(io.FileIO):
                    def write(self, data, primary=primary):
                        raise primary

                    def close(
                        self,
                        loop=loop,
                        entered=entered,
                        release=release,
                        settled=settled,
                        closes=closes,
                    ):
                        loop.call_soon_threadsafe(entered.set)
                        try:
                            if not release.wait(5):
                                raise RuntimeError("cleanup trace watchdog expired")
                            closes.append("close")
                            super().close()
                        finally:
                            settled.set()

                class Custom:
                    async def write(self, data, primary=primary):
                        raise primary

                    async def close(self, entered=entered, closes=closes):
                        entered.set()
                        try:
                            await asyncio.Future()
                        finally:
                            closes.append("close")

                async def acquire_custom(*args, **kwargs):
                    return Custom()

                def acquire_native(*args, **kwargs):
                    filename = args[0] if args else kwargs["file"]
                    mode = args[1] if len(args) > 1 else kwargs["mode"]
                    return File(filename, mode)

                with tempfile.TemporaryDirectory() as directory:
                    if native:
                        aiofiles.threadpool.sync_open = acquire_native
                    else:
                        aiofiles.open = acquire_custom
                    cls = (
                        package.AsyncGzipTextFile
                        if text
                        else package.AsyncGzipBinaryFile
                    )
                    f = cls(Path(directory) / "cleanup.gz", "wt" if text else "wb")

                    async def open_with_timeout(f=f):
                        nonlocal timeout
                        async with asyncio.timeout(None) as timeout:
                            await f.open()

                    opener = asyncio.create_task(
                        open_with_timeout() if control == "timeout" else f.open()
                    )
                    timer = None
                    try:
                        await asyncio.wait_for(entered.wait(), 5)
                        if control == "timeout":
                            timeout.reschedule(loop.time() - 1)
                        else:
                            opener.cancel("cleanup cancellation")
                        timer = threading.Timer(0.03, release.set)
                        timer.start()
                        result = await outcome(opener)
                        # b1 can return before native close settles. Retain the
                        # resource until the independent worker gate completes;
                        # this trace isolates control flow, not settlement timing.
                        if native:
                            assert await asyncio.to_thread(settled.wait, 5)
                        semantic[
                            f"{'text' if text else 'binary'}-{'native' if native else 'custom'}-{control}"
                        ] = dict(
                            outcome=result,
                            cancelled=opener.cancelled(),
                            cancelling=opener.cancelling(),
                            closes=len(closes),
                        )
                    finally:
                        release.set()
                        if timer is not None:
                            timer.join()
                        await asyncio.gather(opener, return_exceptions=True)
                        await f.close()
                        aiofiles.open = original_open
                        aiofiles.threadpool.sync_open = original_sync
    return semantic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    root, script = args.source_root.resolve(), Path(__file__).resolve()
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
    record = dict(
        source=source,
        harness=harness,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        python=sys.version,
        engines=dataclasses.asdict(aiogzip.engine_info()),
        fixture_sha256=hashlib.sha256(b"WP3 cleanup control flow v1").hexdigest(),
        semantic=asyncio.run(capture(aiogzip)),
        diagnostic={},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
