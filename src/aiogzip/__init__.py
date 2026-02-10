"""
AsyncGzipFile - Asynchronous gzip file reader/writer with aiocsv support"""

__version__ = "1.1.0"

"""

This module provides AsyncGzipBinaryFile and AsyncGzipTextFile, async replacements
for gzip.open() with proper separation of binary and text operations.

Recommended usage patterns:

1. Basic file operations:
    from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

    # Binary mode
    async with AsyncGzipBinaryFile("data.gz", "wb") as f:
        await f.write(b"Hello, World!")

    # Text mode
    async with AsyncGzipTextFile("data.gz", "wt") as f:
        await f.write("Hello, World!")

2. CSV processing with aiocsv:
    from aiogzip import AsyncGzipTextFile
    import aiocsv

    async with AsyncGzipTextFile("data.csv.gz", "rt") as f:
        reader = aiocsv.AsyncDictReader(f)
        async for row in reader:
            print(row)

3. Interoperability with gzip.open():
    # Files are fully compatible between AsyncGzipFile and gzip.open()
    # No special handling needed for file format compatibility

Error Handling Strategy:
    This module follows a consistent exception handling pattern:

    1. Specific exceptions first: zlib.error for compression/decompression errors
    2. OSError/IOError: Re-raised as-is to preserve original I/O error information
    3. Generic Exception: Caught and wrapped in OSError with context for unexpected errors
    4. All conversions use 'from e' for proper exception chaining and debugging

    This ensures:
    - Consistent error types (OSError) for all operation failures
    - Preservation of original error information through exception chaining
    - Clear error messages indicating which operation failed
"""

import codecs
import gzip
import io
import os
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

import aiofiles

# Constants
# The wbits parameter for zlib that enables gzip format
# 31 = 16 (gzip format) + 15 (maximum window size)
GZIP_WBITS = 31

# Default chunk size for line reading in text mode (8 KB)
LINE_READ_CHUNK_SIZE = 8192

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


