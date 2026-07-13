"""Tests for asynchronous iterable gzip compression."""

import asyncio
import gzip
import os
import random
import struct
import tracemalloc
import zlib

import pytest

import aiogzip
from aiogzip import _engine


async def _items(values):
    for value in values:
        yield value


async def _collect(source, **kwargs):
    return [chunk async for chunk in aiogzip.compress_chunks(source, **kwargs)]


class InstrumentedSource:
    def __init__(self, values):
        self.values = iter(values)
        self.pulls = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.pulls += 1
        try:
            return next(self.values)
        except StopIteration as error:
            raise StopAsyncIteration from error

    async def aclose(self):
        self.closed = True


class NoCloseSource:
    def __init__(self, values):
        self.values = iter(values)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.values)
        except StopIteration as error:
            raise StopAsyncIteration from error


class NoisyCloseSource(NoCloseSource):
    async def aclose(self):
        raise RuntimeError("source close failed")


def _assert_incomplete(compressed):
    with pytest.raises((EOFError, gzip.BadGzipFile, zlib.error)):
        gzip.decompress(compressed)


class TestCompressChunks:
    @pytest.mark.parametrize("values", [[], [b""], [b"", b"", b""]])
    async def test_empty_source_produces_valid_empty_member(self, values):
        output = await _collect(_items(values), mtime=0)
        compressed = b"".join(output)

        assert output
        assert all(output)
        assert gzip.decompress(compressed) == b""
        assert compressed.startswith(b"\x1f\x8b")

    async def test_one_and_many_input_chunks(self):
        values = [b"first", b"", os.urandom(10000), b"last"]

        output = await _collect(_items(values), mtime=0, output_chunk_size=31)

        assert gzip.decompress(b"".join(output)) == b"".join(values)
        assert all(0 < len(chunk) <= 31 for chunk in output)

    @pytest.mark.parametrize("output_chunk_size", [1, 2, 9, 10, 17, 65536])
    async def test_output_chunk_size_is_a_strict_bound(self, output_chunk_size):
        payload = os.urandom(300000)

        output = await _collect(
            _items([payload]),
            mtime=0,
            output_chunk_size=output_chunk_size,
        )

        assert gzip.decompress(b"".join(output)) == payload
        assert output
        assert all(0 < len(chunk) <= output_chunk_size for chunk in output)

    @pytest.mark.parametrize("seed", range(10))
    async def test_random_input_boundaries(self, seed):
        randomizer = random.Random(seed)
        payload = bytes(randomizer.getrandbits(8) for _ in range(100000))
        values = []
        offset = 0
        while offset < len(payload):
            size = randomizer.randint(1, 2003)
            values.append(payload[offset : offset + size])
            offset += size

        output = await _collect(_items(values), mtime=seed, output_chunk_size=997)

        assert gzip.decompress(b"".join(output)) == payload

    async def test_matches_existing_writer(self, tmp_path):
        payload = (b"compressible data" * 10000) + os.urandom(50000)
        output = await _collect(
            _items([payload]),
            mtime=0,
            original_filename="payload.bin",
        )
        path = tmp_path / "writer.gz"
        await aiogzip.write(
            path,
            payload,
            mtime=0,
            original_filename="payload.bin",
        )

        assert b"".join(output) == path.read_bytes()
        assert gzip.decompress(b"".join(output)) == await aiogzip.read(path)

    async def test_streaming_apis_pipeline_directly(self):
        values = [b"hello ", b"", b"world", os.urandom(10000)]
        compressed = aiogzip.compress_chunks(
            _items(values), mtime=0, output_chunk_size=7
        )

        restored = b"".join(
            [
                chunk
                async for chunk in aiogzip.decompress_chunks(
                    compressed, output_chunk_size=5
                )
            ]
        )

        assert restored == b"".join(values)

    async def test_metadata_and_deterministic_output(self):
        payload = os.urandom(100000)
        options = {
            "mtime": 123,
            "original_filename": "directory/events.jsonl.gz",
            "output_chunk_size": 19,
        }

        first = b"".join(await _collect(_items([payload]), **options))
        second = b"".join(await _collect(_items([payload]), **options))

        assert first == second
        assert struct.unpack("<I", first[4:8])[0] == 123
        assert first[3] & 0x08
        assert b"events.jsonl\x00" in first[:40]
        assert gzip.decompress(first) == payload

    async def test_fast_compression_option_reaches_engine(self, monkeypatch):
        calls = []
        real_compressobj = _engine.compressobj

        def recording_compressobj(level, wbits, fast=False):
            calls.append(fast)
            return real_compressobj(level, wbits, fast=fast)

        monkeypatch.setattr(_engine, "compressobj", recording_compressobj)

        if _engine.have_fast_engine():
            output = await _collect(_items([b"payload"]), mtime=0, fast_compress=True)
        else:
            with pytest.warns(
                UserWarning, match="zlib-ng is not available"
            ) as warnings:
                output = await _collect(
                    _items([b"payload"]), mtime=0, fast_compress=True
                )
            assert warnings[0].filename == __file__

        assert calls == [True]
        assert gzip.decompress(b"".join(output)) == b"payload"

    async def test_large_input_uses_executor(self, monkeypatch):
        calls = []

        async def recording_offload(method, data):
            calls.append(len(data))
            return method(data)

        monkeypatch.setattr(_engine, "run_zlib_in_thread", recording_offload)
        payload = os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1)

        output = await _collect(_items([payload]), mtime=0)

        assert calls == [len(payload)]
        assert gzip.decompress(b"".join(output)) == payload

    def test_argument_validation_is_eager(self):
        source = InstrumentedSource([])

        with pytest.raises(TypeError):
            aiogzip.compress_chunks(source, compresslevel=True)
        with pytest.raises(ValueError):
            aiogzip.compress_chunks(source, compresslevel=10)
        with pytest.raises(TypeError):
            aiogzip.compress_chunks(source, output_chunk_size=1.5)
        with pytest.raises(ValueError):
            aiogzip.compress_chunks(source, output_chunk_size=0)
        with pytest.raises(ValueError):
            aiogzip.compress_chunks(source, mtime=-1)
        with pytest.raises(ValueError):
            aiogzip.compress_chunks(source, original_filename="nul\x00name")

        assert source.pulls == 0

    @pytest.mark.parametrize("source", [[], iter([]), b""])
    def test_synchronous_sources_are_rejected_eagerly(self, source):
        with pytest.raises(TypeError, match="asynchronous iterable"):
            aiogzip.compress_chunks(source)

    async def test_aiter_must_return_async_iterator(self):
        class InvalidAsyncIterable:
            def __aiter__(self):
                return object()

        stream = aiogzip.compress_chunks(InvalidAsyncIterable(), mtime=0)
        with pytest.raises(TypeError, match="must return an asynchronous iterator"):
            await stream.__anext__()

    @pytest.mark.parametrize("invalid", [bytearray(), memoryview(b"data"), "data", 1])
    async def test_invalid_source_item_types(self, invalid):
        with pytest.raises(TypeError, match="source items must be bytes"):
            await _collect(_items([invalid]), mtime=0)

    async def test_strict_size_rejects_synthetic_overflow(self):
        class HugeBytes(bytes):
            def __len__(self):
                return 2**32

        with pytest.raises(OSError, match="4 GiB limit"):
            await _collect(_items([HugeBytes(b"x")]), mtime=0, strict_size=True)

    async def test_source_failure_before_payload_emits_no_trailer(self):
        expected = LookupError("source failed")

        async def source():
            if False:
                yield b""
            raise expected

        emitted = []
        with pytest.raises(LookupError) as caught:
            async for chunk in aiogzip.compress_chunks(source(), mtime=0):
                emitted.append(chunk)

        assert caught.value is expected
        assert b"".join(emitted).startswith(b"\x1f\x8b")
        _assert_incomplete(b"".join(emitted))

    async def test_source_failure_after_compressed_output_emits_no_trailer(self):
        expected = LookupError("source failed")
        payload = os.urandom(300000)

        async def source():
            yield payload
            raise expected

        emitted = []
        with pytest.raises(LookupError) as caught:
            async for chunk in aiogzip.compress_chunks(
                source(), mtime=0, output_chunk_size=1024
            ):
                emitted.append(chunk)

        assert caught.value is expected
        assert len(emitted) > 1
        _assert_incomplete(b"".join(emitted))

    async def test_header_is_prompt_and_early_exit_does_not_pull_source(self):
        source = InstrumentedSource([b"payload"])
        stream = aiogzip.compress_chunks(source, mtime=0, output_chunk_size=4)

        assert source.pulls == 0
        assert await stream.__anext__() == b"\x1f\x8b\x08\x00"
        assert source.pulls == 0

        await stream.aclose()

        assert source.pulls == 0
        assert source.closed

    async def test_complete_consumption_closes_source_iterator(self):
        source = InstrumentedSource([b"payload"])

        output = await _collect(source, mtime=0)

        assert gzip.decompress(b"".join(output)) == b"payload"
        assert source.closed

    async def test_source_without_aclose_is_supported(self):
        source = NoCloseSource([b"payload"])

        output = await _collect(source, mtime=0)

        assert gzip.decompress(b"".join(output)) == b"payload"

    async def test_source_close_error_propagates_after_success(self):
        source = NoisyCloseSource([b"payload"])

        with pytest.raises(RuntimeError, match="source close failed"):
            await _collect(source, mtime=0)

    async def test_close_error_does_not_replace_source_failure(self):
        source = NoisyCloseSource(["not bytes"])

        with pytest.raises(TypeError, match="source items must be bytes"):
            await _collect(source, mtime=0)

    async def test_cancellation_while_waiting_on_source(self):
        started = asyncio.Event()
        closed = asyncio.Event()

        async def source():
            try:
                started.set()
                await asyncio.Event().wait()
                yield b"unreachable"
            finally:
                closed.set()

        stream = aiogzip.compress_chunks(source(), mtime=0)
        assert await stream.__anext__()
        task = asyncio.create_task(stream.__anext__())
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    async def test_cancellation_during_offloaded_compression(self, monkeypatch):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_offload(method, data):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(_engine, "run_zlib_in_thread", blocked_offload)
        payload = os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1)
        stream = aiogzip.compress_chunks(_items([payload]), mtime=0)
        assert await stream.__anext__()
        task = asyncio.create_task(stream.__anext__())
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    async def test_early_exit_after_compressed_output_stops_source(self):
        source = InstrumentedSource([os.urandom(300000), b"unexpected"])
        stream = aiogzip.compress_chunks(source, mtime=0, output_chunk_size=1024)
        emitted = [await stream.__anext__()]
        while source.pulls == 0:
            emitted.append(await stream.__anext__())
        emitted.append(await stream.__anext__())

        await stream.aclose()

        assert source.pulls == 1
        assert source.closed
        _assert_incomplete(b"".join(emitted))

    async def test_concurrent_advancement_is_rejected(self):
        started = asyncio.Event()

        async def source():
            started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        stream = aiogzip.compress_chunks(source(), mtime=0)
        assert await stream.__anext__()
        first = asyncio.create_task(stream.__anext__())
        await started.wait()

        with pytest.raises(RuntimeError):
            await stream.__anext__()

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

    @pytest.mark.slow
    async def test_highly_compressible_input_has_bounded_allocations(self):
        payload_size = 8 * 1024 * 1024

        async def source():
            chunk = b"A" * (64 * 1024)
            for _ in range(payload_size // len(chunk)):
                yield chunk

        total = 0
        tracemalloc.start()
        try:
            async for chunk in aiogzip.compress_chunks(
                source(), mtime=0, output_chunk_size=8192
            ):
                total += len(chunk)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert total > 0
        assert total < payload_size
        assert peak < 3 * 1024 * 1024
