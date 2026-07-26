"""Characterization tests for decoder behavior preserved by the a2 rewrite."""

from __future__ import annotations

import gzip
import itertools
import struct
import zlib

import pytest

from aiogzip import GzipDecoder


def _member(
    payload: bytes,
    *,
    extra: bytes | None = None,
    filename: bytes | None = None,
    comment: bytes | None = None,
    header_crc: bool = False,
) -> tuple[bytes, int]:
    flags = 0
    if extra is not None:
        flags |= 0x04
    if filename is not None:
        flags |= 0x08
    if comment is not None:
        flags |= 0x10
    if header_crc:
        flags |= 0x02

    header = bytearray(b"\x1f\x8b\x08")
    header.append(flags)
    header.extend(struct.pack("<I", 123))
    header.extend(b"\x00\xff")
    if extra is not None:
        header.extend(struct.pack("<H", len(extra)))
        header.extend(extra)
    if filename is not None:
        header.extend(filename + b"\x00")
    if comment is not None:
        header.extend(comment + b"\x00")
    if header_crc:
        header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))

    header_size = len(header)
    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = compressor.compress(payload) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload))
    return bytes(header) + body + trailer, header_size


def _decode(parts: list[bytes], **options: object) -> tuple[bytes, GzipDecoder]:
    decoder = GzipDecoder(**options)
    output = bytearray()
    for part in parts:
        output.extend(b"".join(decoder.feed(part)))
    output.extend(b"".join(decoder.finish()))
    return bytes(output), decoder


@pytest.mark.parametrize(
    ("phase", "prefix", "expected_state"),
    [
        ("header", lambda wire: wire[:5], "header"),
        ("body", lambda wire: wire[:10], "body"),
        ("trailer", lambda wire: wire[:-8], "trailer"),
        ("post-member-padding", lambda wire: wire + b"\x00" * 3, "header"),
    ],
)
def test_empty_feed_preserves_each_decoder_phase(phase, prefix, expected_state):
    payload = b"phase boundary payload" * 20
    wire = gzip.compress(payload, mtime=0)
    first = prefix(wire)
    remainder = b"" if phase == "post-member-padding" else wire[len(first) :]
    decoder = GzipDecoder(output_chunk_size=17)
    output = bytearray(b"".join(decoder.feed(first)))

    assert decoder._state == expected_state
    assert list(decoder.feed(b"")) == []
    assert decoder._state == expected_state

    output.extend(b"".join(decoder.feed(remainder)))
    output.extend(b"".join(decoder.finish()))
    assert bytes(output) == payload


_HEADER_OPTIONS = list(itertools.product((False, True), repeat=4))


@pytest.mark.parametrize(
    ("has_extra", "has_filename", "has_comment", "header_crc"),
    _HEADER_OPTIONS,
)
def test_optional_header_flag_combinations_at_every_input_boundary(
    has_extra, has_filename, has_comment, header_crc
):
    payload = b"optional header matrix"
    extra = b"\x01\x02extra" if has_extra else None
    filename = b"matrix.bin" if has_filename else None
    comment = b"characterization" if has_comment else None
    wire, _ = _member(
        payload,
        extra=extra,
        filename=filename,
        comment=comment,
        header_crc=header_crc,
    )

    output, decoder = _decode(
        [wire[index : index + 1] for index in range(len(wire))],
        output_chunk_size=3,
        collect_member_info=True,
    )

    assert output == payload
    assert decoder.member_count == 1
    info = decoder.members[0]
    assert info.extra == extra
    assert info.original_filename == (
        filename.decode("latin-1") if filename is not None else None
    )
    assert info.comment == (comment.decode("latin-1") if comment is not None else None)
    assert info.flags == (
        (0x04 if has_extra else 0)
        | (0x08 if has_filename else 0)
        | (0x10 if has_comment else 0)
        | (0x02 if header_crc else 0)
    )


def test_exactly_seven_trailer_bytes_are_rejected_by_finish():
    payload = b"payload emitted before a short trailer"
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder(output_chunk_size=5)

    assert b"".join(decoder.feed(wire[:-1])) == payload
    assert decoder._state == "trailer"
    assert len(decoder._pending) == 7
    with pytest.raises(gzip.BadGzipFile, match="truncated trailer"):
        list(decoder.finish())


