"""Boundary, limit, and allocation tests for incremental gzip headers."""

from __future__ import annotations

import gzip
import os
import struct
import tracemalloc
import zlib

import pytest

from aiogzip import GzipDecoder
from aiogzip._codec_buffer import _InputQueue
from aiogzip._gzip_header import _GzipHeaderParser, _ParsedHeader


def _header(
    *,
    extra: bytes | None = None,
    filename: bytes | None = None,
    comment: bytes | None = None,
    header_crc: bool = False,
) -> bytes:
    flags = 0
    if extra is not None:
        flags |= 0x04
    if filename is not None:
        flags |= 0x08
    if comment is not None:
        flags |= 0x10
    if header_crc:
        flags |= 0x02
    result = bytearray(b"\x1f\x8b\x08")
    result.append(flags)
    result.extend(struct.pack("<I", 0xA1B2C3D4))
    result.extend(b"\x00\xff")
    if extra is not None:
        result.extend(struct.pack("<H", len(extra)))
        result.extend(extra)
    if filename is not None:
        result.extend(filename)
        result.append(0)
    if comment is not None:
        result.extend(comment)
        result.append(0)
    if header_crc:
        result.extend(struct.pack("<H", zlib.crc32(result) & 0xFFFF))
    return bytes(result)


def _member(payload: bytes, **header_options: object) -> tuple[bytes, int]:
    header = _header(**header_options)
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    body = compressor.compress(payload) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload))
    return header + body + trailer, len(header)


def _parse_parts(
    parts: list[bytes],
    *,
    collect_metadata: bool = True,
    limit: int = 1024 * 1024,
) -> tuple[_ParsedHeader | None, _GzipHeaderParser, _InputQueue]:
    parser = _GzipHeaderParser(
        collect_metadata=collect_metadata,
        limit=limit,
    )
    pending = _InputQueue()
    result = None
    for part in parts:
        pending.append(part)
        result = parser.advance(pending)
    return result, parser, pending


@pytest.mark.parametrize("split", range(11))
def test_every_split_through_fixed_header_preserves_body(split):
    header = _header()
    result, _, pending = _parse_parts([header[:split], header[split:] + b"body"])

    assert result == _ParsedHeader(
        size=10,
        mtime=0xA1B2C3D4,
        original_filename=None,
        comment=None,
        extra=None,
        flags=0,
    )
    assert pending.take(4) == b"body"


@pytest.mark.parametrize("split", range(9, 20))
def test_every_split_around_extra_length_and_payload(split):
    extra = b"\x01\x02abcdef"
    header = _header(extra=extra)
    result, _, pending = _parse_parts([header[:split], header[split:] + b"body"])

    assert result is not None
    assert result.extra == extra
    assert result.size == len(header)
    assert pending.take(4) == b"body"


@pytest.mark.parametrize(("field", "offset"), [("filename", 10), ("comment", 10)])
def test_every_split_around_string_terminator(field, offset):
    options = {field: b"fragmented-field"}
    header = _header(**options)
    for split in range(offset, len(header) + 1):
        result, _, pending = _parse_parts(
            [header[:split], header[split:] + b"body"],
        )

        assert result is not None
        assert (
            getattr(
                result,
                "original_filename" if field == "filename" else "comment",
            )
            == "fragmented-field"
        )
        assert pending.take(4) == b"body"


@pytest.mark.parametrize("collect_metadata", [False, True])
def test_all_optional_fields_and_fhcrc_split_bytewise(collect_metadata):
    extra = b"\x01\x02extra"
    filename = "café.bin".encode("latin-1")
    comment = b"incremental comment"
    header = _header(
        extra=extra,
        filename=filename,
        comment=comment,
        header_crc=True,
    )
    result, _, pending = _parse_parts(
        [header[index : index + 1] for index in range(len(header))] + [b"body"],
        collect_metadata=collect_metadata,
    )

    assert result is not None
    assert result.extra == (extra if collect_metadata else None)
    assert result.original_filename == ("café.bin" if collect_metadata else None)
    assert result.comment == ("incremental comment" if collect_metadata else None)
    assert pending.take(4) == b"body"


def test_invalid_fhcrc_does_not_consume_body():
    header = bytearray(
        _header(
            extra=b"extra",
            filename=b"name",
            comment=b"comment",
            header_crc=True,
        )
    )
    header[-1] ^= 1
    parser = _GzipHeaderParser(collect_metadata=True, limit=1024)
    pending = _InputQueue()
    pending.append(bytes(header) + b"body")

    with pytest.raises(gzip.BadGzipFile, match="Header CRC check failed"):
        parser.advance(pending)

    assert pending.take(4) == b"body"


