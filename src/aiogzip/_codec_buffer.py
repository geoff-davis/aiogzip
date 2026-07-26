"""Private bounded input and output storage for the sans-I/O codec."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

_NON_ZERO = re.compile(rb"[^\x00]")


def _require_exact_bytes(data: bytes) -> None:
    if type(data) is not bytes:
        raise TypeError("codec buffer spans must be exact bytes")


@dataclass(slots=True)
class _Span:
    """One immutable input span with logical consumption offsets."""

    data: bytes
    start: int
    end: int

    def __post_init__(self) -> None:
        _require_exact_bytes(self.data)
        if not 0 <= self.start <= self.end <= len(self.data):
            raise ValueError("invalid codec buffer span bounds")

    def __len__(self) -> int:
        return self.end - self.start


class _InputQueue:
    """A queue of immutable spans with O(1) length and head removal."""

    __slots__ = ("_size", "_spans")

    def __init__(self) -> None:
        self._spans: deque[_Span] = deque()
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def append(self, data: bytes) -> None:
        """Append one exact immutable span without copying it."""
        _require_exact_bytes(data)
        if data:
            self._spans.append(_Span(data, 0, len(data)))
            self._size += len(data)

    def prepend(self, data: bytes) -> None:
        """Prepend one exact immutable span without disturbing later input."""
        _require_exact_bytes(data)
        if data:
            self._spans.appendleft(_Span(data, 0, len(data)))
            self._size += len(data)

    def peek_byte(self) -> int | None:
        """Return the leading byte without consuming it."""
        if not self._spans:
            return None
        span = self._spans[0]
        return span.data[span.start]

    @property
    def head_size(self) -> int:
        """Number of bytes in the first contiguous span."""
        if not self._spans:
            return 0
        return len(self._spans[0])

    def peek_span(self, max_bytes: int) -> memoryview:
        """Return a zero-copy view of the bounded first contiguous span."""
        if max_bytes < 0:
            raise ValueError("maximum byte count cannot be negative")
        if not self._spans or max_bytes == 0:
            return memoryview(b"")
        span = self._spans[0]
        end = min(span.start + max_bytes, span.end)
        return memoryview(span.data)[span.start : end]

    def find_in_head(self, value: int, max_bytes: int) -> int | None:
        """Return the relative index of *value* in the bounded head span."""
        if not 0 <= value <= 255:
            raise ValueError("searched byte must be between 0 and 255")
        if max_bytes < 0:
            raise ValueError("maximum byte count cannot be negative")
        if not self._spans or max_bytes == 0:
            return None
        span = self._spans[0]
        end = min(span.start + max_bytes, span.end)
        position = span.data.find(bytes((value,)), span.start, end)
        return None if position < 0 else position - span.start

    def consume(self, size: int) -> None:
        """Consume exactly *size* queued bytes by advancing head offsets."""
        if size < 0:
            raise ValueError("cannot consume a negative byte count")
        if size > self._size:
            raise ValueError("cannot consume beyond queued input")

        remaining = size
        while remaining:
            span = self._spans[0]
            available = len(span)
            if remaining < available:
                span.start += remaining
                self._size -= remaining
                return
            self._spans.popleft()
            self._size -= available
            remaining -= available

    def _take_head(self, size: int) -> bytes:
        span = self._spans[0]
        if size == len(span) and span.start == 0 and span.end == len(span.data):
            result = span.data
        else:
            result = span.data[span.start : span.start + size]
        self.consume(size)
        return result

    def take(self, max_bytes: int) -> bytes:
        """Consume and return at most *max_bytes*, copying only that bound."""
        if max_bytes < 0:
            raise ValueError("maximum byte count cannot be negative")
        size = min(max_bytes, self._size)
        if not size:
            return b""
        if size <= len(self._spans[0]):
            return self._take_head(size)

        parts: list[bytes] = []
        remaining = size
        while remaining:
            amount = min(remaining, len(self._spans[0]))
            parts.append(self._take_head(amount))
            remaining -= amount
        return b"".join(parts)

    def take_exact(self, size: int) -> bytes | None:
        """Consume exactly *size* bytes, or return ``None`` without consuming."""
        if size < 0:
            raise ValueError("exact byte count cannot be negative")
        if self._size < size:
            return None
        return self.take(size)

    def pop_window(self, max_bytes: int) -> bytes:
        """Consume one non-empty contiguous window bounded by *max_bytes*."""
        if max_bytes <= 0:
            raise ValueError("window size must be positive")
        return self.take(max_bytes)

    def consume_leading(self, value: int) -> int:
        """Consume consecutive leading bytes equal to *value*."""
        if not 0 <= value <= 255:
            raise ValueError("leading byte must be between 0 and 255")
        consumed = 0
        while self._spans:
            span = self._spans[0]
            position = span.start
            while position < span.end and span.data[position] == value:
                position += 1
            amount = position - span.start
            self.consume(amount)
            consumed += amount
            if position < span.end:
                break
        return consumed

    def consume_leading_zeroes(self) -> int:
        """Consume leading NUL padding without copying complete spans."""
        consumed = 0
        while self._spans:
            span = self._spans[0]
            match = _NON_ZERO.search(span.data, span.start, span.end)
            position = match.start() if match is not None else span.end
            amount = position - span.start
            self.consume(amount)
            consumed += amount
            if match is not None:
                break
        return consumed

    def clear(self) -> None:
        """Release every queued span."""
        self._spans.clear()
        self._size = 0


class _OutputCursor:
    """Retain one immutable output block and emit bounded slices by offset."""

    __slots__ = ("_block", "_offset")

    def __init__(self) -> None:
        self._block: bytes | None = None
        self._offset = 0

    def __len__(self) -> int:
        if self._block is None:
            return 0
        return len(self._block) - self._offset

    def set_block(self, block: bytes) -> None:
        """Install a block after the previous block has drained."""
        _require_exact_bytes(block)
        if self._block is not None:
            raise RuntimeError("codec output block is not drained")
        if block:
            self._block = block
            self._offset = 0

    def pop(self, max_bytes: int) -> bytes | None:
        """Return the next bounded slice, releasing a fully drained block."""
        if max_bytes <= 0:
            raise ValueError("output slice size must be positive")
        block = self._block
        if block is None:
            return None

        end = min(self._offset + max_bytes, len(block))
        if self._offset == 0 and end == len(block):
            output = block
        else:
            output = block[self._offset : end]
        self._offset = end
        if end == len(block):
            self._block = None
            self._offset = 0
        return output

    def clear(self) -> None:
        """Release any pending output block."""
        self._block = None
        self._offset = 0
