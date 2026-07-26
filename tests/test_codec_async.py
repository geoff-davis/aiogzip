"""Tests for the private asyncio bridge over synchronous codec operations."""

import asyncio
import gzip
import os
import struct
import zlib

import pytest

from aiogzip import GzipDecoder, GzipEncoder, _engine
from aiogzip import _codec_async as async_module
from aiogzip._codec_async import _drive_operation
from aiogzip.codec import _CodecProgress


async def _collect(operation, **options):
    return [chunk async for chunk in _drive_operation(operation, **options)]


async def test_small_operation_runs_inline(monkeypatch):
    async def unexpected_offload(method, data):
        raise AssertionError("small operation must stay inline")

    monkeypatch.setattr(async_module, "_run_in_thread", unexpected_offload)
    encoder = GzipEncoder(mtime=0)

    header = await _collect(encoder.start())
    body = await _collect(encoder.feed(b"payload"), workload=b"payload")
    final = await _collect(encoder.finish())

    assert gzip.decompress(b"".join((*header, *body, *final))) == b"payload"


async def test_large_encoder_operation_offloads_only_engine_advancement(monkeypatch):
    calls = []

    async def recording_offload(method, data):
        calls.append(len(data))
        return method(data)

    monkeypatch.setattr(async_module, "_run_in_thread", recording_offload)
    payload = os.urandom(async_module._ZLIB_OFFLOAD_THRESHOLD + 1)
    encoder = GzipEncoder(mtime=0, output_chunk_size=1024)
    header = await _collect(encoder.start())
    body = await _collect(
        encoder.feed(payload),
        workload=payload,
    )
    final = await _collect(encoder.finish())

    assert calls == [len(payload)]
    assert gzip.decompress(b"".join((*header, *body, *final))) == payload


async def test_large_decoder_operation_offloads_only_first_step(monkeypatch):
    calls = []

    async def recording_offload(method, data):
        calls.append(len(data))
        return method(data)

    monkeypatch.setattr(async_module, "_run_in_thread", recording_offload)
    payload = os.urandom(async_module._ZLIB_OFFLOAD_THRESHOLD + 1024)
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder(output_chunk_size=4096)

    output = await _collect(decoder.feed(wire), workload=wire)
    output.extend(await _collect(decoder.finish()))

    assert calls == [len(wire)]
    assert b"".join(output) == payload


