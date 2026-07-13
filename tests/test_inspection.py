"""Tests for gzip stream inspection contracts and behavior."""

import asyncio
import gzip
import io
import os
import struct
import zlib
from dataclasses import FrozenInstanceError

import aiofiles
import pytest

import aiogzip
from aiogzip import GzipInfo, GzipMemberInfo, VerificationResult, _engine
from aiogzip import _inspection as inspection_module
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


class AsyncBytesReader:
    def __init__(self, data, *, max_read=None):
        self.buffer = io.BytesIO(data)
        self.max_read = max_read
        self.closed = False

    async def read(self, size=-1):
        if self.max_read is not None:
            size = min(size, self.max_read)
        return self.buffer.read(size)

    async def close(self):
        self.closed = True


class TestInspectAndVerify:
    @pytest.mark.parametrize("operation", [aiogzip.inspect, aiogzip.verify])
    async def test_zero_byte_input(self, tmp_path, operation):
        path = tmp_path / "empty-input.gz"
        path.write_bytes(b"")

        result = await operation(path)

        assert result.member_count == 0
        assert result.compressed_size == 0
        assert result.uncompressed_size == 0
        if isinstance(result, GzipInfo):
            assert result.members == ()

    async def test_empty_and_normal_members(self, tmp_path):
        empty = gzip.compress(b"", mtime=0)
        payload = bytes(range(256)) * 500
        normal = gzip.compress(payload, mtime=123)
        path = tmp_path / "members.gz"
        path.write_bytes(empty + normal)

        info = await aiogzip.inspect(path, chunk_size=17)
        verified = await aiogzip.verify(path, chunk_size=19)

        assert info.member_count == verified.member_count == 2
        assert info.compressed_size == verified.compressed_size == len(empty + normal)
        assert info.uncompressed_size == verified.uncompressed_size == len(payload)
        assert info.members[0].uncompressed_size == 0
        assert info.members[0].trailer_isize == 0
        assert info.members[0].mtime == 0
        assert info.members[1].uncompressed_size == len(payload)
        assert info.members[1].mtime == 123

    async def test_append_generated_members(self, tmp_path):
        path = tmp_path / "append.gz"
        await aiogzip.write(path, b"first", mtime=0)
        async with aiogzip.open(path, "ab", mtime=1) as stream:
            await stream.write(b"second")

        info = await aiogzip.inspect(path)

        assert info.member_count == 2
        assert [member.uncompressed_size for member in info.members] == [5, 6]
        assert info.members[1].compressed_offset == info.members[0].compressed_size
        assert await aiogzip.read(path) == b"firstsecond"

    async def test_all_header_metadata_and_exact_offsets(self):
        first_payload = b"metadata payload"
        second_payload = os.urandom(10000)
        first = _gzip_member(
            first_payload,
            mtime=0,
            filename="",
            comment="café",
            extra=b"\x00\xffextra",
            header_crc=True,
        )
        second = _gzip_member(second_payload, filename="second.bin")
        raw = first + b"\x00" * 5 + second + b"\x00" * 3
        reader = AsyncBytesReader(raw, max_read=1)

        info = await aiogzip.inspect(None, fileobj=reader, chunk_size=7)

        assert not reader.closed
        assert info.compressed_size == len(raw)
        assert info.uncompressed_size == len(first_payload) + len(second_payload)
        first_info, second_info = info.members
        assert first_info.compressed_offset == 0
        assert first_info.compressed_size == len(first)
        assert first_info.original_filename == ""
        assert first_info.comment == "café"
        assert first_info.extra == b"\x00\xffextra"
        assert first_info.mtime == 0
        assert second_info.compressed_offset == len(first) + 5
        assert second_info.compressed_size == len(second)
        assert second_info.original_filename == "second.bin"

    async def test_external_file_ownership(self):
        raw = gzip.compress(b"payload", mtime=0)
        default_reader = AsyncBytesReader(raw)
        closing_reader = AsyncBytesReader(raw)

        await aiogzip.verify(None, fileobj=default_reader)
        await aiogzip.inspect(None, fileobj=closing_reader, closefd=True)

        assert not default_reader.closed
        assert closing_reader.closed

    @pytest.mark.parametrize("operation", [aiogzip.inspect, aiogzip.verify])
    async def test_exact_limit_succeeds_and_one_less_fails(self, operation):
        raw = gzip.compress(b"abcdef", mtime=0)

        result = await operation(
            None,
            fileobj=AsyncBytesReader(raw),
            max_decompressed_size=6,
            chunk_size=2,
        )
        assert result.uncompressed_size == 6

        with pytest.raises(OSError, match="max_decompressed_size"):
            await operation(
                None,
                fileobj=AsyncBytesReader(raw),
                max_decompressed_size=5,
                chunk_size=2,
            )

    async def test_limit_is_cumulative_across_members(self):
        raw = gzip.compress(b"abc", mtime=0) + gzip.compress(b"def", mtime=0)

        with pytest.raises(OSError, match="max_decompressed_size"):
            await aiogzip.verify(
                None,
                fileobj=AsyncBytesReader(raw),
                max_decompressed_size=5,
                chunk_size=1,
            )

    @pytest.mark.parametrize("invalid", [True, 1.5, "10", 0, -1])
    async def test_invalid_size_parameters(self, invalid):
        expected = TypeError if invalid in (True, 1.5, "10") else ValueError
        with pytest.raises(expected):
            await aiogzip.inspect(
                None,
                fileobj=AsyncBytesReader(b""),
                max_decompressed_size=invalid,
            )

        with pytest.raises(expected):
            await aiogzip.verify(
                None,
                fileobj=AsyncBytesReader(b""),
                chunk_size=invalid,
            )

    @pytest.mark.parametrize("operation", [aiogzip.inspect, aiogzip.verify])
    async def test_trailing_nul_padding_accepted_other_data_rejected(self, operation):
        member = gzip.compress(b"payload", mtime=0)

        result = await operation(None, fileobj=AsyncBytesReader(member + b"\x00" * 9))
        assert result.compressed_size == len(member) + 9

        with pytest.raises(gzip.BadGzipFile):
            await operation(None, fileobj=AsyncBytesReader(member + b"trailing"))

    async def test_trailing_behavior_matches_existing_reader(self, tmp_path):
        member = gzip.compress(b"payload", mtime=0)
        padded = tmp_path / "padded.gz"
        junk = tmp_path / "junk.gz"
        padded.write_bytes(member + b"\x00" * 3)
        junk.write_bytes(member + b"junk")

        assert await aiogzip.read(padded) == b"payload"
        await aiogzip.verify(padded)
        with pytest.raises(OSError):
            await aiogzip.read(junk)
        with pytest.raises(OSError):
            await aiogzip.verify(junk)

    async def test_cross_implementation_consistency(self, tmp_path):
        payload = (b"compressible\n" * 100000) + os.urandom(100000)
        path = tmp_path / "cross.gz"
        await aiogzip.write(path, payload, mtime=0)

        info = await aiogzip.inspect(path)

        raw = path.read_bytes()
        assert gzip.decompress(raw) == payload
        assert await aiogzip.read(path) == payload
        assert info.uncompressed_size == len(payload)
        assert info.members[0].crc32 == zlib.crc32(payload)

    def test_actual_size_and_trailer_isize_are_distinct_fields(self):
        member = GzipMemberInfo(
            index=0,
            compressed_offset=0,
            compressed_size=1,
            uncompressed_size=2**32 + 5,
            mtime=None,
            original_filename=None,
            comment=None,
            extra=None,
            flags=0,
            crc32=0,
            trailer_isize=5,
        )

        assert member.uncompressed_size != member.trailer_isize


