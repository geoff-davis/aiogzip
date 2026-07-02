# pyrefly: ignore
# pyrefly: disable=all
"""Targeted tests for previously-uncovered, real-logic branches.

Covers:
- gzip header parsing of the optional FEXTRA / FNAME / FCOMMENT / FHCRC fields,
  including the incomplete-header (split across reads) early-return branches in
  ``_try_parse_gzip_header_mtime`` (``_common.py``);
- ``mtime`` / ``original_filename`` constructor validation;
- the close() path that propagates an underlying ``close()`` failure, and binary
  ``__anext__`` on an already-closed file.
"""

import gzip
import io
import struct
import zlib

import pytest

from aiogzip import AsyncGzipBinaryFile

# gzip header flag bits
_FHCRC = 0x02
_FEXTRA = 0x04
_FNAME = 0x08
_FCOMMENT = 0x10


def _gzip_member_with_all_header_fields(body: bytes, mtime: int) -> bytes:
    """Hand-build a single gzip member whose header sets every optional flag.

    Python's gzip module only ever emits FNAME, so FEXTRA/FCOMMENT/FHCRC have to
    be constructed by hand to exercise their parsing paths.
    """
    flags = _FEXTRA | _FNAME | _FCOMMENT | _FHCRC
    header = bytearray(b"\x1f\x8b\x08")  # magic + DEFLATE method
    header.append(flags)
    header += struct.pack("<I", mtime)
    header += bytes([0x00, 0xFF])  # XFL, OS=unknown

    # FEXTRA: a single subfield "AB" of length 2 ("xy").
    extra = b"AB" + struct.pack("<H", 2) + b"xy"
    header += struct.pack("<H", len(extra)) + extra
    # FNAME and FCOMMENT: NUL-terminated latin-1 strings.
    header += b"original.bin\x00"
    header += b"a header comment\x00"
    # FHCRC: low 16 bits of the CRC32 of the header bytes so far.
    header += struct.pack("<H", zlib.crc32(bytes(header)) & 0xFFFF)

    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    compressed = compressor.compress(body) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(body) & 0xFFFFFFFF, len(body) & 0xFFFFFFFF)
    return bytes(header) + compressed + trailer


async def test_reads_member_with_all_optional_header_fields(tmp_path):
    """A member with FEXTRA+FNAME+FCOMMENT+FHCRC must decompress and expose mtime.

    Reading with a tiny chunk_size delivers the header a few bytes at a time, so
    the parser walks every optional field and exercises both the incomplete
    (return None, False) and the completed branches.
    """
    body = b"payload exercising all gzip header fields\n" * 25
    mtime = 1_700_000_000
    raw = _gzip_member_with_all_header_fields(body, mtime)

    # Sanity: stdlib agrees the hand-built stream is a valid gzip member.
    assert gzip.decompress(raw) == body

    target = tmp_path / "all_fields.gz"
    target.write_bytes(raw)

    # chunk_size=2 also delivers a 10-byte prefix, hitting the FEXTRA
    # "not enough bytes for xlen yet" early return.
    async with AsyncGzipBinaryFile(target, "rb", chunk_size=2) as f:
        assert await f.read() == body
        assert f.mtime == mtime


async def test_header_fields_parsed_with_large_single_chunk(tmp_path):
    """Same member read in one chunk exercises the completed parse path."""
    body = b"single-chunk body"
    raw = _gzip_member_with_all_header_fields(body, 42)
    target = tmp_path / "all_fields_big.gz"
    target.write_bytes(raw)

    async with AsyncGzipBinaryFile(target, "rb", chunk_size=1 << 20) as f:
        assert await f.read() == body
        assert f.mtime == 42


def test_mtime_must_be_int_or_float():
    with pytest.raises(TypeError, match="mtime must be an int or float"):
        AsyncGzipBinaryFile("x.gz", "wb", mtime="nope")  # type: ignore[arg-type]


def test_mtime_must_be_non_negative():
    with pytest.raises(ValueError, match="mtime must be non-negative"):
        AsyncGzipBinaryFile("x.gz", "wb", mtime=-1)


def test_original_filename_must_be_str_or_bytes():
    with pytest.raises(TypeError, match="original_filename must be a string or bytes"):
        AsyncGzipBinaryFile("x.gz", "wb", original_filename=123)  # type: ignore[arg-type]


class _CloseFailsWriter:
    """Async writer whose write() succeeds but close() raises."""

    def __init__(self) -> None:
        self._buf = io.BytesIO()
        self.name = "close_fails"

    async def write(self, data) -> int:
        return self._buf.write(data)

    async def close(self) -> None:
        raise OSError("underlying close failed")


async def test_close_propagates_underlying_close_failure():
    """When the writer is owned (closefd=True) and its close() raises with no
    prior write failure, close() must surface that error."""
    writer = _CloseFailsWriter()
    f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=True)
    await f.__aenter__()
    await f.write(b"some payload")
    with pytest.raises(OSError, match="underlying close failed"):
        await f.close()


async def test_binary_anext_on_closed_file_stops_iteration(tmp_path):
    """__anext__ on a closed binary stream raises StopAsyncIteration."""
    target = tmp_path / "lines.gz"
    async with AsyncGzipBinaryFile(target, "wb") as f:
        await f.write(b"a\nb\n")

    f = AsyncGzipBinaryFile(target, "rb")
    await f.__aenter__()
    await f.close()
    with pytest.raises(StopAsyncIteration):
        await f.__anext__()