class AsyncGzipBinaryFile:
    """
    An asynchronous gzip file reader/writer for binary data.

    This class provides async gzip compression/decompression for binary data,
    making it a drop-in replacement for gzip.open() in binary mode.

    Features:
    - Full compatibility with gzip.open() file format
    - Binary mode only (no text encoding/decoding)
    - Async context manager support
    - Configurable chunk size for performance tuning

    Basic Usage:
        # Write binary data
        async with AsyncGzipBinaryFile("data.gz", "wb") as f:
            await f.write(b"Hello, World!")

        # Read binary data
        async with AsyncGzipBinaryFile("data.gz", "rb") as f:
            data = await f.read()  # Returns bytes

    Interoperability with gzip.open():
        # Files created by AsyncGzipBinaryFile can be read by gzip.open()
        async with AsyncGzipBinaryFile("data.gz", "wb") as f:
            await f.write(b"data")

        with gzip.open("data.gz", "rb") as f:
            data = f.read()  # Works perfectly!
    """

    __slots__ = (
        "_filename",
        "_mode",
        "_mode_op",
        "_mode_plus",
        "_writing_mode",
        "_chunk_size",
        "_compresslevel",
        "_header_mtime",
        "_header_filename_override",
        "_external_file",
        "_closefd",
        "_file_mode",
        "_file",
        "_engine",
        "_buffer",
        "_buffer_offset",
        "_is_closed",
        "_eof",
        "_owns_file",
        "_crc",
        "_input_size",
        "_position",
        "_mtime",
        "_header_probe_buffer",
    )

    DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KB
    BUFFER_COMPACTION_THRESHOLD = 64 * 1024  # Compact buffer when offset exceeds this

    def __init__(
        self,
        filename: Union[str, bytes, Path, None],
        mode: str = "rb",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        compresslevel: int = 6,
        mtime: Optional[Union[int, float]] = None,
        original_filename: Optional[Union[str, bytes]] = None,
        fileobj: Optional[WithAsyncReadWrite] = None,
        closefd: Optional[bool] = None,
    ) -> None:
        # Validate inputs using shared validation functions
        _validate_filename(filename, fileobj)
        _validate_chunk_size(chunk_size)

        # Validate mode and derive file characteristics
        mode_op, saw_b, saw_t, plus = _parse_mode_tokens(mode)
        if saw_t:
            raise ValueError("Binary mode cannot include text ('t')")
        if mode_op not in {"r", "w", "a", "x"}:
            raise ValueError(f"Invalid mode '{mode}'.")

        self._filename = filename
        self._mode = mode
        self._mode_op = mode_op
        self._mode_plus = plus
        self._writing_mode = mode_op in {"w", "a", "x"}
        if self._writing_mode:
            _validate_compresslevel(compresslevel)
        self._chunk_size = chunk_size
        self._compresslevel = compresslevel
        self._header_mtime = _normalize_mtime(mtime)
        self._header_filename_override = _validate_original_filename(original_filename)
        self._external_file = fileobj
        self._closefd = closefd if closefd is not None else fileobj is None

        # Determine the underlying file mode based on gzip mode
        file_mode_suffix = "b"
        self._file_mode = f"{mode_op}{file_mode_suffix}"
        if plus:
            self._file_mode += "+"

        self._file: Any = None
        self._engine: ZlibEngine = None
        self._buffer = bytearray()  # Use bytearray for efficient buffer growth
        self._buffer_offset: int = 0  # Offset to the start of valid data in _buffer
        self._is_closed: bool = False
        self._eof: bool = False
        self._owns_file: bool = False
        self._crc: int = 0
        self._input_size: int = 0
        self._position: int = 0
        self._mtime: Optional[int] = None
        self._header_probe_buffer = bytearray()

    async def __aenter__(self) -> "AsyncGzipBinaryFile":
        """Enter the async context manager and initialize resources."""
        if self._external_file is not None:
            self._file = self._external_file
            self._owns_file = False
        else:
            if self._filename is None:
                raise ValueError("Filename must be provided when fileobj is not given")
            self._file = await aiofiles.open(  # type: ignore
                self._filename, self._file_mode
            )
            self._owns_file = True

        # Initialize compression/decompression engine based on mode
        if self._writing_mode:
            self._engine = zlib.compressobj(
                level=self._compresslevel, wbits=-zlib.MAX_WBITS
            )
            header = _build_gzip_header(
                _derive_header_filename(self._header_filename_override, self._filename),
                self._header_mtime,
                self._compresslevel,
            )
            await self._file.write(header)
            self._crc = 0
            self._input_size = 0
        else:  # read mode
            self._engine = zlib.decompressobj(wbits=GZIP_WBITS)
            self._position = 0
            self._mtime = None
            self._header_probe_buffer.clear()

        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Exit the context manager, flushing and closing the file."""
        await self.close()

    # File API compatibility helpers
    async def tell(self) -> int:
        """Return the current uncompressed file position."""
        return self._position

    async def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        """Move to a new file position, mirroring gzip.GzipFile semantics."""
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")
        if self._writing_mode:
            if whence == os.SEEK_CUR:
                target = self._position + offset
            elif whence == os.SEEK_SET:
                target = offset
            else:
                raise ValueError("Seek from end not supported in write mode")
            if target < self._position:
                raise OSError("Negative seek in write mode")
            count = target - self._position
            if count > 0:
                zero_chunk = b"\x00" * min(1024, count)
                remaining = count
                while remaining > 0:
                    chunk = (
                        zero_chunk
                        if remaining >= len(zero_chunk)
                        else zero_chunk[:remaining]
                    )
                    await self.write(chunk)
                    remaining -= len(chunk)
            return self._position

        if whence == os.SEEK_SET:
            target = offset
        elif whence == os.SEEK_CUR:
            target = self._position + offset
        elif whence == os.SEEK_END:
            raise ValueError("Seek from end not supported in read mode")
        else:
            raise ValueError("Invalid whence value")

        if target < 0:
            raise OSError("Negative seek in read mode")

        if target < self._position:
            await self._rewind_reader()

        await self._consume_bytes(target - self._position)
        return self._position

    def raw(self) -> Any:
        """Expose the underlying file object for advanced integrations."""
        return self._file

    @property
    def name(self) -> Union[str, bytes, Path, None]:
        """Return the name of the file.

        This property provides compatibility with the standard file API.
        Returns the filename passed to the constructor, or None if the file
        was opened with a file object instead of a filename.

        Returns:
            The filename as str, bytes, or Path, or None if opened via fileobj.
        """
        return self._filename

    @property
    def closed(self) -> bool:
        """Return True when this file has been closed."""
        return self._is_closed

    @property
    def mtime(self) -> Optional[int]:
        """Return the gzip member mtime after the header has been read."""
        return self._mtime

    def fileno(self) -> int:
        """Return the underlying file descriptor number."""
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")
        fileno_method = getattr(self._file, "fileno", None)
        if fileno_method is None:
            raise io.UnsupportedOperation("fileno() not supported by underlying file")
        result = fileno_method()
        if hasattr(result, "__await__"):
            raise io.UnsupportedOperation(
                "fileno() is not awaitable in underlying file"
            )
        return int(result)

    def isatty(self) -> bool:
        """Return True if the underlying stream is interactive."""
        if self._file is None:
            return False
        isatty_method = getattr(self._file, "isatty", None)
        if not callable(isatty_method):
            return False
        result = isatty_method()
        if hasattr(result, "__await__"):
            close_method = getattr(result, "close", None)
            if callable(close_method):
                close_method()
            return False
        return bool(result)

    def detach(self) -> Any:
        """Detach is unsupported to mirror gzip.GzipFile behavior."""
        raise io.UnsupportedOperation("detach")

    def truncate(self, size: Optional[int] = None) -> int:
        """Truncation is unsupported for gzip-compressed streams."""
        raise io.UnsupportedOperation("truncate")

    async def peek(self, size: int = -1) -> bytes:
        """Return up to size bytes without advancing the read position."""
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")
        available = len(self._buffer) - self._buffer_offset
        target = size
        if target is None or target <= 0:
            target = available if available > 0 else 1
        while available < target and not self._eof:
            await self._fill_buffer()
            available = len(self._buffer) - self._buffer_offset
            if available == 0 and self._eof:
                break
        end = self._buffer_offset + min(target, available)
        return bytes(self._buffer[self._buffer_offset : end])

    async def readinto(self, b: Union[bytearray, memoryview]) -> int:
        """Read bytes directly into a pre-allocated, writable buffer."""
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")
        view = memoryview(b)
        if view.readonly:
            raise TypeError("readinto() argument must be writable")
        data = await self.read(len(view))
        view[: len(data)] = data
        return len(data)

    async def read1(self, size: int = -1) -> bytes:
        """Read up to size bytes from the buffer without looping."""
        return await self.read(size)

    async def readinto1(self, b: Union[bytearray, memoryview]) -> int:
        """Read directly into the buffer without looping."""
        return await self.readinto(b)

    async def readline(self, limit: int = -1) -> bytes:
        """Read and return one line from the binary stream."""
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")
        if limit is None:
            limit = -1
        if limit == 0:
            return b""

        chunks: List[bytes] = []
        total = 0
        while True:
            if self._buffer_offset >= len(self._buffer):
                if self._eof:
                    break
                await self._fill_buffer()
                if self._buffer_offset >= len(self._buffer) and self._eof:
                    break

            available = bytes(self._buffer[self._buffer_offset :])
            if not available:
                break

            newline_index = available.find(b"\n")
            take = len(available) if newline_index == -1 else newline_index + 1
            if limit != -1:
                take = min(take, limit - total)

            if take > 0:
                chunk = available[:take]
                chunks.append(chunk)
                self._buffer_offset += take
                self._position += take
                total += take

            if self._buffer_offset >= len(self._buffer):
                del self._buffer[:]
                self._buffer_offset = 0

            if (newline_index != -1 and take == newline_index + 1) or (
                limit != -1 and total >= limit
            ):
                break

        return b"".join(chunks)

    async def readlines(self, hint: int = -1) -> List[bytes]:
        """Read and return a list of lines from the binary stream."""
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

        lines: List[bytes] = []
        total = 0
        while True:
            line = await self.readline()
            if not line:
                break
            lines.append(line)
            total += len(line)
            if hint > 0 and total >= hint:
                break
        return lines

    async def writelines(self, lines: Iterable[bytes]) -> None:
        """Write a sequence of bytes-like lines to the binary stream."""
        if not self._writing_mode:
            raise OSError("File not open for writing")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

        for line in lines:
            await self.write(line)

    def readable(self) -> bool:
        return self._mode_op == "r"

    def writable(self) -> bool:
        return self._writing_mode

    def seekable(self) -> bool:
        return True

    async def rewind(self) -> None:
        if self._mode_op != "r":
            raise OSError("Can't rewind in write mode")
        await self.seek(0)

    async def write(self, data: Union[bytes, bytearray, memoryview]) -> int:
        """
        Compresses and writes binary data to the file.

        Args:
            data: Bytes to write

        Examples:
            async with AsyncGzipBinaryFile("file.gz", "wb") as f:
                await f.write(b"Hello, World!")  # Bytes input
        """
        if not self._writing_mode:
            raise OSError("File not open for writing")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")

        buffer = self._coerce_byteslike(data)
        self._crc = zlib.crc32(buffer, self._crc)
        self._input_size += len(buffer)
        self._position = self._input_size

        try:
            compressed = self._engine.compress(buffer)
            if compressed:
                await self._file.write(compressed)
        except zlib.error as e:
            raise OSError(f"Error compressing data: {e}") from e
        except OSError:
            # Re-raise I/O errors as-is
            raise
        except Exception as e:
            raise OSError(f"Unexpected error during compression: {e}") from e

        return len(buffer)

    @staticmethod
    def _coerce_byteslike(data: Any) -> Union[bytes, bytearray, memoryview]:
        """Accept bytes-like inputs while preserving efficient paths for bytes."""
        if isinstance(data, (bytes, bytearray)):
            return data
        if isinstance(data, memoryview):
            if not data.contiguous:
                return data.tobytes()
            if data.itemsize != 1:
                return data.cast("B")
            return data
        try:
            view = memoryview(data)
        except TypeError as exc:
            raise TypeError(
                f"write() argument must be a bytes-like object, not {type(data).__name__}"
            ) from exc
        if not view.contiguous:
            return view.tobytes()
        if view.itemsize != 1:
            return view.cast("B")
        return view

    async def read(self, size: int = -1) -> bytes:
        """
        Reads and decompresses binary data from the file.

        Args:
            size: Number of bytes to read (-1 for all remaining data)

        Returns:
            bytes

        Examples:
            async with AsyncGzipBinaryFile("file.gz", "rb") as f:
                data = await f.read()  # Returns bytes
                partial = await f.read(100)  # Returns first 100 bytes
        """
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")

        if size is None:
            size = -1
        if size < 0:
            size = -1

        # If size is -1, read all data in chunks to avoid memory issues
        if size == -1:
            # Return buffered data + read remaining (no recursion)
            chunks = []
            total_read = 0
            if self._buffer_offset < len(self._buffer):
                chunk = bytes(self._buffer[self._buffer_offset :])
                chunks.append(chunk)
                total_read += len(chunk)

            del self._buffer[:]  # Clear while retaining capacity
            self._buffer_offset = 0

            while not self._eof:
                await self._fill_buffer()
                if self._buffer:
                    chunk = bytes(self._buffer)
                    chunks.append(chunk)
                    total_read += len(chunk)
                    del self._buffer[:]  # Clear while retaining capacity

            data = b"".join(chunks)
            self._position += total_read
            return data
        else:
            # Otherwise, read until the buffer has enough data to satisfy the request.
            while (len(self._buffer) - self._buffer_offset) < size and not self._eof:
                # If buffer has too much garbage at the front, compact it
                if self._buffer_offset > self.BUFFER_COMPACTION_THRESHOLD:
                    del self._buffer[: self._buffer_offset]
                    self._buffer_offset = 0

                await self._fill_buffer()

            # Determine how much we can actually read
            available = len(self._buffer) - self._buffer_offset
            actual_read_size = min(size, available)

            data_to_return = bytes(
                self._buffer[
                    self._buffer_offset : self._buffer_offset + actual_read_size
                ]
            )
            self._buffer_offset += actual_read_size
            self._position += actual_read_size

            # If we consumed everything, reset to keep buffer clean
            if self._buffer_offset >= len(self._buffer):
                del self._buffer[:]
                self._buffer_offset = 0

            return data_to_return

    async def _fill_buffer(self) -> None:
        """Internal helper to read a compressed chunk and decompress it.

        Handles multi-member gzip archives (created by append mode) by detecting
        when one member ends and starting a new decompressor for the next member.
        """
        if self._eof or self._file is None:
            return

        try:
            compressed_chunk = await self._file.read(self._chunk_size)
        except OSError:
            # Re-raise I/O errors as-is
            raise
        except Exception as e:
            raise OSError(f"Error reading from file: {e}") from e

        if self._mtime is None and compressed_chunk:
            self._header_probe_buffer.extend(compressed_chunk)
            parsed_mtime, complete = _try_parse_gzip_header_mtime(
                bytes(self._header_probe_buffer)
            )
            if complete:
                self._mtime = parsed_mtime
                self._header_probe_buffer.clear()

        if not compressed_chunk:
            # End of file - flush any remaining data from decompressor
            self._eof = True
            try:
                remaining = self._engine.flush()
                if remaining:
                    self._buffer.extend(remaining)
            except zlib.error as e:
                raise gzip.BadGzipFile(
                    f"Error finalizing gzip decompression: {e}"
                ) from e
            return

        # Decompress the chunk
        try:
            decompressed = self._engine.decompress(compressed_chunk)
            self._buffer.extend(decompressed)

            # Handle multi-member gzip archives (created by append mode).
            # CPython's gzip reader ignores zero padding between/after members,
            # so strip NUL bytes before attempting to parse another member.
            unused = self._engine.unused_data
            while unused:
                unused = unused.lstrip(b"\x00")
                if not unused:
                    break

                self._engine = zlib.decompressobj(wbits=GZIP_WBITS)
                decompressed = self._engine.decompress(unused)
                self._buffer.extend(decompressed)
                unused = self._engine.unused_data
        except zlib.error as e:
            raise gzip.BadGzipFile(f"Error decompressing gzip data: {e}") from e
        except Exception as e:
            raise OSError(f"Unexpected error during decompression: {e}") from e

    async def _consume_bytes(self, amount: int) -> None:
        """Advance the read position by consuming bytes without returning them."""
        remaining = amount
        while remaining > 0:
            available = len(self._buffer) - self._buffer_offset
            if available <= 0:
                if self._eof:
                    break
                await self._fill_buffer()
                available = len(self._buffer) - self._buffer_offset
                if available <= 0 and self._eof:
                    break
            take = min(remaining, available)
            self._buffer_offset += take
            self._position += take
            remaining -= take
            if self._buffer_offset >= len(self._buffer):
                del self._buffer[:]
                self._buffer_offset = 0

    async def _rewind_reader(self) -> None:
        """Rewind the underlying file and reset decompression state."""
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")
        seek_method = getattr(self._file, "seek", None)
        if not callable(seek_method):
            raise OSError("Underlying file is not seekable")
        result = seek_method(0, os.SEEK_SET)
        if hasattr(result, "__await__"):
            await result
        else:
            # synchronous seek already performed
            pass
        self._engine = zlib.decompressobj(wbits=GZIP_WBITS)
        del self._buffer[:]
        self._buffer_offset = 0
        self._eof = False
        self._position = 0

    async def flush(self) -> None:
        """
        Flush any buffered compressed data to the file.

        In write/append mode, this forces any buffered compressed data to be
        written to the underlying file. Note that this does NOT write the gzip
        trailer - use close() for that.

        In read mode, this is a no-op for compatibility with the file API.

        Examples:
            async with AsyncGzipBinaryFile("file.gz", "wb") as f:
                await f.write(b"Hello")
                await f.flush()  # Ensure data is written
                await f.write(b" World")
        """
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

        if self._writing_mode and self._file is not None:
            # Flush any buffered compressed data (but not the final trailer)
            # Using Z_SYNC_FLUSH allows us to flush without ending the stream
            try:
                flushed_data = self._engine.flush(zlib.Z_SYNC_FLUSH)
                if flushed_data:
                    await self._file.write(flushed_data)

                # Also flush the underlying file if it has a flush method
                flush_method = getattr(self._file, "flush", None)
                if callable(flush_method):
                    result = flush_method()
                    if hasattr(result, "__await__"):
                        await result
            except zlib.error as e:
                raise OSError(f"Error flushing compressed data: {e}") from e
            except OSError:
                raise
            except Exception as e:
                raise OSError(f"Unexpected error during flush: {e}") from e

    async def close(self) -> None:
        """Flushes any remaining compressed data and closes the file."""
        if self._is_closed:
            return

        # Mark as closed immediately to prevent concurrent close attempts
        self._is_closed = True

        try:
            if self._writing_mode and self._file is not None:
                # Flush the compressor to write the gzip trailer
                remaining_data = self._engine.flush()
                if remaining_data:
                    await self._file.write(remaining_data)
                trailer = _build_gzip_trailer(self._crc, self._input_size)
                await self._file.write(trailer)

            if self._file is not None and (self._owns_file or self._closefd):
                # Close only if we own it or closefd=True
                close_method = getattr(self._file, "close", None)
                if callable(close_method):
                    result = close_method()
                    if hasattr(result, "__await__"):
                        await result
        except Exception:
            # If an error occurs during close, we're still closed
            # but we need to propagate the exception
            raise

    def __aiter__(self) -> "AsyncGzipBinaryFile":
        """Make AsyncGzipBinaryFile iterable over newline-delimited chunks."""
        return self

    async def __anext__(self) -> bytes:
        """Return the next line from the binary stream."""
        if self._is_closed:
            raise StopAsyncIteration
        line = await self.readline()
        if line == b"":
            raise StopAsyncIteration
        return line


class AsyncGzipTextFile:
    """
    An asynchronous gzip file reader/writer for text data.

    This class wraps AsyncGzipBinaryFile and provides text mode operations
    with proper UTF-8 handling for multi-byte characters.

    Features:
    - Full compatibility with gzip.open() file format
    - Text mode with automatic encoding/decoding
    - Proper handling of multi-byte UTF-8 characters
    - Line-by-line iteration support
    - Async context manager support

    Basic Usage:
        # Write text data
        async with AsyncGzipTextFile("data.gz", "wt") as f:
            await f.write("Hello, World!")  # String input

        # Read text data
        async with AsyncGzipTextFile("data.gz", "rt") as f:
            text = await f.read()  # Returns string

        # Line-by-line iteration
        async with AsyncGzipTextFile("data.gz", "rt") as f:
            async for line in f:
                print(line.strip())
    """

    __slots__ = (
        "_filename",
        "_mode",
        "_mode_op",
        "_mode_plus",
        "_writing_mode",
        "_chunk_size",
        "_encoding",
        "_errors",
        "_newline",
        "_compresslevel",
        "_header_mtime",
        "_header_filename_override",
        "_external_file",
        "_closefd",
        "_binary_mode",
        "_binary_file",
        "_is_closed",
        "_decoder",
        "_text_buffer",
        "_trailing_cr",
        "_line_offset",
        "_cookie_cache",
    )

    # Maximum number of entries to keep in the cookie cache for tell()/seek()
    MAX_COOKIE_CACHE_SIZE = 1000

    def __init__(
        self,
        filename: Union[str, bytes, Path, None],
        mode: str = "rt",
        chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
        encoding: Optional[str] = "utf-8",
        errors: Optional[str] = "strict",
        newline: Union[str, None] = None,
        compresslevel: int = 6,
        mtime: Optional[Union[int, float]] = None,
        original_filename: Optional[Union[str, bytes]] = None,
        fileobj: Optional[WithAsyncReadWrite] = None,
        closefd: Optional[bool] = None,
    ) -> None:
        # Validate inputs using shared validation functions
        _validate_filename(filename, fileobj)
        _validate_chunk_size(chunk_size)

        # Validate text-specific parameters
        if encoding is None:
            encoding = "utf-8"
        if not encoding:
            raise ValueError("Encoding cannot be empty")
        if errors is None:
            errors = "strict"
        if newline not in {None, "", "\n", "\r", "\r\n"}:
            raise ValueError(f"illegal newline value: {newline}")

        mode_op, saw_b, saw_t, plus = _parse_mode_tokens(mode)
        if saw_b:
            raise ValueError("Text mode cannot include binary ('b')")
        if mode_op not in {"r", "w", "a", "x"}:
            raise ValueError(f"Invalid mode '{mode}'.")

        self._filename = filename
        self._mode = mode
        self._mode_op = mode_op
        self._mode_plus = plus
        self._writing_mode = mode_op in {"w", "a", "x"}
        if self._writing_mode:
            _validate_compresslevel(compresslevel)
        self._chunk_size = chunk_size
        self._encoding = encoding
        self._errors = errors
        self._newline = newline
        self._compresslevel = compresslevel
        self._header_mtime = _normalize_mtime(mtime)
        self._header_filename_override = _validate_original_filename(original_filename)
        self._external_file = fileobj
        self._closefd = closefd if closefd is not None else fileobj is None

        # Determine the underlying binary file mode
        self._binary_mode = f"{mode_op}b"
        if plus:
            self._binary_mode += "+"

        self._binary_file: Optional[AsyncGzipBinaryFile] = None
        self._is_closed: bool = False

        # Decoder and buffer state
        self._decoder = codecs.getincrementaldecoder(self._encoding)(
            errors=self._errors
        )
        self._text_buffer: str = ""  # Central buffer for decoded text
        self._trailing_cr: bool = False  # Track if last decoded chunk ended with \r
        self._line_offset: int = 0  # Track logical character position for tell()
        self._cookie_cache: Dict[int, _TextCookieState] = {}

    async def __aenter__(self) -> "AsyncGzipTextFile":
        """Enter the async context manager and initialize resources."""
        filename = os.fspath(self._filename) if self._filename is not None else None
        self._binary_file = AsyncGzipBinaryFile(
            filename=filename,
            mode=self._binary_mode,
            chunk_size=self._chunk_size,
            compresslevel=self._compresslevel,
            mtime=self._header_mtime,
            original_filename=self._header_filename_override,
            fileobj=self._external_file,
            closefd=self._closefd,
        )
        await self._binary_file.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Exit the context manager, flushing and closing the file."""
        await self.close()

    # File API compatibility helpers
    async def tell(self) -> int:
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")
        bytes_offset = await self._binary_file.tell()
        decoder_state = self._decoder.getstate()
        pending_bytes, _ = decoder_state
        flag = 1 if pending_bytes else 0
        cookie = (bytes_offset << 1) | flag
        # Bound the cache size to prevent unbounded memory growth
        if len(self._cookie_cache) >= self.MAX_COOKIE_CACHE_SIZE:
            # Remove oldest entries (first half of the cache)
            keys_to_remove = list(self._cookie_cache.keys())[
                : self.MAX_COOKIE_CACHE_SIZE // 2
            ]
            for key in keys_to_remove:
                del self._cookie_cache[key]
        self._cookie_cache[cookie] = _TextCookieState(
            byte_offset=bytes_offset,
            decoder_state=decoder_state,
            text_buffer=self._text_buffer,
            trailing_cr=self._trailing_cr,
        )
        return cookie

    async def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")
        if whence == os.SEEK_CUR:
            if offset != 0:
                raise io.UnsupportedOperation("can't do nonzero cur-relative seeks")
            return await self.tell()
        if whence == os.SEEK_END:
            if offset != 0:
                raise io.UnsupportedOperation("can't do nonzero end-relative seeks")
            await self.read()
            return await self.tell()
        if whence != os.SEEK_SET:
            raise ValueError("Invalid whence value")

        cached_state = self._cookie_cache.get(offset)
        if cached_state is not None:
            await self._binary_file.seek(cached_state.byte_offset)
            self._decoder.setstate(cached_state.decoder_state)
            self._text_buffer = cached_state.text_buffer
            self._trailing_cr = cached_state.trailing_cr
            return offset

        if offset != 0:
            raise OSError(
                "Cannot seek to uncached text cookie; call tell() near the target position"
            )

        byte_offset = offset >> 1
        await self._binary_file.seek(byte_offset)
        self._decoder.reset()
        self._text_buffer = ""
        self._trailing_cr = False
        return offset

    def fileno(self) -> int:
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")
        return self._binary_file.fileno()

    def raw(self) -> Any:
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")
        return self._binary_file.raw()

    @property
    def name(self) -> Union[str, bytes, Path, None]:
        """Return the name of the file.

        This property provides compatibility with the standard file API.
        Returns the filename passed to the constructor, or None if the file
        was opened with a file object instead of a filename.

        Returns:
            The filename as str, bytes, or Path, or None if opened via fileobj.
        """
        return self._filename

    @property
    def closed(self) -> bool:
        """Return True when this file has been closed."""
        return self._is_closed

    @property
    def encoding(self) -> str:
        """Return the configured text encoding."""
        return self._encoding

    @property
    def errors(self) -> str:
        """Return the configured text error handler."""
        return self._errors

    @property
    def newlines(self) -> Optional[str]:
        """Return newline handling configuration."""
        return self._newline

    @property
    def buffer(self) -> AsyncGzipBinaryFile:
        """Expose the underlying binary gzip stream."""
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")
        return self._binary_file

    def readable(self) -> bool:
        return self._mode_op == "r"

    def writable(self) -> bool:
        return self._writing_mode

    def seekable(self) -> bool:
        return True

    async def write(self, data: str) -> int:
        """
        Encodes and writes text data to the file.

        Args:
            data: String to write

        Examples:
            async with AsyncGzipTextFile("file.gz", "wt") as f:
                await f.write("Hello, World!")  # String input
        """
        if not self._writing_mode:
            raise OSError("File not open for writing")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")

        if not isinstance(data, str):
            raise TypeError("write() argument must be str, not bytes")

        # Translate newlines according to Python's text I/O semantics
        text_to_encode = data
        if self._newline is None:
            # Translate \n to os.linesep on write
            text_to_encode = text_to_encode.replace("\n", os.linesep)
        elif self._newline in ("\n", "\r", "\r\n"):
            text_to_encode = text_to_encode.replace("\n", self._newline)
        else:
            # newline == '' means no translation; any other value treat as no translation
            pass

        # Encode string to bytes
        encoded_data = text_to_encode.encode(self._encoding, errors=self._errors)
        await self._binary_file.write(encoded_data)
        return len(data)

    async def _read_chunk_and_decode(self) -> bool:
        """Read a chunk of binary data, decode it, and append to text buffer.

        Returns:
            bool: True if data was added to the buffer, False if EOF was reached.
        """
        if self._binary_file is None:
            return False

        if self._binary_file._eof:
            return False

        raw_chunk = await self._binary_file.read(self._chunk_size)
        if not raw_chunk:
            # EOF: flush the decoder
            final_decoded = self._decoder.decode(b"", final=True)
            if final_decoded:
                self._text_buffer += self._apply_newline_decoding(final_decoded)
                return True
            return False

        # Decode incrementally (buffering incomplete bytes internally)
        decoded_chunk = self._decoder.decode(raw_chunk, final=False)

        if decoded_chunk:
            self._text_buffer += self._apply_newline_decoding(decoded_chunk)
            return True

        return True  # We read bytes but produced no text (incomplete multibyte char), still not EOF

    async def read(self, size: int = -1) -> str:
        """
        Reads and decodes text data from the file.

        Args:
            size: Number of characters to read (-1 for all remaining data)

        Returns:
            str

        Examples:
            async with AsyncGzipTextFile("file.gz", "rt") as f:
                text = await f.read()  # Returns string
                partial = await f.read(100)  # Returns first 100 chars as string
        """
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")

        if size is None:
            size = -1
        if size < 0:
            size = -1

        # Handle read(0) - should return empty string without draining buffer
        if size == 0:
            return ""

        if size == -1:
            # Read all remaining data
            # We use a list to accumulate chunks for performance
            chunks = [self._text_buffer]
            self._text_buffer = ""

            while True:
                has_more = await self._read_chunk_and_decode()
                if not has_more:
                    break
                if self._text_buffer:
                    chunks.append(self._text_buffer)
                    self._text_buffer = ""

            return "".join(chunks)
        else:
            # Check if we have enough data in our text buffer
            while len(self._text_buffer) < size:
                has_more = await self._read_chunk_and_decode()
                if not has_more:
                    break

            # Return the requested number of characters
            result = self._text_buffer[:size]
            self._text_buffer = self._text_buffer[size:]
            return result

    def _at_stream_eof(self) -> bool:
        """Return True if the underlying binary file has reached EOF."""
        if self._binary_file is None:
            return True
        return bool(self._binary_file._eof)

    def _get_line_terminator_pos(self, text: str) -> Tuple[int, int]:
        """Find position of line terminator in text based on newline mode.

        Returns:
            Tuple of (position, length) where position is index of first terminator
            character and length is the terminator length (1 or 2).
            Returns (-1, 0) if no terminator found.
        """
        if self._newline is None or self._newline == "":
            # Universal newlines: accept \n, \r, or \r\n
            pos_n = text.find("\n")
            pos_r = text.find("\r")

            if pos_n == -1 and pos_r == -1:
                return (-1, 0)

            candidate = (-1, 0)

            if pos_n != -1:
                candidate = (pos_n, 1)

            if pos_r != -1:
                cr_length = (
                    2 if pos_r + 1 < len(text) and text[pos_r + 1] == "\n" else 1
                )
                cr_is_trailing = pos_r + 1 == len(text)
                should_wait_for_lf = (
                    self._newline == ""
                    and cr_length == 1
                    and cr_is_trailing
                    and not self._at_stream_eof()
                )
                if not should_wait_for_lf:
                    cr_candidate = (pos_r, cr_length)
                    if candidate[0] == -1 or pos_r < candidate[0]:
                        candidate = cr_candidate

            return candidate
        elif self._newline == "\n":
            pos = text.find("\n")
            return (pos, 1) if pos != -1 else (-1, 0)
        elif self._newline == "\r":
            pos = text.find("\r")
            return (pos, 1) if pos != -1 else (-1, 0)
        elif self._newline == "\r\n":
            pos = text.find("\r\n")
            return (pos, 2) if pos != -1 else (-1, 0)
        else:
            # Fallback to \n
            pos = text.find("\n")
            return (pos, 1) if pos != -1 else (-1, 0)

    def _apply_newline_decoding(self, text: str) -> str:
        """Apply newline decoding/translation semantics similar to TextIOWrapper.

        - newline is None: universal newline translation on input -> normalize CRLF/CR to \n
        - newline is '': no translation
        - newline is one of '\n', '\r', '\r\n': no translation on input

        Handles CRLF sequences split across chunk boundaries by tracking trailing \r.
        """
        if not text:
            return text
        if self._newline is None:
            # Universal newline translation
            # Handle trailing \r from previous chunk
            if self._trailing_cr and text and text[0] == "\n":
                # Previous chunk ended with \r, this starts with \n - it's a CRLF
                # Remove the \n since the \r was already converted to \n in previous chunk
                text = text[1:]

            # Reset trailing CR flag
            self._trailing_cr = False

            # Check if this chunk ends with \r (before we do replacements)
            # This \r might be followed by \n in the next chunk
            if text and text[-1] == "\r":
                self._trailing_cr = True

            # Convert CRLF to LF, then remaining CR to LF
            text = text.replace("\r\n", "\n")
            text = text.replace("\r", "\n")

            return text
        # newline '' or explicit newline: do not translate on input
        return text

    def __aiter__(self) -> "AsyncGzipTextFile":
        """Make AsyncGzipTextFile iterable for line-by-line reading."""
        return self

    async def __anext__(self) -> str:
        """Return the next line from the file."""
        if self._is_closed:
            raise StopAsyncIteration

        # Read until we get a complete line
        while True:
            # Try to get a line from our buffer using newline-aware search
            pos, length = self._get_line_terminator_pos(self._text_buffer)
            if pos != -1:
                # Found a line terminator
                line = self._text_buffer[: pos + length]
                self._text_buffer = self._text_buffer[pos + length :]
                return line

            # Read more data
            has_more = await self._read_chunk_and_decode()
            if not has_more:
                # EOF
                if self._text_buffer:
                    result = self._text_buffer
                    self._text_buffer = ""  # Clear buffer
                    return result  # Last line without newline
                else:
                    raise StopAsyncIteration

    async def readline(self, limit: int = -1) -> str:
        """
        Read and return one line from the file.

        A line is defined as text ending with a newline character ('\\n').
        If the file ends without a newline, the last line is returned without one.

        Args:
            limit: Maximum number of characters to return. Stops at newline,
                EOF, or once the limit is reached (matching TextIOBase semantics).

        Returns:
            str: The next line from the file, including the newline if present.
                 Returns empty string at EOF.

        Examples:
            async with AsyncGzipTextFile("file.gz", "rt") as f:
                line = await f.readline()  # Read one line
                while line:
                    print(line.rstrip())
                    line = await f.readline()
        """
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._mode_op != "r":
            raise OSError("File not open for reading")

        if limit is None:
            limit = -1
        if limit == 0:
            return ""

        # Try to get a line from our buffer using newline-aware search
        while True:
            pos, length = self._get_line_terminator_pos(self._text_buffer)

            if pos != -1:
                # Found a line terminator - extract the line
                end = pos + length
                line = self._text_buffer[:end]
                self._text_buffer = self._text_buffer[end:]
                # Apply limit if specified
                if limit != -1 and len(line) > limit:
                    self._text_buffer = line[limit:] + self._text_buffer
                    line = line[:limit]
                return line

            # No terminator found - check if we have enough data for limit
            if limit != -1 and len(self._text_buffer) >= limit:
                line = self._text_buffer[:limit]
                self._text_buffer = self._text_buffer[limit:]
                return line

            # Need more data - try to read
            has_more = await self._read_chunk_and_decode()
            if not has_more:
                # EOF reached - return whatever is in the buffer
                if not self._text_buffer:
                    return ""
                line = self._text_buffer
                self._text_buffer = ""
                # Apply limit if specified
                if limit != -1 and len(line) > limit:
                    self._text_buffer = line[limit:] + self._text_buffer
                    line = line[:limit]
                return line
            # Loop continues to search for terminator in newly read data

    async def readlines(self, hint: int = -1) -> List[str]:
        """
        Read and return a list of lines from the file.

        Args:
            hint: Optional size hint. If given and greater than 0, lines totaling
                approximately hint bytes are read (counted before decoding).
                The actual number of bytes read may be more or less than hint.
                If hint is -1 or not given, all remaining lines are read.

        Returns:
            List[str]: A list of lines from the file, each including any trailing
            newline character.

        Examples:
            async with AsyncGzipTextFile("file.gz", "rt") as f:
                lines = await f.readlines()  # Read all lines
                for line in lines:
                    print(line.rstrip())

            # With size hint
            async with AsyncGzipTextFile("file.gz", "rt") as f:
                lines = await f.readlines(1024)  # Read ~1KB of lines
        """
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._mode_op != "r":
            raise OSError("File not open for reading")

        lines: List[str] = []
        total_size = 0

        while True:
            line = await self.readline()
            if not line:
                break
            lines.append(line)
            total_size += len(line)
            if hint > 0 and total_size >= hint:
                break

        return lines

    async def writelines(self, lines: Iterable[str]) -> None:
        """
        Write a list of lines to the file.

        Note that newlines are not added automatically; each string in the
        iterable should include its own line terminator if desired.

        Args:
            lines: An iterable of strings to write.

        Examples:
            async with AsyncGzipTextFile("file.gz", "wt") as f:
                await f.writelines(["line1\\n", "line2\\n", "line3\\n"])

            # From a generator
            async with AsyncGzipTextFile("file.gz", "wt") as f:
                await f.writelines(f"{i}\\n" for i in range(100))
        """
        if not self._writing_mode:
            raise OSError("File not open for writing")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

        for line in lines:
            await self.write(line)

    async def flush(self) -> None:
        """
        Flush any buffered data to the file.

        In write/append mode, this forces any buffered text to be encoded
        and written to the underlying binary file.

        In read mode, this is a no-op for compatibility with the file API.

        Examples:
            async with AsyncGzipTextFile("file.gz", "wt") as f:
                await f.write("Hello")
                await f.flush()  # Ensure data is written
                await f.write(" World")
        """
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

        if self._binary_file is not None:
            await self._binary_file.flush()

    async def close(self) -> None:
        """Closes the file."""
        if self._is_closed:
            return

        # Mark as closed immediately to prevent concurrent close attempts
        self._is_closed = True
        self._cookie_cache.clear()

        try:
            if not self._writing_mode:
                # Flush the decoder to ensure all buffered bytes are processed
                # This is important for handling incomplete multi-byte characters at EOF
                self._decoder.decode(b"", final=True)

            if self._binary_file is not None:
                await self._binary_file.close()
        except Exception:
            # If an error occurs during close, we're still closed
            # but we need to propagate the exception
            raise


