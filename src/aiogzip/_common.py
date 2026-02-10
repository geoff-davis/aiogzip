"""Shared constants, helpers, and protocols for aiogzip internals."""

import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

# Constants
# The wbits parameter for zlib that enables gzip format
# 31 = 16 (gzip format) + 15 (maximum window size)
GZIP_WBITS = 31

# gzip header constants
GZIP_FLAG_FNAME = 0x08
GZIP_FLAG_FHCRC = 0x02
GZIP_FLAG_FEXTRA = 0x04
GZIP_FLAG_FCOMMENT = 0x10
GZIP_METHOD_DEFLATE = 8
GZIP_OS_UNKNOWN = 255
_COMPRESS_LEVEL_FAST = 1
_COMPRESS_LEVEL_BEST = 9

# Type alias for zlib compression/decompression objects
# These are the return types of zlib.compressobj() and zlib.decompressobj()
# The actual types (zlib.Compress/zlib.Decompress) are C extension types that
# aren't exposed in the type stubs, so we use Any at runtime and for type checking
ZlibEngine = Any


# Validation helper functions
def _validate_filename(filename: Union[str, bytes, Path, None], fileobj: Any) -> None:
    """Validate filename parameter.

    Args:
        filename: The filename to validate
        fileobj: The fileobj parameter (for checking if at least one is provided)

    Raises:
        ValueError: If both filename and fileobj are None, or if filename is empty
        TypeError: If filename is not a string, bytes, or PathLike object
    """
    if filename is None and fileobj is None:
        raise ValueError("Either filename or fileobj must be provided")
    if filename is not None:
        if not isinstance(filename, (str, bytes, os.PathLike)):
            raise TypeError("Filename must be a string, bytes, or PathLike object")
        if isinstance(filename, str) and not filename:
            raise ValueError("Filename cannot be empty")


def _validate_chunk_size(chunk_size: int) -> None:
    """Validate chunk_size parameter.

    Args:
        chunk_size: The chunk size to validate

    Raises:
        ValueError: If chunk size is invalid
    """
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive")


def _validate_compresslevel(compresslevel: int) -> None:
    """Validate compresslevel parameter.

    Args:
        compresslevel: The compression level to validate

    Raises:
        ValueError: If compression level is not between -1 and 9
    """
    if not (-1 <= compresslevel <= 9):
        raise ValueError("Compression level must be between -1 and 9")


def _normalize_mtime(mtime: Optional[Union[int, float]]) -> Optional[int]:
    """Validate and normalize mtime values."""
    if mtime is None:
        return None
    if not isinstance(mtime, (int, float)):
        raise TypeError("mtime must be an int or float if provided")
    if mtime < 0:
        raise ValueError("mtime must be non-negative")
    return int(mtime)


def _validate_original_filename(
    filename: Optional[Union[str, bytes]],
) -> Optional[Union[str, bytes]]:
    """Validate optional original filename parameter."""
    if filename is None or isinstance(filename, (str, bytes)):
        return filename
    raise TypeError("original_filename must be a string or bytes if provided")


def _derive_header_filename(
    explicit: Optional[Union[str, bytes]],
    fallback: Union[str, bytes, os.PathLike, None],
) -> bytes:
    """Derive the filename stored in the gzip header."""
    candidate: Union[str, bytes, os.PathLike, None] = (
        explicit if explicit is not None else fallback
    )
    if candidate is None:
        return b""

    if isinstance(candidate, os.PathLike):
        candidate = os.fspath(candidate)

    if isinstance(candidate, bytes):
        base_bytes = os.path.basename(candidate)
        if base_bytes.endswith(b".gz"):
            base_bytes = base_bytes[:-3]
        return base_bytes

    if isinstance(candidate, str):
        base_str = os.path.basename(candidate)
        if base_str.endswith(".gz"):
            base_str = base_str[:-3]
        try:
            return base_str.encode("latin-1")
        except UnicodeEncodeError:
            return b""

    raise TypeError("original_filename must be a string or bytes if provided")


def _build_gzip_header(
    filename_bytes: bytes, mtime: Optional[int], compresslevel: int
) -> bytes:
    """Construct a gzip header matching CPython's gzip implementation."""
    header = bytearray()
    header.extend(b"\x1f\x8b")
    header.append(GZIP_METHOD_DEFLATE)
    flags = GZIP_FLAG_FNAME if filename_bytes else 0
    header.append(flags)
    seconds = int(time.time()) if mtime is None else int(mtime)
    header.extend(struct.pack("<I", seconds))

    if compresslevel == _COMPRESS_LEVEL_BEST:
        xfl = 2
    elif compresslevel == _COMPRESS_LEVEL_FAST:
        xfl = 4
    else:
        xfl = 0
    header.append(xfl)
    header.append(GZIP_OS_UNKNOWN)

    if filename_bytes:
        header.extend(filename_bytes)
        header.append(0)

    return bytes(header)


