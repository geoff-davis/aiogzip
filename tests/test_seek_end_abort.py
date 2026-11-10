"""An end-relative seek aborted while parked on codec work (#172, BC24).

An exceptional ``async with`` exit aborts the active read call. When that
call is ``seek(-n, SEEK_END)`` parked at a codec checkpoint (not at a source
call), the abort ends its drain loop by setting EOF. The seek must then raise
the abort error: it must not rewind, touch the closed source, or revive the
aborted reader (BC9).
"""

import asyncio
import gzip
import io
import os

import pytest

from aiogzip import AsyncGzipBinaryFile

# Highly compressible, so one small source read feeds many inflate batches and
# the reader passes cooperative checkpoints while holding no source call.
PAYLOAD = b"A" * (8 * 1024 * 1024)
COMPRESSED = gzip.compress(PAYLOAD)
ABORTED = "read aborted because the gzip file was closed"


class _Source:
    def __init__(self, close_fails=False):
        self._buffer = io.BytesIO(COMPRESSED)
        self._close_fails = close_fails
        self.closed = False
        self.log = []

    async def read(self, size=-1):
        self.log.append("read")
        return self._buffer.read(size)

    async def seek(self, offset, whence=os.SEEK_SET):
        self.log.append("seek")
        return self._buffer.seek(offset, whence)

    def seekable(self):
        return True

    def tell(self):
        return self._buffer.tell()

    async def close(self):
        self.log.append("close")
        if self._close_fails:
            raise OSError("close failed")
        self.closed = True


async def _park_on_codec_work(f, task):
    """Run ``task`` until its read call holds no source call.

    A path source first waits on an executor read, which takes wall-clock
    time on a loaded machine, so the wait is bounded by a deadline rather
    than a number of loop turns.
    """
    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0)
        assert not task.done(), "the call finished before it could be aborted"
        if (
            f._read_call_active
            and f._source_owner is None
            and f._source_native_call is None
        ):
            return
    raise AssertionError("the call never parked on codec work")


async def _abort_during(f, call):
    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with f:
            task = asyncio.create_task(call(f))
            await _park_on_codec_work(f, task)
            raise RuntimeError("body")
    return task


@pytest.mark.parametrize("offset", [-3, -len(PAYLOAD), 0])
async def test_custom_source_is_not_touched_after_close(offset):
    source = _Source()
    f = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)
    task = await _abort_during(f, lambda f: f.seek(offset, os.SEEK_END))
    with pytest.raises(OSError, match=ABORTED):
        await task
    assert f.closed
    assert source.log[-1] == "close"
    assert "seek" not in source.log


@pytest.mark.parametrize("offset", [-3, 0])
async def test_failed_abort_close_does_not_revive_the_reader(offset):
    source = _Source(close_fails=True)
    f = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)
    task = await _abort_during(f, lambda f: f.seek(offset, os.SEEK_END))
    with pytest.raises(OSError, match=ABORTED):
        await task
    # The handle stays open so that the close can be retried, and broken.
    assert not f.closed
    assert source.log[-1] == "close"
    with pytest.raises(OSError, match="read stream is broken"):
        await f.read(10)
    source._close_fails = False
    await f.close()


@pytest.mark.parametrize("offset", [-3, 0])
async def test_path_source_raises_the_abort_error(tmp_path, offset):
    path = tmp_path / "data.gz"
    path.write_bytes(COMPRESSED)
    f = AsyncGzipBinaryFile(path, "rb")
    task = await _abort_during(f, lambda f: f.seek(offset, os.SEEK_END))
    with pytest.raises(OSError, match=ABORTED):
        await task
    assert f.closed
