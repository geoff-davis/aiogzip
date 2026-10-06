"""WP3 opening reservations and unpublished native initialization ownership."""

import asyncio
import gzip
import io
import sys
import threading
from pathlib import Path

import aiofiles.threadpool
import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
    ConcurrentOperationError,
    _binary,
)

sys.path.insert(0, str(Path(__file__).parent / "stateful"))
from model import CLOSED, OPENING, U  # noqa: E402
from observer import assert_lifecycle  # noqa: E402


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.parametrize("ownership", ["path", "borrowed", "closefd"])
@pytest.mark.parametrize("cancellations", [1, 3])
async def test_native_initialization_remains_owned_until_settled(
    monkeypatch, tmp_path, text, writing, ownership, cancellations
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    events = []
    path = tmp_path / "initialization.gz"
    path.write_bytes(gzip.compress(b"payload"))

    def gate():
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("initialization watchdog expired")
        events.append("last access")

    class Reader(io.BufferedReader):
        def seekable(self):
            result = super().seekable()
            gate()
            return result

        def close(self):
            events.append("close")
            super().close()

    class Writer(io.BufferedWriter):
        def write(self, data):
            result = super().write(data)
            gate()
            return result

        def close(self):
            events.append("close")
            super().close()

    raw = (Writer if writing else Reader)(io.FileIO(path, "wb" if writing else "rb"))
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    options = {}
    if ownership == "path":
        monkeypatch.setattr(aiofiles.threadpool, "sync_open", lambda *a, **k: raw)
    else:
        options = dict(
            fileobj=aiofiles.threadpool.wrap(raw, loop=loop),
            closefd=ownership == "closefd",
        )
    f = cls(
        path if ownership == "path" else None,
        ("w" if writing else "r") + ("t" if text else "b"),
        **options,
    )
    opener = asyncio.create_task(f.open())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert_lifecycle(f, U, "open_starts")
        with pytest.raises(ConcurrentOperationError):
            await f.open()
        with pytest.raises(ConcurrentOperationError):
            await f.close()
        assert_lifecycle(f, OPENING, "overlapping_open_or_close")
        for number in range(cancellations):
            opener.cancel(f"cancel-{number}")
            await asyncio.sleep(0)
        assert not opener.done()
        assert not raw.closed
        release.set()
        with pytest.raises(asyncio.CancelledError, match="cancel-0"):
            await opener
        assert events == (
            ["last access", "close"] if ownership == "path" else ["last access"]
        )
        assert_lifecycle(f, OPENING, "initialization_fails")
        await f.close()
        assert_lifecycle(f, U, "close")
        await f.close()
        assert_lifecycle(f, CLOSED, "close")
        assert events.count("close") == (1 if ownership == "path" else 0)
    finally:
        release.set()
        await asyncio.gather(opener, return_exceptions=True)
        await f.close()
        if not raw.closed:
            raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
async def test_cancel_before_open_starts_does_not_acquire(monkeypatch, text, writing):
    acquired = []

    async def acquire(*args, **kwargs):
        acquired.append(True)
        raise AssertionError("must not acquire")

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls("unused.gz", ("w" if writing else "r") + ("t" if text else "b"))
    opener = asyncio.create_task(f.open())
    opener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opener
    assert not acquired
    await f.close()
    assert_lifecycle(f, U, "close")


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("existing_cause", [False, True])
async def test_failed_header_preserves_primary_error_when_cleanup_fails(
    monkeypatch, text, existing_cause
):
    events = []
    primary = OSError("header failure")
    original_cause = ValueError("sink cause") if existing_cause else None
    primary.__cause__ = original_cause
    cleanup = RuntimeError("cleanup failure")

    class Resource:
        async def write(self, data):
            raise primary

        async def close(self):
            events.append("close")
            raise cleanup

    async def acquire(*args, **kwargs):
        return Resource()

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls("unused.gz", "wt" if text else "wb")
    with pytest.raises(OSError) as caught:
        await f.open()
    assert caught.value is primary
    assert primary.__cause__ is original_cause
    assert primary.__notes__ == [
        "Opening cleanup also failed: RuntimeError('cleanup failure')"
    ]
    assert events == ["close"]
    assert_lifecycle(f, OPENING, "cleanup_raises_exception")
    await f.close()
    assert_lifecycle(f, U, "close")
    assert events == ["close"]


@pytest.mark.parametrize("text", [False, True])
async def test_native_wrap_failure_closes_acquired_resource(
    monkeypatch, tmp_path, text
):
    path = tmp_path / "wrap.gz"
    path.write_bytes(b"")
    acquired = []
    original = aiofiles.threadpool.sync_open

    def acquire(*args, **kwargs):
        raw = original(*args, **kwargs)
        acquired.append(raw)
        return raw

    def fail_wrap(*args, **kwargs):
        raise RuntimeError("wrap failed")

    monkeypatch.setattr(aiofiles.threadpool, "sync_open", acquire)
    monkeypatch.setattr(aiofiles.threadpool, "wrap", fail_wrap)
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls(path, "rt" if text else "rb")
    try:
        with pytest.raises(RuntimeError, match="wrap failed"):
            await f.open()
        assert len(acquired) == 1 and acquired[0].closed
        assert_lifecycle(f, OPENING, "initialization_fails")
        await f.close()
        assert_lifecycle(f, U, "close")
    finally:
        for raw in acquired:
            raw.close()
