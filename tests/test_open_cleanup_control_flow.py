"""Cleanup control flow outranks ordinary failed-open errors."""

import asyncio
import io
import threading

import aiofiles.threadpool
import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile, _binary, _text


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("route", ["custom-header", "native-header", "native-wrap"])
async def test_timeout_during_failed_open_cleanup(monkeypatch, tmp_path, text, route):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release, settled = threading.Event(), threading.Event()
    timeout_ready = asyncio.Event()
    timeout = None
    events = []
    primary = OSError("initialization failure")
    original_cause = ValueError("original cause")
    primary.__cause__ = original_cause

    class File(io.FileIO):
        def write(self, data):
            raise primary

        def close(self):
            loop.call_soon_threadsafe(entered.set)
            try:
                if not release.wait(5):
                    raise RuntimeError("cleanup watchdog expired")
                events.append("close")
                super().close()
            finally:
                settled.set()

    class Custom:
        async def write(self, data):
            raise primary

        async def close(self):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                events.append("close")

    raw = None
    if route == "custom-header":

        async def acquire(*args, **kwargs):
            return Custom()

        monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    else:
        raw = File(tmp_path / "timeout.gz", "wb")
        monkeypatch.setattr(aiofiles.threadpool, "sync_open", lambda *args: raw)
        if route == "native-wrap":

            def fail_wrap(*args, **kwargs):
                raise primary

            monkeypatch.setattr(aiofiles.threadpool, "wrap", fail_wrap)
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls(tmp_path / "timeout.gz", "wt" if text else "wb")

    async def open_with_timeout():
        nonlocal timeout
        async with asyncio.timeout(None) as timeout:
            timeout_ready.set()
            await f.open()

    opener = asyncio.create_task(open_with_timeout())
    timer = None
    try:
        await asyncio.wait_for(timeout_ready.wait(), 5)
        await asyncio.wait_for(entered.wait(), 5)
        timeout.reschedule(loop.time() - 1)
        timer = threading.Timer(0.03, release.set)
        timer.start()
        with pytest.raises(TimeoutError) as caught:
            await opener
        cancellation = caught.value.__cause__
        assert isinstance(cancellation, asyncio.CancelledError)
        assert cancellation.__context__ is primary
        assert primary.__cause__ is original_cause
        assert opener.cancelling() == 0
        assert events == ["close"]
        if raw is not None:
            assert raw.closed and settled.is_set()
        assert (f._binary_file if text else f._file) is None
    finally:
        release.set()
        if timer is not None:
            timer.join()
        await asyncio.gather(opener, return_exceptions=True)
        if raw is not None and not raw.closed:
            raw.close()
        await f.close()


@pytest.mark.parametrize("control", ["cancel", "timeout", "interrupt"])
async def test_text_wrapper_cleanup_control_flow(monkeypatch, control):
    entered = asyncio.Event()
    primary = OSError("binary setup failed")
    original_cause = ValueError("setup cause")
    primary.__cause__ = original_cause
    events = []
    timeout = None

    class Interrupt(BaseException):
        pass

    class Binary:
        def __init__(self, *args, **kwargs):
            pass

        async def open(self):
            raise primary

        async def close(self):
            entered.set()
            if control == "interrupt":
                events.append("close")
                raise Interrupt("cleanup interrupted")
            try:
                await asyncio.Future()
            finally:
                events.append("close")

    monkeypatch.setattr(_text, "AsyncGzipBinaryFile", Binary)
    f = AsyncGzipTextFile("unused.gz", "rt")

    async def open_with_timeout():
        nonlocal timeout
        async with asyncio.timeout(None) as timeout:
            await f.open()

    opener = asyncio.create_task(
        open_with_timeout() if control == "timeout" else f.open()
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if control == "cancel":
            opener.cancel("outside cancel")
        elif control == "timeout":
            timeout.reschedule(asyncio.get_running_loop().time() - 1)
        expected = {
            "cancel": asyncio.CancelledError,
            "timeout": TimeoutError,
            "interrupt": Interrupt,
        }[control]
        with pytest.raises(expected) as caught:
            await opener
        error = caught.value.__cause__ if control == "timeout" else caught.value
        assert error.__context__ is primary
        assert primary.__cause__ is original_cause
        assert events == ["close"]
        assert f._binary_file is None
        if control == "cancel":
            assert opener.cancelled()
        elif control == "timeout":
            assert opener.cancelling() == 0
    finally:
        opener.cancel()
        await asyncio.gather(opener, return_exceptions=True)
        await f.close()
