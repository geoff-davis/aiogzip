"""An interrupt raised by the late close of a cancelled open propagates (#158).

When a path open completes after its caller was cancelled, the late file is
closed. An interrupt from that close (``KeyboardInterrupt``, ``SystemExit``)
once became a note on the cancellation; the branch for an ordinary failure
already let it propagate. BC26.
"""

import asyncio
import io
import sys
import threading
from pathlib import Path

import aiofiles.threadpool
import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

sys.path.insert(0, str(Path(__file__).parent / "stateful"))
from model import OPENING, U  # noqa: E402
from observer import assert_lifecycle  # noqa: E402


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.parametrize("repeated_cancel", [False, True])
@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
async def test_interrupt_from_the_late_close_outranks_the_cancellation(
    monkeypatch, tmp_path, text, writing, repeated_cancel, interrupt_type
):
    loop = asyncio.get_running_loop()
    interrupt = interrupt_type("injected interrupt")
    entered_open, entered_close = asyncio.Event(), asyncio.Event()
    release_open, release_close = threading.Event(), threading.Event()
    acquired = []

    class File(io.FileIO):
        closes = 0

        def close(self):
            if self.closes:
                return super().close()
            loop.call_soon_threadsafe(entered_close.set)
            if not release_close.wait(5):
                raise RuntimeError("cleanup watchdog expired")
            self.closes += 1
            super().close()
            raise interrupt

    def acquire(*args):
        raw = File(*args)
        acquired.append(raw)
        loop.call_soon_threadsafe(entered_open.set)
        if not release_open.wait(5):
            raise RuntimeError("open watchdog expired")
        return raw

    monkeypatch.setattr(aiofiles.threadpool, "sync_open", acquire)
    path = tmp_path / "interrupt.gz"
    path.write_bytes(b"")
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls(path, ("w" if writing else "r") + ("t" if text else "b"))
    # The interrupt must be caught in this task: one that escapes a task
    # stops the event loop.
    opener = asyncio.current_task()

    async def drive():
        await asyncio.wait_for(entered_open.wait(), 5)
        opener.cancel("original acquisition cancel")
        release_open.set()
        await asyncio.wait_for(entered_close.wait(), 5)
        if repeated_cancel:
            opener.cancel("later cleanup cancel")
            await asyncio.sleep(0)
        release_close.set()

    driver = asyncio.create_task(drive())
    try:
        with pytest.raises(interrupt_type) as caught:
            await f.open()
        while opener.uncancel():
            pass
        assert caught.value is interrupt
        context = interrupt.__context__
        assert isinstance(context, asyncio.CancelledError)
        assert context.args == ("original acquisition cancel",)
        assert not hasattr(context, "__notes__")
        assert acquired[0].closed and acquired[0].closes == 1
        assert_lifecycle(f, OPENING, "acquisition_fails")
        await f.close()
        assert_lifecycle(f, U, "close")
    finally:
        release_open.set()
        release_close.set()
        await asyncio.gather(driver, return_exceptions=True)
        for raw in acquired:
            raw.close()
        await f.close()
