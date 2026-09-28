"""Ownership and accounting when a small compression feed advances inline."""

import asyncio
import gzip
import random

import pytest

from aiogzip import _codec_async as driver
from aiogzip import _streaming as stream
from aiogzip import compress_chunks
from aiogzip.codec import _CodecProgress


class Operation:
    def __init__(self, events=(), *, failure=None, close_failure=None):
        self.events = iter(events)
        self.failure = failure
        self.close_failure = close_failure
        self.closes = 0
        self.advances = 0

    def _advance_raw(self):
        self.advances += 1
        if self.failure is not None:
            raise self.failure
        return next(self.events)

    def close(self):
        self.closes += 1
        if self.close_failure is not None:
            raise self.close_failure


@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_first_step_failure_closes_before_discard(cleanup_fails, cancel):
    failure = asyncio.CancelledError() if cancel else ValueError("feed failed")
    operation = Operation(
        failure=failure,
        close_failure=RuntimeError("close failed") if cleanup_fails else None,
    )
    events = []

    class Encoder:
        def start(self):
            return Operation()

        def _feed_snapshot(self, snapshot):
            return operation

        def discard(self):
            assert operation.closes == 1
            events.append("discard")

    async def source():
        try:
            yield b"x"
            pytest.fail("source read ahead after failure")
        finally:
            events.append("source-close")

    with pytest.raises(type(failure)) as caught:
        async for _ in stream._compress_chunks_impl(source(), Encoder()):
            pass
    assert caught.value is failure
    assert events == ["discard", "source-close"]
    assert operation.closes == 1


@pytest.mark.parametrize("delta", [-1, 0, 1])
async def test_small_feed_preserves_offload_boundary(monkeypatch, delta):
    threshold = driver._ZLIB_OFFLOAD_THRESHOLD
    payload = random.Random(1).randbytes(threshold + delta)
    submitted = []

    async def executor(method, data):
        submitted.append(len(data))
        return method(data)

    monkeypatch.setattr(driver, "_run_in_thread", executor)

    async def source():
        yield payload

    wire = b"".join([part async for part in compress_chunks(source(), mtime=0)])
    assert gzip.decompress(wire) == payload
    assert submitted == ([] if delta < 0 else [len(payload)])


@pytest.mark.parametrize("first", [b"x", _CodecProgress(1)])
async def test_precomputed_result_counts_before_next_advance(monkeypatch, first):
    operation = Operation([b"tail"])
    budget = driver._StreamBudget(source_items=7, source_bytes=10)
    checkpoints = []

    async def checkpoint():
        # The result must be accounted for before pulling another codec step.
        checkpoints.append(operation.advances)

    monkeypatch.setattr(driver, "_cooperative_checkpoint", checkpoint)
    monkeypatch.setattr(driver, "_INLINE_OUTPUT_BYTES_CHECKPOINT", 1)
    monkeypatch.setattr(driver, "_NO_OUTPUT_BYTES_CHECKPOINT", 1)
    iterator = driver._drive_operation(operation, budget=budget, first_result=first)
    result = await anext(iterator)
    assert checkpoints[0] == 0
    assert result == (first if isinstance(first, bytes) else b"tail")
    assert budget.source_items == budget.source_bytes == 0
    await iterator.aclose()
    assert operation.closes == 1


async def test_immediate_completion_preserves_codec_budget(monkeypatch):
    budget = driver._StreamBudget(
        output_bytes=10, output_chunks=2, no_output_bytes=3, no_output_steps=1
    )
    monkeypatch.setattr(stream, "_StreamBudget", lambda: budget)
    feeds = []

    class Encoder:
        def start(self):
            return Operation()

        def _feed_snapshot(self, snapshot):
            operation = Operation()
            feeds.append(operation)
            return operation

        def finish(self):
            return Operation()

        def discard(self):
            pass

    async def source():
        yield b"x"
        yield b"y"

    assert [x async for x in stream._compress_chunks_impl(source(), Encoder())] == []
    assert budget == driver._StreamBudget(
        source_items=2,
        source_bytes=2,
        output_bytes=10,
        output_chunks=2,
        no_output_bytes=3,
        no_output_steps=1,
    )
    assert all(op.advances == 1 and op.closes == 0 for op in feeds)


async def test_precomputed_done_does_not_advance_again():
    operation = Operation(failure=AssertionError("advanced completed operation"))
    assert [
        x async for x in driver._drive_operation(operation, first_result=driver._DONE)
    ] == []
    assert operation.advances == operation.closes == 0


async def test_mixed_feeds_match_unprimed_driver(monkeypatch):
    from aiogzip import GzipEncoder

    payload = random.Random(2).randbytes(256 * 1024)

    async def run():
        operations = []

        class Encoder(GzipEncoder):
            def _feed_snapshot(self, snapshot):
                inner = super()._feed_snapshot(snapshot)
                outcomes = []
                operations.append(outcomes)

                class Observed:
                    def _advance_raw(self):
                        try:
                            result = inner._advance_raw()
                        except StopIteration:
                            outcomes.append("done")
                            raise
                        outcomes.append(result)
                        return result

                    def close(self):
                        inner.close()

                return Observed()

        async def source():
            for i in range(0, len(payload), 64):
                yield payload[i : i + 64]

        wire = b"".join(
            [x async for x in stream._compress_chunks_impl(source(), Encoder(mtime=0))]
        )
        return wire, operations

    actual, operations = await run()
    # Disable only pre-advancement: the driver keeps its normal offload threshold.
    monkeypatch.setattr(stream, "_ZLIB_OFFLOAD_THRESHOLD", 0)
    expected, unprimed = await run()
    assert actual == expected
    assert gzip.decompress(actual) == payload
    assert operations == unprimed
    assert any(len(events) == 1 for events in operations)
    assert any(len(events) > 1 for events in operations)
    assert all(
        events[-1] == "done" and events.count("done") == 1 for events in operations
    )


async def test_consumer_exit_invalidates_precomputed_feed_before_source_close():
    from aiogzip import GzipEncoder

    events = []
    active = []

    class Encoder(GzipEncoder):
        def discard(self):
            active.append(self._active_token)
            super().discard()
            events.append("discard")

    encoder = Encoder(mtime=0)

    async def source():
        try:
            yield random.Random(3).randbytes(64 * 1024)
            pytest.fail("read ahead after consumer exit")
        finally:
            assert encoder._active_token is None
            assert encoder._discarded
            events.append("source-close")

    iterator = stream._compress_chunks_impl(source(), encoder)
    await anext(iterator)  # Header from start().
    assert await anext(iterator)  # Precomputed output from the first feed step.
    await iterator.aclose()
    assert events == ["discard", "source-close"]
    assert len(active) == 1 and active[0] is not None
    with pytest.raises(RuntimeError, match="invalidated"):
        active[0]._advance_raw()
