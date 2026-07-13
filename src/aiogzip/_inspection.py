"""Gzip stream inspection result types and private scanner internals."""

import asyncio
import gzip
import struct
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, AsyncIterator, List, Optional, Tuple, Union, cast

import aiofiles

from . import _engine
from ._common import (
    _MAX_CHUNK_SIZE,
    GZIP_FLAG_FCOMMENT,
    GZIP_FLAG_FEXTRA,
    GZIP_FLAG_FHCRC,
    GZIP_FLAG_FNAME,
    GZIP_METHOD_DEFLATE,
    WithAsyncRead,
    WithAsyncReadWrite,
    ZlibEngine,
    _validate_chunk_size,
    _validate_filename,
    _validate_optional_positive_int,
)

_RESERVED_FLAGS = 0xE0
_Filename = Union[str, bytes, Path, None]
_ReadFileObj = Optional[Union[WithAsyncRead, WithAsyncReadWrite]]


@dataclass(frozen=True)
class GzipMemberInfo:
    """Validated metadata and sizes for one gzip member.

    ``mtime`` preserves the literal unsigned header value, including zero.
    Filename and comment fields are decoded one-to-one with Latin-1; absent
    fields are ``None``, while present empty fields are empty strings.
    """

    index: int
    compressed_offset: int
    compressed_size: int
    uncompressed_size: int
    mtime: int
    original_filename: Optional[str]
    comment: Optional[str]
    extra: Optional[bytes]
    flags: int
    crc32: int
    trailer_isize: int


@dataclass(frozen=True)
class GzipInfo:
    """Aggregate information for a completely validated gzip stream."""

    members: Tuple[GzipMemberInfo, ...]
    compressed_size: int
    uncompressed_size: int

    @property
    def member_count(self) -> int:
        """Return the number of gzip members in stream order."""
        return len(self.members)


@dataclass(frozen=True)
class VerificationResult:
    """Aggregate counts returned after successful integrity verification."""

    member_count: int
    compressed_size: int
    uncompressed_size: int


@dataclass(frozen=True)
class _ParsedHeader:
    size: int
    mtime: int
    original_filename: Optional[str]
    comment: Optional[str]
    extra: Optional[bytes]
    flags: int


def _parse_header(data: bytes, collect_metadata: bool) -> Optional[_ParsedHeader]:
    """Parse one complete gzip header, returning ``None`` when incomplete."""
    if len(data) < 2:
        return None
    if data[:2] != b"\x1f\x8b":
        raise gzip.BadGzipFile("Not a gzipped file")
    if len(data) < 3:
        return None
    if data[2] != GZIP_METHOD_DEFLATE:
        raise gzip.BadGzipFile(f"Unknown compression method {data[2]}")
    if len(data) < 4:
        return None

    flags = data[3]
    if flags & _RESERVED_FLAGS:
        raise gzip.BadGzipFile(f"Reserved flags are set in gzip header: {flags:#04x}")
    if len(data) < 10:
        return None

    mtime = struct.unpack("<I", data[4:8])[0]
    position = 10
    extra: Optional[bytes] = None
    filename: Optional[str] = None
    comment: Optional[str] = None

    if flags & GZIP_FLAG_FEXTRA:
        if len(data) < position + 2:
            return None
        extra_length = struct.unpack("<H", data[position : position + 2])[0]
        position += 2
        if len(data) < position + extra_length:
            return None
        if collect_metadata:
            extra = data[position : position + extra_length]
        position += extra_length

    if flags & GZIP_FLAG_FNAME:
        terminator = data.find(b"\x00", position)
        if terminator < 0:
            return None
        if collect_metadata:
            filename = data[position:terminator].decode("latin-1")
        position = terminator + 1

    if flags & GZIP_FLAG_FCOMMENT:
        terminator = data.find(b"\x00", position)
        if terminator < 0:
            return None
        if collect_metadata:
            comment = data[position:terminator].decode("latin-1")
        position = terminator + 1

    if flags & GZIP_FLAG_FHCRC:
        if len(data) < position + 2:
            return None
        expected = struct.unpack("<H", data[position : position + 2])[0]
        actual = _engine.crc32(data[:position]) & 0xFFFF
        if actual != expected:
            raise gzip.BadGzipFile(
                f"Header CRC check failed ({actual:#06x} != {expected:#06x})"
            )
        position += 2

    return _ParsedHeader(
        size=position,
        mtime=mtime,
        original_filename=filename,
        comment=comment,
        extra=extra,
        flags=flags,
    )


