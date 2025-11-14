"""
AsyncGzipFile - Asynchronous gzip file reader/writer with aiocsv support"""

__version__ = "0.4"

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

import os
import zlib
from pathlib import Path
from typing import Any, Protocol, Union, Tuple, Optional

import aiofiles


# Constants
# The wbits parameter for zlib that enables gzip format
# 31 = 16 (gzip format) + 15 (maximum window size)
GZIP_WBITS = 31

# Maximum allowed chunk size for reading/writing (10 MB)
MAX_CHUNK_SIZE = 10 * 1024 * 1024

# Default chunk size for line reading in text mode (8 KB)
LINE_READ_CHUNK_SIZE = 8192

# Type alias for zlib compression/decompression objects
# These are the return types of zlib.compressobj() and zlib.decompressobj()
# Using Any because the actual types (zlib.Compress/Decompress) aren't directly accessible
ZlibEngine = Any


# Validation helper functions
def _validate_filename(filename: Union[str, bytes, Path, None], fileobj) -> None:
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
    if chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(
            f"Chunk size too large (max {MAX_CHUNK_SIZE // (1024 * 1024)}MB)"
        )


def _validate_compresslevel(compresslevel: int) -> None:
    """Validate compresslevel parameter.

    Args:
        compresslevel: The compression level to validate

    Raises:
        ValueError: If compression level is not between 0 and 9
    """
    if not (0 <= compresslevel <= 9):
        raise ValueError("Compression level must be between 0 and 9")


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


class WithAsyncRead(Protocol):
    """Protocol for async file-like objects that can be read."""

    async def read(self, size: int = -1) -> Union[str, bytes]: ...


class WithAsyncWrite(Protocol):
    """Protocol for async file-like objects that can be written."""

    async def write(self, data: Union[str, bytes]) -> int: ...


