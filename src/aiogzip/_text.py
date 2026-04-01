"""Text gzip stream implementation."""

import codecs
import io
import os
import secrets
import struct
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple, Union

from ._binary import AsyncGzipBinaryFile
from ._common import (
    WithAsyncReadWrite,
    _normalize_mtime,
    _parse_mode_tokens,
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
        "_text_buffer_offset",
        "_trailing_cr",
        "_seen_newline_types",
        "_cookie_nonce",
        "_buffer_origin_offset",
        "_buffer_origin_decoder_state",
        "_buffer_origin_trailing_cr",
        "_buffer_origin_seen_newline_types",
        "_universal_newlines",
    )

    _SEEN_CR = 1
    _SEEN_LF = 2
    _SEEN_CRLF = 4
    _COOKIE_VERSION = 1
    _COOKIE_HEADER = struct.Struct(">BQQQiBBI")
    _TEXT_COMPACTION_THRESHOLD = 16384  # Compact text buffer when offset exceeds 16KB

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
        self._text_buffer: str = ""  # Backing store for buffered decoded text
        self._text_buffer_offset: int = 0  # Start of unread text within _text_buffer
        self._trailing_cr: bool = False  # Track if last decoded chunk ended with \r
        self._seen_newline_types: int = 0
        self._cookie_nonce: int = secrets.randbits(64)
        initial_decoder_state = self._decoder.getstate()
        self._buffer_origin_offset: int = 0
        self._buffer_origin_decoder_state: Tuple[Any, int] = initial_decoder_state
        self._buffer_origin_trailing_cr: bool = False
        self._buffer_origin_seen_newline_types: int = 0
        self._universal_newlines: bool = newline in {None, ""}

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
        try:
            await self._binary_file.__aenter__()
        except Exception:
            try:
                await self._binary_file.close()
            except Exception:
                pass
            self._binary_file = None
            raise
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
        decoder_state = self._decoder.getstate()
        if self._can_use_plain_position(decoder_state):
            return self._binary_file._position

        if self._buffered_text_len() > 0:
            origin_offset = self._buffer_origin_offset
            decoder_state = self._buffer_origin_decoder_state
            trailing_cr = self._buffer_origin_trailing_cr
            seen_newlines = self._buffer_origin_seen_newline_types
            chars_to_skip = self._text_buffer_offset
        else:
            origin_offset = self._binary_file._position
            decoder_state = self._decoder.getstate()
            trailing_cr = self._trailing_cr
            seen_newlines = self._seen_newline_types
            chars_to_skip = 0

        return self._encode_cookie(
            origin_offset=origin_offset,
            decoder_state=decoder_state,
            trailing_cr=trailing_cr,
            seen_newlines=seen_newlines,
            chars_to_skip=chars_to_skip,
        )

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

        if offset != 0:
            if offset >= 0:
                await self._seek_to_plain_position(offset)
                return offset

            (
                origin_offset,
                decoder_state,
                trailing_cr,
                seen_newlines,
                chars_to_skip,
            ) = self._decode_cookie(offset)
            await self._binary_file.seek(origin_offset)
            self._decoder.setstate(decoder_state)
            self._trailing_cr = trailing_cr
            self._seen_newline_types = seen_newlines
            self._set_buffer("")
            self._set_buffer_origin(
                origin_offset=origin_offset,
                decoder_state=decoder_state,
                trailing_cr=trailing_cr,
                seen_newlines=seen_newlines,
            )
            await self._replay_characters(chars_to_skip, strict=True)
            return offset

        await self._reset_to_start()
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
        Returns the filename passed to the constructor, or falls back to the
        underlying file object's ``name`` attribute when available.

        Returns:
            The filename as str, bytes, or Path, or None if no name is available.
        """
        if self._filename is not None:
            return self._filename
        if self._external_file is not None:
            return getattr(self._external_file, "name", None)
        if self._binary_file is None:
            return None
        return self._binary_file.name

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
    def newlines(self) -> Optional[Union[str, Tuple[str, ...]]]:
        """Return newline types observed while reading, like TextIOWrapper."""
        if self._seen_newline_types == 0:
            return None

        seen = []
        if self._seen_newline_types & self._SEEN_CR:
            seen.append("\r")
        if self._seen_newline_types & self._SEEN_LF:
            seen.append("\n")
        if self._seen_newline_types & self._SEEN_CRLF:
            seen.append("\r\n")

        if len(seen) == 1:
            return seen[0]
        return tuple(seen)

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

    def _buffered_text_len(self) -> int:
        """Return the number of unread characters in the decoded text buffer."""
        return len(self._text_buffer) - self._text_buffer_offset

    def _set_buffer(self, text: str) -> None:
        """Replace the unread decoded text buffer."""
        self._text_buffer = text
        self._text_buffer_offset = 0

    def _append_buffer(self, text: str) -> None:
        """Append decoded text, compacting consumed prefix when it grows large."""
        if not text:
            return
        self._text_buffer += text
        # Compact when dead space exceeds threshold (mirrors binary mode strategy)
        if self._text_buffer_offset > self._TEXT_COMPACTION_THRESHOLD:
            self._text_buffer = self._text_buffer[self._text_buffer_offset :]
            self._text_buffer_offset = 0

    def _consume_buffer(self, size: int) -> str:
        """Consume and return up to ``size`` characters from the decoded buffer."""
        buf = self._text_buffer
        start = self._text_buffer_offset
        end = start + size
        if end >= len(buf):
            # Consuming everything — return without slice when possible
            self._text_buffer = ""
            self._text_buffer_offset = 0
            return buf if start == 0 else buf[start:]
        result = buf[start:end]
        self._text_buffer_offset = end
        return result

    def _can_use_plain_position(self, decoder_state: Tuple[Any, int]) -> bool:
        """Return True when the current state is representable as a plain position."""
        decoder_bytes, decoder_flag = decoder_state
        return (
            self._buffered_text_len() == 0
            and decoder_bytes == b""
            and decoder_flag == 0
            and not self._trailing_cr
        )

    async def _reset_to_start(self) -> None:
        """Reset the text stream to its initial read state."""
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")
        await self._binary_file.seek(0)
        self._decoder.reset()
        self._set_buffer("")
        self._trailing_cr = False
        self._seen_newline_types = 0
        self._set_buffer_origin(
            origin_offset=0,
            decoder_state=self._decoder.getstate(),
            trailing_cr=False,
            seen_newlines=0,
        )

    def _set_buffer_origin(
        self,
        *,
        origin_offset: int,
        decoder_state: Tuple[Any, int],
        trailing_cr: bool,
        seen_newlines: int,
    ) -> None:
        """Record the decoder state from which the current buffered text can be replayed."""
        self._buffer_origin_offset = origin_offset
        self._buffer_origin_decoder_state = decoder_state
        self._buffer_origin_trailing_cr = trailing_cr
        self._buffer_origin_seen_newline_types = seen_newlines

    def _capture_buffer_origin(self) -> None:
        """Snapshot the current decoder state before decoding fresh unread text."""
        self._set_buffer_origin(
            origin_offset=self._binary_file._position,
            decoder_state=self._decoder.getstate(),
            trailing_cr=self._trailing_cr,
            seen_newlines=self._seen_newline_types,
        )

    async def _seek_to_plain_position(self, offset: int) -> None:
        """Restore a plain text position by replaying bytes from the stream start."""
        if self._binary_file is None:
            raise ValueError("File not opened. Use async context manager.")

        await self._reset_to_start()
        remaining = offset
        while remaining > 0:
            raw_chunk = await self._binary_file.read(min(self._chunk_size, remaining))
            if not raw_chunk:
                break
            remaining -= len(raw_chunk)
            decoded_chunk = self._decoder.decode(raw_chunk, final=False)
            if decoded_chunk:
                self._apply_newline_decoding(decoded_chunk)

        if remaining == 0 and not self._binary_file._eof:
            await self._binary_file.peek(1)

        if remaining == 0 and self._binary_file._eof:
            final_decoded = self._decoder.decode(b"", final=True)
            if final_decoded:
                self._apply_newline_decoding(final_decoded)
            self._finalize_pending_newline_state()

        self._set_buffer("")
        self._set_buffer_origin(
            origin_offset=offset,
            decoder_state=self._decoder.getstate(),
            trailing_cr=self._trailing_cr,
            seen_newlines=self._seen_newline_types,
        )

    def _encode_cookie(
        self,
        *,
        origin_offset: int,
        decoder_state: Tuple[Any, int],
        trailing_cr: bool,
        seen_newlines: int,
        chars_to_skip: int,
    ) -> int:
        """Serialize the current text state into an opaque int cookie."""
        decoder_bytes, decoder_flag = decoder_state
        payload = self._COOKIE_HEADER.pack(
            self._COOKIE_VERSION,
            self._cookie_nonce,
            origin_offset,
            chars_to_skip,
            decoder_flag,
            int(trailing_cr),
            seen_newlines,
            len(decoder_bytes),
        )
        payload += decoder_bytes
        return -(int.from_bytes(payload, "big") + 1)

    def _decode_cookie(
        self, cookie: int
    ) -> Tuple[int, Tuple[bytes, int], bool, int, int]:
        """Decode and validate an opaque cookie for this open text stream."""
        if not isinstance(cookie, int) or cookie >= 0:
            raise OSError("Cannot seek to invalid text cookie for this stream")

        payload_int = (-cookie) - 1
        raw = payload_int.to_bytes((payload_int.bit_length() + 7) // 8, "big")
        if len(raw) < self._COOKIE_HEADER.size:
            raise OSError("Cannot seek to invalid text cookie for this stream")

        (
            version,
            nonce,
            origin_offset,
            chars_to_skip,
            decoder_flag,
            trailing_cr,
            seen_newlines,
            decoder_len,
        ) = self._COOKIE_HEADER.unpack(raw[: self._COOKIE_HEADER.size])
        decoder_bytes = raw[self._COOKIE_HEADER.size :]

        if (
            version != self._COOKIE_VERSION
            or nonce != self._cookie_nonce
            or len(decoder_bytes) != decoder_len
        ):
            raise OSError("Cannot seek to invalid text cookie for this stream")

        return (
            origin_offset,
            (decoder_bytes, decoder_flag),
            bool(trailing_cr),
            seen_newlines,
            chars_to_skip,
        )

    async def _replay_characters(self, chars_to_skip: int, *, strict: bool) -> None:
        """Replay decoded text forward from a cookie origin to the target position."""
        remaining = chars_to_skip
        while remaining > 0:
            while self._buffered_text_len() == 0:
                has_more = await self._read_chunk_and_decode()
                if not has_more:
                    if strict:
                        raise OSError(
                            "Cannot seek to invalid text cookie for this stream"
                        )
                    break
            if self._buffered_text_len() == 0:
                break

            take = min(remaining, self._buffered_text_len())
            self._consume_buffer(take)
            remaining -= take

    async def _read_chunk_and_decode(self) -> bool:
        """Read a chunk of binary data, decode it, and append to text buffer.

        Returns:
            bool: True if data was added to the buffer, False if EOF was reached.
        """
        bf = self._binary_file
        if bf is None:
            return False

        if bf._eof:
            # Inline _finalize_pending_newline_state
            if self._universal_newlines and self._trailing_cr:
                self._seen_newline_types |= self._SEEN_CR
                self._trailing_cr = False
            return False

        # Inline _capture_buffer_origin when buffer is empty
        if len(self._text_buffer) == self._text_buffer_offset:
            self._buffer_origin_offset = bf._position
            self._buffer_origin_decoder_state = self._decoder.getstate()
            self._buffer_origin_trailing_cr = self._trailing_cr
            self._buffer_origin_seen_newline_types = self._seen_newline_types

        raw_chunk = await bf.read(self._chunk_size)
        if not raw_chunk:
            final_decoded = self._decoder.decode(b"", final=True)
            if final_decoded:
                self._append_buffer(self._apply_newline_decoding(final_decoded))
            if self._universal_newlines and self._trailing_cr:
                self._seen_newline_types |= self._SEEN_CR
                self._trailing_cr = False
            return bool(final_decoded)

        decoded_chunk = self._decoder.decode(raw_chunk, final=False)

        if decoded_chunk:
            self._append_buffer(self._apply_newline_decoding(decoded_chunk))

        return True

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
            # Fast path: drain buffer, then read all remaining binary data
            # in one shot to avoid per-chunk buffer append/consume overhead
            chunks = []
            buf = self._text_buffer
            off = self._text_buffer_offset
            if off < len(buf):
                chunks.append(buf[off:] if off else buf)
                self._text_buffer = ""
                self._text_buffer_offset = 0

            bf = self._binary_file
            decoder = self._decoder
            apply_nl = self._apply_newline_decoding

            raw_all = await bf.read(-1)
            if raw_all:
                decoded = decoder.decode(raw_all, final=False)
                if decoded:
                    chunks.append(apply_nl(decoded))

            final = decoder.decode(b"", final=True)
            if final:
                chunks.append(apply_nl(final))
            self._finalize_pending_newline_state()

            return "".join(chunks)
        else:
            # Check if we have enough data in our text buffer
            while self._buffered_text_len() < size:
                has_more = await self._read_chunk_and_decode()
                if not has_more:
                    break

            # Return the requested number of characters
            return self._consume_buffer(size)

    def _find_line_terminator(self, search_from: int = 0) -> Tuple[int, int]:
        """Find position of next line terminator in the buffered text.

        Searches directly in ``_text_buffer`` starting from
        ``_text_buffer_offset + search_from`` to avoid both slice copies and
        redundant re-scanning of already-searched regions.

        Args:
            search_from: Number of characters past the buffer offset to begin
                searching.  Callers use this after appending new data so that
                only the freshly added portion is scanned.

        Returns:
            Tuple of (position, length) where position is relative to the current
            buffer offset and length is the terminator length (1 or 2).
            Returns (-1, 0) if no terminator found.
        """
        buf = self._text_buffer
        buf_end = len(buf)
        search_start = self._text_buffer_offset + search_from
        base = self._text_buffer_offset

        if self._newline is None or self._newline == "":
            pos_n = buf.find("\n", search_start)
            pos_r = buf.find("\r", search_start)

            if pos_n == -1 and pos_r == -1:
                return (-1, 0)

            if pos_r == -1:
                return (pos_n - base, 1)

            cr_length = 2 if pos_r + 1 < buf_end and buf[pos_r + 1] == "\n" else 1
            cr_is_trailing = pos_r + 1 == buf_end
            should_wait_for_lf = (
                self._newline == ""
                and cr_length == 1
                and cr_is_trailing
                and not self._binary_file._eof
            )
            rel_pos = pos_r - base
            if should_wait_for_lf:
                return (pos_n - base, 1) if pos_n != -1 else (-1, 0)
            if pos_n == -1 or rel_pos <= pos_n - base:
                return (rel_pos, cr_length)
            return (pos_n - base, 1)
        elif self._newline == "\n":
            pos = buf.find("\n", search_start)
            return (pos - base, 1) if pos != -1 else (-1, 0)
        elif self._newline == "\r":
            pos = buf.find("\r", search_start)
            return (pos - base, 1) if pos != -1 else (-1, 0)
        elif self._newline == "\r\n":
            pos = buf.find("\r\n", search_start)
            return (pos - base, 2) if pos != -1 else (-1, 0)
        else:
            pos = buf.find("\n", search_start)
            return (pos - base, 1) if pos != -1 else (-1, 0)

    def _apply_newline_decoding(self, text: str) -> str:
        """Apply newline decoding/translation semantics similar to TextIOWrapper.

        - newline is None: universal newline translation on input -> normalize CRLF/CR to \n
        - newline is '': no translation
        - newline is one of '\n', '\r', '\r\n': no translation on input

        Handles CRLF sequences split across chunk boundaries by tracking trailing \r.
        """
        if not text:
            return text
        if not self._universal_newlines:
            return text

        trailing_cr = self._trailing_cr
        seen = self._seen_newline_types

        # Handle trailing CR from previous chunk
        if trailing_cr:
            if text[0] == "\n":
                seen |= self._SEEN_CRLF
            else:
                seen |= self._SEEN_CR

        pending_trailing_cr = text[-1] == "\r"

        # Track newline types using C-speed string operations
        need = 7 & ~seen  # 7 == _SEEN_CR | _SEEN_LF | _SEEN_CRLF
        if need:
            scan = text[:-1] if pending_trailing_cr else text

            has_crlf = "\r\n" in scan if need & 4 else False
            if has_crlf:
                seen |= self._SEEN_CRLF

            if need & 2 and "\n" in scan:
                if not has_crlf or "\n" in scan.replace("\r\n", "\r\r"):
                    seen |= self._SEEN_LF

            if need & 1 and "\r" in scan:
                if not has_crlf or "\r" in scan.replace("\r\n", "\n\n"):
                    seen |= self._SEEN_CR

        self._seen_newline_types = seen

        if self._newline == "":
            self._trailing_cr = pending_trailing_cr
            return text

        # Universal newline translation (newline is None)
        if trailing_cr and text[0] == "\n":
            text = text[1:]

        self._trailing_cr = pending_trailing_cr

        if "\r" not in text:
            return text

        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
        return text

    def _finalize_pending_newline_state(self) -> None:
        """Record a trailing standalone CR when EOF resolves the ambiguity."""
        if self._universal_newlines and self._trailing_cr:
            self._seen_newline_types |= self._SEEN_CR
            self._trailing_cr = False

    def __aiter__(self) -> "AsyncGzipTextFile":
        """Make AsyncGzipTextFile iterable for line-by-line reading."""
        return self

    async def __anext__(self) -> str:
        """Return the next line from the file."""
        if self._is_closed:
            raise StopAsyncIteration

        search_from = 0
        while True:
            pos, length = self._find_line_terminator(search_from)
            if pos != -1:
                return self._consume_buffer(pos + length)

            # Track how far we've scanned before reading more data.
            # Back up 1 char in case a \r at the boundary pairs with a new \n.
            buf_len = len(self._text_buffer) - self._text_buffer_offset
            has_more = await self._read_chunk_and_decode()
            if not has_more:
                remaining = len(self._text_buffer) - self._text_buffer_offset
                if remaining > 0:
                    return self._consume_buffer(remaining)
                raise StopAsyncIteration
            search_from = max(0, buf_len - 1)

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
        search_from = 0
        while True:
            pos, length = self._find_line_terminator(search_from)

            if pos != -1:
                end = pos + length
                if limit != -1 and end > limit:
                    return self._consume_buffer(limit)
                return self._consume_buffer(end)

            buf_len = len(self._text_buffer) - self._text_buffer_offset
            if limit != -1 and buf_len >= limit:
                return self._consume_buffer(limit)

            has_more = await self._read_chunk_and_decode()
            if not has_more:
                if buf_len == 0:
                    return ""
                remaining = len(self._text_buffer) - self._text_buffer_offset
                if limit != -1 and remaining > limit:
                    return self._consume_buffer(limit)
                return self._consume_buffer(remaining)
            search_from = max(0, buf_len - 1)

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