class TestInspectionCorruption:
    @pytest.mark.parametrize(
        "raw",
        [
            b"bad magic",
            b"\x1f\x8b\x07\x00" + b"\x00" * 6,
            b"\x1f\x8b\x08\xe0" + b"\x00" * 6,
            b"\x1f\x8b\x08",
            b"\x1f\x8b\x08\x04" + b"\x00" * 6 + b"\x05\x00ab",
            b"\x1f\x8b\x08\x08" + b"\x00" * 6 + b"unterminated",
            b"\x1f\x8b\x08\x10" + b"\x00" * 6 + b"unterminated",
            b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"invalid deflate",
            _gzip_member(b"payload")[:-8],
            _gzip_member(b"payload")[:-3],
        ],
    )
    async def test_malformed_boundaries(self, raw):
        with pytest.raises(gzip.BadGzipFile):
            await aiogzip.inspect(None, fileobj=AsyncBytesReader(raw), chunk_size=1)
        with pytest.raises(gzip.BadGzipFile):
            await aiogzip.verify(None, fileobj=AsyncBytesReader(raw), chunk_size=3)

    @pytest.mark.parametrize("damage", ["header_crc", "crc", "isize", "body"])
    async def test_integrity_corruption(self, damage):
        raw = bytearray(_gzip_member(b"payload" * 100, header_crc=True))
        if damage == "header_crc":
            raw[10] ^= 0x80
        elif damage == "crc":
            raw[-8] ^= 0x80
        elif damage == "isize":
            raw[-4] ^= 0x80
        else:
            raw[20] ^= 0xFF

        with pytest.raises(gzip.BadGzipFile):
            await aiogzip.inspect(None, fileobj=AsyncBytesReader(bytes(raw)))

    async def test_valid_first_member_corrupt_second_member(self):
        raw = bytearray(_gzip_member(b"valid") + _gzip_member(b"corrupt"))
        raw[-8] ^= 1

        with pytest.raises(gzip.BadGzipFile, match="member 1"):
            await aiogzip.inspect(None, fileobj=AsyncBytesReader(bytes(raw)))