class _IncrementalGzipDecoder:
    """Incrementally validate gzip members and yield bounded output chunks."""

    def __init__(
        self,
        *,
        max_decompressed_size: Optional[int],
        output_chunk_size: int,
        collect_member_info: bool,
    ) -> None:
        _validate_chunk_size(output_chunk_size)
        _validate_optional_positive_int(max_decompressed_size, "max_decompressed_size")
        self._max_decompressed_size = max_decompressed_size
        self._output_chunk_size = output_chunk_size
        self._collect_member_info = collect_member_info
        self._pending = bytearray()
        self._state = "header"
        self._engine: ZlibEngine = None
        self._header: Optional[_ParsedHeader] = None
        self._members: List[GzipMemberInfo] = []
        self._member_count = 0
        self._member_offset = 0
        self._member_crc = 0
        self._member_size = 0
        self._compressed_size = 0
        self._consumed_size = 0
        self._uncompressed_size = 0
        self._allow_padding = False
        self._finished = False
        self._failed = False
        self._active = False

    @property
    def members(self) -> Tuple[GzipMemberInfo, ...]:
        return tuple(self._members)

    @property
    def member_count(self) -> int:
        return self._member_count

    @property
    def compressed_size(self) -> int:
        return self._compressed_size

    @property
    def uncompressed_size(self) -> int:
        return self._uncompressed_size

    def discard(self) -> None:
        """Release codec state and buffered data without final validation."""
        self._failed = True
        self._pending.clear()
        self._engine = None
        self._header = None
        self._members.clear()

    def feed(self, data: bytes) -> AsyncIterator[bytes]:
        """Accept compressed bytes and return a bounded-output async iterator."""
        if self._finished:
            raise ValueError("gzip decoder is already finalized")
        if self._failed:
            raise OSError("gzip decoder is unusable after a prior failure")
        if not isinstance(data, bytes):
            raise TypeError("gzip decoder input must be bytes")
        self._compressed_size += len(data)
        self._pending.extend(data)
        return self._process(finalizing=False)

    def finish(self) -> AsyncIterator[bytes]:
        """Finalize parsing and reject any incomplete gzip structure."""
        if self._finished:
            raise ValueError("gzip decoder is already finalized")
        if self._failed:
            raise OSError("gzip decoder is unusable after a prior failure")
        return self._process(finalizing=True)

    def _consume(self, size: int) -> None:
        del self._pending[:size]
        self._consumed_size += size

    def _account_output(self, output: bytes) -> None:
        size = len(output)
        self._member_crc = _engine.crc32(output, self._member_crc)
        self._member_size += size
        self._uncompressed_size += size
        limit = self._max_decompressed_size
        if limit is not None and self._uncompressed_size > limit:
            raise OSError(
                f"decompressed output exceeded max_decompressed_size "
                f"({self._uncompressed_size} > {limit} bytes)"
            )

    def _output_limit(self) -> int:
        limit = self._max_decompressed_size
        if limit is None:
            return self._output_chunk_size
        remaining = limit - self._uncompressed_size
        return min(self._output_chunk_size, remaining + 1)

    async def _inflate(self, data: bytes) -> bytes:
        decompress = partial(self._engine.decompress, max_length=self._output_limit())
        try:
            if len(data) >= _engine.ZLIB_OFFLOAD_THRESHOLD:
                return await _engine.run_zlib_in_thread(decompress, data)
            return cast(bytes, decompress(data))
        except asyncio.CancelledError:
            self._failed = True
            self._engine = None
            self._pending.clear()
            raise
        except _engine.ZLIB_ERRORS as error:
            raise gzip.BadGzipFile(
                f"Error decompressing gzip member {self._member_count} at "
                f"compressed offset {self._member_offset}: {error}"
            ) from error

    def _complete_member(self, trailer: bytes) -> None:
        expected_crc, trailer_isize = struct.unpack("<II", trailer)
        actual_crc = self._member_crc & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise gzip.BadGzipFile(
                f"CRC check failed in gzip member {self._member_count} at "
                f"compressed offset {self._member_offset}"
            )
        if self._member_size & 0xFFFFFFFF != trailer_isize:
            raise gzip.BadGzipFile(
                f"ISIZE check failed in gzip member {self._member_count} at "
                f"compressed offset {self._member_offset}"
            )

        header = self._header
        assert header is not None
        self._consume(8)
        if self._collect_member_info:
            self._members.append(
                GzipMemberInfo(
                    index=self._member_count,
                    compressed_offset=self._member_offset,
                    compressed_size=self._consumed_size - self._member_offset,
                    uncompressed_size=self._member_size,
                    mtime=header.mtime,
                    original_filename=header.original_filename,
                    comment=header.comment,
                    extra=header.extra,
                    flags=header.flags,
                    crc32=actual_crc,
                    trailer_isize=trailer_isize,
                )
            )
        self._member_count += 1
        self._header = None
        self._engine = None
        self._state = "header"
        self._allow_padding = True

    async def _process(self, finalizing: bool) -> AsyncIterator[bytes]:
        if self._active:
            raise RuntimeError("gzip decoder cannot be advanced concurrently")
        self._active = True
        completed = False
        try:
            while True:
                if self._state == "header":
                    if self._allow_padding:
                        padding = len(self._pending) - len(
                            self._pending.lstrip(b"\x00")
                        )
                        if padding:
                            self._consume(padding)
                        if not self._pending:
                            break

                    parsed = _parse_header(
                        bytes(self._pending), self._collect_member_info
                    )
                    if parsed is None:
                        if len(self._pending) > _MAX_CHUNK_SIZE:
                            raise gzip.BadGzipFile(
                                "gzip header exceeds the 128 MiB safety limit"
                            )
                        break
                    self._member_offset = self._consumed_size
                    self._header = parsed
                    self._consume(parsed.size)
                    self._engine = _engine.decompressobj(-_engine.MAX_WBITS)
                    self._member_crc = 0
                    self._member_size = 0
                    self._state = "body"
                    self._allow_padding = False
                    continue

                if self._state == "body":
                    if not self._pending:
                        break
                    payload = bytes(self._pending)
                    output = await self._inflate(payload)
                    if self._engine.eof:
                        remaining = self._engine.unused_data
                    else:
                        remaining = self._engine.unconsumed_tail
                    consumed = len(payload) - len(remaining)
                    if consumed:
                        self._consume(consumed)
                    if output:
                        self._account_output(output)
                        yield output
                    if self._engine.eof:
                        self._state = "trailer"
                        continue
                    if not consumed and not output:
                        break
                    continue

                if self._state == "trailer":
                    if len(self._pending) < 8:
                        break
                    self._complete_member(bytes(self._pending[:8]))
                    continue

                raise AssertionError(f"unknown gzip decoder state: {self._state}")

            if finalizing:
                if self._state == "body":
                    raise gzip.BadGzipFile(
                        f"gzip member {self._member_count} at compressed offset "
                        f"{self._member_offset} ended before the deflate stream completed"
                    )
                if self._state == "trailer":
                    raise gzip.BadGzipFile(
                        f"gzip member {self._member_count} at compressed offset "
                        f"{self._member_offset} has a truncated trailer"
                    )
                if self._pending:
                    raise gzip.BadGzipFile("truncated gzip member header")
                self._finished = True
            completed = True
        except BaseException:
            self._failed = True
            raise
        finally:
            self._active = False
            if finalizing and not completed:
                self._pending.clear()
                self._engine = None


