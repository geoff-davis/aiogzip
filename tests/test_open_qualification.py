"""WP3 qualification: native acquisition, cleanup, and custom initialization."""

import asyncio
import gzip
import io
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import aiofiles.threadpool
import pytest

import aiogzip
from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
    ConcurrentOperationError,
    _binary,
)


def handle(text, writing, path=None, **options):
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    return cls(path, ("w" if writing else "r") + ("t" if text else "b"), **options)


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
async def test_queued_native_acquisition_survives_repeated_cancel(
    monkeypatch, tmp_path, text, writing
):
    loop = asyncio.get_running_loop()
    queued = asyncio.Event()
    release = threading.Event()
    acquired = []
    original_open = aiofiles.threadpool.sync_open
    original_submit = loop.run_in_executor
    path = tmp_path / "queued.gz"
    path.write_bytes(gzip.compress(b"payload"))

    def acquire(*args):
        raw = original_open(*args)
        acquired.append(raw)
        return raw

    with ThreadPoolExecutor(max_workers=1) as executor:
        blocker = executor.submit(release.wait, 5)

        def submit(selected, function, *args):
            future = original_submit(
                executor if selected is None else selected, function, *args
            )
            if function is acquire:
                queued.set()
            return future

        monkeypatch.setattr(aiofiles.threadpool, "sync_open", acquire)
        monkeypatch.setattr(loop, "run_in_executor", submit)
        f = handle(text, writing, path)
        opener = asyncio.create_task(f.open())
        try:
            await asyncio.wait_for(queued.wait(), 5)
            for index in range(3):
                opener.cancel(f"request-{index}")
                await asyncio.sleep(0)
            assert not acquired and not opener.done()
            with pytest.raises(ConcurrentOperationError):
                await f.close()
            release.set()
            with pytest.raises(asyncio.CancelledError, match="request-0"):
                await opener
            assert len(acquired) == 1 and acquired[0].closed
            assert (f._binary_file if text else f._file) is None
            await f.close()
        finally:
            release.set()
            await asyncio.gather(opener, return_exceptions=True)
            blocker.result(timeout=5)
            for raw in acquired:
                raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
