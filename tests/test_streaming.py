"""Tests for asynchronous iterable gzip streaming APIs."""

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
from aiogzip import _streaming as streaming_module


async def _chunks(data, size):
    for offset in range(0, len(data), size):
        yield data[offset : offset + size]


async def _items(values):
    for value in values:
        yield value


async def _collect(source, **kwargs):
    return [chunk async for chunk in aiogzip.decompress_chunks(source, **kwargs)]


def _metadata_member(payload):
    flags = 0x04 | 0x08 | 0x10 | 0x02
    header = bytearray(b"\x1f\x8b\x08")
    header.append(flags)
    header.extend(struct.pack("<I", 123))
    header.extend(b"\x00\xff")
    extra = b"\x01\x02extra"
    header.extend(struct.pack("<H", len(extra)))
    header.extend(extra)
    header.extend("café.bin".encode("latin-1") + b"\x00")
    header.extend(b"streaming test\x00")
    header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))
    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = compressor.compress(payload) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload))
    return bytes(header) + body + trailer


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


class TestDecompressChunks:
    @pytest.mark.parametrize("values", [[], [b""], [b"", b"", b""]])
    async def test_zero_byte_source(self, values):
        output = await _collect(_items(values))

        assert output == []

    async def test_final_decoder_output_is_forwarded(self, monkeypatch):
        class FinalOutputDecoder:
            def __init__(self, **kwargs):
                pass

            def feed(self, data):
                return iter(())

            def finish(self):
                return iter((b"final output",))

            def discard(self):
                pass

        monkeypatch.setattr(streaming_module, "GzipDecoder", FinalOutputDecoder)

        output = await _collect(_items([]))

        assert output == [b"final output"]

    @pytest.mark.parametrize("input_chunk_size", [1, 2, 3, 7, 17, 257, 4096])
    async def test_one_member_arbitrary_input_chunks(self, input_chunk_size):
        payload = (b"streaming payload\n" * 5000) + os.urandom(4096)
        compressed = gzip.compress(payload, mtime=0)

        output = await _collect(
            _chunks(compressed, input_chunk_size), output_chunk_size=113
        )

        assert b"".join(output) == payload
        assert output
        assert all(0 < len(chunk) <= 113 for chunk in output)

    async def test_concatenated_members_and_empty_chunks(self):
        payloads = [b"first", b"", os.urandom(10000)]
        compressed = b"".join(gzip.compress(value, mtime=0) for value in payloads)
        values = []
        for offset in range(0, len(compressed), 11):
            values.extend([b"", compressed[offset : offset + 11]])

        output = await _collect(_items(values), output_chunk_size=7)

        assert b"".join(output) == b"".join(payloads)
        assert all(0 < len(chunk) <= 7 for chunk in output)

    async def test_simple_bytes_subclass_source_item_is_accepted(self):
        class Compressed(bytes):
            pass

        compressed = Compressed(gzip.compress(b"subclass payload", mtime=0))

        assert b"".join(await _collect(_items([compressed]))) == b"subclass payload"

    async def test_hostile_bytes_subclass_uses_raw_buffer_snapshot(self):
        class Hostile(bytes):
            def __bytes__(self):
                raise AssertionError("__bytes__ must not run")

            def __len__(self):
                raise AssertionError("__len__ must not run")

            def __iter__(self):
                raise AssertionError("__iter__ must not run")

            def __getitem__(self, key):
                raise AssertionError("__getitem__ must not run")

        wire = gzip.compress(b"raw payload", mtime=0)

        assert b"".join(await _collect(_items([Hostile(wire)]))) == b"raw payload"

    async def test_metadata_heavy_header_split_bytewise(self):
        payload = b"metadata payload" * 100
        compressed = _metadata_member(payload)

        output = await _collect(_chunks(compressed, 1), output_chunk_size=13)

        assert b"".join(output) == payload

    @pytest.mark.parametrize("output_chunk_size", [1, 2, 9, 256 * 1024, 1024 * 1024])
    async def test_output_chunk_size_is_a_strict_bound(self, output_chunk_size):
        payload = os.urandom(300000)
        compressed = gzip.compress(payload, mtime=0)

        output = await _collect(
            _chunks(compressed, 1009), output_chunk_size=output_chunk_size
        )

        assert b"".join(output) == payload
        assert output
        assert all(0 < len(chunk) <= output_chunk_size for chunk in output)

    @pytest.mark.parametrize("seed", range(10))
    async def test_random_input_boundaries(self, seed):
        randomizer = random.Random(seed)
        payload = bytes(randomizer.getrandbits(8) for _ in range(50000))
        compressed = gzip.compress(payload, mtime=seed)

        async def random_chunks():
            offset = 0
            while offset < len(compressed):
                size = randomizer.randint(1, 997)
                yield compressed[offset : offset + size]
                offset += size

        output = await _collect(random_chunks(), output_chunk_size=251)

        assert b"".join(output) == payload
        assert gzip.decompress(compressed) == payload

    async def test_matches_file_reader_and_stdlib(self, tmp_path):
        payload = (b"abc123" * 100000) + os.urandom(50000)
        compressed = gzip.compress(payload, mtime=0)
        path = tmp_path / "stream.gz"
        path.write_bytes(compressed)

        streamed = b"".join(await _collect(_chunks(compressed, 313)))

        assert streamed == await aiogzip.read(path)
        assert streamed == gzip.decompress(compressed)

    @pytest.mark.parametrize(
        "compressed",
        [
            b"not gzip",
            b"\x1f\x8b",
            gzip.compress(b"payload", mtime=0)[:-9],
            gzip.compress(b"payload", mtime=0)[:-1],
        ],
    )
    async def test_malformed_or_truncated_input(self, compressed):
        with pytest.raises(gzip.BadGzipFile):
            await _collect(_chunks(compressed, 2))

    async def test_trailer_corruption_can_follow_yielded_payload(self):
        payload = b"payload available before trailer validation"
        compressed = bytearray(gzip.compress(payload, mtime=0))
        compressed[-8] ^= 1
        stream = aiogzip.decompress_chunks(_items([bytes(compressed)]))
        output = []

        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            while True:
                output.append(await stream.__anext__())

        assert b"".join(output) == payload

    async def test_corrupt_deflate_payload(self):
        compressed = bytearray(gzip.compress(os.urandom(1000), mtime=0))
        compressed[len(compressed) // 2] ^= 0xFF

        with pytest.raises(gzip.BadGzipFile):
            await _collect(_items([bytes(compressed)]))

    @pytest.mark.parametrize("damage", ["reserved flags", "header crc"])
    async def test_corrupt_header_fields(self, damage):
        if damage == "reserved flags":
            compressed = bytearray(gzip.compress(b"payload", mtime=0))
            compressed[3] |= 0x20
        else:
            compressed = bytearray(_metadata_member(b"payload"))
            compressed[4] ^= 1

        with pytest.raises(gzip.BadGzipFile):
            await _collect(_chunks(bytes(compressed), 1))

    async def test_trailing_padding_matches_reader_behavior(self):
        member = gzip.compress(b"payload", mtime=0)

        assert b"".join(await _collect(_items([member + b"\x00" * 5]))) == b"payload"
        with pytest.raises(gzip.BadGzipFile):
            await _collect(_items([member + b"junk"]))

    async def test_exact_and_cumulative_decompression_limits(self):
        compressed = gzip.compress(b"abc", mtime=0) + gzip.compress(b"def", mtime=0)

        output = await _collect(
            _chunks(compressed, 3),
            output_chunk_size=2,
            max_decompressed_size=6,
        )
        assert b"".join(output) == b"abcdef"

        with pytest.raises(OSError, match="max_decompressed_size"):
            await _collect(
                _chunks(compressed, 3),
                output_chunk_size=2,
                max_decompressed_size=5,
            )

    async def test_limit_failure_does_not_yield_over_limit_output(self):
        compressed = gzip.compress(b"A" * (8 * 1024 * 1024), mtime=0)
        emitted = 0

        with pytest.raises(OSError, match="max_decompressed_size"):
            async for chunk in aiogzip.decompress_chunks(
                _chunks(compressed, 31),
                output_chunk_size=128,
                max_decompressed_size=1000,
            ):
                emitted += len(chunk)

        assert emitted <= 1000

    @pytest.mark.parametrize("invalid", [True, 1.5, "1", 0, -1, 128 * 1024 * 1024 + 1])
    def test_invalid_output_chunk_size_is_rejected_eagerly(self, invalid):
        expected = TypeError if invalid in (True, 1.5, "1") else ValueError

        with pytest.raises(expected):
            aiogzip.decompress_chunks(_items([]), output_chunk_size=invalid)

    @pytest.mark.parametrize("invalid", [True, 1.5, "1", 0, -1])
    def test_invalid_limit_is_rejected_eagerly(self, invalid):
        expected = TypeError if invalid in (True, 1.5, "1") else ValueError

        with pytest.raises(expected):
            aiogzip.decompress_chunks(_items([]), max_decompressed_size=invalid)

    @pytest.mark.parametrize("source", [[], iter([]), b""])
    def test_synchronous_sources_are_rejected_eagerly(self, source):
        with pytest.raises(TypeError, match="asynchronous iterable"):
            aiogzip.decompress_chunks(source)

    async def test_aiter_must_return_an_async_iterator(self):
        class InvalidAsyncIterable:
            def __aiter__(self):
                return object()

        with pytest.raises(TypeError, match="must return an asynchronous iterator"):
            await _collect(InvalidAsyncIterable())

    @pytest.mark.parametrize("invalid", [bytearray(), memoryview(b"data"), "data", 1])
    async def test_invalid_source_item_types(self, invalid):
        with pytest.raises(TypeError, match="source items must be bytes"):
            await _collect(_items([invalid]))

    async def test_source_exception_propagates(self):
        expected = LookupError("source failed")

        async def failing_source():
            yield gzip.compress(b"first", mtime=0)
            raise expected

        stream = aiogzip.decompress_chunks(failing_source())
        assert await stream.__anext__() == b"first"
        with pytest.raises(LookupError) as caught:
            await stream.__anext__()
        assert caught.value is expected

    async def test_source_iterator_closes_after_complete_consumption(self):
        source = InstrumentedSource([gzip.compress(b"payload", mtime=0)])

        assert b"".join(await _collect(source)) == b"payload"
        assert source.closed

    async def test_source_without_aclose_is_supported(self):
        source = NoCloseSource([gzip.compress(b"payload", mtime=0)])

        assert b"".join(await _collect(source)) == b"payload"

    async def test_source_close_error_propagates_after_success(self):
        source = NoisyCloseSource([gzip.compress(b"payload", mtime=0)])

        with pytest.raises(RuntimeError, match="source close failed"):
            await _collect(source)

    async def test_source_close_error_does_not_replace_operation_failure(self):
        source = NoisyCloseSource(["not bytes"])

        with pytest.raises(TypeError, match="source items must be bytes"):
            await _collect(source)

    async def test_no_eager_source_consumption_and_early_close(self):
        compressed = gzip.compress(b"payload", mtime=0)
        source = InstrumentedSource([compressed, b"", b"unexpected"])

        stream = aiogzip.decompress_chunks(source, output_chunk_size=1)
        assert source.pulls == 0
        assert await stream.__anext__() == b"p"
        assert source.pulls == 1

        await stream.aclose()

        assert source.pulls == 1
        assert source.closed

    async def test_cancellation_while_waiting_on_source(self):
        started = asyncio.Event()
        closed = asyncio.Event()

        async def waiting_source():
            try:
                started.set()
                await asyncio.Event().wait()
                yield b"unreachable"
            finally:
                closed.set()

        stream = aiogzip.decompress_chunks(waiting_source())
        task = asyncio.create_task(stream.__anext__())
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()

    async def test_cancellation_during_offloaded_codec_work(self, monkeypatch):
        compressed = gzip.compress(
            os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1024), mtime=0
        )
        started = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()

        async def blocked_offload(method, data):
            started.set()
            try:
                await release.wait()
                return method(data)
            finally:
                completed.set()

        monkeypatch.setattr(_engine, "run_zlib_in_thread", blocked_offload)
        stream = aiogzip.decompress_chunks(_items([compressed]))
        task = asyncio.create_task(stream.__anext__())
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()

    async def test_cancellation_after_output_has_been_yielded(self):
        payload = b"output before cancellation"
        compressed = gzip.compress(payload, mtime=0)
        waiting = asyncio.Event()
        closed = asyncio.Event()

        async def source():
            try:
                yield compressed[:-8]
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        stream = aiogzip.decompress_chunks(source())
        assert await stream.__anext__() == payload
        task = asyncio.create_task(stream.__anext__())
        await waiting.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()

    async def test_concurrent_advancement_has_a_clear_error(self):
        started = asyncio.Event()

        async def waiting_source():
            started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        stream = aiogzip.decompress_chunks(waiting_source())
        first = asyncio.create_task(stream.__anext__())
        await started.wait()

        with pytest.raises(RuntimeError):
            await stream.__anext__()

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

    @pytest.mark.slow
    async def test_highly_compressible_input_has_bounded_python_allocations(self):
        payload_size = 8 * 1024 * 1024
        compressed = gzip.compress(b"A" * payload_size, mtime=0)
        total = 0
        tracemalloc.start()
        try:
            async for chunk in aiogzip.decompress_chunks(
                _chunks(compressed, 97), output_chunk_size=8192
            ):
                total += len(chunk)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert total == payload_size
        assert peak < 3 * 1024 * 1024
