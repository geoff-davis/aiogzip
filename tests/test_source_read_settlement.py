"""WP2: real native settlement and conservative custom-source consumption."""

import asyncio
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import aiofiles.threadpool
import pytest

import aiogzip
from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile, ConcurrentOperationError

PAYLOAD = hashlib.shake_256(b"WP2 member A").digest(2048).hex().encode() + b"\n"
TAIL = b"distinct member B\n"
MEMBER = gzip.compress(PAYLOAD, mtime=0)
WIRE = MEMBER + gzip.compress(TAIL, mtime=0)
CUTS = {
    "header": 5,
    "body": len(MEMBER) // 2,
    "trailer": len(MEMBER) - 4,
    "member": len(MEMBER),
}


def wrapper(source, text, *, closefd=False, **options):
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    return cls(None, "rt" if text else "rb", fileobj=source, closefd=closefd, **options)


def expected(text):
    return (PAYLOAD + TAIL).decode() if text else PAYLOAD + TAIL


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("boundary", list(CUTS))
@pytest.mark.parametrize("repetitions", [1, 3])
@pytest.mark.parametrize("rewind", [False, True])
async def test_native_cancel_retains_exact_input(
    tmp_path, text, boundary, repetitions, rewind
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    events = []
    path = tmp_path / "members.gz"
    path.write_bytes(WIRE)

    class Reader(io.BufferedReader):
        gated = False

        def read(self, size=-1):
            if not self.gated:
                self.gated = True
                data = super().read(CUTS[boundary])
                events.append("consumed")
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("native read watchdog expired")
                events.append("settled")
                return data
            return super().read(size)

        def close(self):
            events.append("close")
            super().close()

    raw = Reader(io.FileIO(path, "rb"))
    source = aiofiles.threadpool.wrap(raw, loop=loop)
    f = wrapper(source, text, closefd=False)
    caller = None
    try:
        await f.open()
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(repetitions):
            caller.cancel()
            await asyncio.sleep(0)
            assert not caller.done()
            operations = [f.read(1), f.seek(0), f.close()]
            if text:
                operations.extend(
                    [f.buffer.read(1), f.buffer.seek(0), f.buffer.close()]
                )
            for operation in operations:
                with pytest.raises(ConcurrentOperationError):
                    await operation
        assert not raw.closed
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert events == ["consumed", "settled"]
        if rewind:
            assert await f.seek(0) == 0
        assert await f.read() == expected(text)
        assert await f.read() == ("" if text else b"")
        await f.close()
        assert not raw.closed
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()
        raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("boundary", list(CUTS))
@pytest.mark.parametrize("failure", ["cancel", "error"])
@pytest.mark.parametrize("seekable", [False, True])
async def test_custom_consumption_is_terminal_until_physical_rewind(
    text, boundary, failure, seekable
):
    entered, release = asyncio.Event(), asyncio.Event()

    class Source:
        first = True
        closed = False

        def __init__(self):
            self.buffer = io.BytesIO(WIRE)

        def tell(self):
            return self.buffer.tell()

        async def seekable(self):
            return seekable

        async def seek(self, offset, whence=0):
            if not seekable:
                raise OSError("not seekable")
            return self.buffer.seek(offset, whence)

        async def read(self, size=-1):
            if self.first:
                self.first = False
                data = self.buffer.read(CUTS[boundary])
                entered.set()
                if failure == "error":
                    raise OSError("failure after consumption")
                await release.wait()
                return data
            return self.buffer.read(size)

        async def close(self):
            self.closed = True

    source = Source()
    f = wrapper(source, text)
    caller = None
    try:
        await f.open()
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(entered.wait(), 5)
        if failure == "cancel":
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
        else:
            with pytest.raises(OSError, match="failure after consumption"):
                await caller
        for read in (f.read(), f.readline(), f.readlines()):
            with pytest.raises(OSError, match="broken"):
                await read
        if text:
            with pytest.raises(OSError, match="broken"):
                await f.buffer.read()
        if seekable:
            assert await f.seek(0) == 0
            assert await f.read() == expected(text)
        else:
            # The replay cache cannot recover a gap in physical consumption.
            with pytest.raises(OSError, match="not seekable"):
                await f.seek(0)
            with pytest.raises(OSError, match="broken"):
                await f.read()
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()
        assert not source.closed


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("failure", ["cancel", "error"])
@pytest.mark.parametrize("checkpoint", [False, True])
async def test_custom_no_effect_retry_requires_checkpoint(text, failure, checkpoint):
    entered = asyncio.Event()

    class Source:
        first = True

        def __init__(self):
            self.buffer = io.BytesIO(WIRE)
            self.tell = self.buffer.tell if checkpoint else None

        async def read(self, size=-1):
            if self.first:
                self.first = False
                entered.set()
                if failure == "error":
                    raise OSError("transient")
                await asyncio.Future()
            return self.buffer.read(size)

    f = wrapper(Source(), text)
    caller = None
    try:
        await f.open()
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(entered.wait(), 5)
        if failure == "cancel":
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
        else:
            with pytest.raises(OSError, match="transient"):
                await caller
        if checkpoint:
            assert await f.read() == expected(text)
        else:
            with pytest.raises(OSError, match="broken"):
                await f.read()
    finally:
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("seekable", [False, True])
@pytest.mark.parametrize("rewind", [False, True])
async def test_native_cancel_preserves_decoded_prefix_and_cached_rewind(
    tmp_path, text, seekable, rewind
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    path = tmp_path / "members.gz"
    path.write_bytes(WIRE)

    class Reader(io.BufferedReader):
        calls = 0

        def seekable(self):
            return seekable

        def read(self, size=-1):
            self.calls += 1
            if self.calls == 1:
                return super().read(len(MEMBER))
            if self.calls == 2:
                data = super().read(size)
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("native prefix watchdog expired")
                return data
            return super().read(size)

    raw = Reader(io.FileIO(path, "rb"))
    f = wrapper(aiofiles.threadpool.wrap(raw, loop=loop), text)
    caller = None
    try:
        await f.open()
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(entered.wait(), 5)
        caller.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        if rewind:
            assert await f.seek(0) == 0
        assert await f.read() == expected(text)
        assert await f.read() == ("" if text else b"")
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()
        raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("native", [False, True])
async def test_exceptional_context_exit_settles_source_before_close(
    tmp_path, text, native
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    events = []
    caller = None
    timer = None
    raw = None

    if native:
        path = tmp_path / "members.gz"
        path.write_bytes(WIRE)

        class Reader(io.BufferedReader):
            def read(self, size=-1):
                data = super().read(size)
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("context watchdog expired")
                events.append("last access")
                return data

            def close(self):
                events.append("close")
                super().close()

        raw = Reader(io.FileIO(path, "rb"))
        source = aiofiles.threadpool.wrap(raw, loop=loop)
    else:

        class Source:
            async def read(self, size=-1):
                entered.set()
                try:
                    await asyncio.Future()
                finally:
                    events.append("last access")

            async def close(self):
                events.append("close")

        source = Source()

    f = wrapper(source, text, closefd=True)
    try:
        with pytest.raises(ValueError, match="body failure"):
            async with f:
                caller = asyncio.create_task(f.read())
                await asyncio.wait_for(entered.wait(), 5)
                if native:
                    timer = threading.Timer(0.05, release.set)
                    timer.start()
                raise ValueError("body failure")
        assert events == ["last access", "close"]
        with pytest.raises(OSError, match="read aborted"):
            await caller
        assert f.closed
    finally:
        release.set()
        if timer is not None:
            timer.join()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()
        if raw is not None and not raw.closed:
            raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("failure", ["cancel", "error"])
@pytest.mark.parametrize("moved", [False, True])
async def test_rewind_failure_classifies_physical_effects(
    tmp_path, text, native, failure, moved
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    thread_release = threading.Event()
    async_release = asyncio.Event()
    raw = None

    if native:
        path = tmp_path / "rewind.gz"
        path.write_bytes(WIRE)

        class Reader(io.BufferedReader):
            fail = True

            def seek(self, offset, whence=0):
                if not self.fail:
                    return super().seek(offset, whence)
                self.fail = False
                if moved:
                    super().seek(offset, whence)
                loop.call_soon_threadsafe(entered.set)
                if not thread_release.wait(5):
                    raise RuntimeError("seek watchdog expired")
                if failure == "error":
                    raise OSError("injected seek failure")
                return super().seek(offset, whence)

        raw = Reader(io.FileIO(path, "rb"))
        source = aiofiles.threadpool.wrap(raw, loop=loop)
    else:

        class Source:
            fail = True

            def __init__(self):
                self.buffer = io.BytesIO(WIRE)

            def tell(self):
                return self.buffer.tell()

            def seekable(self):
                return True

            async def read(self, size=-1):
                return self.buffer.read(size)

            async def seek(self, offset, whence=0):
                if not self.fail:
                    return self.buffer.seek(offset, whence)
                self.fail = False
                if moved:
                    self.buffer.seek(offset, whence)
                entered.set()
                await async_release.wait()
                if failure == "error":
                    raise OSError("injected seek failure")
                return self.buffer.seek(offset, whence)

        source = Source()

    f = wrapper(source, text)
    caller = None
    try:
        await f.open()
        prefix = await f.read(2)
        caller = asyncio.create_task(f.seek(0))
        await asyncio.wait_for(entered.wait(), 5)
        if failure == "cancel":
            caller.cancel()
            await asyncio.sleep(0)
            if native:
                assert not caller.done()
                with pytest.raises(ConcurrentOperationError):
                    await f.close()
        thread_release.set()
        async_release.set()
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await caller
        else:
            with pytest.raises(OSError, match="injected seek failure"):
                await caller
        broken = moved or (native and failure == "cancel")
        if broken:
            with pytest.raises(OSError, match="broken"):
                await f.read()
            assert await f.seek(0) == 0
            assert await f.read() == expected(text)
        else:
            assert prefix + await f.read() == expected(text)
    finally:
        thread_release.set()
        async_release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()
        if raw is not None:
            raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("moved", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_native_error_is_classified_after_settlement(
    tmp_path, text, moved, cancel
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    error = OSError("native read failed")
    path = tmp_path / "failure.gz"
    path.write_bytes(WIRE)

    class Reader(io.BufferedReader):
        fail = True

        def read(self, size=-1):
            if not self.fail:
                return super().read(size)
            self.fail = False
            if moved:
                super().read(len(MEMBER))
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("native error watchdog expired")
            raise error

    raw = Reader(io.FileIO(path, "rb"))
    f = wrapper(aiofiles.threadpool.wrap(raw, loop=loop), text)
    caller = None
    try:
        await f.open()
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(entered.wait(), 5)
        if cancel:
            for _ in range(3):
                caller.cancel()
                await asyncio.sleep(0)
                assert not caller.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError) as caught:
                await caller
            assert caught.value.__cause__ is error
        else:
            with pytest.raises(OSError) as caught:
                await caller
            assert caught.value is error
        if moved:
            with pytest.raises(OSError, match="broken"):
                await f.read()
        else:
            assert await f.read() == expected(text)
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()
        raw.close()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("when", ["before-start", "after-completion"])
async def test_cancel_at_submission_boundaries_preserves_input(
    tmp_path, monkeypatch, text, when
):
    from aiogzip._source_io import _NativeSourceCall

    path = tmp_path / "boundaries.gz"
    path.write_bytes(WIRE)
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls(path, "rt" if text else "rb")
    loop = asyncio.get_running_loop()
    original = loop.run_in_executor
    caller = None
    cancelled = False

    def submit(executor, method, *args):
        nonlocal cancelled
        work = original(executor, method, *args)
        if (
            when == "after-completion"
            and isinstance(method, _NativeSourceCall)
            and not cancelled
        ):
            cancelled = True
            work.add_done_callback(lambda _: caller.cancel())
        return work

    try:
        await f.open()
        monkeypatch.setattr(loop, "run_in_executor", submit)
        caller = asyncio.create_task(f.read())
        if when == "before-start":
            caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert await f.read() == expected(text)
        assert await f.read() == ("" if text else b"")
    finally:
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()


@pytest.mark.parametrize("empty_cache", [False, True])
@pytest.mark.parametrize("cancel_eof", [False, True])
async def test_nonseekable_pending_input_and_eof_replay(
    tmp_path, empty_cache, cancel_eof
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    path = tmp_path / "replay.gz"
    path.write_bytes(WIRE)

    class Reader(io.BufferedReader):
        calls = 0

        def seekable(self):
            return False

        def read(self, size=-1):
            self.calls += 1
            gate_call = 1 if empty_cache else 2
            if self.calls < gate_call:
                return super().read(len(WIRE) if cancel_eof else len(MEMBER))
            data = super().read(size)
            if self.calls == gate_call:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("replay watchdog expired")
            return data

    raw = Reader(io.FileIO(path, "rb"))
    f = wrapper(aiofiles.threadpool.wrap(raw, loop=loop), False)
    caller = None
    try:
        await f.open()
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(entered.wait(), 5)
        caller.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert await f.seek(0) == 0
        assert await f.read() == PAYLOAD + TAIL
        assert await f.read() == b""
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await f.close()
        raw.close()


async def test_queued_native_read_retains_input_in_configured_executor(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from aiogzip._source_io import _NativeSourceCall

    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    release = threading.Event()
    blocked, submitted = asyncio.Event(), asyncio.Event()
    path = tmp_path / "queued.gz"
    path.write_bytes(WIRE)
    raw = io.BufferedReader(io.FileIO(path, "rb"))
    f = wrapper(aiofiles.threadpool.wrap(raw, loop=loop, executor=executor), False)
    caller = blocker = None
    original = loop.run_in_executor

    def occupy():
        loop.call_soon_threadsafe(blocked.set)
        if not release.wait(5):
            raise RuntimeError("queue watchdog expired")

    def submit(pool, method, *args):
        if isinstance(method, _NativeSourceCall):
            assert pool is executor
            submitted.set()
        return original(pool, method, *args)

    try:
        await f.open()
        blocker = original(executor, occupy)
        await asyncio.wait_for(blocked.wait(), 5)
        monkeypatch.setattr(loop, "run_in_executor", submit)
        caller = asyncio.create_task(f.read())
        await asyncio.wait_for(submitted.wait(), 5)
        for _ in range(3):
            caller.cancel()
            await asyncio.sleep(0)
            assert not caller.done()
            assert raw.tell() == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert await f.read() == PAYLOAD + TAIL
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        if blocker is not None:
            await blocker
        await f.close()
        raw.close()
        executor.shutdown(wait=True)


def test_native_source_runner_shutdown_orders_read_and_close(tmp_path):
    path = tmp_path / "shutdown.gz"
    path.write_bytes(WIRE)
    program = r"""
import asyncio
import io
import json
import sys
import threading
import aiofiles.threadpool
import aiogzip

events = []
release = threading.Event()
timer = None
raw = None

async def main():
    global raw, timer
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()

    class Reader(io.BufferedReader):
        def read(self, size=-1):
            data = super().read(size)
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("shutdown read watchdog expired")
            events.append("last access")
            return data

        def close(self):
            events.append("close")
            super().close()

    raw = Reader(io.FileIO(sys.argv[1], "rb"))
    source = aiofiles.threadpool.wrap(raw, loop=loop)

    async def consume():
        async with aiogzip.AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True) as f:
            await f.read()

    caller = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 5)
    timer = threading.Timer(0.05, release.set)
    timer.start()
    assert not caller.done()

try:
    asyncio.run(main())
finally:
    release.set()
    if timer is not None:
        timer.join()
    if raw is not None and not raw.closed:
        raw.close()
print(json.dumps({"events": events, "import": aiogzip.__file__}))
"""
    origin = Path(aiogzip.__file__).resolve()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(origin.parent.parent)
    result = subprocess.run(
        [sys.executable, "-c", program, str(path)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=15,
    )
    report = json.loads(result.stdout)
    if Path(report["import"]).resolve() != origin:
        raise RuntimeError(f"shutdown child imported a different package: {report}")
    assert report["events"] == ["last access", "close"]