def _build_gzip_trailer(crc: int, size: int) -> bytes:
    """Construct the gzip trailer (CRC32 + uncompressed size)."""
    return struct.pack("<II", crc & 0xFFFFFFFF, size & 0xFFFFFFFF)


def _try_parse_gzip_header_mtime(data: bytes) -> Tuple[Optional[int], bool]:
    """Try parsing gzip header mtime from raw bytes.

    Returns:
        (mtime, complete)
        - mtime: Parsed mtime value when available, else None.
        - complete: True if enough bytes were available to finish parsing header.
    """
    if len(data) < 10:
        return None, False
    if data[0:2] != b"\x1f\x8b" or data[2] != GZIP_METHOD_DEFLATE:
        return None, True

    flags = data[3]
    mtime = struct.unpack("<I", data[4:8])[0]
    pos = 10

    if flags & GZIP_FLAG_FEXTRA:
        if len(data) < pos + 2:
            return None, False
        xlen = struct.unpack("<H", data[pos : pos + 2])[0]
        pos += 2 + xlen
        if len(data) < pos:
            return None, False

    if flags & GZIP_FLAG_FNAME:
        terminator = data.find(b"\x00", pos)
        if terminator == -1:
            return None, False
        pos = terminator + 1

    if flags & GZIP_FLAG_FCOMMENT:
        terminator = data.find(b"\x00", pos)
        if terminator == -1:
            return None, False
        pos = terminator + 1

    if flags & GZIP_FLAG_FHCRC:
        if len(data) < pos + 2:
            return None, False

    return mtime, True


def _parse_mode_tokens(mode: str) -> Tuple[str, bool, bool, bool]:
    """Parse a mode string into (op, saw_b, saw_t, plus) flags."""
    if not isinstance(mode, str):
        raise TypeError("mode must be a string")
    if not mode:
        raise ValueError("Mode string cannot be empty")

    op: Optional[str] = None
    saw_b = False
    saw_t = False
    plus = False

    for ch in mode:
        if ch in {"r", "w", "a", "x"}:
            if op is not None:
                raise ValueError("Mode string can only specify one of r, w, a, or x")
            op = ch
        elif ch == "b":
            if saw_b:
                raise ValueError("Mode string cannot specify 'b' more than once")
            saw_b = True
        elif ch == "t":
            if saw_t:
                raise ValueError("Mode string cannot specify 't' more than once")
            saw_t = True
        elif ch == "+":
            if plus:
                raise ValueError("Mode string cannot include '+' more than once")
            plus = True
        else:
            raise ValueError(f"Invalid mode character '{ch}'")

    if op is None:
        raise ValueError("Mode string must include one of 'r', 'w', 'a', or 'x'")
    if saw_b and saw_t:
        raise ValueError("Mode string cannot include both 'b' and 't'")

    return op, saw_b, saw_t, plus


@runtime_checkable
class WithAsyncRead(Protocol):
    """Protocol for async file-like objects that can be read."""

    async def read(self, size: int = -1) -> Union[str, bytes]: ...


@runtime_checkable
class WithAsyncWrite(Protocol):
    """Protocol for async file-like objects that can be written."""

    async def write(self, data: Union[str, bytes]) -> int: ...


@runtime_checkable
class WithAsyncReadWrite(Protocol):
    """Protocol for async file-like objects that can be read and written."""

    async def read(self, size: int = -1) -> Union[str, bytes]: ...
    async def write(self, data: Union[str, bytes]) -> int: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class _TextCookieState:
    """Internal snapshot of decoder/buffer state for tell()/seek() cookies."""

    byte_offset: int
    decoder_state: Tuple[Any, int]
    text_buffer: str
    trailing_cr: bool


__all__ = [
    "GZIP_WBITS",
    "GZIP_FLAG_FNAME",
    "GZIP_FLAG_FHCRC",
    "GZIP_FLAG_FEXTRA",
    "GZIP_FLAG_FCOMMENT",
    "GZIP_METHOD_DEFLATE",
    "GZIP_OS_UNKNOWN",
    "ZlibEngine",
    "_validate_filename",
    "_validate_chunk_size",
    "_validate_compresslevel",
    "_normalize_mtime",
    "_validate_original_filename",
    "_derive_header_filename",
    "_build_gzip_header",
    "_build_gzip_trailer",
    "_try_parse_gzip_header_mtime",
    "_parse_mode_tokens",
    "WithAsyncRead",
    "WithAsyncWrite",
    "WithAsyncReadWrite",
    "_TextCookieState",
]
