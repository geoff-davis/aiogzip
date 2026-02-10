"""Binary gzip stream implementation."""

import gzip
import io
import os
import zlib
from pathlib import Path
from typing import Any, Iterable, List, Optional, Union

import aiofiles

from ._common import (
    GZIP_WBITS,
    WithAsyncReadWrite,
    ZlibEngine,
    _build_gzip_header,
    _build_gzip_trailer,
    _derive_header_filename,
    _normalize_mtime,
    _parse_mode_tokens,
    _try_parse_gzip_header_mtime,
    _validate_chunk_size,
    _validate_compresslevel,
    _validate_filename,
    _validate_original_filename,
)


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
                if self._buffer_offset >= len(self._buffer):
                    continue

            start = self._buffer_offset
            end = len(self._buffer)
            newline_index = self._buffer.find(b"\n", start)
            if newline_index != -1:
                end = newline_index + 1
            if limit != -1:
                remaining = limit - total
                if remaining <= 0:
                    break
                end = min(end, start + remaining)

            if end <= start:
                break

            chunk = bytes(self._buffer[start:end])
            chunks.append(chunk)
            consumed = end - start
            self._buffer_offset = end
            self._position += consumed
            total += consumed

            if self._buffer_offset >= len(self._buffer):
                del self._buffer[:]
                self._buffer_offset = 0

            if (newline_index != -1 and end == newline_index + 1) or (
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