async def test_cancellation_waits_for_worker_then_poisons_codec(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def controlled_offload(method, data):
        started.set()
        try:
            await release.wait()
            return method(data)
        finally:
            completed.set()

    monkeypatch.setattr(async_module, "_run_in_thread", controlled_offload)
    payload = os.urandom(async_module._ZLIB_OFFLOAD_THRESHOLD + 1)
    encoder = GzipEncoder(mtime=0)
    list(encoder.start())
    stream = _drive_operation(
        encoder.feed(payload),
        workload=payload,
    )
    task = asyncio.create_task(stream.__anext__())
    await started.wait()

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    with pytest.raises(RuntimeError, match="active operation"):
        encoder.finish()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert completed.is_set()
    with pytest.raises(OSError, match="unusable"):
        encoder.finish()


async def test_abandoned_driver_closes_operation_and_poisons_codec():
    encoder = GzipEncoder(mtime=0, output_chunk_size=1)
    list(encoder.start())
    stream = _drive_operation(encoder.feed(os.urandom(300_000)))

    assert await stream.__anext__()
    await stream.aclose()

    with pytest.raises(OSError, match="unusable"):
        encoder.finish()


async def test_operation_error_remains_primary_when_close_fails():
    expected = LookupError("operation failed")
    close_calls = 0

    class FailingOperation:
        def __iter__(self):
            return self

        def __next__(self):
            raise expected

        def _advance_raw(self):
            return self.__next__()

        def close(self):
            nonlocal close_calls
            close_calls += 1
            raise RuntimeError("cleanup failed")

    with pytest.raises(LookupError) as caught:
        await _collect(FailingOperation())

    assert caught.value is expected
    assert close_calls == 1


class _SequenceOperation:
    def __init__(self, events):
        self.events = iter(events)
        self.close_calls = 0
        self.raw_calls = 0

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            event = self._advance_raw()
            if isinstance(event, bytes):
                return event

    def _advance_raw(self):
        self.raw_calls += 1
        return next(self.events)

    def close(self):
        self.close_calls += 1


async def test_inline_chunk_threshold_gives_sibling_ticker_progress(monkeypatch):
    monkeypatch.setattr(async_module, "_INLINE_OUTPUT_BYTES_CHECKPOINT", 1_000_000)
    monkeypatch.setattr(async_module, "_INLINE_OUTPUT_CHUNKS_CHECKPOINT", 3)
    progressed = asyncio.Event()

    async def ticker():
        progressed.set()

    task = asyncio.create_task(ticker())
    operation = _SequenceOperation([b"a", b"b", b"c", b"d"])

    assert await _collect(operation) == [b"a", b"b", b"c", b"d"]
    assert progressed.is_set()
    await task


@pytest.mark.parametrize(
    ("events", "threshold_name", "threshold"),
    [
        ([b"ab", b"cd"], "_INLINE_OUTPUT_BYTES_CHECKPOINT", 4),
        ([b"a", b"b"], "_INLINE_OUTPUT_CHUNKS_CHECKPOINT", 2),
        (
            [_CodecProgress(2), _CodecProgress(2)],
            "_NO_OUTPUT_BYTES_CHECKPOINT",
            4,
        ),
        (
            [_CodecProgress(1), _CodecProgress(1)],
            "_NO_OUTPUT_STEPS_CHECKPOINT",
            2,
        ),
    ],
)
async def test_each_fairness_threshold_triggers_checkpoint(
    monkeypatch, events, threshold_name, threshold
):
    calls = 0

    async def checkpoint():
        nonlocal calls
        calls += 1

    for name in (
        "_INLINE_OUTPUT_BYTES_CHECKPOINT",
        "_INLINE_OUTPUT_CHUNKS_CHECKPOINT",
        "_NO_OUTPUT_BYTES_CHECKPOINT",
        "_NO_OUTPUT_STEPS_CHECKPOINT",
    ):
        monkeypatch.setattr(async_module, name, 1_000_000)
    monkeypatch.setattr(async_module, threshold_name, threshold)
    monkeypatch.setattr(async_module, "_cooperative_checkpoint", checkpoint)

    await _collect(_SequenceOperation(events))

    assert calls == 1


async def test_no_checkpoint_before_any_threshold(monkeypatch):
    calls = 0

    async def checkpoint():
        nonlocal calls
        calls += 1

    monkeypatch.setattr(async_module, "_cooperative_checkpoint", checkpoint)
    operation = _SequenceOperation([b"a", _CodecProgress(1), b"b"])

    assert await _collect(operation) == [b"a", b"b"]
    assert calls == 0


async def test_visible_output_resets_consecutive_no_output_steps(monkeypatch):
    calls = 0

    async def checkpoint():
        nonlocal calls
        calls += 1

    monkeypatch.setattr(async_module, "_NO_OUTPUT_STEPS_CHECKPOINT", 8)
    monkeypatch.setattr(async_module, "_cooperative_checkpoint", checkpoint)
    progress = [_CodecProgress(1)] * 7

    assert await _collect(_SequenceOperation([*progress, b"x", *progress])) == [b"x"]
    assert calls == 0


async def test_executor_hop_resets_checkpoint_accounting(monkeypatch):
    calls = 0

    async def inline_offload(method, data):
        return method(data)

    async def checkpoint():
        nonlocal calls
        calls += 1

    monkeypatch.setattr(async_module, "_run_in_thread", inline_offload)
    monkeypatch.setattr(async_module, "_NO_OUTPUT_STEPS_CHECKPOINT", 8)
    monkeypatch.setattr(async_module, "_cooperative_checkpoint", checkpoint)
    operation = _SequenceOperation([_CodecProgress(1), *([_CodecProgress(1)] * 7)])

    await _collect(
        operation,
        workload=b"x" * async_module._ZLIB_OFFLOAD_THRESHOLD,
    )

    assert calls == 0


def test_public_iteration_swallows_private_progress(monkeypatch):
    calls = 0

    class NoOutputEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def decompress(self, data, max_length=0):
            nonlocal calls
            calls += 1
            return b""

    monkeypatch.setattr(_engine, "decompressobj", lambda _wbits: NoOutputEngine())
    monkeypatch.setattr("aiogzip.codec._INFLATE_INPUT_WINDOW", 1)
    decoder = GzipDecoder()
    operation = decoder.feed(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xffabc")

    assert list(operation) == []
    assert calls == 3
    decoder.discard()


async def test_private_advancement_makes_at_most_one_inflate_call(monkeypatch):
    calls = 0

    class NoOutputEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def decompress(self, data, max_length=0):
            nonlocal calls
            calls += 1
            return b""

    monkeypatch.setattr(_engine, "decompressobj", lambda _wbits: NoOutputEngine())
    decoder = GzipDecoder()
    operation = decoder.feed(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xffabc")

    result = operation._advance_raw()

    assert result == _CodecProgress(3)
    assert calls == 1
    operation.close()


async def test_no_output_steps_give_sibling_ticker_progress(monkeypatch):
    calls = 0

    class NoOutputEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def decompress(self, data, max_length=0):
            nonlocal calls
            calls += 1
            return b""

    monkeypatch.setattr(_engine, "decompressobj", lambda _wbits: NoOutputEngine())
    monkeypatch.setattr("aiogzip.codec._INFLATE_INPUT_WINDOW", 1)
    monkeypatch.setattr(async_module, "_NO_OUTPUT_STEPS_CHECKPOINT", 2)
    progressed = asyncio.Event()

    async def ticker():
        progressed.set()

    task = asyncio.create_task(ticker())
    decoder = GzipDecoder()
    operation = decoder.feed(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xffabc")

    assert await _collect(operation) == []
    assert progressed.is_set()
    assert calls == 3
    await task
    decoder.discard()


async def test_cancellation_after_progress_closes_operation_once(monkeypatch):
    entered = asyncio.Event()

    async def checkpoint():
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(async_module, "_NO_OUTPUT_STEPS_CHECKPOINT", 1)
    monkeypatch.setattr(async_module, "_cooperative_checkpoint", checkpoint)
    operation = _SequenceOperation([_CodecProgress(1)])
    stream = _drive_operation(operation)
    task = asyncio.create_task(stream.__anext__())
    await entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert operation.close_calls == 1


def _empty_block_gzip(empty_blocks):
    payload = b"aiogzip-empty-block-prefix"
    length = len(payload)
    raw = bytearray(b"\x00")
    raw.extend(struct.pack("<H", length))
    raw.extend(struct.pack("<H", length ^ 0xFFFF))
    raw.extend(payload)
    raw.extend(b"\x00\x00\x00\xff\xff" * empty_blocks)
    raw.extend(b"\x01\x00\x00\xff\xff")
    trailer = struct.pack("<II", zlib.crc32(payload) & 0xFFFFFFFF, length)
    return b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff" + bytes(raw) + trailer


async def test_valid_empty_block_stream_makes_scheduler_progress():
    wire = _empty_block_gzip(60_000)
    expected = gzip.decompress(wire)
    ticks = 0
    done = False
    primed = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not done:
            ticks += 1
            primed.set()
            await asyncio.sleep(0)

    ticker_task = asyncio.create_task(ticker())
    await primed.wait()
    decoder = GzipDecoder()
    output = await _collect(decoder.feed(wire), workload=wire)
    output.extend(await _collect(decoder.finish()))
    done = True
    await ticker_task

    assert b"".join(output) == expected
    assert ticks > 1
