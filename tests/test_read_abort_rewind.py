"""BC9: a native rewind settled by an aborting context exit stays aborted.

Exceptional context exit marks the reader broken, then waits for an in-flight
native seek instead of cancelling it. b1 and C0 let the resumed rewind reset
the reader with a fresh decoder, so seek() returned 0 from a handle that exit
then closed (b1's seek hit the closed file instead). The rewind now reports the
same abort error as a custom source, and the closed reader keeps no decoder.
"""

import asyncio
import concurrent.futures
import gzip
import threading

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

PAYLOAD = b"line of text\n" * 2000


class _GatedExecutor(concurrent.futures.ThreadPoolExecutor):
    """Default executor whose next submission waits for ``release``."""

    def __init__(self, loop):
        super().__init__(max_workers=4)
        self.loop = loop
        self.armed = False
        self.entered = asyncio.Event()
        self.release = threading.Event()

    def submit(self, fn, /, *args, **kwargs):
        if not self.armed:
            return super().submit(fn, *args, **kwargs)
        self.armed = False

        def parked():
            self.loop.call_soon_threadsafe(self.entered.set)
            if not self.release.wait(10):
                raise TimeoutError("gate never released")
            return fn(*args, **kwargs)

        return super().submit(parked)


@pytest.fixture
async def gated_executor():
    loop = asyncio.get_running_loop()
    executor = _GatedExecutor(loop)
    loop.set_default_executor(executor)
    yield executor
    executor.release.set()


def _write(path, corrupt):
    data = bytearray(gzip.compress(PAYLOAD, mtime=0))
    if corrupt:
        data[-8] ^= 0xFF  # CRC mismatch: a validation failure after the body
    path.write_bytes(bytes(data))


def _binary(stream):
    return stream._binary_file if hasattr(stream, "_binary_file") else stream


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("poisoned", [False, True])
async def test_abort_during_a_native_rewind_keeps_the_reader_aborted(
    tmp_path, gated_executor, text, poisoned
):
    path = tmp_path / "in.gz"
    _write(path, corrupt=poisoned)
    stream = AsyncGzipTextFile(path, "rt") if text else AsyncGzipBinaryFile(path, "rb")
    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with stream:
            if poisoned:
                # Poison the reader so seek(0) takes the recovery rewind.
                with pytest.raises(OSError):
                    await stream.read()
                assert not _binary(stream)._read_is_healthy()
            else:
                # A backward seek from a healthy reader also rewinds.
                await stream.read(100)
            gated_executor.armed = True
            task = asyncio.create_task(stream.seek(0))
            await asyncio.wait_for(gated_executor.entered.wait(), 5)
            # Release concurrently with exit: exit awaits the native seek, which
            # then completes normally before the reader is closed.
            asyncio.get_running_loop().call_soon(gated_executor.release.set)
            raise RuntimeError("body")
    assert task is not None
    with pytest.raises(OSError, match="read aborted because the gzip file was closed"):
        await task
    assert stream.closed
    binary = _binary(stream)
    assert binary._read_health.name == "BROKEN"
    assert binary._eof
    assert binary._decoder is None or binary._decoder._discarded
