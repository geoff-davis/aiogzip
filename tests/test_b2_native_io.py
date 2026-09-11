"""Native I/O and isolated runner-shutdown reproductions for b2 WP0."""

import asyncio
import gzip
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import aiofiles.threadpool
import pytest

from aiogzip import AsyncGzipBinaryFile


@pytest.mark.xfail(strict=True, reason="F2: aiofiles read loses consumed member A")
async def test_native_source_consumption_cannot_accept_suffix(monkeypatch, tmp_path):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    settled = threading.Event()
    a, b = b"native member A\n", b"native member B\n"
    wire_a = gzip.compress(a, mtime=0)
    path = tmp_path / "members.gz"
    path.write_bytes(wire_a + gzip.compress(b, mtime=0))

    class GatedReader(io.BufferedReader):
        def read(self, size=-1):
            if self.tell() == 0:
                result = super().read(len(wire_a))
                loop.call_soon_threadsafe(entered.set)
                try:
                    if not release.wait(5):
                        raise RuntimeError("native read watchdog expired")
                    return result
                finally:
                    settled.set()
            return super().read(size)

    raw = GatedReader(io.FileIO(path, "rb"))
    monkeypatch.setattr(aiofiles.threadpool, "sync_open", lambda *a, **kw: raw)
    f = AsyncGzipBinaryFile(path, "rb")
    caller = None
    try:
        await f.open()
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(entered.wait(), 5)
        caller.cancel()
        for _ in range(8):
            await asyncio.sleep(0)
        release.set()
        assert await asyncio.to_thread(settled.wait, 5)
        with pytest.raises(asyncio.CancelledError):
            await caller
        try:
            result = await f.read()
        except OSError:
            return
        assert result == a + b, f"accepted native suffix-only stream: {result!r}"
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        if entered.is_set():
            assert await asyncio.to_thread(settled.wait, 5)
        await f.close()
        raw.close()


@pytest.mark.xfail(strict=True, reason="F1: runner shutdown cancels native helper")
def test_actual_runner_shutdown_preserves_native_cleanup_order():
    # asyncio.run really cancels all outstanding tasks in this CHILD process.
    # A timer releases native work independently of the event loop. The parent
    # has a separate process timeout; neither watchdog depends on asyncio progress.
    program = r"""
import asyncio
import json
import threading
from aiogzip._codec_async import _drive_operation

events = []
release = threading.Event()
timer = None

async def main():
    global timer
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()

    class Operation:
        def _advance_raw(self):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("worker watchdog expired")
            events.append("last native access")
            return b"output"

        def close(self):
            events.append("cleanup")

    stream = _drive_operation(Operation(), workload=b"x", offload_threshold=1)
    caller = asyncio.create_task(anext(stream))
    await asyncio.wait_for(entered.wait(), 5)
    timer = threading.Timer(0.1, release.set)
    timer.start()
    # Returning invokes asyncio.run's blanket shutdown cancellation.
    assert not caller.done()

try:
    asyncio.run(main())
finally:
    release.set()
    if timer is not None:
        timer.join()
print(json.dumps(events))
"""
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert json.loads(result.stdout) == ["last native access", "cleanup"]
