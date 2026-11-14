"""File reads of gzip members whose headers carry large or combined optional fields.

These drive the public file handle over fragmented and gated sources: the
header may be split at any byte, the header timestamp is published only after
the header is complete and its checksum has passed, and a truncated header is
reported only when the source reports end of file.
"""

import asyncio
import gzip
import struct
import zlib

import pytest
from conftest import FramedAsyncReader

import aiogzip


def _raw_deflate(payload: bytes) -> bytes:
    compressor = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
    return compressor.compress(payload) + compressor.flush()


def optional_header_fixture(
    field: str,
    size: int,
    *,
    complete: bool,
    mtime: int = 0,
    fhcrc: bool = False,
) -> tuple[bytes, bytes]:
    """Build a deterministic gzip member with one large optional field."""
    flag = {"fname": 0x08, "fcomment": 0x10}[field]
    if fhcrc:
        flag |= 0x02
    header = bytearray(b"\x1f\x8b\x08")
    header.append(flag)
    header.extend(struct.pack("<I", mtime))
    header.extend(b"\x00\xff")
    header.extend(b"x" * size)
    if not complete:
        return bytes(header), b""
    header.append(0)
    if fhcrc:
        header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))
    payload = b"header fixture payload\n"
    trailer = struct.pack(
        "<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload) & 0xFFFFFFFF
    )
    return bytes(header) + _raw_deflate(payload) + trailer, payload


def combined_header_fixture(
    *,
    extra_size: int = 17,
    fname_size: int = 19,
    fcomment_size: int = 23,
    mtime: int = 0,
    fhcrc: bool = True,
) -> tuple[bytes, bytes, dict[str, int]]:
    """Build a valid member with every optional field and split landmarks."""
    if not 0 <= extra_size <= 0xFFFF:
        raise ValueError("extra_size must fit the gzip XLEN field")
    if fname_size < 0 or fcomment_size < 0:
        raise ValueError("string field sizes must be non-negative")

    flags = 0x04 | 0x08 | 0x10 | (0x02 if fhcrc else 0)
    header = bytearray(b"\x1f\x8b\x08")
    header.append(flags)
    header.extend(struct.pack("<I", mtime))
    header.extend(b"\x00\xff")
    landmarks = {"fixed_end": len(header)}

    header.extend(struct.pack("<H", extra_size))
    landmarks["xlen_end"] = len(header)
    header.extend(b"e" * extra_size)
    landmarks["extra_end"] = len(header)
    header.extend(b"n" * fname_size + b"\x00")
    landmarks["fname_end"] = len(header)
    header.extend(b"c" * fcomment_size + b"\x00")
    landmarks["fcomment_end"] = len(header)
    if fhcrc:
        header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))
    landmarks["fhcrc_end"] = len(header)

    payload = b"combined header fixture payload\n"
    trailer = struct.pack(
        "<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload) & 0xFFFFFFFF
    )
    return bytes(header) + _raw_deflate(payload) + trailer, payload, landmarks


class SeekableMemorySource:
    """Minimal asynchronous source with bounded reads and observable counts."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.read_calls = 0
        self.max_requested = 0
        self.max_returned = 0

    def seekable(self) -> bool:
        return True

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        self.max_requested = max(self.max_requested, size)
        if size < 0:
            size = len(self.data) - self.position
        end = min(len(self.data), self.position + size)
        result = self.data[self.position : end]
        self.position = end
        self.max_returned = max(self.max_returned, len(result))
        return result

    async def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            position = offset
        elif whence == 1:
            position = self.position + offset
        elif whence == 2:
            position = len(self.data) + offset
        else:
            raise ValueError(f"invalid whence: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self.position = position
        return position


@pytest.mark.parametrize(
    "split_name",
    [
        "magic-1",
        "magic-2",
        "method",
        "flags",
        "fixed-9",
        "fixed-end",
        "xlen-1",
        "xlen-end",
        "extra-end",
        "fname-terminator",
        "fcomment-terminator",
        "fhcrc-1",
    ],
)
@pytest.mark.asyncio
async def test_combined_header_adversarial_splits(split_name):
    wire, expected, landmarks = combined_header_fixture(mtime=123456789)
    splits = {
        "magic-1": 1,
        "magic-2": 2,
        "method": 3,
        "flags": 4,
        "fixed-9": 9,
        "fixed-end": landmarks["fixed_end"],
        "xlen-1": landmarks["fixed_end"] + 1,
        "xlen-end": landmarks["xlen_end"],
        "extra-end": landmarks["extra_end"],
        "fname-terminator": landmarks["fname_end"] - 1,
        "fcomment-terminator": landmarks["fcomment_end"] - 1,
        "fhcrc-1": landmarks["fhcrc_end"] - 1,
    }
    split = splits[split_name]
    source = FramedAsyncReader(wire[:split], wire[split:])

    async with aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(wire),
    ) as stream:
        assert await stream.read() == expected
        assert stream.mtime == 123456789


@pytest.mark.asyncio
async def test_corrupt_fhcrc_is_rejected_before_mtime_commit():
    wire, _, landmarks = combined_header_fixture(mtime=987654321)
    damaged = bytearray(wire)
    damaged[landmarks["fhcrc_end"] - 1] ^= 0xFF
    source = FramedAsyncReader(bytes(damaged))

    async with aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(damaged),
    ) as stream:
        with pytest.raises(gzip.BadGzipFile, match="Header CRC"):
            await stream.read()
        assert stream.mtime is None


@pytest.mark.asyncio
async def test_incomplete_header_fails_only_when_source_reports_eof():
    wire, _ = optional_header_fixture("fname", 4096, complete=False, mtime=42)
    eof_requested = asyncio.Event()
    release_eof = asyncio.Event()

    class EofGateSource(FramedAsyncReader):
        async def read(self, size=-1):
            if self._frame_index < len(self._frames):
                return await super().read(size)
            eof_requested.set()
            await release_eof.wait()
            return b""

    source = EofGateSource(wire)
    stream = aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(wire),
    )
    await stream.open()
    try:
        task = asyncio.create_task(stream.read())
        await eof_requested.wait()
        assert not task.done()
        assert stream.mtime is None
        release_eof.set()
        with pytest.raises(gzip.BadGzipFile, match="truncated"):
            await task
        assert stream.mtime is None
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_source_read_count_is_linear_and_seekable_reader_has_no_cache():
    chunk_size = 257
    counts = []
    expected_counts = []
    for field_size in (4096, 8192):
        wire, _ = optional_header_fixture("fname", field_size, complete=False)
        expected_counts.append((len(wire) + chunk_size - 1) // chunk_size + 1)
        source = SeekableMemorySource(wire)
        async with aiogzip.open(
            None,
            "rb",
            fileobj=source,
            closefd=False,
            chunk_size=chunk_size,
        ) as stream:
            with pytest.raises(gzip.BadGzipFile, match="truncated"):
                await stream.read()
            assert source.max_returned <= chunk_size
            assert stream._compressed_cache == b""
            assert stream._cache_rewindable_reads is False
            counts.append(source.read_calls)

    assert counts == expected_counts
    assert counts[1] - counts[0] == 16
    assert "_header_probe_buffer" not in aiogzip.AsyncGzipBinaryFile.__slots__
