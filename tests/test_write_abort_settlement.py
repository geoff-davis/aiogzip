"""BC8: an aborted or cancelled writer never touches its sink after close.

b1 and C0 closed the sink on exceptional context exit while a write or flush
was still in flight: a custom sink then received that write after close(),
and a native file write hit the closed file, surfacing as "Unexpected error
during flush: write to closed file". Exit now settles the in-flight sink call
first, as it already did for read-side source calls.
"""

import asyncio
import concurrent.futures
import gzip
import os
import threading
import zlib

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class _Sink:
    """Custom sink that can block one write or flush and records misuse."""

    def __init__(self, block=None):
        self.block = block  # "write", "flush" or None
        self.data = bytearray()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closes = 0
        self.touched_after_close = 0
        self.writes = 0

    async def _maybe_block(self, method):
        if self.block == method:
            self.block = None
            self.entered.set()
            await self.release.wait()

    async def write(self, data):
        if self.closes:
            self.touched_after_close += 1
        self.writes += 1
        if self.writes > 1:  # never block the header write
            await self._maybe_block("write")
        if self.closes:
            self.touched_after_close += 1
        self.data += data
        return len(data)

    async def flush(self):
        if self.closes:
            self.touched_after_close += 1
        await self._maybe_block("flush")

    async def close(self):
        self.closes += 1


def _decoded(data):
    decompressor = zlib.decompressobj(31)
    return decompressor.decompress(bytes(data)), decompressor.eof


async def _abort_while(stream, sink, call):
    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with stream:
            task = asyncio.create_task(call())
            await asyncio.wait_for(sink.entered.wait(), 5)
            raise RuntimeError("body")
    assert task is not None
    sink.release.set()
    return task


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("block", ["write", "flush"])
async def test_abort_settles_a_blocked_custom_sink_call(text, block):
    # Blocking in flush is a control: C0 already settled an in-flight custom
    # flush. The defect was confined to sink writes.
    sink = _Sink(block)
    if text:
        stream = AsyncGzipTextFile(None, "wt", fileobj=sink, closefd=True)
        payload = "x" * 10
    else:
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True)
        payload = b"x" * 10

    async def write_then_flush():
        await stream.write(payload)
        await stream.flush()

    task = await _abort_while(stream, sink, write_then_flush)
    with pytest.raises(
        OSError, match=f"{block if block == 'flush' else 'flush'} aborted"
    ):
        await task
    assert stream.closed
    assert sink.closes == 1
    assert sink.touched_after_close == 0
    data, complete = _decoded(sink.data)
    assert not complete
    assert payload.encode()[: len(data)] == data if text else payload.startswith(data)


async def test_abort_settles_a_blocked_custom_sink_write_from_a_large_write():
    sink = _Sink("write")
    stream = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True, mtime=0)
    task = await _abort_while(stream, sink, lambda: stream.write(os.urandom(600_000)))
    with pytest.raises(OSError, match="write aborted"):
        await task
    assert sink.touched_after_close == 0
    assert sink.closes == 1


async def test_abort_consumes_only_its_own_cancellation_request():
    sink = _Sink("write")
    stream = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True)

    async def write_then_flush():
        await stream.write(b"x")
        await stream.flush()

    task = await _abort_while(stream, sink, write_then_flush)
    # Context exit consumed only its own cancellation request.
    with pytest.raises(OSError, match="flush aborted"):
        await asyncio.wait_for(task, 5)
    assert task.cancelling() == 0
    assert sink.touched_after_close == 0


@pytest.mark.parametrize("text", [False, True])
async def test_abort_preserves_outside_cancellation_of_the_writer_task(text):
    sink = _Sink("write")
    if text:
        stream = AsyncGzipTextFile(None, "wt", fileobj=sink, closefd=True)
    else:
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True)
    writer = None
    try:
        with pytest.raises(RuntimeError, match="body"):
            async with stream:
                writer = asyncio.create_task(
                    _write_then_flush(stream, "x" if text else b"x")
                )
                await asyncio.wait_for(sink.entered.wait(), 5)
                # Queue an independent request immediately before context exit
                # adds its own, without allowing the writer to resume between.
                writer.cancel("outside")
                raise RuntimeError("body")
        with pytest.raises(OSError, match="flush aborted"):
            await asyncio.wait_for(writer, 5)
        assert writer.cancelling() == 1
        assert sink.touched_after_close == 0
    finally:
        sink.release.set()
        if writer is not None:
            await asyncio.gather(writer, return_exceptions=True)


async def _write_then_flush(stream, payload):
    await stream.write(payload)
    await stream.flush()


class _GatedExecutor(concurrent.futures.ThreadPoolExecutor):
    """Default executor whose next submission waits for ``release``."""

    def __init__(self, loop):
        super().__init__(max_workers=4)
        self.loop = loop
        self.armed = False
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.ran = threading.Event()

    def submit(self, fn, /, *args, **kwargs):
        if not self.armed:
            return super().submit(fn, *args, **kwargs)
        self.armed = False

        def parked():
            self.loop.call_soon_threadsafe(self.entered.set)
            if not self.release.wait(10):
                raise TimeoutError("gate never released")
            try:
                return fn(*args, **kwargs)
            finally:
                self.ran.set()

        return super().submit(parked)


