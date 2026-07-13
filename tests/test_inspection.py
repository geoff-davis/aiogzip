"""Tests for gzip stream inspection contracts and behavior."""

import asyncio
import os
import struct
import zlib
from dataclasses import FrozenInstanceError

import pytest

from aiogzip import GzipInfo, GzipMemberInfo, VerificationResult, _engine
from aiogzip._inspection import _IncrementalGzipDecoder


def _gzip_member(
    payload,
    *,
    mtime=0,
    filename=None,
    comment=None,
    extra=None,
    header_crc=False,
):
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
    header.extend(struct.pack("<I", mtime))
    header.extend(b"\x00\xff")
    if extra is not None:
        header.extend(struct.pack("<H", len(extra)))
        header.extend(extra)
    if filename is not None:
        header.extend(filename.encode("latin-1") + b"\x00")
    if comment is not None:
        header.extend(comment.encode("latin-1") + b"\x00")
    if header_crc:
        header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))

    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = compressor.compress(payload) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload) & 0xFFFFFFFF)
    return bytes(header) + body + trailer


async def _decode(raw, *, input_chunk_size, output_chunk_size=64, limit=None):
    decoder = _IncrementalGzipDecoder(
        max_decompressed_size=limit,
        output_chunk_size=output_chunk_size,
        collect_member_info=True,
    )
    output = []
    for offset in range(0, len(raw), input_chunk_size):
        async for piece in decoder.feed(raw[offset : offset + input_chunk_size]):
            output.append(piece)
    async for piece in decoder.finish():
        output.append(piece)
    return decoder, output


def _member() -> GzipMemberInfo:
    return GzipMemberInfo(
        index=0,
        compressed_offset=0,
        compressed_size=25,
        uncompressed_size=5,
        mtime=0,
        original_filename="data.bin",
        comment=None,
        extra=None,
        flags=8,
        crc32=0x3610A686,
        trailer_isize=5,
    )


def test_gzip_info_member_count():
    member = _member()
    info = GzipInfo(members=(member,), compressed_size=25, uncompressed_size=5)

    assert info.member_count == 1
    assert info.members == (member,)


def test_empty_gzip_info_contract():
    info = GzipInfo(members=(), compressed_size=0, uncompressed_size=0)

    assert info.member_count == 0


@pytest.mark.parametrize(
    "value",
    [
        _member(),
        GzipInfo(members=(_member(),), compressed_size=25, uncompressed_size=5),
        VerificationResult(member_count=1, compressed_size=25, uncompressed_size=5),
    ],
)
def test_result_types_are_immutable(value):
    with pytest.raises(FrozenInstanceError):
        value.compressed_size = 0


class TestIncrementalGzipDecoder:
    async def test_empty_input(self):
        decoder, output = await _decode(b"", input_chunk_size=1)

        assert output == []
        assert decoder.members == ()
        assert decoder.member_count == 0
        assert decoder.compressed_size == 0
        assert decoder.uncompressed_size == 0

    async def test_metadata_members_offsets_and_padding_bytewise(self):
        first_payload = b"first member"
        second_payload = bytes(range(256)) * 3
        first = _gzip_member(
            first_payload,
            mtime=0,
            filename="café.bin",
            comment="comment",
            extra=b"\x01\x02\x03",
            header_crc=True,
        )
        second = _gzip_member(second_payload, mtime=123456)
        raw = first + b"\x00\x00\x00" + second

        decoder, output = await _decode(raw, input_chunk_size=1, output_chunk_size=17)

        assert b"".join(output) == first_payload + second_payload
        assert output and all(0 < len(piece) <= 17 for piece in output)
        assert decoder.compressed_size == len(raw)
        assert decoder.uncompressed_size == len(first_payload) + len(second_payload)
        assert decoder.member_count == 2
        one, two = decoder.members
        assert one.compressed_offset == 0
        assert one.compressed_size == len(first)
        assert one.uncompressed_size == len(first_payload)
        assert one.mtime == 0
        assert one.original_filename == "café.bin"
        assert one.comment == "comment"
        assert one.extra == b"\x01\x02\x03"
        assert one.flags == 0x1E
        assert one.crc32 == zlib.crc32(first_payload)
        assert one.trailer_isize == len(first_payload)
        assert two.compressed_offset == len(first) + 3
        assert two.compressed_size == len(second)
        assert two.mtime == 123456

    @pytest.mark.parametrize("input_chunk_size", [2, 3, 7, 17, 257, 4096])
    async def test_arbitrary_input_and_strict_output_chunks(self, input_chunk_size):
        payload = (b"highly compressible data\n" * 10000) + os.urandom(4096)
        raw = _gzip_member(payload)

        decoder, output = await _decode(
            raw,
            input_chunk_size=input_chunk_size,
            output_chunk_size=31,
        )

        assert b"".join(output) == payload
        assert output and all(0 < len(piece) <= 31 for piece in output)
        assert decoder.members[0].uncompressed_size == len(payload)

    async def test_metadata_collection_can_be_disabled(self):
        decoder = _IncrementalGzipDecoder(
            max_decompressed_size=None,
            output_chunk_size=1024,
            collect_member_info=False,
        )
        raw = _gzip_member(b"one") + _gzip_member(b"two")

        async for _ in decoder.feed(raw):
            pass
        async for _ in decoder.finish():
            pass

        assert decoder.members == ()
        assert decoder.member_count == 2
        assert decoder.uncompressed_size == 6

    async def test_decompression_limit_is_cumulative(self):
        raw = _gzip_member(b"abc") + _gzip_member(b"def")

        decoder, output = await _decode(raw, input_chunk_size=5, limit=6)
        assert b"".join(output) == b"abcdef"
        assert decoder.uncompressed_size == 6

        with pytest.raises(OSError, match="max_decompressed_size"):
            await _decode(raw, input_chunk_size=5, limit=5)

    @pytest.mark.parametrize("damage", ["crc", "isize", "header-crc"])
    async def test_integrity_errors(self, damage):
        raw = bytearray(_gzip_member(b"payload", header_crc=True))
        if damage == "crc":
            raw[-8] ^= 0x01
            match = "CRC check failed"
        elif damage == "isize":
            raw[-4] ^= 0x01
            match = "ISIZE check failed"
        else:
            raw[10] ^= 0x01
            match = "Header CRC check failed"

        with pytest.raises(OSError, match=match):
            await _decode(bytes(raw), input_chunk_size=3)

    @pytest.mark.parametrize(
        "raw",
        [
            b"not gzip",
            b"\x1f\x8b",
            _gzip_member(b"payload")[:-1],
            _gzip_member(b"payload") + b"junk",
        ],
    )
    async def test_malformed_or_truncated_input(self, raw):
        with pytest.raises(OSError):
            await _decode(raw, input_chunk_size=2)

    async def test_cancelled_offload_discards_decoder(self, monkeypatch):
        raw = _gzip_member(os.urandom(_engine.ZLIB_OFFLOAD_THRESHOLD + 1024))
        decoder = _IncrementalGzipDecoder(
            max_decompressed_size=None,
            output_chunk_size=1024,
            collect_member_info=False,
        )

        async def cancel_offload(method, data):
            raise asyncio.CancelledError

        monkeypatch.setattr(_engine, "run_zlib_in_thread", cancel_offload)

        with pytest.raises(asyncio.CancelledError):
            async for _ in decoder.feed(raw):
                pass
        with pytest.raises(OSError, match="unusable"):
            decoder.feed(b"")