@pytest.mark.parametrize("field", ["filename", "comment"])
@pytest.mark.parametrize("collect_metadata", [False, True])
def test_reduced_limit_accepts_exact_terminator_and_preserves_body(
    field, collect_metadata
):
    limit = 64
    value = b"x" * (limit - 11)
    header = _header(**{field: value})
    assert len(header) == limit

    result, parser, pending = _parse_parts(
        [header + b"body"],
        collect_metadata=collect_metadata,
        limit=limit,
    )

    assert result is not None
    assert parser.size == limit
    assert pending.take(4) == b"body"


@pytest.mark.parametrize("field", ["filename", "comment"])
@pytest.mark.parametrize("collect_metadata", [False, True])
def test_reduced_limit_rejects_before_consuming_first_over_limit_byte(
    field, collect_metadata
):
    limit = 64
    header = _header(**{field: b"x" * (limit - 10)})
    parser = _GzipHeaderParser(
        collect_metadata=collect_metadata,
        limit=limit,
    )
    pending = _InputQueue()
    pending.append(header + b"body")

    with pytest.raises(gzip.BadGzipFile, match="header exceeds"):
        parser.advance(pending)

    assert parser.size == limit
    assert pending.peek_byte() == 0
    assert pending.take(5) == b"\x00body"


@pytest.mark.parametrize("field", ["filename", "comment"])
def test_incomplete_large_field_peak_allocation_without_metadata(field):
    field_size = 4 * 1024 * 1024
    incomplete = _header(**{field: b"x" * field_size})[:-1]
    parts = [
        incomplete[offset : offset + 64 * 1024]
        for offset in range(0, len(incomplete), 64 * 1024)
    ]
    parser = _GzipHeaderParser(collect_metadata=False, limit=8 * 1024 * 1024)
    pending = _InputQueue()

    tracemalloc.start()
    for part in parts:
        pending.append(part)
        assert parser.advance(pending) is None
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < 4 * 1024 * 1024


@pytest.mark.parametrize("field", ["filename", "comment"])
def test_large_field_peak_allocation_with_metadata(field):
    field_size = 4 * 1024 * 1024
    header = _header(**{field: b"x" * field_size})
    parts = [
        header[offset : offset + 64 * 1024]
        for offset in range(0, len(header), 64 * 1024)
    ]
    parser = _GzipHeaderParser(collect_metadata=True, limit=8 * 1024 * 1024)
    pending = _InputQueue()

    tracemalloc.start()
    result = None
    for part in parts:
        pending.append(part)
        result = parser.advance(pending)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert result is not None
    assert peak <= field_size * 2.25 + 4 * 1024 * 1024


def test_multiple_members_with_large_metadata_and_fragmented_padding():
    first, _ = _member(b"first", filename=b"a" * (128 * 1024), header_crc=True)
    second, _ = _member(b"second", comment=b"b" * (128 * 1024), header_crc=True)
    spans = [first, *([b"\x00"] * 4096), second]
    decoder = GzipDecoder(collect_member_info=True)

    output = bytearray()
    for span in spans:
        output.extend(b"".join(decoder.feed(span)))
    output.extend(b"".join(decoder.finish()))

    assert output == b"firstsecond"
    assert decoder.members[0].original_filename == "a" * (128 * 1024)
    assert decoder.members[1].comment == "b" * (128 * 1024)
    assert decoder.members[1].compressed_offset == len(first) + 4096


def test_second_header_zero_bytes_are_not_padding_when_split_bytewise():
    first = gzip.compress(b"first", mtime=0)
    second = gzip.compress(b"second", mtime=0)
    decoder = GzipDecoder(collect_member_info=True)
    output = bytearray()

    for byte in first + b"\x00\x00\x00" + second:
        output.extend(b"".join(decoder.feed(bytes((byte,)))))
    output.extend(b"".join(decoder.finish()))

    assert output == b"firstsecond"
    assert decoder.members[1].compressed_offset == len(first) + 3


def test_trailer_split_across_many_spans_is_read_exactly():
    payload = b"trailer spans"
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder()
    output = bytearray(b"".join(decoder.feed(wire[:-8])))

    for byte in wire[-8:]:
        output.extend(b"".join(decoder.feed(bytes((byte,)))))
    output.extend(b"".join(decoder.finish()))

    assert output == payload
    assert decoder.member_count == 1


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("AIOGZIP_RELEASE_TESTS") != "1",
    reason="set AIOGZIP_RELEASE_TESTS=1 for the real 128 MiB header boundary",
)
def test_real_header_limit_boundary():
    limit = 128 * 1024 * 1024
    header = _header(filename=b"x" * (limit - 11))
    result, parser, pending = _parse_parts(
        [header + b"body"],
        collect_metadata=False,
        limit=limit,
    )

    assert result is not None
    assert parser.size == limit
    assert pending.take(4) == b"body"
