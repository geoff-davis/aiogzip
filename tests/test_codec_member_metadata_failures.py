"""Completed-member metadata remains available after a later failure."""

from __future__ import annotations

import gzip
import struct
import zlib
from dataclasses import FrozenInstanceError

import pytest

from aiogzip import GzipDecoder, _engine

FIRST_PAYLOAD = b"validated first member"
SECOND_PAYLOAD = bytes(range(256)) * 32


def _member_with_bad_fhcrc(payload: bytes) -> bytes:
    header = bytearray(b"\x1f\x8b\x08\x0a")
    header.extend(struct.pack("<I", 456))
    header.extend(b"\x00\xff")
    header.extend(b"later.bin\x00")
    header.extend(struct.pack("<H", (zlib.crc32(header) & 0xFFFF) ^ 1))
    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = compressor.compress(payload) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload))
    return bytes(header) + body + trailer


def _assert_unusable_and_released(decoder: GzipDecoder) -> None:
    assert not decoder.finished
    assert len(decoder._pending) == 0
    assert decoder._inflate_input is None
    assert len(decoder._output) == 0
    assert decoder._eof_after_output is False
    assert decoder._engine is None
    assert decoder._header is None
    assert decoder._header_parser is None
    assert decoder._state == "header"
    assert decoder._member_offset == 0
    assert decoder._member_crc == 0
    assert decoder._member_size == 0
    assert decoder._allow_padding is False
    with pytest.raises(OSError, match="unusable"):
        decoder.feed(b"")
    with pytest.raises(OSError, match="unusable"):
        decoder.finish()


def _trigger_later_failure(decoder: GzipDecoder, failure: str) -> None:
    second = gzip.compress(SECOND_PAYLOAD, mtime=456)

    if failure == "crc":
        damaged = bytearray(second)
        damaged[-8] ^= 1
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            list(decoder.feed(bytes(damaged)))
    elif failure == "isize":
        damaged = bytearray(second)
        damaged[-4] ^= 1
        with pytest.raises(gzip.BadGzipFile, match="ISIZE check failed"):
            list(decoder.feed(bytes(damaged)))
    elif failure == "truncated-header":
        assert list(decoder.feed(b"\x1f\x8b\x08")) == []
        with pytest.raises(gzip.BadGzipFile, match="truncated gzip member header"):
            list(decoder.finish())
    elif failure == "malformed-optional-header":
        with pytest.raises(gzip.BadGzipFile, match="Header CRC check failed"):
            list(decoder.feed(_member_with_bad_fhcrc(SECOND_PAYLOAD)))
    elif failure == "reserved-flags":
        damaged = bytearray(second)
        damaged[3] |= 0x20
        with pytest.raises(gzip.BadGzipFile, match="Reserved flags"):
            list(decoder.feed(bytes(damaged)))
    elif failure == "truncated-body":
        list(decoder.feed(second[:12]))
        with pytest.raises(gzip.BadGzipFile, match="deflate stream completed"):
            list(decoder.finish())
    elif failure == "truncated-trailer":
        assert b"".join(decoder.feed(second[:-1])) == SECOND_PAYLOAD
        with pytest.raises(gzip.BadGzipFile, match="truncated trailer"):
            list(decoder.finish())
    elif failure == "decompression-limit":
        with pytest.raises(OSError, match="max_decompressed_size"):
            list(decoder.feed(second))
    elif failure == "trailing-junk":
        with pytest.raises(gzip.BadGzipFile):
            list(decoder.feed(b"not a gzip member"))
    elif failure == "operation-close":
        operation = decoder.feed(second)
        assert next(operation)
        operation.close()
    elif failure == "discard-during-member":
        operation = decoder.feed(second)
        assert next(operation)
        decoder.discard()
        with pytest.raises(RuntimeError, match="invalidated"):
            next(operation)
    elif failure == "discard-between-members":
        decoder.discard()
    elif failure == "repeated-discard":
        decoder.discard()
        decoder.discard()
    else:  # pragma: no cover - protects the parameterized test itself
        raise AssertionError(f"unknown failure case: {failure}")


FAILURES = [
    "crc",
    "isize",
    "truncated-header",
    "malformed-optional-header",
    "reserved-flags",
    "truncated-body",
    "truncated-trailer",
    "decompression-limit",
    "trailing-junk",
    "operation-close",
    "discard-during-member",
    "discard-between-members",
    "repeated-discard",
]


@pytest.mark.parametrize("collect_member_info", [False, True])
@pytest.mark.parametrize("failure", FAILURES)
def test_completed_metadata_survives_later_failure_and_discard(
    failure, collect_member_info
):
    first = gzip.compress(FIRST_PAYLOAD, mtime=123)
    limit = len(FIRST_PAYLOAD) + 31 if failure == "decompression-limit" else None
    decoder = GzipDecoder(
        collect_member_info=collect_member_info,
        max_decompressed_size=limit,
        output_chunk_size=7,
    )

    assert b"".join(decoder.feed(first)) == FIRST_PAYLOAD
    assert decoder.member_count == 1
    before = decoder.members

    _trigger_later_failure(decoder, failure)

    assert decoder.member_count == 1
    assert len(decoder.members) == (decoder.member_count if collect_member_info else 0)
    if collect_member_info:
        assert decoder.members == before
        assert decoder.members[0] is before[0]
        assert decoder.members[0].index == 0
        assert decoder.members[0].compressed_offset == 0
        assert decoder.members[0].compressed_size == len(first)
        assert decoder.members[0].uncompressed_size == len(FIRST_PAYLOAD)
        assert decoder.members[0].mtime == 123
        assert decoder.members[0].original_filename is None
        assert decoder.members[0].comment is None
        assert decoder.members[0].extra is None
        assert decoder.members[0].flags == 0
        assert decoder.members[0].crc32 == zlib.crc32(FIRST_PAYLOAD)
        assert decoder.members[0].trailer_isize == len(FIRST_PAYLOAD)
        with pytest.raises(FrozenInstanceError):
            decoder.members[0].index = 99
    else:
        assert before == ()
        assert decoder.members == ()

    _assert_unusable_and_released(decoder)


@pytest.mark.parametrize(
    "use_zlib_ng",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                _engine._zng is None,
                reason="zlib-ng not installed",
            ),
        ),
    ],
    ids=["stdlib", "zlib-ng"],
)
def test_retained_completed_record_is_engine_independent(monkeypatch, use_zlib_ng):
    monkeypatch.setattr(_engine, "_HAVE_ZNG", use_zlib_ng)
    first = gzip.compress(FIRST_PAYLOAD, mtime=123)
    second = bytearray(gzip.compress(SECOND_PAYLOAD, mtime=456))
    second[-8] ^= 1
    decoder = GzipDecoder(collect_member_info=True)

    assert b"".join(decoder.feed(first)) == FIRST_PAYLOAD
    expected = decoder.members
    with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
        list(decoder.feed(bytes(second)))

    assert decoder.members == expected
    assert decoder.members[0].crc32 == zlib.crc32(FIRST_PAYLOAD)