@dataclass(frozen=True)
class _ScanResult:
    members: Tuple[GzipMemberInfo, ...]
    member_count: int
    compressed_size: int
    uncompressed_size: int


async def _scan_gzip(
    filename: _Filename,
    *,
    fileobj: _ReadFileObj,
    closefd: Optional[bool],
    max_decompressed_size: Optional[int],
    chunk_size: int,
    collect_members: bool,
) -> _ScanResult:
    """Read and validate a complete gzip source without retaining payload."""
    _validate_filename(filename, fileobj)
    _validate_chunk_size(chunk_size)
    _validate_optional_positive_int(max_decompressed_size, "max_decompressed_size")

    source: Any
    owns_source = fileobj is None
    if fileobj is None:
        assert filename is not None
        source = await aiofiles.open(filename, "rb")
    else:
        source = fileobj
    should_close = owns_source or bool(closefd)

    decoder = _IncrementalGzipDecoder(
        max_decompressed_size=max_decompressed_size,
        output_chunk_size=chunk_size,
        collect_member_info=collect_members,
    )
    scan_failed = False
    try:
        while True:
            try:
                chunk = await source.read(chunk_size)
            except OSError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise OSError(f"Error reading from file: {error}") from error
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise TypeError("binary gzip source read() must return bytes")
            async for _ in decoder.feed(chunk):
                pass
        async for _ in decoder.finish():
            pass
        return _ScanResult(
            members=decoder.members,
            member_count=decoder.member_count,
            compressed_size=decoder.compressed_size,
            uncompressed_size=decoder.uncompressed_size,
        )
    except BaseException:
        scan_failed = True
        raise
    finally:
        if should_close:
            close_method = getattr(source, "close", None)
            if callable(close_method):
                try:
                    result = close_method()
                    if hasattr(result, "__await__"):
                        await result
                except BaseException:
                    if not scan_failed:
                        raise
