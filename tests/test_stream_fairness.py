"""Across-item fairness and cleanup for immediately ready iterable sources."""

import asyncio
import gzip
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aiogzip
from aiogzip import _codec_async, _streaming, compress_chunks, decompress_chunks
from aiogzip.codec import _CodecProgress


@pytest.mark.parametrize(
    "mode",
    [
        "compress-empty",
        "compress-tiny",
        "decode-empty",
        "decode-tiny",
        "decode-members",
    ],
)
async def test_ready_source_progress_precedes_exhaustion(mode):
    payload = b"x" * 4096
    compressed = gzip.compress(payload, mtime=0)
    wrapper = compress_chunks if mode.startswith("compress") else decompress_chunks
    if mode.endswith("empty"):
        items = [b""] * 4096 + [payload if wrapper is compress_chunks else compressed]
    elif mode == "compress-tiny":
        items = [b"x"] * 4096
    elif mode == "decode-tiny":
        compressed = gzip.compress(bytes(range(256)) * 32, mtime=0)
        payload = bytes(range(256)) * 32
        items = [compressed[i : i + 1] for i in range(len(compressed))]
    else:
        items = [gzip.compress(b"", mtime=0)] * 4096 + [compressed]
    fetched = 0
    observations = []
    stop = False

    async def source():
        nonlocal fetched
        for item in items:
            fetched += 1
            yield item

    async def ticker():
        while not stop:
            observations.append(fetched)
            await asyncio.sleep(0)

    sibling = asyncio.create_task(ticker())
    try:
        output = b"".join([chunk async for chunk in wrapper(source())])
    finally:
        stop = True
        await sibling
    assert (
        gzip.decompress(output) if wrapper is compress_chunks else output
    ) == payload
    assert observations and observations[0] < len(items)
    assert (
        max(
            b - a
            for a, b in zip([0, *observations], [*observations, fetched], strict=True)
        )
        <= _streaming._SOURCE_ITEMS_CHECKPOINT
    )


@pytest.mark.parametrize(
    "events,threshold",
    [
        ([b"xx"], "_INLINE_OUTPUT_BYTES_CHECKPOINT"),
        ([_CodecProgress(2)], "_NO_OUTPUT_BYTES_CHECKPOINT"),
        ([_CodecProgress(0)], "_NO_OUTPUT_STEPS_CHECKPOINT"),
        ([b"x"], "_INLINE_OUTPUT_CHUNKS_CHECKPOINT"),
    ],
)
async def test_codec_budget_survives_operation_boundaries(
    monkeypatch, events, threshold
):
    class Operation:
        def __init__(self):
            self.events = iter(events)

        def _advance_raw(self):
            return next(self.events)

        def close(self):
            pass

    checkpoints = 0

    async def checkpoint():
        nonlocal checkpoints
        checkpoints += 1

    monkeypatch.setattr(_codec_async, threshold, 3)
    monkeypatch.setattr(_codec_async, "_cooperative_checkpoint", checkpoint)
    budget = _codec_async._StreamBudget()
    for _ in range(3):
        async for _ in _codec_async._drive_operation(Operation(), budget=budget):
            pass
    assert checkpoints == 1


@pytest.mark.parametrize("wrapper", [compress_chunks, decompress_chunks])
async def test_source_checkpoint_cancellation_closes_without_prefetch(
    monkeypatch, wrapper
):
    fetched = 0
    closed = 0

    async def source():
        nonlocal fetched, closed
        try:
            for _ in range(1000):
                fetched += 1
                yield b""
        finally:
            closed += 1

    async def checkpoint():
        assert fetched == 3
        raise asyncio.CancelledError

    monkeypatch.setattr(_streaming, "_SOURCE_ITEMS_CHECKPOINT", 3)
    monkeypatch.setattr(_streaming, "_cooperative_checkpoint", checkpoint)
    with pytest.raises(asyncio.CancelledError):
        async for _ in wrapper(source()):
            pass
    assert fetched == 3
    assert closed == 1


@pytest.mark.parametrize("wrapper", ["compress_chunks", "decompress_chunks"])
def test_infinite_empty_source_can_be_cancelled(wrapper):
    # A real process watchdog bounds a broken implementation that never yields.
    code = """
import asyncio
import aiogzip
import sys
async def main():
    closed = False
    async def source():
        nonlocal closed
        try:
            while True:
                yield b""
        finally:
            closed = True
    async def consume():
        async for _ in getattr(aiogzip, sys.argv[1])(source()):
            pass
    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("consumer was not cancelled")
    assert closed
asyncio.run(main())
"""
    env = dict(os.environ, PYTHONPATH=str(Path(aiogzip.__file__).resolve().parents[1]))
    subprocess.run(
        [sys.executable, "-c", code, wrapper],
        env=env,
        check=True,
        timeout=15,
        capture_output=True,
    )


async def test_ready_executor_result_does_not_reset_stream_budget(monkeypatch):
    class Operation:
        def __init__(self):
            self.events = iter([_CodecProgress(1)])

        def _advance_raw(self):
            return next(self.events)

        def close(self):
            pass

    checkpoints = 0

    async def already_ready(method, data):
        return method(data)

    async def checkpoint():
        nonlocal checkpoints
        checkpoints += 1

    monkeypatch.setattr(_codec_async, "_run_in_thread", already_ready)
    monkeypatch.setattr(_codec_async, "_cooperative_checkpoint", checkpoint)
    monkeypatch.setattr(_codec_async, "_NO_OUTPUT_STEPS_CHECKPOINT", 2)
    budget = _codec_async._StreamBudget(source_items=17, source_bytes=100)
    for _ in range(2):
        async for _ in _codec_async._drive_operation(
            Operation(), workload=b"x", offload_threshold=1, budget=budget
        ):
            pass
    assert checkpoints == 1
    assert budget == _codec_async._StreamBudget()
