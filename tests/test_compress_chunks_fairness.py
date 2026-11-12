"""compress_chunks() yields while compressing small items inline (issue #194).

Loop turns are counted, never timed.
"""

import asyncio
import gzip

import pytest

import aiogzip
from aiogzip import _streaming

ITEM = 64 * 1024


async def _ready_source(items):
    for item in items:
        yield item


async def _collect(stream) -> bytes:
    return b"".join([chunk async for chunk in stream])


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


class TestMediumPriorityEdgeCases:
    @pytest.mark.asyncio
    async def test_compressible_small_items_yield_by_input_compressed(self):
        # 8 MiB of zeros in 128 items: under the source-item and source-byte
        # checkpoints, and too little output for the output checkpoint.
        items = [bytes(ITEM)] * 128
        packed, turns = await _count_turns_during(
            _collect(aiogzip.compress_chunks(_ready_source(items)))
        )
        assert gzip.decompress(packed) == bytes(ITEM * 128)
        bound = _streaming._INLINE_COMPRESS_BYTES_CHECKPOINT
        assert turns >= (ITEM * 128) // (bound + ITEM)

    @pytest.mark.asyncio
    async def test_inline_compression_can_be_cancelled(self):
        consumed = 0

        async def source():
            nonlocal consumed
            for _ in range(1024):
                consumed += 1
                yield bytes(ITEM)

        task = asyncio.ensure_future(_collect(aiogzip.compress_chunks(source())))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert consumed < 64

    @pytest.mark.asyncio
    async def test_stream_under_the_bound_adds_no_checkpoint(self):
        items = [bytes(ITEM)] * 4
        packed, turns = await _count_turns_during(
            _collect(aiogzip.compress_chunks(_ready_source(items)))
        )
        assert gzip.decompress(packed) == bytes(ITEM * 4)
        assert turns == 0

    @pytest.mark.asyncio
    async def test_offloaded_items_do_not_spend_the_inline_budget(self, monkeypatch):
        checkpoints = 0
        real = _streaming._cooperative_checkpoint

        async def counting():
            nonlocal checkpoints
            checkpoints += 1
            await real()

        monkeypatch.setattr(_streaming, "_cooperative_checkpoint", counting)
        items = [bytes(1024 * 1024)] * 8
        packed = await _collect(aiogzip.compress_chunks(_ready_source(items)))
        assert gzip.decompress(packed) == bytes(8 * 1024 * 1024)
        assert checkpoints == 0
