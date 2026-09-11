"""WP0 acquisition/initialization evidence; no production repairs yet."""

import asyncio
import threading

import aiofiles.threadpool
import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
    ConcurrentOperationError,
    _binary,
)


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="F3: close misses late acquisition"
)
async def test_close_during_acquisition_has_no_late_resource_owner(
    monkeypatch, text, writing
):
    entered, release = asyncio.Event(), asyncio.Event()

    class Resource:
        closes = 0

        async def write(self, data):
            return len(data)

        async def close(self):
            self.closes += 1

    resource = Resource()

    async def acquire(*args, **kwargs):
        entered.set()
        await release.wait()
        return resource

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls("unused.gz", ("w" if writing else "r") + ("t" if text else "b"))
    opener = asyncio.create_task(f.open())
    closer = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        closer = asyncio.create_task(f.close())
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(opener, closer, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(
                result, ConcurrentOperationError
            ):
                raise result
        await f.close()
        observed_closes = resource.closes
    finally:
        release.set()
        await asyncio.gather(
            opener, *([closer] if closer else []), return_exceptions=True
        )
        await f.close()
        if not resource.closes:
            await resource.close()
    assert f.closed and observed_closes == 1, observed_closes


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F3: cancelled native open loses its resource",
)
async def test_native_acquisition_cancel_has_a_final_owner(
    monkeypatch, tmp_path, text, writing
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release, settled = threading.Event(), threading.Event()
    path = tmp_path / "native-open.gz"
    path.write_bytes(b"")
    acquired = []
    original_open = aiofiles.threadpool.sync_open

    def acquire(*args, **kwargs):
        raw = original_open(*args, **kwargs)
        acquired.append(raw)
        loop.call_soon_threadsafe(entered.set)
        try:
            if not release.wait(5):
                raise RuntimeError("native open watchdog expired")
            return raw
        finally:
            settled.set()

    monkeypatch.setattr(aiofiles.threadpool, "sync_open", acquire)
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls(path, ("w" if writing else "r") + ("t" if text else "b"))
    opener = asyncio.create_task(f.open())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        opener.cancel()
        for _ in range(8):
            await asyncio.sleep(0)
        release.set()
        assert await asyncio.to_thread(settled.wait, 5)
        with pytest.raises(asyncio.CancelledError):
            await opener
        await f.close()
        observed_closed = acquired[0].closed
    finally:
        release.set()
        await asyncio.gather(opener, return_exceptions=True)
        if entered.is_set():
            assert await asyncio.to_thread(settled.wait, 5)
        await f.close()
        for raw in acquired:
            raw.close()
    assert observed_closed


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.parametrize("external", [False, True])
async def test_codec_initialization_failure_preserves_resource_ownership(
    monkeypatch, text, writing, external
):
    class Resource:
        closes = 0

        async def read(self, size=-1):
            return b""

        async def write(self, data):
            return len(data)

        async def close(self):
            self.closes += 1

    resource = Resource()

    async def acquire(*args, **kwargs):
        return resource

    def fail_codec(*args, **kwargs):
        raise RuntimeError("injected codec initialization failure")

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    monkeypatch.setattr(
        _binary, "GzipEncoder" if writing else "GzipDecoder", fail_codec
    )
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    kwargs = {"fileobj": resource, "closefd": False} if external else {}
    f = cls(
        None if external else "unused.gz",
        ("w" if writing else "r") + ("t" if text else "b"),
        **kwargs,
    )
    with pytest.raises(RuntimeError, match="injected codec initialization failure"):
        await f.open()
    await f.close()
    await f.close()
    assert resource.closes == (0 if external else 1)