def test_runner_shutdown_settles_native_acquisition(tmp_path, text, writing):
    script = r"""
import asyncio, io, json, sys, threading
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
import aiogzip
import aiofiles.threadpool
assert Path(aiogzip.__file__).resolve() == Path(sys.argv[1]).resolve()
text, writing = sys.argv[3] == "True", sys.argv[4] == "True"
acquired = []
release = threading.Event()
class File(io.FileIO):
    closes = 0
    def close(self):
        self.closes += 1
        super().close()
async def main():
    global opener, f, timer
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    def acquire(path, mode):
        raw = File(path, mode)
        acquired.append(raw)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("shutdown watchdog expired")
        return raw
    aiofiles.threadpool.sync_open = acquire
    cls = aiogzip.AsyncGzipTextFile if text else aiogzip.AsyncGzipBinaryFile
    f = cls(sys.argv[2], ("w" if writing else "r") + ("t" if text else "b"))
    opener = asyncio.create_task(f.open())
    await asyncio.wait_for(entered.wait(), 5)
    timer = threading.Timer(0.05, release.set)
    timer.start()
    # asyncio.run itself cancels the outstanding opener.
try:
    asyncio.run(main())
    timer.join()
    print(json.dumps(dict(cancelled=opener.cancelled(), closed=acquired[0].closed,
        closes=acquired[0].closes, unpublished=(f._binary_file if text else f._file) is None)))
finally:
    release.set()
    for raw in acquired:
        if not raw.closed:
            raw.close()
"""
    path = tmp_path / "shutdown.gz"
    path.write_bytes(b"")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            aiogzip.__file__,
            str(path),
            str(text),
            str(writing),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert json.loads(result.stdout) == dict(
        cancelled=True, closed=True, closes=1, unpublished=True
    )


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("primary_kind", ["header", "wrap"])
async def test_native_cleanup_stays_reserved_through_repeated_cancel(
    monkeypatch, tmp_path, text, primary_kind
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    original_cause = ValueError("original cause")
    primary = OSError("initialization failed")
    primary.__cause__ = original_cause
    events = []

    class File(io.FileIO):
        def write(self, data):
            raise primary

        def close(self):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("close watchdog expired")
            events.append("close")
            super().close()

    raw = File(tmp_path / "cleanup.gz", "wb")
    monkeypatch.setattr(aiofiles.threadpool, "sync_open", lambda *args: raw)
    if primary_kind == "wrap":

        def fail_wrap(*args, **kwargs):
            raise primary

        monkeypatch.setattr(aiofiles.threadpool, "wrap", fail_wrap)
    f = handle(text, True, tmp_path / "cleanup.gz")
    opener = asyncio.create_task(f.open())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for index in range(3):
            opener.cancel(f"cleanup-{index}")
            await asyncio.sleep(0)
        assert not opener.done() and not raw.closed
        with pytest.raises(ConcurrentOperationError):
            await f.open()
        with pytest.raises(ConcurrentOperationError):
            await f.close()
        release.set()
        with pytest.raises(OSError) as caught:
            await opener
        assert caught.value is primary
        assert primary.__cause__ is original_cause
        assert any("CancelledError" in note for note in primary.__notes__)
        assert events == ["close"] and raw.closed
        assert (f._binary_file if text else f._file) is None
        await f.close()
    finally:
        release.set()
        await asyncio.gather(opener, return_exceptions=True)
        if not raw.closed:
            raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_custom_initialization_failure_is_unpublished_and_retryable(
    monkeypatch, text, writing, external, failure
):
    entered = asyncio.Event()
    release = asyncio.Event()
    resources = []

    class Resource:
        closes = 0
        fail = True

        def __init__(self):
            self.data = bytearray()

        async def initialize(self):
            if self.fail:
                self.fail = False
                entered.set()
                await release.wait()
                if failure == "error":
                    raise OSError("initialization error")

        async def write(self, data):
            await self.initialize()
            self.data.extend(data)
            return len(data)

        async def read(self, size=-1):
            return b""

        async def seek(self, *args):
            return 0

        async def seekable(self):
            await self.initialize()
            return True

        async def close(self):
            self.closes += 1

    resource = Resource()

    async def acquire(*args, **kwargs):
        resources.append(resource)
        return resource

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    f = handle(
        text,
        writing,
        None if external else "unused.gz",
        **(dict(fileobj=resource, closefd=False) if external else {}),
    )
    opener = asyncio.create_task(f.open())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (f._binary_file if text else f._file) is None
        with pytest.raises(ConcurrentOperationError):
            await f.open()
        with pytest.raises(ConcurrentOperationError):
            await f.close()
        if failure == "cancel":
            opener.cancel()
        release.set()
        if failure == "error" and not writing:
            # A failing seekability probe has always meant non-seekable.
            assert await opener is f
        else:
            with pytest.raises(
                asyncio.CancelledError if failure == "cancel" else OSError
            ):
                await opener
            assert resource.closes == (0 if external else 1)
            assert (f._binary_file if text else f._file) is None
            # A fresh acquisition or caller-owned resource can be retried.
            if not external:
                resource = Resource()
                resource.fail = False
            assert await f.open() is f
        await f.close()
        await f.close()
        assert resource.closes == (0 if external else 1)
    finally:
        release.set()
        await asyncio.gather(opener, return_exceptions=True)
        await f.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize(
    "outcome", ["short", "zero", "negative", "bool", "none", "excess", "error"]
)
async def test_partial_initial_header_ownership(monkeypatch, text, external, outcome):
    primary = OSError("after partial header")
    original_cause = ValueError("sink cause")
    primary.__cause__ = original_cause

    class Sink:
        def __init__(self):
            self.data = bytearray()
            self.calls = 0
            self.closes = 0

        async def write(self, data):
            self.calls += 1
            if self.calls > 1 and outcome != "short":
                if outcome == "error":
                    raise primary
                return {
                    "zero": 0,
                    "negative": -1,
                    "bool": True,
                    "none": None,
                    "excess": len(data) + 1,
                }[outcome]
            self.data.extend(data[:2])
            return min(2, len(data))

        async def close(self):
            self.closes += 1

    sink = Sink()

    async def acquire(*args, **kwargs):
        return sink

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    f = handle(
        text,
        True,
        None if external else "header.gz",
        **(dict(fileobj=sink, closefd=False) if external else {}),
    )
    try:
        if outcome == "short":
            await f.open()
            await f.write("payload" if text else b"payload")
            await f.close()
            assert gzip.decompress(sink.data) == b"payload"
        else:
            with pytest.raises(OSError) as caught:
                await f.open()
            if outcome == "error":
                assert caught.value is primary and primary.__cause__ is original_cause
            assert bytes(sink.data) == b"\x1f\x8b"
            assert (f._binary_file if text else f._file) is None
            with pytest.raises(ValueError, match="not opened"):
                await f.write("late" if text else b"late")
        await f.close()
        await f.close()
        assert sink.closes == (0 if external else 1)
    finally:
        await f.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.parametrize("body_error", [False, True])
async def test_context_exit_during_open_does_not_abandon_opener(
    monkeypatch, text, writing, body_error
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
    f = handle(text, writing, "unused.gz")
    opener = asyncio.create_task(f.open())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if body_error:
            # Equivalent to the context protocol's exceptional exit: it must
            # not replace the body's error or claim to have closed the opener.
            error = ValueError("body failure")
            assert await f.__aexit__(ValueError, error, None) is None
        else:
            with pytest.raises(ConcurrentOperationError):
                await f.__aexit__(None, None, None)
        assert not f.closed and not opener.done() and resource.closes == 0
        release.set()
        assert await opener is f
        if text:
            assert f.buffer._closed_observer is not None
            assert f.buffer._read_poison_observer is not None
            await f.buffer.close()
            assert f.closed
        await f.close()
        assert resource.closes == 1
    finally:
        release.set()
        await asyncio.gather(opener, return_exceptions=True)
        await f.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("writing", [False, True])
async def test_native_acquisition_error_and_cancel_preserve_primary_cancel(
    monkeypatch, tmp_path, text, writing
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    failure = OSError("acquisition failed")

    def acquire(*args):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("acquisition watchdog expired")
        raise failure

    monkeypatch.setattr(aiofiles.threadpool, "sync_open", acquire)
    f = handle(text, writing, tmp_path / "failed.gz")
    opener = asyncio.create_task(f.open())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for index in range(3):
            opener.cancel(f"acquire-{index}")
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError, match="acquire-0") as caught:
            await opener
        assert caught.value.__cause__ is failure
        assert (f._binary_file if text else f._file) is None
        await f.close()
    finally:
        release.set()
        await asyncio.gather(opener, return_exceptions=True)
        await f.close()


@pytest.mark.parametrize("text", [False, True])
async def test_cooperative_cleanup_finishes_before_releasing_open_reservation(
    monkeypatch, text
):
    entered, release = asyncio.Event(), asyncio.Event()
    events = []
    primary = OSError("header failed")

    class Resource:
        async def write(self, data):
            raise primary

        async def close(self):
            entered.set()
            try:
                await release.wait()
            finally:
                # The cooperative close completes its resource work even when
                # cancelled; no hidden source activity survives this boundary.
                events.append("closed")

    async def acquire(*args, **kwargs):
        return Resource()

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    f = handle(text, True, "unused.gz")
    opener = asyncio.create_task(f.open())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(ConcurrentOperationError):
            await f.close()
        with pytest.raises(ConcurrentOperationError):
            await f.open()
        opener.cancel("during cleanup")
        with pytest.raises(OSError) as caught:
            await opener
        assert caught.value is primary
        assert events == ["closed"]
        assert any("during cleanup" in note for note in primary.__notes__)
        assert (f._binary_file if text else f._file) is None
        await f.close()
    finally:
        release.set()
        await asyncio.gather(opener, return_exceptions=True)
        await f.close()
