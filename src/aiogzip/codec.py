"""Pure synchronous, sans-I/O gzip encoding and decoding.

The codec classes own RFC 1952 framing and validation but perform no I/O and
do not schedule work. Each state-changing method returns a lazy, single-use
iterator. Exhaust every iterator before starting another operation.

Codec instances and their operation iterators are not thread-safe. Callers
sharing an instance must serialize each complete operation lifecycle.
"""

from __future__ import annotations

import gzip
import struct
import warnings
from collections.abc import Iterator
from dataclasses import dataclass

from . import _engine
from ._common import (
    _MAX_CHUNK_SIZE,
    GZIP_FLAG_FCOMMENT,
    GZIP_FLAG_FEXTRA,
    GZIP_FLAG_FHCRC,
    GZIP_FLAG_FNAME,
    GZIP_METHOD_DEFLATE,
    ZlibEngine,
    _build_gzip_header,
    _build_gzip_trailer,
    _derive_header_filename,
    _normalize_mtime,
    _validate_chunk_size,
    _validate_compresslevel,
    _validate_optional_positive_int,
    _validate_original_filename,
)
from ._metadata import GzipMemberInfo

__all__ = ["GzipDecoder", "GzipEncoder"]

_RESERVED_FLAGS = 0xE0


def _snapshot_bytes_input(data: bytes) -> bytes:
    """Return an exact immutable bytes snapshot without invoking overrides."""
    if type(data) is bytes:
        return data
    if isinstance(data, bytes):
        return memoryview(data).tobytes()
    raise TypeError("gzip codec input must be bytes")


class _Operation(Iterator[bytes]):
    """Single-use iterator tied to a codec-owned reservation token."""

    __slots__ = ("_advancing", "_closed", "_iterator", "_owner")

    def __init__(self, owner: _CodecBase, iterator: Iterator[bytes]) -> None:
        self._owner = owner
        self._iterator = iterator
        self._advancing = False
        self._closed = False

    def __iter__(self) -> _Operation:
        return self

    def __next__(self) -> bytes:
        if self._owner._discarded:
            raise RuntimeError("gzip codec operation was invalidated by discard()")
        if self._closed:
            raise StopIteration
        if self._advancing:
            raise RuntimeError("gzip codec operation cannot be advanced reentrantly")
        if self._owner._active_token is not self:
            raise RuntimeError("gzip codec operation is no longer active")

        self._advancing = True
        try:
            output = next(self._iterator)
        except StopIteration:
            self._closed = True
            self._owner._operation_succeeded(self)
            raise
        except BaseException:
            self._closed = True
            self._owner._operation_failed(self)
            raise
        finally:
            self._advancing = False
        return output

    def close(self) -> None:
        """Close this operation, poisoning its codec unless already invalid."""
        if self._closed:
            return
        invalidated = self._owner._discarded
        self._closed = True
        iterator = self._iterator
        self._iterator = iter(())
        if not invalidated:
            self._owner._operation_failed(self)
        close = getattr(iterator, "close", None)
        if callable(close):
            close()


class _CodecBase:
    """Shared deterministic operation ownership."""

    _active_token: object | None
    _discarded: bool
    _unusable: bool

    def __init__(self) -> None:
        self._active_token = None
        self._discarded = False
        self._unusable = False

    def _check_available(self, name: str) -> None:
        if self._active_token is not None:
            raise RuntimeError(f"gzip {name} has an active operation")
        if self._unusable:
            raise OSError(f"gzip {name} is unusable after a prior failure")

    def _reserve(self, iterator: Iterator[bytes]) -> Iterator[bytes]:
        operation = _Operation(self, iterator)
        self._active_token = operation
        return operation

    def _operation_succeeded(self, token: object) -> None:
        if self._active_token is token:
            self._active_token = None

    def _operation_failed(self, token: object) -> None:
        if self._active_token is token:
            self._active_token = None
            self._unusable = True
            self._release_state()

    def _release_state(self) -> None:
        raise NotImplementedError

    def discard(self) -> None:
        """Irreversibly invalidate active work and release codec state."""
        if self._discarded:
            return
        self._discarded = True
        self._unusable = True
        self._active_token = None
        self._release_state()


def _output_chunks(data: bytes, chunk_size: int) -> Iterator[bytes]:
    for offset in range(0, len(data), chunk_size):
        yield data[offset : offset + chunk_size]