class WithAsyncReadWrite(Protocol):
    """Protocol for async file-like objects that can be read and written."""

    async def read(self, size: int = -1) -> Union[str, bytes]: ...
    async def write(self, data: Union[str, bytes]) -> int: ...


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

    DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KB

    def __init__(
        self,
        filename: Union[str, bytes, Path, None],
        mode: str = "rb",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        compresslevel: int = 6,
        fileobj: Optional[WithAsyncReadWrite] = None,
        closefd: bool = True,
    ) -> None:
        # Validate inputs using shared validation functions
        _validate_filename(filename, fileobj)
        _validate_chunk_size(chunk_size)
        _validate_compresslevel(compresslevel)

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
        self._chunk_size = chunk_size
        self._compresslevel = compresslevel
        self._external_file = fileobj
        self._closefd = closefd

        # Determine the underlying file mode based on gzip mode
        file_mode_suffix = "b"
        self._file_mode = f"{mode_op}{file_mode_suffix}"
        if plus:
            self._file_mode += "+"

        self._file = None
        self._engine: ZlibEngine = None
        self._buffer = bytearray()  # Use bytearray for efficient buffer growth
        self._is_closed: bool = False
        self._eof: bool = False
        self._owns_file: bool = False

    async def __aenter__(self) -> "AsyncGzipBinaryFile":
        """Enter the async context manager and initialize resources."""
        if self._external_file is not None:
            self._file = self._external_file
            self._owns_file = False
        else:
            if self._filename is None:
                raise ValueError("Filename must be provided when fileobj is not given")
            self._file = await aiofiles.open(self._filename, self._file_mode)
            self._owns_file = True

        # Initialize compression/decompression engine based on mode
        if self._writing_mode:
            self._engine = zlib.compressobj(level=self._compresslevel, wbits=GZIP_WBITS)
        else:  # read mode
            self._engine = zlib.decompressobj(wbits=GZIP_WBITS)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager, flushing and closing the file."""
        await self.close()

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
            raise IOError("File not open for writing")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Use async context manager.")

        buffer = self._coerce_byteslike(data)

        try:
            compressed = self._engine.compress(buffer)
            if compressed:
                await self._file.write(compressed)
        except zlib.error as e:
            raise OSError(f"Error compressing data: {e}") from e
        except (OSError, IOError):
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
            raise IOError("File not open for reading")
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
            chunks = [bytes(self._buffer)] if self._buffer else []
            del self._buffer[:]  # Clear while retaining capacity

            while not self._eof:
                await self._fill_buffer()
                if self._buffer:
                    chunks.append(bytes(self._buffer))
                    del self._buffer[:]  # Clear while retaining capacity

            return b"".join(chunks)
        else:
            # Otherwise, read until the buffer has enough data to satisfy the request.
            while len(self._buffer) < size and not self._eof:
                await self._fill_buffer()

            data_to_return = bytes(self._buffer[:size])
            del self._buffer[:size]  # More efficient than slicing for bytearray

        return data_to_return

    async def _fill_buffer(self):
        """Internal helper to read a compressed chunk and decompress it.

        Handles multi-member gzip archives (created by append mode) by detecting
        when one member ends and starting a new decompressor for the next member.
        """
        if self._eof or self._file is None:
            return

        try:
            compressed_chunk = await self._file.read(self._chunk_size)
        except (OSError, IOError):
            # Re-raise I/O errors as-is
            raise
        except Exception as e:
            raise OSError(f"Error reading from file: {e}") from e

        if not compressed_chunk:
            # End of file - flush any remaining data from decompressor
            self._eof = True
            try:
                remaining = self._engine.flush()
                if remaining:
                    self._buffer.extend(remaining)
            except zlib.error as e:
                raise OSError(f"Error finalizing gzip decompression: {e}") from e
            return

        # Decompress the chunk
        try:
            decompressed = self._engine.decompress(compressed_chunk)
            self._buffer.extend(decompressed)

            # Handle multi-member gzip archives (created by append mode)
            # Loop to handle multiple members in the unused data
            while self._engine.unused_data:
                # Start a new decompressor for the next member
                unused = self._engine.unused_data
                self._engine = zlib.decompressobj(wbits=GZIP_WBITS)
                # Decompress the unused data with the new decompressor
                if unused:
                    decompressed = self._engine.decompress(unused)
                    self._buffer.extend(decompressed)
        except zlib.error as e:
            raise OSError(f"Error decompressing gzip data: {e}") from e
        except Exception as e:
            raise OSError(f"Unexpected error during decompression: {e}") from e

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
            except (OSError, IOError):
                raise
            except Exception as e:
                raise OSError(f"Unexpected error during flush: {e}") from e

    async def close(self):
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

    def __aiter__(self):
        """Raise error for binary file iteration."""
        raise TypeError("AsyncGzipBinaryFile can only be iterated in text mode")


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

    def __init__(
        self,
        filename: Union[str, bytes, Path, None],
        mode: str = "rt",
        chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
        encoding: str = "utf-8",
        errors: str = "strict",
        newline: Union[str, None] = None,
        compresslevel: int = 6,
        fileobj: Optional[WithAsyncReadWrite] = None,
        closefd: bool = True,
    ) -> None:
        # Validate inputs using shared validation functions
        _validate_filename(filename, fileobj)
        _validate_chunk_size(chunk_size)
        _validate_compresslevel(compresslevel)

        # Validate text-specific parameters
        if not encoding:
            raise ValueError("Encoding cannot be empty")
        if errors is None:
            raise ValueError("Errors cannot be None")

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
        self._chunk_size = chunk_size
        self._encoding = encoding
        self._errors = errors
        self._newline = newline
        self._compresslevel = compresslevel
        self._external_file = fileobj
        self._closefd = closefd

        # Determine the underlying binary file mode
        self._binary_mode = f"{mode_op}b"
        if plus:
            self._binary_mode += "+"

        self._binary_file: Optional[AsyncGzipBinaryFile] = None
        self._text_buffer: str = ""
        self._is_closed: bool = False
        self._pending_bytes: bytes = b""  # Buffer for incomplete multi-byte sequences
        self._text_data: str = (
            ""  # Buffer for decoded text data that hasn't been returned yet
        )
        self._line_buffer: str = ""  # Initialize line buffer here for efficiency
        self._max_incomplete_bytes = self._determine_max_incomplete_bytes()
        self._trailing_cr: bool = False  # Track if last decoded chunk ended with \r

    def _determine_max_incomplete_bytes(self) -> int:
        """
        Determine the maximum number of bytes an incomplete character sequence
        can have for the current encoding. This is calculated once at init time
        for efficiency.

        Returns:
            Maximum bytes to check for incomplete sequences at buffer boundaries
        """
        encoding_lower = self._encoding.lower().replace("-", "").replace("_", "")
        if encoding_lower in ("utf8", "utf8"):
            return 4  # UTF-8: max 4 bytes per character
        elif encoding_lower.startswith("utf16") or encoding_lower.startswith("utf32"):
            return 4  # UTF-16/32: max 4 bytes
        elif encoding_lower in ("ascii", "latin1", "iso88591"):
            return 1  # Single-byte encodings
        else:
            # For unknown encodings, use a safe fallback
            return 8

    async def __aenter__(self):
        """Enter the async context manager and initialize resources."""
        filename = os.fspath(self._filename) if self._filename is not None else None
        self._binary_file = AsyncGzipBinaryFile(
            filename,
            self._binary_mode,
            self._chunk_size,
            self._compresslevel,
            fileobj=self._external_file,
            closefd=self._closefd,
        )  # pyrefly: ignore
        await self._binary_file.__aenter__()  # pyrefly: ignore
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager, flushing and closing the file."""
        await self.close()

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
            raise IOError("File not open for writing")
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
            raise IOError("File not open for reading")
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
            # Read all remaining data (including any buffered text)
            raw_data: bytes = await self._binary_file.read(-1)
            # Combine with any pending bytes
            all_data = self._pending_bytes + raw_data
            self._pending_bytes = b""  # pyrefly: ignore
            decoded = self._safe_decode(all_data)
            decoded = self._apply_newline_decoding(decoded)
            # Combine buffered text with newly decoded data
            result = self._text_data + decoded
            self._text_data = ""  # pyrefly: ignore
            return result
        else:
            # Check if we have enough data in our text buffer
            if len(self._text_data) >= size:
                result = self._text_data[:size]
                self._text_data = self._text_data[size:]
                return result

            # Read more data if needed
            while len(self._text_data) < size and not self._binary_file._eof:
                # Read a chunk of bytes (estimate bytes needed, UTF-8 can be up to 4 bytes per char)
                chars_needed = size - len(self._text_data)
                bytes_estimate = chars_needed * 4
                chunk_size = max(4096, min(bytes_estimate, 64 * 1024))
                raw_chunk: bytes = await self._binary_file.read(chunk_size)

                if not raw_chunk:
                    break

                # Combine with any pending bytes
                all_data = self._pending_bytes + raw_chunk
                self._pending_bytes = b""  # pyrefly: ignore

                # Decode the chunk safely
                decoded_chunk, remaining_bytes = self._safe_decode_with_remainder(
                    all_data
                )
                self._pending_bytes = remaining_bytes
                self._text_data += self._apply_newline_decoding(decoded_chunk)

            # Return the requested number of characters
            result = self._text_data[:size] if size > 0 else self._text_data
            self._text_data = (
                self._text_data[size:] if size > 0 else ""  # pyrefly: ignore
            )  # pyrefly: ignore
            return result

    def _safe_decode(self, data: bytes) -> str:
        """
        Safely decode bytes to string, handling multi-byte UTF-8 characters
        that might be split across buffer boundaries.
        """
        if not data:
            return ""

        # For read(-1), we are at logical EOF for this read operation.
        # Defer to the configured error policy (default: strict).
        return data.decode(self._encoding, errors=self._errors)

    def _safe_decode_with_remainder(self, data: bytes) -> Tuple[str, bytes]:
        """
        Safely decode bytes to string, handling multi-byte characters
        that might be split across buffer boundaries. Returns both the decoded
        string and any remaining bytes that couldn't be decoded.
        """
        if not data:
            return "", b""

        # First, try a strict decode to see if the buffer is fully decodable.
        try:
            return data.decode(self._encoding), b""
        except UnicodeDecodeError as strict_err:
            # Attempt to detect an incomplete multi-byte sequence at the end
            # and buffer it for the next read.
            max_check = min(self._max_incomplete_bytes, len(data))
            for i in range(1, max_check + 1):
                try:
                    decoded_prefix = data[:-i].decode(self._encoding)
                    remaining_suffix = data[-i:]
                    return decoded_prefix, remaining_suffix
                except UnicodeDecodeError:
                    continue

            # If not a boundary issue, honor the configured errors policy.
            if self._errors == "strict":
                raise strict_err
            # Non-strict: decode with the provided policy and do not carry remainder
            return data.decode(self._encoding, errors=self._errors), b""

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
                cr_length = 2 if pos_r + 1 < len(text) and text[pos_r + 1] == "\n" else 1
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

    def __aiter__(self):
        """Make AsyncGzipTextFile iterable for line-by-line reading."""
        return self

    async def __anext__(self):
        """Return the next line from the file."""
        if self._is_closed:
            raise StopAsyncIteration

        # Read until we get a complete line
        while True:
            # Try to get a line from our buffer using newline-aware search
            pos, length = self._get_line_terminator_pos(self._line_buffer)
            if pos != -1:
                # Found a line terminator
                line = self._line_buffer[: pos + length]
                self._line_buffer = self._line_buffer[pos + length :]
                return line

            # Read more data
            chunk: str = await self.read(LINE_READ_CHUNK_SIZE)
            if not chunk:  # EOF
                if self._line_buffer:
                    result = self._line_buffer
                    self._line_buffer = ""  # Clear buffer
                    return result  # Last line without newline
                else:
                    raise StopAsyncIteration

            self._line_buffer += chunk

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
            raise IOError("File not open for reading")

        if limit is None:
            limit = -1
        if limit == 0:
            return ""

        # Try to get a line from our buffer using newline-aware search
        while True:
            pos, length = self._get_line_terminator_pos(self._line_buffer)
            if pos != -1:
                # Found a line terminator
                end = pos + length
                line = self._line_buffer[:end]
                self._line_buffer = self._line_buffer[end:]
            elif limit != -1 and len(self._line_buffer) >= limit:
                line = self._line_buffer[:limit]
                self._line_buffer = self._line_buffer[limit:]
                return line
            else:
                # Read more data
                chunk: str = await self.read(LINE_READ_CHUNK_SIZE)
                if not chunk:  # EOF
                    if not self._line_buffer:
                        return ""  # EOF with empty buffer
                    line = self._line_buffer
                    self._line_buffer = ""
                else:
                    self._line_buffer += chunk
                    continue

            if limit != -1 and len(line) > limit:
                # Preserve leftover characters (including newline) for the next call
                self._line_buffer = line[limit:] + self._line_buffer
                line = line[:limit]
            return line

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

    async def close(self):
        """Closes the file."""
        if self._is_closed:
            return

        # Mark as closed immediately to prevent concurrent close attempts
        self._is_closed = True

        try:
            if self._binary_file is not None:
                await self._binary_file.close()
        except Exception:
            # If an error occurs during close, we're still closed
            # but we need to propagate the exception
            raise


def AsyncGzipFile(filename, mode="rb", **kwargs):
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
    if "t" in mode:
        return AsyncGzipTextFile(filename, mode, **kwargs)
    else:
        return AsyncGzipBinaryFile(filename, mode, **kwargs)