class TestInspectionLifecycle:
    async def _tracking_internal_source(self, path, monkeypatch):
        real_source = await aiofiles.open(path, "rb")
        tracking = AsyncBytesReader(await real_source.read())
        await real_source.close()

        async def tracking_open(filename, mode):
            return tracking

        monkeypatch.setattr(inspection_module.aiofiles, "open", tracking_open)
        return tracking

    async def test_internal_source_closes_after_success(self, tmp_path, monkeypatch):
        path = tmp_path / "valid.gz"
        path.write_bytes(gzip.compress(b"payload"))
        tracking = await self._tracking_internal_source(path, monkeypatch)

        await aiogzip.inspect(path)

        assert tracking.closed

    async def test_internal_source_closes_after_corruption(self, tmp_path, monkeypatch):
        path = tmp_path / "corrupt.gz"
        path.write_bytes(b"not gzip")
        tracking = await self._tracking_internal_source(path, monkeypatch)

        with pytest.raises(gzip.BadGzipFile):
            await aiogzip.verify(path)

        assert tracking.closed

    async def test_internal_source_closes_after_cancellation(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "cancel.gz"
        path.write_bytes(b"")

        class CancellingReader(AsyncBytesReader):
            async def read(self, size=-1):
                raise asyncio.CancelledError

        tracking = CancellingReader(b"")

        async def tracking_open(filename, mode):
            return tracking

        monkeypatch.setattr(inspection_module.aiofiles, "open", tracking_open)

        with pytest.raises(asyncio.CancelledError):
            await aiogzip.inspect(path)

        assert tracking.closed

    async def test_read_errors_propagate(self):
        expected = OSError("source failed")

        class FailingReader(AsyncBytesReader):
            async def read(self, size=-1):
                raise expected

        with pytest.raises(OSError) as caught:
            await aiogzip.verify(None, fileobj=FailingReader(b""))

        assert caught.value is expected