class GzipEncoder(_CodecBase):
    """Incrementally encode exactly one complete gzip member.

    Methods return bounded lazy iterators. The iterator from each operation
    must be exhausted before another method is called. Explicitly closing an
    incomplete operation makes the encoder unusable; dropping it leaves the
    encoder reserved until :meth:`discard` is called.

    This class performs no I/O or executor offload and is not thread-safe.
    """

    def __init__(
        self,
        *,
        compresslevel: int = 6,
        mtime: int | float | None = None,
        original_filename: str | bytes | None = None,
        fast_compress: bool = False,
        strict_size: bool = False,
        output_chunk_size: int = 256 * 1024,
    ) -> None:
        super().__init__()
        _validate_compresslevel(compresslevel)
        _validate_chunk_size(output_chunk_size)
        self._compresslevel = compresslevel
        self._mtime = _normalize_mtime(mtime)
        validated_filename = _validate_original_filename(original_filename)
        self._filename = _derive_header_filename(validated_filename, None)
        self._fast_compress = bool(fast_compress)
        self._strict_size = bool(strict_size)
        self._output_chunk_size = output_chunk_size
        if self._fast_compress and not _engine.have_fast_engine():
            warnings.warn(
                "fast_compress=True requested but zlib-ng is not available; "
                "falling back to stdlib zlib. Install the extra with "
                "'pip install aiogzip[fast]' to enable faster compression.",
                stacklevel=2,
            )
        self._engine: ZlibEngine = _engine.compressobj(
            compresslevel,
            -_engine.MAX_WBITS,
            fast=self._fast_compress,
        )
        self._crc = 0
        self._input_size = 0
        self._started = False
        self._finished = False

    @property
    def input_size(self) -> int:
        """Number of uncompressed bytes committed to this member."""
        return self._input_size

    @property
    def crc32(self) -> int:
        """Running CRC-32 of committed uncompressed input."""
        return self._crc

    @property
    def started(self) -> bool:
        """Whether the header-producing operation has advanced."""
        return self._started

    @property
    def finished(self) -> bool:
        """Whether the finish operation completed successfully."""
        return self._finished

    def _release_state(self) -> None:
        self._engine = None

    def _check_encoder_available(self) -> None:
        self._check_available("encoder")
        if self._finished:
            raise ValueError("gzip encoder is already finalized")

    def start(self) -> Iterator[bytes]:
        """Start the member and lazily emit its gzip header exactly once."""
        self._check_encoder_available()
        if self._started:
            raise ValueError("gzip encoder is already started")
        return self._reserve(self._start())

    def _start(self) -> Iterator[bytes]:
        header = _build_gzip_header(self._filename, self._mtime, self._compresslevel)
        self._started = True
        yield from _output_chunks(header, self._output_chunk_size)

    def feed(self, data: bytes) -> Iterator[bytes]:
        """Consume one immutable input snapshot and emit compressed chunks."""
        self._check_encoder_available()
        if not self._started:
            raise ValueError("gzip encoder must be started before feeding data")
        snapshot = _snapshot_bytes_input(data)
        size = len(snapshot)
        if self._strict_size and self._input_size + size > 0xFFFFFFFF:
            raise OSError(
                f"uncompressed member size would exceed the gzip ISIZE "
                f"field's 4 GiB limit ({self._input_size} + {size} > "
                f"{0xFFFFFFFF}); drop strict_size to allow ISIZE "
                f"truncation or split the payload into multiple members"
            )
        return self._reserve(self._feed(snapshot))

    def _feed(self, data: bytes) -> Iterator[bytes]:
        try:
            compressed = self._engine.compress(data)
        except _engine.ZLIB_ERRORS as error:
            raise OSError(f"Error compressing data: {error}") from error
        except Exception as error:
            raise OSError(f"Unexpected error during compression: {error}") from error
        self._crc = _engine.crc32(data, self._crc) & 0xFFFFFFFF
        self._input_size += len(data)
        if compressed:
            for offset in range(0, len(compressed), self._output_chunk_size):
                yield compressed[offset : offset + self._output_chunk_size]

    def flush(self) -> Iterator[bytes]:
        """Perform a non-finalizing ``Z_SYNC_FLUSH`` operation."""
        self._check_encoder_available()
        if not self._started:
            raise ValueError("gzip encoder must be started before flushing")
        return self._reserve(self._flush())

    def _flush(self) -> Iterator[bytes]:
        try:
            output = self._engine.flush(_engine.Z_SYNC_FLUSH)
        except _engine.ZLIB_ERRORS as error:
            raise OSError(f"Error flushing compressed data: {error}") from error
        except Exception as error:
            raise OSError(
                f"Unexpected error during compression flush: {error}"
            ) from error
        yield from _output_chunks(output, self._output_chunk_size)

    def finish(self) -> Iterator[bytes]:
        """Finalize DEFLATE and lazily emit the gzip trailer exactly once."""
        self._check_encoder_available()
        if not self._started:
            raise ValueError("gzip encoder must be started before finalizing")
        return self._reserve(self._finish())

    def _finish(self) -> Iterator[bytes]:
        try:
            remaining = self._engine.flush()
        except _engine.ZLIB_ERRORS as error:
            raise OSError(f"Error finalizing compressed data: {error}") from error
        except Exception as error:
            raise OSError(
                f"Unexpected error during compression finalization: {error}"
            ) from error
        trailer = _build_gzip_trailer(self._crc, self._input_size)
        yield from _output_chunks(remaining, self._output_chunk_size)
        yield from _output_chunks(trailer, self._output_chunk_size)
        self._finished = True
        self._engine = None


