"""Scan fairness with never-suspending sources, and chunk-stream driver cleanup.

Loop turns are counted, never timed.
"""

import asyncio
import gc
import gzip
import os
import warnings

import pytest

import aiogzip


class _ReadySource:
    """An in-memory async reader whose read() never suspends."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.reads = 0

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        end = len(self._data) if size < 0 else self._pos + size
        chunk = self._data[self._pos : end]
        self._pos += len(chunk)
        return chunk


async def _count_turns_during(awaitable):
    turns = 0
    done = False

    async def sibling():
        nonlocal turns
        while not done:
            turns += 1
            await asyncio.sleep(0)

    task = asyncio.ensure_future(sibling())
    await asyncio.sleep(0)
    turns = 0
    try:
        result = await awaitable
    finally:
        seen = turns
        done = True
        await task
    return result, seen


@pytest.fixture(scope="module")
def incompressible_gzip():
    # 24 MiB of stored (level 0) data: every 256 KiB read expands to about
    # 256 KiB, far under the driver's 1 MiB per-operation checkpoint.
    payload = os.urandom(1024 * 1024) * 24
    return payload, gzip.compress(payload, compresslevel=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("scan", ["verify", "inspect"])
async def test_scan_of_ready_source_yields_to_the_event_loop(incompressible_gzip, scan):
    payload, data = incompressible_gzip
    source = _ReadySource(data)
    result, turns = await _count_turns_during(
        getattr(aiogzip, scan)(None, fileobj=source)
    )
    assert result.uncompressed_size == len(payload)
    assert source.reads > 50
    # Output crosses the 1 MiB inline budget about 24 times.
    assert turns >= 10


@pytest.mark.asyncio
async def test_scan_of_ready_source_can_be_cancelled(incompressible_gzip):
    _, data = incompressible_gzip
    source = _ReadySource(data)
    task = asyncio.ensure_future(aiogzip.verify(None, fileobj=source))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert source._pos < len(data)


@pytest.mark.parametrize("direction", ["compress", "decompress"])
def test_early_aclose_closes_the_inner_driver_at_once(direction):
    """No task is left for the loop's asynchronous-generator hook."""
    payload = os.urandom(512 * 1024)

    async def source():
        if direction == "compress":
            for _ in range(8):
                yield payload
        else:
            data = gzip.compress(payload * 8, compresslevel=0)
            for start in range(0, len(data), 64 * 1024):
                yield data[start : start + 64 * 1024]

    async def main():
        make = (
            aiogzip.compress_chunks
            if direction == "compress"
            else aiogzip.decompress_chunks
        )
        kwargs = {"compresslevel": 0} if direction == "compress" else {}
        stream = make(source(), **kwargs)
        seen = 0
        async for _ in stream:
            seen += 1
            if seen == 3:
                break
        before = len(asyncio.all_tasks())
        await stream.aclose()
        # A deferred close would appear as a new pending task here.
        assert len(asyncio.all_tasks()) == before

    loop = asyncio.new_event_loop()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            loop.run_until_complete(main())
            # Deliberately no shutdown_asyncgens(): nothing may be pending.
            assert not asyncio.all_tasks(loop)
            loop.close()
            gc.collect()
    finally:
        if not loop.is_closed():
            loop.close()
