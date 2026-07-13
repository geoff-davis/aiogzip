"""Tests for the private incremental gzip encoder."""

import asyncio
import gzip
import os
import struct
import zlib

import pytest

import aiogzip
from aiogzip import _engine
from aiogzip._streaming import _IncrementalGzipEncoder


def _encoder(**overrides):
    options = {
        "compresslevel": 6,
        "mtime": 0,
        "original_filename": None,
        "fast_compress": False,
        "strict_size": False,
        "output_chunk_size": 64,
    }
    options.update(overrides)
    return _IncrementalGzipEncoder(**options)


async def _encode(values, **overrides):
    encoder = _encoder(**overrides)
    output = list(encoder.start())
    for value in values:
        async for chunk in encoder.feed(value):
            output.append(chunk)
    async for chunk in encoder.finish():
        output.append(chunk)
    return encoder, output


class TestIncrementalGzipEncoder:
    async def test_empty_input_produces_one_valid_member(self):
        encoder, output = await _encode([])
        compressed = b"".join(output)

        assert gzip.decompress(compressed) == b""
        assert compressed.startswith(b"\x1f\x8b")
        assert len(compressed) >= 20
        assert encoder.input_size == 0
        assert encoder.crc32 == 0

    @pytest.mark.parametrize("output_chunk_size", [1, 2, 9, 10, 17, 256 * 1024])
    async def test_strict_output_bound(self, output_chunk_size):
        payload = os.urandom(300000)

        _, output = await _encode([payload], output_chunk_size=output_chunk_size)

        assert gzip.decompress(b"".join(output)) == payload
        assert output
        assert all(0 < len(chunk) <= output_chunk_size for chunk in output)

    async def test_many_input_chunks_preserve_order(self):
        values = [b"first", b"", os.urandom(10000), b"last"]

        encoder, output = await _encode(values, output_chunk_size=31)

        assert gzip.decompress(b"".join(output)) == b"".join(values)
        assert encoder.input_size == sum(len(value) for value in values)
        assert encoder.crc32 == zlib.crc32(b"".join(values))

    async def test_metadata_matches_existing_writer(self, tmp_path):
        payload = b"metadata payload" * 100
        encoder, output = await _encode(
            [payload],
            mtime=123,
            original_filename="directory/events.jsonl.gz",
        )
        streamed = b"".join(output)
        path = tmp_path / "different.gz"
        await aiogzip.write(
            path,
            payload,
            mtime=123,
            original_filename="directory/events.jsonl.gz",
        )

        assert streamed == path.read_bytes()
        assert gzip.decompress(streamed) == payload
        assert struct.unpack("<I", streamed[4:8])[0] == 123
        assert streamed[3] & 0x08
        assert b"events.jsonl\x00" in streamed[:40]
        assert encoder.input_size == len(payload)

    async def test_explicit_metadata_is_deterministic(self):
        payload = os.urandom(100000)

        _, first = await _encode([payload], mtime=0, original_filename="payload.bin")
        _, second = await _encode([payload], mtime=0, original_filename="payload.bin")

        assert b"".join(first) == b"".join(second)

    async def test_default_filename_is_absent(self):
        _, output = await _encode([b"payload"])

        assert b"".join(output)[3] & 0x08 == 0

    async def test_default_compression_uses_stdlib_selection(self, monkeypatch):
        calls = []
        real_compressobj = _engine.compressobj

        def recording_compressobj(level, wbits, fast=False):
            calls.append(fast)
            return real_compressobj(level, wbits, fast=fast)

        monkeypatch.setattr(_engine, "compressobj", recording_compressobj)

        _, output = await _encode([b"payload"])

        assert calls == [False]
        assert gzip.decompress(b"".join(output)) == b"payload"

    async def test_fast_compression_selection_roundtrips(self, monkeypatch):
        calls = []
        real_compressobj = _engine.compressobj

        def recording_compressobj(level, wbits, fast=False):
            calls.append(fast)
            return real_compressobj(level, wbits, fast=fast)

        monkeypatch.setattr(_engine, "compressobj", recording_compressobj)

        _, output = await _encode([b"payload"], fast_compress=True)

        assert calls == [True]
        assert gzip.decompress(b"".join(output)) == b"payload"

    def test_fast_compression_warns_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(_engine, "have_fast_engine", lambda: False)

        with pytest.warns(UserWarning, match="zlib-ng is not available"):
            _encoder(fast_compress=True)

    async def test_large_feed_uses_executor_offload(self, monkeypatch):
        calls = []

        async def recording_offload(method, data):
            calls.append(len(data))
            return method(data)

        monkeypatch.setattr(_engine, "run_zlib_in_thread", recording_offload)
        payload = os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1)

        _, output = await _encode([payload])

        assert calls == [len(payload)]
        assert gzip.decompress(b"".join(output)) == payload

    async def test_cancelled_offload_makes_encoder_unusable(self, monkeypatch):
        started = asyncio.Event()

        async def blocked_offload(method, data):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(_engine, "run_zlib_in_thread", blocked_offload)
        encoder = _encoder()
        list(encoder.start())
        payload = os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1)
        feed = encoder.feed(payload)
        task = asyncio.create_task(feed.__anext__())
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(OSError, match="unusable"):
            encoder.finish()

    async def test_codec_error_makes_encoder_unusable(self, monkeypatch):
        class BrokenCompressor:
            def compress(self, data):
                raise zlib.error("broken codec")

            def flush(self):
                return b""

        monkeypatch.setattr(
            _engine, "compressobj", lambda *args, **kwargs: BrokenCompressor()
        )
        encoder = _encoder()
        list(encoder.start())

        with pytest.raises(OSError, match="Error compressing data"):
            async for _ in encoder.feed(b"payload"):
                pass
        with pytest.raises(OSError, match="unusable"):
            encoder.feed(b"more")

    async def test_unexpected_codec_error_is_wrapped(self, monkeypatch):
        class BrokenCompressor:
            def compress(self, data):
                raise RuntimeError("unexpected codec failure")

            def flush(self):
                return b""

        monkeypatch.setattr(
            _engine, "compressobj", lambda *args, **kwargs: BrokenCompressor()
        )
        encoder = _encoder()
        list(encoder.start())

        with pytest.raises(OSError, match="Unexpected error during compression"):
            async for _ in encoder.feed(b"payload"):
                pass

    @pytest.mark.parametrize(
        ("failure", "message"),
        [
            (zlib.error("flush failed"), "Error finalizing compressed data"),
            (
                RuntimeError("flush failed"),
                "Unexpected error during compression finalization",
            ),
        ],
    )
    async def test_finalization_errors_make_encoder_unusable(
        self, monkeypatch, failure, message
    ):
        class BrokenCompressor:
            def compress(self, data):
                return b""

            def flush(self):
                raise failure

        monkeypatch.setattr(
            _engine, "compressobj", lambda *args, **kwargs: BrokenCompressor()
        )
        encoder = _encoder()
        list(encoder.start())

        with pytest.raises(OSError, match=message):
            async for _ in encoder.finish():
                pass
        assert encoder._failed

    async def test_abandoned_feed_makes_encoder_unusable(self):
        encoder = _encoder(output_chunk_size=1)
        list(encoder.start())
        feed = encoder.feed(os.urandom(300000))

        assert await feed.__anext__()
        await feed.aclose()

        with pytest.raises(OSError, match="unusable"):
            encoder.finish()

    async def test_abandoned_finalization_is_rejected(self):
        encoder = _encoder(output_chunk_size=1)
        list(encoder.start())
        async for _ in encoder.feed(b"payload"):
            pass
        finalization = encoder.finish()

        assert await finalization.__anext__()
        await finalization.aclose()

        assert encoder._failed
        with pytest.raises(ValueError, match="already finalized"):
            encoder.finish()

    async def test_finalizes_exactly_once_and_rejects_later_feeds(self):
        encoder = _encoder()
        list(encoder.start())
        async for _ in encoder.feed(b"payload"):
            pass
        output = [chunk async for chunk in encoder.finish()]

        assert output
        with pytest.raises(ValueError, match="already finalized"):
            encoder.finish()
        with pytest.raises(ValueError, match="already finalized"):
            encoder.feed(b"more")

    async def test_concurrent_advancement_is_rejected(self, monkeypatch):
        started = asyncio.Event()

        async def blocked_offload(method, data):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(_engine, "run_zlib_in_thread", blocked_offload)
        encoder = _encoder()
        list(encoder.start())
        first_feed = encoder.feed(os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1))
        first = asyncio.create_task(first_feed.__anext__())
        await started.wait()

        second_feed = encoder.feed(b"second")
        with pytest.raises(RuntimeError, match="concurrently"):
            await second_feed.__anext__()

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

    def test_start_and_finish_order_is_enforced(self):
        encoder = _encoder()

        with pytest.raises(ValueError, match="started before feeding"):
            encoder.feed(b"payload")
        with pytest.raises(ValueError, match="started before finalizing"):
            encoder.finish()
        list(encoder.start())
        with pytest.raises(ValueError, match="already started"):
            encoder.start()

    def test_discard_is_one_way(self):
        encoder = _encoder()
        list(encoder.start())

        encoder.discard()

        assert encoder._engine is None
        with pytest.raises(OSError, match="unusable"):
            encoder.feed(b"payload")

    @pytest.mark.parametrize("invalid", [bytearray(), memoryview(b"data"), "data", 1])
    def test_feed_accepts_only_bytes(self, invalid):
        encoder = _encoder()
        list(encoder.start())

        with pytest.raises(TypeError, match="input must be bytes"):
            encoder.feed(invalid)

    @pytest.mark.parametrize("invalid", [True, 1.5, "6", -2, 10])
    def test_invalid_compression_level(self, invalid):
        expected = TypeError if invalid in (True, 1.5, "6") else ValueError
        with pytest.raises(expected):
            _encoder(compresslevel=invalid)

    @pytest.mark.parametrize("invalid", [True, 1.5, "1", 0, -1])
    def test_invalid_output_chunk_size(self, invalid):
        expected = TypeError if invalid in (True, 1.5, "1") else ValueError
        with pytest.raises(expected):
            _encoder(output_chunk_size=invalid)

    @pytest.mark.parametrize("invalid", [-1, 2**32, "now", object()])
    def test_invalid_mtime(self, invalid):
        expected = TypeError if not isinstance(invalid, (int, float)) else ValueError
        with pytest.raises(expected):
            _encoder(mtime=invalid)

    @pytest.mark.parametrize("invalid", [1, "nul\x00name", b"nul\x00name"])
    def test_invalid_original_filename(self, invalid):
        expected = TypeError if invalid == 1 else ValueError
        with pytest.raises(expected):
            _encoder(original_filename=invalid)

    def test_strict_size_rejects_crossing_isize_limit(self):
        encoder = _encoder(strict_size=True)
        list(encoder.start())
        encoder._input_size = 0xFFFFFFFF

        with pytest.raises(OSError, match="4 GiB limit"):
            encoder.feed(b"x")

    async def test_non_strict_trailer_wraps_isize(self):
        encoder = _encoder(strict_size=False)
        list(encoder.start())
        encoder._input_size = 2**32 + 5

        output = [chunk async for chunk in encoder.finish()]

        assert struct.unpack("<I", b"".join(output)[-4:])[0] == 5