def AsyncGzipFile(
    filename: Union[str, bytes, Path, None], mode: str = "rb", **kwargs: Any
) -> Union[AsyncGzipBinaryFile, AsyncGzipTextFile]:
    """
    Factory function that returns the appropriate AsyncGzip class based on mode.

    This provides backward compatibility with the original AsyncGzipFile interface
    while using the new separated binary and text file classes.

    Args:
        filename: Path to the file
        mode: File mode ('rb', 'wb', 'rt', 'wt', etc.)
        **kwargs: Additional arguments passed to the appropriate class

    Returns:
        AsyncGzipBinaryFile for binary modes ('rb', 'wb', 'ab')
        AsyncGzipTextFile for text modes ('rt', 'wt', 'at')
    """
    if not isinstance(mode, str):
        raise TypeError("mode must be a string")
    text_mode = "t" in mode
    if not text_mode:
        for arg_name in ("encoding", "errors", "newline"):
            if kwargs.get(arg_name) is not None:
                raise ValueError(
                    f"Argument '{arg_name}' not supported in binary mode"
                )
        kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in {"encoding", "errors", "newline"}
        }
    if text_mode:
        return AsyncGzipTextFile(filename, mode, **kwargs)
    else:
        return AsyncGzipBinaryFile(filename, mode, **kwargs)