@pytest.mark.parametrize(
    ("field", "trailer_index", "message"),
    [
        ("CRC", 0, "CRC check failed"),
        ("ISIZE", 4, "ISIZE check failed"),
    ],
)
def test_trailer_failure_occurs_after_payload_emission(field, trailer_index, message):
    payload = b"payload is available before integrity validation"
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder(output_chunk_size=7)

    assert b"".join(decoder.feed(wire[:-8])) == payload
    trailer = bytearray(wire[-8:])
    trailer[trailer_index] ^= 1
    with pytest.raises(gzip.BadGzipFile, match=message):
        list(decoder.feed(bytes(trailer)))
    assert decoder.uncompressed_size == len(payload), field


@pytest.mark.parametrize("padding_size", [0, 3])
def test_member_offsets_exclude_leading_padding(padding_size):
    first = gzip.compress(b"first", mtime=0)
    second = gzip.compress(b"second", mtime=0)
    wire = first + b"\x00" * padding_size + second

    output, decoder = _decode([wire], collect_member_info=True)

    assert output == b"firstsecond"
    one, two = decoder.members
    assert one.compressed_offset == 0
    assert one.compressed_size == len(first)
    assert two.compressed_offset == len(first) + padding_size
    assert two.compressed_size == len(second)


def test_metadata_disabled_does_not_retain_optional_header_values():
    wire, header_size = _member(
        b"metadata-free",
        extra=b"\x01\x02extra",
        filename=b"private.bin",
        comment=b"private comment",
        header_crc=True,
    )
    decoder = GzipDecoder(collect_member_info=False)

    assert list(decoder.feed(wire[:header_size])) == []
    assert decoder._header is not None
    assert decoder._header.extra is None
    assert decoder._header.original_filename is None
    assert decoder._header.comment is None

    assert b"".join(decoder.feed(wire[header_size:])) == b"metadata-free"
    assert list(decoder.finish()) == []
    assert decoder.member_count == 1
    assert decoder.members == ()


@pytest.mark.parametrize("output_chunk_size", [1, 1024 * 1024])
@pytest.mark.parametrize(
    ("limit_delta", "succeeds"),
    [(-1, False), (0, True), (1, True)],
)
def test_decompression_limit_around_exact_payload_size(
    output_chunk_size, limit_delta, succeeds
):
    payload = b"A" * 257
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder(
        output_chunk_size=output_chunk_size,
        max_decompressed_size=len(payload) + limit_delta,
    )
    output = bytearray()

    if succeeds:
        output.extend(b"".join(decoder.feed(wire)))
        output.extend(b"".join(decoder.finish()))
        assert bytes(output) == payload
    else:
        with pytest.raises(OSError, match="max_decompressed_size"):
            for chunk in decoder.feed(wire):
                output.extend(chunk)
        assert len(output) <= len(payload) - 1


def test_compressed_size_is_accounted_when_feed_returns():
    wire = gzip.compress(b"call-time accounting", mtime=0)
    decoder = GzipDecoder()

    operation = decoder.feed(wire)

    assert decoder.compressed_size == len(wire)
    assert len(decoder._pending) == 0
    operation.close()
    with pytest.raises(OSError, match="unusable"):
        decoder.finish()


def test_decoder_reentrant_advancement_fails_at_inner_call():
    payload = b"decoder reentrancy"
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder()
    original_inflate = decoder._inflate
    operation_holder = {}
    caught = []

    def reentrant_inflate(data, max_length):
        try:
            next(operation_holder["operation"])
        except RuntimeError as error:
            caught.append(str(error))
        return original_inflate(data, max_length)

    decoder._inflate = reentrant_inflate
    operation = decoder.feed(wire)
    operation_holder["operation"] = operation

    assert b"".join(operation) == payload
    assert caught == ["gzip codec operation cannot be advanced reentrantly"]
    assert list(decoder.finish()) == []


@pytest.mark.parametrize(
    ("index", "replacement", "message"),
    [
        (2, 0, "Unknown compression method"),
        (3, 0xE0, "Reserved flags are set"),
    ],
)
def test_invalid_method_and_reserved_flags_fail_at_header_boundary(
    index, replacement, message
):
    wire = bytearray(gzip.compress(b"payload", mtime=0))
    wire[index] = replacement
    decoder = GzipDecoder()

    with pytest.raises(gzip.BadGzipFile, match=message):
        list(decoder.feed(bytes(wire[: index + 1])))
