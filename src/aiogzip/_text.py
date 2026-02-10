"""Text gzip stream implementation."""

import codecs
import io
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from ._binary import AsyncGzipBinaryFile
from ._common import (
    WithAsyncReadWrite,
    _normalize_mtime,
    _parse_mode_tokens,
    _TextCookieState,
    _validate_chunk_size,
    _validate_compresslevel,
    _validate_filename,
    _validate_original_filename,
)


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