@dataclass(frozen=True, slots=True)
class _ParsedHeader:
    size: int
    mtime: int
    original_filename: str | None
    comment: str | None
    extra: bytes | None
    flags: int


def _parse_header(data: bytes, collect_metadata: bool) -> _ParsedHeader | None:
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
    extra: bytes | None = None
    filename: str | None = None
    comment: str | None = None

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


class GzipDecoder(_CodecBase):
    """Incrementally decode and validate zero or more gzip members.

    Payload bytes may be emitted before their member trailer is available, so
    integrity is established only after :meth:`finish` is exhausted. Completed
    metadata is retained only when ``collect_member_info=True``.

    Methods return bounded lazy iterators that must be exhausted. This class
    performs no I/O or executor offload and is not thread-safe.
    """

    def __init__(
        self,
        *,
        output_chunk_size: int = 256 * 1024,
        max_decompressed_size: int | None = None,
        collect_member_info: bool = False,
    ) -> None:
        super().__init__()
        _validate_chunk_size(output_chunk_size)
        _validate_optional_positive_int(max_decompressed_size, "max_decompressed_size")
        self._output_chunk_size = output_chunk_size
        self._max_decompressed_size = max_decompressed_size
        self._collect_member_info = bool(collect_member_info)
        self._pending = bytearray()
        self._state = "header"
        self._engine: ZlibEngine = None
        self._header: _ParsedHeader | None = None
        self._members: list[GzipMemberInfo] = []
        self._member_count = 0
        self._member_offset = 0
        self._member_crc = 0
        self._member_size = 0
        self._compressed_size = 0
        self._consumed_size = 0
        self._uncompressed_size = 0
        self._allow_padding = False
        self._finished = False

    @property
    def members(self) -> tuple[GzipMemberInfo, ...]:
        """Completed, trailer-validated members when collection is enabled."""
        return tuple(self._members)

    @property
    def member_count(self) -> int:
        """Number of completed and trailer-validated members."""
        return self._member_count

    @property
    def compressed_size(self) -> int:
        """Number of compressed bytes accepted by :meth:`feed`."""
        return self._compressed_size

    @property
    def uncompressed_size(self) -> int:
        """Number of decompressed bytes accounted by the decoder."""
        return self._uncompressed_size

    @property
    def finished(self) -> bool:
        """Whether :meth:`finish` completed full-stream validation."""
        return self._finished

    def _release_state(self) -> None:
        self._pending.clear()
        self._engine = None
        self._header = None
        self._members.clear()

    def _check_decoder_available(self) -> None:
        self._check_available("decoder")
        if self._finished:
            raise ValueError("gzip decoder is already finalized")

    def feed(self, data: bytes) -> Iterator[bytes]:
        """Accept compressed bytes and lazily emit bounded decoded output."""
        self._check_decoder_available()
        snapshot = _snapshot_bytes_input(data)
        operation = self._reserve(self._feed(snapshot))
        self._compressed_size += len(snapshot)
        return operation

    def _feed(self, data: bytes) -> Iterator[bytes]:
        self._pending.extend(data)
        yield from self._process(finalizing=False)

    def finish(self) -> Iterator[bytes]:
        """Prove that all accepted input forms a complete valid gzip stream."""
        self._check_decoder_available()
        return self._reserve(self._process(finalizing=True))

    def _consume(self, size: int) -> None:
        del self._pending[:size]
        self._consumed_size += size

    def _output_limit(self) -> int:
        limit = self._max_decompressed_size
        if limit is None:
            return self._output_chunk_size
        remaining = limit - self._uncompressed_size
        return min(self._output_chunk_size, remaining + 1)

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

    def _inflate(self, data: bytes) -> _engine._InflateStep:
        try:
            return _engine.inflate_step(
                self._engine,
                data,
                max_length=self._output_limit(),
            )
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

    def _process(self, *, finalizing: bool) -> Iterator[bytes]:
        while True:
            if self._state == "header":
                if self._allow_padding:
                    padding = len(self._pending) - len(self._pending.lstrip(b"\x00"))
                    if padding:
                        self._consume(padding)
                    if not self._pending:
                        break

                parsed = _parse_header(bytes(self._pending), self._collect_member_info)
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
                step = self._inflate(payload)
                if step.consumed:
                    self._consume(step.consumed)
                if step.output:
                    self._account_output(step.output)
                    yield step.output
                if step.eof:
                    self._state = "trailer"
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
