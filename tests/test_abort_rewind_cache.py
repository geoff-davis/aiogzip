"""G19 F1: a failed abort close must not leave a hole in the rewind cache.

An exceptional context exit settles an in-flight native read before closing
the file. If that close fails, the reader stays open and broken, and
``seek(0)`` on a non-seekable source recovers by replaying the cache. The
settled chunk was consumed from the source, so it must be replayed too; if
it cannot be retained, recovery must be refused rather than return a suffix.
"""

import asyncio
import gzip
import io
import threading

import aiofiles.threadpool
import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

PAYLOADS = [f"member-{i:02d}\n".encode() * 50 for i in range(6)]
MEMBERS = [gzip.compress(p, mtime=0) for p in PAYLOADS]
CHUNK = len(MEMBERS[0])
assert all(len(m) == CHUNK for m in MEMBERS)
WIRE = b"".join(MEMBERS)


class Boom(Exception):
    pass


def _source(loop, entered, release):
    class Reader(io.BufferedReader):
        reads = 0
        closes = 0

        def seekable(self):
            return False

        def read(self, size=-1):
            self.reads += 1
            if self.reads == 2:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("native read watchdog expired")
            return super().read(size)

        def close(self):
            self.closes += 1
            if self.closes == 1:
                raise OSError("simulated close failure")
            super().close()

    return aiofiles.threadpool.wrap(Reader(io.BytesIO(WIRE)), loop=loop)


async def _abort_during_read(text, cancel_read, **options):
    """Leave a reader open and broken after an abort that settled a read."""
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    f = cls(
        None,
        "rt" if text else "rb",
        fileobj=_source(loop, entered, release),
        closefd=True,
        chunk_size=CHUNK,
        **options,
    )
    reader = None
    try:
        with pytest.raises(Boom):
            async with f:
                # One task does every read, so the gated native read is
                # always the second chunk, after member 0 is cached.
                reader = asyncio.create_task(f.read())
                await entered.wait()
                if cancel_read:
                    # The read settles under cancellation after the abort
                    # has already broken the reader.
                    reader.cancel()
                    await asyncio.sleep(0)
                loop.call_later(0.05, release.set)
                raise Boom()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError if cancel_read else OSError):
        await reader
    assert not f.closed
    return f


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("cancel_read", [False, True])
async def test_rewind_after_failed_abort_close_replays_settled_read(text, cancel_read):
    f = await _abort_during_read(text, cancel_read)
    try:
        await f.seek(0)
        whole = b"".join(PAYLOADS)
        assert await f.read() == (whole.decode() if text else whole)
    finally:
        await f.close()


async def test_rewind_refuses_when_settled_read_exceeds_cache():
    # The cache holds member 0 but not member 1, so replay is disabled
    # rather than resumed past the missing member. (A cancelled read keeps
    # its result as pending input instead, which the cap does not limit.)
    f = await _abort_during_read(False, False, max_rewind_cache_size=CHUNK + CHUNK // 2)
    try:
        with pytest.raises(OSError, match="not seekable"):
            await f.seek(0)
    finally:
        await f.close()
