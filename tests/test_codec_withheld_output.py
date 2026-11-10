"""``GzipDecoder.feed()`` emits everything its input can decode (#171).

A bounded inflate step can fill its output bound exactly as it consumes the
last input byte. The engine may then hold output it can produce with no more
input (a match in progress, or codes in its bit buffer). The decoder once
stopped there, so the tail of a message ended with ``Z_PARTIAL_FLUSH`` or
``Z_BLOCK`` came out only when later input arrived, and ``finish()`` on a
truncated stream raised without emitting it.
"""

import gzip
import zlib

import pytest

from aiogzip import GzipDecoder

HEADER = b"\x1f\x8b\x08\x00" + bytes(4) + b"\x00\xff"
# Sizes around the 256 KiB inflate batch, where the bound fills exactly.
SIZES = [*range(262_100, 262_200, 7), 262_144, 262_145, 262_165, 524_288, 524_300]
FLUSHES = [zlib.Z_PARTIAL_FLUSH, zlib.Z_BLOCK, zlib.Z_SYNC_FLUSH, zlib.Z_FULL_FLUSH]


def _message(size, flush, strategy=zlib.Z_DEFAULT_STRATEGY):
    payload = b"x" * size
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15, 9, strategy)
    wire = compressor.compress(payload) + compressor.flush(flush)
    # What an unbounded inflate can decode from this input alone.
    decodable = zlib.decompressobj(-15).decompress(wire)
    return wire, decodable, compressor


@pytest.mark.parametrize("flush", FLUSHES)
@pytest.mark.parametrize("strategy", [zlib.Z_DEFAULT_STRATEGY, zlib.Z_RLE])
@pytest.mark.parametrize("output_chunk_size", [1024, 64 * 1024, 1024 * 1024])
def test_feed_emits_all_decodable_output(flush, strategy, output_chunk_size):
    for size in SIZES:
        wire, decodable, compressor = _message(size, flush, strategy)
        decoder = GzipDecoder(output_chunk_size=output_chunk_size)
        got = b"".join(decoder.feed(HEADER + wire))
        assert got == decodable, (size, len(got), len(decodable))
        assert b"".join(decoder.feed(b"")) == b""

        # The stream continues normally afterwards.
        rest = compressor.compress(b"NEXT") + compressor.flush()
        payload = b"x" * size + b"NEXT"
        trailer = zlib.crc32(payload).to_bytes(4, "little") + (
            len(payload) & 0xFFFFFFFF
        ).to_bytes(4, "little")
        tail = b"".join(decoder.feed(rest + trailer)) + b"".join(decoder.finish())
        assert got + tail == payload
        assert decoder.finished


def test_finish_emits_recoverable_output_before_a_truncation_error():
    wire, decodable, _ = _message(262_165, zlib.Z_PARTIAL_FLUSH)
    decoder = GzipDecoder()
    got = bytearray()
    for chunk in decoder.feed(HEADER + wire):
        got += chunk
    with pytest.raises(gzip.BadGzipFile, match="ended before the deflate stream"):
        for chunk in decoder.finish():
            got += chunk
    assert bytes(got) == decodable


@pytest.mark.parametrize("over", [0, 1, 21])
def test_decompression_limit_is_exact_when_output_is_drained(over):
    size = 262_165
    wire, decodable, _ = _message(size, zlib.Z_PARTIAL_FLUSH)
    assert len(decodable) == size
    decoder = GzipDecoder(max_decompressed_size=size - over)
    got = bytearray()
    if over:
        with pytest.raises(OSError, match="max_decompressed_size"):
            for chunk in decoder.feed(HEADER + wire):
                got += chunk
        assert bytes(got) == decodable[: size - over]
    else:
        for chunk in decoder.feed(HEADER + wire):
            got += chunk
        assert bytes(got) == decodable


def test_complete_streams_are_unchanged():
    for size in SIZES:
        payload = b"x" * size
        decoder = GzipDecoder()
        got = b"".join(decoder.feed(gzip.compress(payload))) + b"".join(
            decoder.finish()
        )
        assert got == payload