@pytest.fixture
async def gated_executor():
    loop = asyncio.get_running_loop()
    executor = _GatedExecutor(loop)
    loop.set_default_executor(executor)
    yield executor
    executor.release.set()


@pytest.mark.parametrize("text", [False, True])
async def test_abort_settles_a_native_write_before_closing_the_file(
    tmp_path, gated_executor, text
):
    path = tmp_path / "out.gz"
    if text:
        stream = AsyncGzipTextFile(path, "wt")
        payload = "x" * 1000
    else:
        stream = AsyncGzipBinaryFile(path, "wb")
        payload = b"x" * 1000

    async def write_then_flush():
        await stream.write(payload)
        await stream.flush()

    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with stream:
            gated_executor.armed = True
            task = asyncio.create_task(write_then_flush())
            await asyncio.wait_for(gated_executor.entered.wait(), 5)
            # Release concurrently with exit: exit must wait for the native
            # call to finish before it closes the file.
            asyncio.get_running_loop().call_soon(gated_executor.release.set)
            raise RuntimeError("body")
    assert task is not None
    with pytest.raises(OSError, match="flush aborted"):
        await task
    assert stream.closed
    data, complete = _decoded(path.read_bytes())
    assert not complete
    expected = payload.encode() if text else payload
    assert expected.startswith(data)


async def test_cancelled_queued_native_write_never_runs(tmp_path, gated_executor):
    path = tmp_path / "out.gz"
    stream = AsyncGzipBinaryFile(path, "wb")
    await stream.open()
    await stream.write(b"x" * 1000)
    gated_executor.armed = True
    task = asyncio.create_task(stream.flush())
    await asyncio.wait_for(gated_executor.entered.wait(), 5)
    # Queued, not started: cancellation prevents the native call outright.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gated_executor.release.set()
    await asyncio.get_running_loop().run_in_executor(None, gated_executor.ran.wait, 5)
    await stream.close()
    # Only the header reached the file: the prevented flush wrote nothing.
    assert _decoded(path.read_bytes()) == (b"", False)


class _BlockingFile:
    """Delegate to a real file, blocking inside the first write()."""

    def __init__(self, real):
        self.real = real
        self.entered = threading.Event()
        self.release = threading.Event()
        self.blocked = False

    def write(self, data):
        if not self.blocked:
            self.blocked = True
            self.entered.set()
            if not self.release.wait(10):
                raise TimeoutError("write never released")
        return self.real.write(data)

    def __getattr__(self, name):
        return getattr(self.real, name)


async def test_cancelled_started_native_write_settles_before_propagating(tmp_path):
    path = tmp_path / "out.gz"
    stream = AsyncGzipBinaryFile(path, "wb")
    await stream.open()
    await stream.write(b"x" * 1000)
    blocking = _BlockingFile(stream._file._file)
    stream._file._file = blocking
    task = asyncio.create_task(stream.flush())
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, blocking.entered.wait, 5)
    task.cancel()
    for _ in range(20):
        await asyncio.sleep(0)
    # The native write has started, so cancellation waits for it to finish
    # rather than letting a later close() race the worker.
    assert not task.done()
    blocking.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stream.close()
    with pytest.raises((EOFError, gzip.BadGzipFile)):
        gzip.decompress(path.read_bytes())


async def test_abort_during_offloaded_compression_never_reaches_the_sink(
    gated_executor,
):
    # Exit closes the sink while the codec step is in the executor; the
    # resumed write must not deliver its output to the closed sink.
    sink = _Sink()
    stream = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True)
    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with stream:
            gated_executor.armed = True
            task = asyncio.create_task(stream.write(os.urandom(600_000)))
            await asyncio.wait_for(gated_executor.entered.wait(), 5)
            raise RuntimeError("body")
    assert sink.closes == 1
    gated_executor.release.set()
    with pytest.raises(OSError, match="write aborted"):
        await task
    assert sink.touched_after_close == 0


@pytest.mark.parametrize("lines", [[], [""], ["a"]])
async def test_text_writelines_refuses_a_broken_writer_even_when_empty(lines):
    # b1 and C0 returned success for writelines([]) on a broken text writer,
    # while binary writelines([]) and every other text write raised.
    sink = _Sink("flush")
    stream = AsyncGzipTextFile(None, "wt", fileobj=sink, closefd=False)
    await stream.open()
    await stream.write("abc")
    flush = asyncio.create_task(stream.flush())
    await asyncio.wait_for(sink.entered.wait(), 5)
    flush.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flush
    for call in (stream.writelines(lines), stream.buffer.writelines([])):
        with pytest.raises(OSError, match="write stream is broken"):
            await call
    await stream.close()
