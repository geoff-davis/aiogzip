"""Tests for the private asyncio bridge over synchronous codec operations."""

import asyncio
import gzip
import os

import pytest

from aiogzip import GzipDecoder, GzipEncoder, _engine
from aiogzip._codec_async import _drive_operation


async def _collect(operation, **options):
    return [chunk async for chunk in _drive_operation(operation, **options)]


async def test_small_operation_runs_inline(monkeypatch):
    async def unexpected_offload(method, data):
        raise AssertionError("small operation must stay inline")

    monkeypatch.setattr(_engine, "run_zlib_in_thread", unexpected_offload)
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

    monkeypatch.setattr(_engine, "run_zlib_in_thread", recording_offload)
    payload = os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1)
    encoder = GzipEncoder(mtime=0, output_chunk_size=1024)
    header = await _collect(encoder.start())
    body = await _collect(
        encoder.feed(payload),
        workload=payload,
        offload_first_only=True,
    )
    final = await _collect(encoder.finish())

    assert calls == [len(payload)]
    assert gzip.decompress(b"".join((*header, *body, *final))) == payload


async def test_large_decoder_operation_offloads_bounded_steps(monkeypatch):
    calls = []

    async def recording_offload(method, data):
        calls.append(len(data))
        return method(data)

    monkeypatch.setattr(_engine, "run_zlib_in_thread", recording_offload)
    payload = os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1024)
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder(output_chunk_size=4096)

    output = await _collect(decoder.feed(wire), workload=wire)
    output.extend(await _collect(decoder.finish()))

    assert calls
    assert all(size == len(wire) for size in calls)
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

    monkeypatch.setattr(_engine, "run_zlib_in_thread", controlled_offload)
    payload = os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1)
    encoder = GzipEncoder(mtime=0)
    list(encoder.start())
    stream = _drive_operation(
        encoder.feed(payload),
        workload=payload,
        offload_first_only=True,
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

    class FailingOperation:
        def __iter__(self):
            return self

        def __next__(self):
            raise expected

        def close(self):
            raise RuntimeError("cleanup failed")

    with pytest.raises(LookupError) as caught:
        await _collect(FailingOperation())

    assert caught.value is expected
