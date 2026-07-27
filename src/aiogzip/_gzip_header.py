"""Incremental RFC 1952 header parsing for the sans-I/O decoder."""

from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass

from . import _engine
from ._codec_buffer import _InputQueue
from ._common import (
    GZIP_FLAG_FCOMMENT,
    GZIP_FLAG_FEXTRA,
    GZIP_FLAG_FHCRC,
    GZIP_FLAG_FNAME,
    GZIP_METHOD_DEFLATE,
)

_RESERVED_FLAGS = 0xE0


@dataclass(frozen=True, slots=True)
class _ParsedHeader:
    """Metadata and encoded size of one complete gzip member header."""

    size: int
    mtime: int
    original_filename: str | None
    comment: str | None
    extra: bytes | None
    flags: int


class _GzipHeaderParser:
    """Consume one gzip header incrementally without rescanning prior input."""

    __slots__ = (
        "_collect_metadata",
        "_comment",
        "_crc",
        "_extra",
        "_extra_remaining",
        "_field_buffer",
        "_fixed",
        "_flags",
        "_filename",
        "_limit",
        "_mtime",
        "_plain_result",
        "_result",
        "_size",
        "_state",
    )

    def __init__(self, *, collect_metadata: bool, limit: int) -> None:
        if limit <= 0:
            raise ValueError("gzip header limit must be positive")
        self._collect_metadata = collect_metadata
        self._limit = limit
        self._state = "fixed"
        self._size = 0
        self._crc = 0
        self._fixed = bytearray()
        self._field_buffer: bytearray | None = None
        self._extra_remaining = 0
        self._flags = 0
        self._mtime = 0
        self._filename: str | None = None
        self._extra: bytes | None = None
        self._comment: str | None = None
        self._plain_result: _ParsedHeader | None = None
        self._result: _ParsedHeader | None = None

    @property
    def started(self) -> bool:
        """Whether any byte of this header has been consumed."""
        return self._size != 0

    @property
    def size(self) -> int:
        """Number of header bytes consumed so far."""
        return self._size

    def reset(self) -> None:
        """Prepare this parser for the next member with the same policy."""
        self._state = "fixed"
        self._size = 0
        self._crc = 0
        self._fixed.clear()
        self._field_buffer = None
        self._extra_remaining = 0
        self._flags = 0
        self._mtime = 0
        self._filename = None
        self._extra = None
        self._comment = None
        self._result = None

    def _available(self, pending: _InputQueue) -> int:
        remaining = self._limit - self._size
        if remaining == 0 and pending:
            raise gzip.BadGzipFile("gzip header exceeds the 128 MiB safety limit")
        return min(len(pending), remaining)

    def _consume(
        self,
        pending: _InputQueue,
        amount: int,
        *,
        checksum: bool = True,
        capture: bytearray | None = None,
    ) -> int:
        consumed = 0
        while consumed < amount:
            available = self._available(pending)
            if not available:
                break
            view = pending.peek_span(min(amount - consumed, available))
            if checksum:
                self._crc = _engine.crc32(view, self._crc)
            if capture is not None:
                capture.extend(view)
            size = len(view)
            pending.consume(size)
            self._size += size
            consumed += size
        return consumed

    def _next_optional_state(self, completed: str) -> None:
        if completed == "fixed" and self._flags & GZIP_FLAG_FEXTRA:
            self._state = "extra-length"
        elif completed in ("fixed", "extra") and self._flags & GZIP_FLAG_FNAME:
            self._state = "filename"
        elif completed in ("fixed", "extra", "filename") and (
            self._flags & GZIP_FLAG_FCOMMENT
        ):
            self._state = "comment"
        elif self._flags & GZIP_FLAG_FHCRC:
            self._state = "header-crc"
        else:
            self._state = "done"

    def _advance_fixed(self, pending: _InputQueue) -> bool:
        checkpoints = (2, 3, 4, 10)
        target = next(size for size in checkpoints if len(self._fixed) < size)
        self._consume(
            pending,
            target - len(self._fixed),
            checksum=bool(self._flags & GZIP_FLAG_FHCRC),
            capture=self._fixed,
        )
        size = len(self._fixed)
        if size < target:
            return False
        if size == 2 and self._fixed != b"\x1f\x8b":
            raise gzip.BadGzipFile("Not a gzipped file")
        if size == 3 and self._fixed[2] != GZIP_METHOD_DEFLATE:
            raise gzip.BadGzipFile(f"Unknown compression method {self._fixed[2]}")
        if size == 4:
            self._flags = self._fixed[3]
            if self._flags & _RESERVED_FLAGS:
                raise gzip.BadGzipFile(
                    f"Reserved flags are set in gzip header: {self._flags:#04x}"
                )
            if self._flags & GZIP_FLAG_FHCRC:
                self._crc = _engine.crc32(self._fixed)
        if size == 10:
            self._mtime = struct.unpack_from("<I", self._fixed, 4)[0]
            self._fixed.clear()
            self._next_optional_state("fixed")
        return True

    def _advance_extra_length(self, pending: _InputQueue) -> bool:
        if self._field_buffer is None:
            self._field_buffer = bytearray()
        self._consume(
            pending,
            2 - len(self._field_buffer),
            checksum=bool(self._flags & GZIP_FLAG_FHCRC),
            capture=self._field_buffer,
        )
        if len(self._field_buffer) < 2:
            return False
        self._extra_remaining = struct.unpack("<H", self._field_buffer)[0]
        self._field_buffer = bytearray() if self._collect_metadata else None
        self._state = "extra"
        return True

    def _advance_extra(self, pending: _InputQueue) -> bool:
        consumed = self._consume(
            pending,
            self._extra_remaining,
            checksum=bool(self._flags & GZIP_FLAG_FHCRC),
            capture=self._field_buffer,
        )
        self._extra_remaining -= consumed
        if self._extra_remaining:
            return False
        if self._field_buffer is not None:
            self._extra = bytes(self._field_buffer)
        self._field_buffer = None
        self._next_optional_state("extra")
        return True

    def _advance_string(self, pending: _InputQueue) -> bool:
        if self._collect_metadata and self._field_buffer is None:
            self._field_buffer = bytearray()
        available = self._available(pending)
        if not available:
            return False
        amount = min(available, pending.head_size)
        terminator = pending.find_in_head(0, amount)
        take = amount if terminator is None else terminator + 1
        view = pending.peek_span(take)
        if self._flags & GZIP_FLAG_FHCRC:
            self._crc = _engine.crc32(view, self._crc)
        if self._field_buffer is not None:
            self._field_buffer.extend(view if terminator is None else view[:-1])
        pending.consume(take)
        self._size += take
        if terminator is None:
            return True

        value = (
            self._field_buffer.decode("latin-1")
            if self._field_buffer is not None
            else None
        )
        completed = self._state
        if completed == "filename":
            self._filename = value
        else:
            self._comment = value
        self._field_buffer = None
        self._next_optional_state(completed)
        return True

    def _advance_header_crc(self, pending: _InputQueue) -> bool:
        if self._field_buffer is None:
            self._field_buffer = bytearray()
        self._consume(
            pending,
            2 - len(self._field_buffer),
            checksum=False,
            capture=self._field_buffer,
        )
        if len(self._field_buffer) < 2:
            return False
        expected = struct.unpack("<H", self._field_buffer)[0]
        actual = self._crc & 0xFFFF
        if actual != expected:
            raise gzip.BadGzipFile(
                f"Header CRC check failed ({actual:#06x} != {expected:#06x})"
            )
        self._field_buffer = None
        self._state = "done"
        return True

    def advance(self, pending: _InputQueue) -> _ParsedHeader | None:
        """Consume available header bytes and return metadata once complete."""
        if (
            self._state == "fixed"
            and not self._fixed
            and pending.head_size >= 10
            and self._limit >= 10
        ):
            # Most members have one contiguous fixed header and no optional
            # fields. Complete that common case without traversing the
            # incremental state dispatch used by fragmented headers.
            fixed = pending.take_view(10)
            if fixed[0] != 0x1F or fixed[1] != 0x8B:
                raise gzip.BadGzipFile("Not a gzipped file")
            if fixed[2] != GZIP_METHOD_DEFLATE:
                raise gzip.BadGzipFile(f"Unknown compression method {fixed[2]}")
            flags = fixed[3]
            if flags & _RESERVED_FLAGS:
                raise gzip.BadGzipFile(
                    f"Reserved flags are set in gzip header: {flags:#04x}"
                )
            self._flags = flags
            self._mtime = struct.unpack_from("<I", fixed, 4)[0]
            if flags & GZIP_FLAG_FHCRC:
                self._crc = _engine.crc32(fixed, self._crc)
            self._size = 10
            if not flags & (
                GZIP_FLAG_FEXTRA
                | GZIP_FLAG_FNAME
                | GZIP_FLAG_FCOMMENT
                | GZIP_FLAG_FHCRC
            ):
                self._state = "done"
                result = self._plain_result
                if (
                    result is None
                    or result.mtime != self._mtime
                    or result.flags != flags
                ):
                    result = _ParsedHeader(
                        size=10,
                        mtime=self._mtime,
                        original_filename=None,
                        comment=None,
                        extra=None,
                        flags=flags,
                    )
                    self._plain_result = result
                self._result = result
                return self._result
            self._next_optional_state("fixed")

        while self._state != "done":
            state = self._state
            if state == "fixed":
                progressed = self._advance_fixed(pending)
            elif state == "extra-length":
                progressed = self._advance_extra_length(pending)
            elif state == "extra":
                progressed = self._advance_extra(pending)
            elif state in ("filename", "comment"):
                progressed = self._advance_string(pending)
            elif state == "header-crc":
                progressed = self._advance_header_crc(pending)
            else:
                raise AssertionError(f"unknown gzip header state: {state}")
            if not progressed:
                return None

        if self._result is None:
            self._result = _ParsedHeader(
                size=self._size,
                mtime=self._mtime,
                original_filename=self._filename,
                comment=self._comment,
                extra=self._extra,
                flags=self._flags,
            )
        return self._result
