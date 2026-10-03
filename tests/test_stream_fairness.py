"""Across-item fairness and cleanup for immediately ready iterable sources."""

import asyncio
import gzip
import os
import random
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
@pytest.mark.parametrize("empty_between", [False, True])
async def test_codec_budget_survives_operation_boundaries(
    monkeypatch, events, threshold, empty_between
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
        if empty_between:
            # An empty feed must preserve the accumulated work for the next
            # operation even when the driver skips loading its budget.
            empty = Operation()
            empty.events = iter(())
            async for _ in _codec_async._drive_operation(empty, budget=budget):
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


async def test_executor_wait_is_not_a_stream_budget_checkpoint(monkeypatch):
    class Operation:
        def __init__(self):
            self.events = iter([_CodecProgress(1)])

        def _advance_raw(self):
            return next(self.events)

        def close(self):
            pass

    checkpoints = 0

    async def checkpoint():
        nonlocal checkpoints
        checkpoints += 1

    # Exercise real executor hops. They yield, but policy deliberately retains
    # the stream counters until the explicit checkpoint below.
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


@pytest.mark.parametrize("wrapper", [compress_chunks, decompress_chunks])
@pytest.mark.parametrize("action", ["early-exit", "source-failure", "slow-destination"])
async def test_checkpoint_lifecycle_retains_pull_ownership(
    monkeypatch, wrapper, action
):
    # The empty prefix crosses a real source checkpoint before data arrives.
    payload = random.Random(101).randbytes(2 * 1024 * 1024)
    source_data = (
        payload if wrapper is compress_chunks else gzip.compress(payload, mtime=0)
    )
    events = []
    fetched = 0
    checkpoints = 0
    failure = OSError("source failed after checkpoint")
    codec_name = "GzipEncoder" if wrapper is compress_chunks else "GzipDecoder"
    codec_type = getattr(_streaming, codec_name)

    class ObservedCodec(codec_type):
        def discard(self):
            events.append("discard")
            return super().discard()

    original_checkpoint = _streaming._cooperative_checkpoint
    advance = _codec_async._raw_next_or_done
    advances = 0

    def observed_advance(operation, workload):
        nonlocal advances
        advances += 1
        return advance(operation, workload)

    monkeypatch.setattr(_codec_async, "_raw_next_or_done", observed_advance)

    async def checkpoint():
        nonlocal checkpoints
        checkpoints += 1
        await original_checkpoint()

    async def source():
        nonlocal fetched
        try:
            for _ in range(_streaming._SOURCE_ITEMS_CHECKPOINT):
                fetched += 1
                yield b""
            if action == "source-failure":
                raise failure
            fetched += 1
            yield source_data
            raise AssertionError("source was prefetched while consumer stopped")
        finally:
            events.append("source-close")

    monkeypatch.setattr(_streaming, codec_name, ObservedCodec)
    monkeypatch.setattr(_streaming, "_cooperative_checkpoint", checkpoint)
    stream = wrapper(source(), output_chunk_size=1024)
    try:
        if action == "source-failure":
            with pytest.raises(OSError) as caught:
                async for _ in stream:
                    pass
            assert caught.value is failure
        else:
            # Compression emits its header before pulling the source.
            while fetched <= _streaming._SOURCE_ITEMS_CHECKPOINT:
                assert await anext(stream)
            assert checkpoints >= 1
            if action == "slow-destination":
                entered = asyncio.Event()
                release = asyncio.Event()

                async def destination():
                    entered.set()
                    await release.wait()

                writer = asyncio.create_task(destination())
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    before = fetched, checkpoints, advances, list(events)
                    for _ in range(8):
                        await asyncio.sleep(0)
                    assert (fetched, checkpoints, advances, events) == before
                    assert events == []
                finally:
                    release.set()
                    await writer
    finally:
        await stream.aclose()
    assert checkpoints >= 1
    assert fetched == _streaming._SOURCE_ITEMS_CHECKPOINT + (action != "source-failure")
    expected = (
        ["source-close", "discard"]
        if action == "source-failure"
        else ["discard", "source-close"]
    )
    assert events == expected


@pytest.mark.parametrize(
    "mode", ["compress-output", "decode-output", "decode-no-output"]
)
async def test_single_large_item_keeps_codec_checkpoints(monkeypatch, mode):
    # Generate the fixture before observing cooperative work. The no-output
    # case cannot reach the source-item ceiling or rely on an executor hop.
    payload = bytes(range(256)) * (4 * 1024 * 1024 // 256)
    if mode == "compress-output":
        payload = random.Random(101).randbytes(4 * 1024 * 1024)
    wrapper = compress_chunks if mode.startswith("compress") else decompress_chunks
    if mode == "decode-no-output":
        payload = b""
        item = gzip.compress(b"", mtime=0) * 20000
        assert len(item) < _codec_async._DECODE_OFFLOAD_THRESHOLD
    else:
        item = (
            payload if wrapper is compress_chunks else gzip.compress(payload, mtime=0)
        )
    delivered = 0
    fetched = 0
    output_at_checkpoints = []
    original_checkpoint = _codec_async._cooperative_checkpoint

    async def source():
        nonlocal fetched
        fetched += 1
        yield item

    async def checkpoint():
        assert fetched == 1
        output_at_checkpoints.append(delivered)
        await original_checkpoint()

    monkeypatch.setattr(_codec_async, "_cooperative_checkpoint", checkpoint)
    chunks = []
    async for chunk in wrapper(source(), output_chunk_size=65536):
        assert chunk
        chunks.append(chunk)
        delivered += len(chunk)
    output = b"".join(chunks)
    assert (
        gzip.decompress(output) if wrapper is compress_chunks else output
    ) == payload
    assert output_at_checkpoints
    if mode == "decode-no-output":
        assert set(output_at_checkpoints) == {0}
    else:
        assert len(output_at_checkpoints) >= 3
        # Checkpoint is before publishing the chunk that reaches the ceiling;
        # include a one-chunk margin when comparing observable delivery gaps.
        positions = [0, *output_at_checkpoints, delivered]
        assert (
            max(b - a for a, b in zip(positions, positions[1:], strict=False))
            <= _codec_async._INLINE_OUTPUT_BYTES_CHECKPOINT + 65536
        )
