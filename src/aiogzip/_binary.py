"""Binary gzip stream implementation."""

import asyncio
import gzip
import io
import os
import warnings
from pathlib import Path
from typing import (
    Any,
    Iterable,
    List,
    NoReturn,
    Optional,
    Union,
    cast,
)

import aiofiles

from . import _engine
from ._codec_async import (
    _DECODE_OFFLOAD_THRESHOLD,
    _ZLIB_OFFLOAD_THRESHOLD,
    _drive_operation,
)
from ._common import (
    _MAX_CHUNK_SIZE,
    WithAsyncRead,
    WithAsyncReadWrite,
    WithAsyncWrite,
    _check_can_open,
    _format_file_repr,
    _normalize_mtime,
    _parse_mode_tokens,
    _validate_chunk_size,
    _validate_compresslevel,
    _validate_filename,
    _validate_optional_positive_int,
    _validate_original_filename,
)
from .codec import GzipDecoder, GzipEncoder, _AsyncDrivableOperation


def _decompression_error_message(error: gzip.BadGzipFile) -> str:
    """Preserve the file API's error prefix around richer codec context."""
    detail = str(error)
    if detail.startswith("CRC check failed"):
        detail = f"incorrect data check ({detail})"
    elif detail.startswith("ISIZE check failed"):
        detail = f"incorrect length check ({detail})"
    elif "ended before" in detail and "truncated" not in detail:
        detail = f"truncated or incomplete stream ({detail})"
    return f"Error decompressing gzip data: {detail}"


class ConcurrentOperationError(OSError):
    """Raised when overlapping operations use one file handle concurrently.

    Await the operation that already owns the handle before retrying the
    rejected call. One file handle is intentionally single-task-owned.
    """


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

        # Imperative lifecycle when `async with` is impractical
        f = AsyncGzipBinaryFile("data.gz", "rb")
        await f.open()
        try:
            data = await f.read()
        finally:
            await f.close()

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
        "_encoder",
        "_decoder",
        "_buffer",
        "_buffer_offset",
        "_is_closed",
        "_eof",
        "_owns_file",
        "_position",
        "_mtime",
        "_decoder_header_generation",
        "_compressed_cache",
        "_replay_offset",
        "_cache_rewindable_reads",
        "_underlying_seekable",
        "_max_rewind_cache_size",
        "_write_broken",
        "_write_call_active",
        "_read_call_active",
        "_active_call_waiter",
        "_read_broken",
        "_read_validation_failed",
        "_max_decompressed_size",
        "_strict_size",
        "_fast_compress",
    )

    # 256 KiB balances bulk-read throughput against per-file memory. Below it
    # (e.g. the former 64 KiB) read-all throughput drops ~35-60% on large
    # files from per-chunk overhead. Larger sizes give little extra while
    # costing proportionally more memory per open file. File reads already
    # yield during asynchronous I/O, so decoder executor offload is reserved
    # for larger accepted inputs. Callers can still pass any chunk_size
    # explicitly.
    DEFAULT_CHUNK_SIZE = 256 * 1024  # 256 KiB
    # When the read buffer's head offset crosses this, drop the consumed
    # prefix so the bytearray does not grow unbounded while reads march
    # forward. Matches DEFAULT_CHUNK_SIZE so a full typical chunk fits.
    BUFFER_COMPACTION_THRESHOLD = 256 * 1024
    # Reusable zero-chunk size for write-mode forward seek() filler.
    _SEEK_ZERO_CHUNK_SIZE = 1024

    def __init__(
        self,
        filename: Union[str, bytes, Path, None],
        mode: str = "rb",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        compresslevel: int = 6,
        mtime: Optional[Union[int, float]] = None,
        original_filename: Optional[Union[str, bytes]] = None,
        fileobj: Optional[
            Union[WithAsyncRead, WithAsyncWrite, WithAsyncReadWrite]
        ] = None,
        closefd: Optional[bool] = None,
        max_decompressed_size: Optional[int] = None,
        max_rewind_cache_size: Optional[int] = _MAX_CHUNK_SIZE,
        strict_size: bool = False,
        fast_compress: bool = False,
    ) -> None:
        # Validate inputs using shared validation functions
        _validate_filename(filename, fileobj)
        _validate_chunk_size(chunk_size)
        _validate_optional_positive_int(max_decompressed_size, "max_decompressed_size")
        _validate_optional_positive_int(max_rewind_cache_size, "max_rewind_cache_size")

        # Validate mode and derive file characteristics
        mode_op, saw_b, saw_t, plus = _parse_mode_tokens(mode)
        if saw_t:
            raise ValueError("Binary mode cannot include text ('t')")
        # _parse_mode_tokens guarantees mode_op is one of r/w/a/x here.

        self._filename = filename
        self._mode = mode
        self._mode_op = mode_op
        self._mode_plus = plus
        self._writing_mode = mode_op in {"w", "a", "x"}
        if self._writing_mode:
            _validate_compresslevel(compresslevel)
        self._fast_compress = bool(fast_compress)
        if (
            self._writing_mode
            and self._fast_compress
            and not _engine.have_fast_engine()
        ):
            warnings.warn(
                "fast_compress=True requested but zlib-ng is not available; "
                "falling back to stdlib zlib. Install the extra with "
                "'pip install aiogzip[fast]' to enable faster compression.",
                stacklevel=2,
            )
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
        self._encoder: Optional[GzipEncoder] = None
        self._decoder: Optional[GzipDecoder] = None
        self._buffer = bytearray()  # Use bytearray for efficient buffer growth
        self._buffer_offset: int = 0  # Offset to the start of valid data in _buffer
        self._is_closed: bool = False
        self._eof: bool = False
        self._owns_file: bool = False
        self._position: int = 0
        self._mtime: Optional[int] = None
        self._decoder_header_generation: int = 0
        self._compressed_cache = bytearray()
        self._replay_offset: Optional[int] = None
        self._cache_rewindable_reads: bool = False
        self._underlying_seekable: bool = True
        self._max_rewind_cache_size: Optional[int] = max_rewind_cache_size
        self._write_broken: bool = False
        self._write_call_active: bool = False
        self._read_call_active: bool = False
        self._active_call_waiter: Optional[asyncio.Future[None]] = None
        self._read_broken: bool = False
        self._read_validation_failed: bool = False
        self._max_decompressed_size: Optional[int] = max_decompressed_size
        self._strict_size: bool = bool(strict_size)

    async def open(self) -> "AsyncGzipBinaryFile":
        """Open the file for I/O and return ``self``.

        This performs the same initialization as entering the async context
        manager, for callers who prefer an explicit try/finally over ``async
        with``::

            f = AsyncGzipBinaryFile("data.gz", "rb")
            await f.open()
            try:
                data = await f.read()
            finally:
                await f.close()

        Raises:
            ValueError: if the file is already open, or has already been closed
                (a closed instance cannot be reopened, matching io objects).
        """
        _check_can_open(self._is_closed, self._file is not None)
        try:
            if self._external_file is not None:
                self._file = cast(Any, self._external_file)
                self._owns_file = False
            else:
                # __init__'s _validate_filename guarantees a filename exists
                # whenever no fileobj was given; assert keeps the narrowing.
                assert self._filename is not None
                self._file = await aiofiles.open(  # type: ignore
                    self._filename, self._file_mode
                )
                self._owns_file = True

            # Initialize compression/decompression engine based on mode
            if self._writing_mode:
                header_filename = self._header_filename_override
                if header_filename is None and self._filename is not None:
                    header_filename = os.fspath(self._filename)

                # __init__ already emits the established file-boundary warning
                # when fast compression is unavailable. Avoid duplicating it
                # when the codec performs its own direct-use warning.
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="fast_compress=True requested.*",
                    )
                    self._encoder = GzipEncoder(
                        compresslevel=self._compresslevel,
                        mtime=self._header_mtime,
                        original_filename=header_filename,
                        fast_compress=self._fast_compress,
                        strict_size=self._strict_size,
                        output_chunk_size=max(
                            self._chunk_size, self.DEFAULT_CHUNK_SIZE
                        ),
                    )
                for header_chunk in self._encoder.start():
                    await self._write_all(header_chunk)
            else:  # read mode
                self._decoder = GzipDecoder(
                    # ``chunk_size`` governs transport reads and write
                    # batching. Preserve the codec's tuned bounded-output
                    # floor so tiny compatibility-test read sizes do not turn
                    # a large inflate result into thousands of Python
                    # operations.
                    output_chunk_size=max(self._chunk_size, self.DEFAULT_CHUNK_SIZE),
                    max_decompressed_size=self._max_decompressed_size,
                )
                self._eof = False
                self._read_call_active = False
                self._read_broken = False
                self._read_validation_failed = False
                self._position = 0
                self._mtime = None
                self._decoder_header_generation = 0
                self._compressed_cache.clear()
                self._replay_offset = None
                self._underlying_seekable = await self._probe_underlying_seekable()
                self._cache_rewindable_reads = not self._underlying_seekable

            return self
        except BaseException:
            # BaseException, not Exception: a task cancelled mid-open (e.g.
            # during the header write) must not leave _file set — the handle
            # would leak and every retry would hit "File is already open".
            await self._cleanup_failed_enter()
            raise

    async def __aenter__(self) -> "AsyncGzipBinaryFile":
        """Enter the async context manager and initialize resources."""
        return await self.open()

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Exit the context manager, flushing and closing the file."""
        try:
            await self.close()
        except ConcurrentOperationError:
            if exc_val is None:
                # A clean context exit owns normal finalization. Wait for the
                # spawned call that still owns this handle, then close it here
                # rather than leaking an open file and unterminated member.
                await self._wait_for_active_call()
                await self.close()
                return
            # A task spawned from the body may still own the codec. Preserve
            # the body's exception and close resources without discarding the
            # live operation underneath that task.
            try:
                await self._abort_active_call_on_exit()
            except BaseException:
                # As in close()'s failed-write path, the primary exception wins
                # after the underlying close has at least been attempted.
                pass

    # Sync-protocol stubs. Without these, ``with`` / ``for`` fail with generic
    # "does not support the context manager protocol" / "is not iterable"
    # TypeErrors; these raise the same type but tell the caller the fix.
    def __enter__(self) -> NoReturn:
        raise TypeError(
            "AsyncGzipBinaryFile must be used with 'async with', not 'with' "
            "(e.g. \"async with aiogzip.open(path, 'rb') as f:\")"
        )

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> NoReturn:
        # Unreachable via ``with`` because __enter__ always raises; kept so the
        # class satisfies context-manager introspection with a curated error.
        raise TypeError(
            "AsyncGzipBinaryFile must be used with 'async with', not 'with' "
            "(e.g. \"async with aiogzip.open(path, 'rb') as f:\")"
        )

    def __iter__(self) -> NoReturn:
        raise TypeError(
            "AsyncGzipBinaryFile must be iterated with 'async for', not 'for' "
            '(e.g. "async for chunk in f:")'
        )

    def __repr__(self) -> str:
        return _format_file_repr(self)

    # File API compatibility helpers
    async def tell(self) -> int:
        """Return the current uncompressed file position."""
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        return self._position

    async def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        """Move to a new file position, mirroring gzip.GzipFile semantics."""
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")
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
                zero_chunk = b"\x00" * min(self._SEEK_ZERO_CHUNK_SIZE, count)
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

        if self._read_call_active:
            self._check_read_call_usable()

        self._read_call_active = True
        try:
            # A fresh decoder over the rewound source is the one supported
            # recovery path for a poisoned reader. Other seeks cannot safely
            # use state from the failed decoder, including relative seeks that
            # happen to target 0.
            if self._read_broken and whence == os.SEEK_SET and offset == 0:
                await self._rewind_reader()
                return 0

            self._check_read_usable()

            if whence == os.SEEK_SET:
                target = offset
            elif whence == os.SEEK_CUR:
                target = self._position + offset
            elif whence == os.SEEK_END:
                while not self._eof:
                    await self._fill_buffer()
                    buffered = len(self._buffer) - self._buffer_offset
                    if buffered > 0:
                        self._buffer_offset = len(self._buffer)
                        self._position += buffered
                        del self._buffer[:]
                        self._buffer_offset = 0
                target = self._position + offset
                if target < 0:
                    target = 0
                elif target > self._position:
                    target = self._position
            else:
                raise ValueError("Invalid whence value")

            if target < 0:
                raise OSError("Negative seek in read mode")

            if target < self._position:
                await self._rewind_reader()

            await self._consume_bytes(target - self._position)
            return self._position
        finally:
            self._finish_read_call()

    def raw(self) -> Any:
        """Expose the underlying file object for advanced integrations."""
        return self._file

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
        candidate = (
            self._external_file if self._external_file is not None else self._file
        )
        return getattr(candidate, "name", None)

    @property
    def closed(self) -> bool:
        """Return True when this file has been closed."""
        return self._is_closed

    @property
    def mtime(self) -> Optional[int]:
        """Return the timestamp from the most recently parsed member header.

        The value is ``None`` until the first complete valid header is read.
        Decoder read-ahead can advance it beyond the bytes returned by the
        current read call when concatenated members share one source chunk.
        """
        return self._mtime

    def fileno(self) -> int:
        """Return the underlying file descriptor number."""
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")
        fileno_method = getattr(self._file, "fileno", None)
        if fileno_method is None:
            raise io.UnsupportedOperation("fileno() not supported by underlying file")
        result = fileno_method()
        if hasattr(result, "__await__"):
            # Dispose of the never-awaited coroutine so it does not emit a
            # "coroutine was never awaited" RuntimeWarning.
            close_method = getattr(result, "close", None)
            if callable(close_method):
                close_method()
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
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")
        if self._read_call_active or self._read_broken:
            self._check_read_call_usable(True)
        if size is not None and size > _MAX_CHUNK_SIZE:
            raise ValueError(
                f"peek size must be <= {_MAX_CHUNK_SIZE} bytes "
                f"({_MAX_CHUNK_SIZE // (1024 * 1024)} MiB)"
            )
        available = len(self._buffer) - self._buffer_offset
        target = size
        if target is None or target <= 0:
            target = available if available > 0 else 1
        if available < target and not self._eof:
            self._read_call_active = True
            try:
                while available < target and not self._eof:
                    await self._fill_buffer()
                    available = len(self._buffer) - self._buffer_offset
                    if available == 0 and self._eof:
                        break
            finally:
                self._finish_read_call()
        end = self._buffer_offset + min(target, available)
        return bytes(self._buffer[self._buffer_offset : end])

    def _copy_into_view(self, view: memoryview, written: int) -> int:
        """Copy as much of the current buffer span as fits into ``view[written:]``.

        Returns the number of bytes copied (0 when the buffer is empty). Applies
        the same advance/clear-when-drained bookkeeping as the ``read()`` path,
        but writes straight into the caller's view instead of allocating a
        ``bytes`` object.
        """
        buf = self._buffer
        offset = self._buffer_offset
        available = len(buf) - offset
        if available <= 0:
            return 0
        n = len(view) - written
        if n > available:
            n = available
        view[written : written + n] = memoryview(buf)[offset : offset + n]
        new_offset = offset + n
        self._position += n
        if new_offset >= len(buf):
            del buf[:]
            self._buffer_offset = 0
        else:
            self._buffer_offset = new_offset
        return n

    async def _fill_until(self, size: int) -> int:
        """Refill until ``size`` unread bytes are buffered (or EOF).

        Compacts a large consumed prefix before each refill so a long run of
        partial reads cannot grow the buffer unbounded. Shared by the sized
        ``read()`` path and ``readinto()``. Returns the unread byte count,
        which may be short of ``size`` only at EOF.
        """
        available = len(self._buffer) - self._buffer_offset
        threshold = self.BUFFER_COMPACTION_THRESHOLD
        while available < size and not self._eof:
            if self._buffer_offset > threshold:
                del self._buffer[: self._buffer_offset]
                self._buffer_offset = 0
            await self._fill_buffer()
            available = len(self._buffer) - self._buffer_offset
        return available

    async def readinto(self, b: Union[bytearray, memoryview]) -> int:
        """Read bytes directly into a pre-allocated, writable buffer.

        Fills the caller's buffer straight from the decompression buffer,
        avoiding the intermediate ``bytes`` object that delegating to ``read()``
        would allocate. Returns the number of bytes written (0 at EOF).
        """
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")
        if self._read_call_active or self._read_broken:
            self._check_read_call_usable(True)
        view = memoryview(b)
        if view.readonly:
            raise TypeError("readinto() argument must be writable")
        # Accept any writable buffer (e.g. array.array with itemsize > 1) by
        # viewing it as bytes, like the stdlib io machinery does.
        view = view.cast("B")

        total = len(view)
        if total == 0:
            return 0

        # Fill the internal buffer until it can satisfy the whole request (or
        # EOF), then copy once. Filling before consuming preserves read()'s
        # error semantics: if a refill raises mid-request, the stream position
        # and already-buffered data are left intact for the caller to salvage.
        self._read_call_active = True
        try:
            await self._fill_until(total)
        finally:
            self._finish_read_call()
        return self._copy_into_view(view, 0)

    async def read1(self, size: int = -1) -> bytes:
        """Read up to size bytes with at most one data-producing fill.

        A single compressed chunk can decode to nothing (e.g. while consuming
        the gzip header), so fills repeat until at least one byte is available;
        like stdlib gzip's ``read1()``, an empty result means EOF.
        """
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")
        if self._read_call_active or self._read_broken:
            self._check_read_call_usable(True)

        if size is None:
            size = -1
        if size == 0:
            return b""

        available = len(self._buffer) - self._buffer_offset
        if available <= 0 and not self._eof:
            self._read_call_active = True
            try:
                while available <= 0 and not self._eof:
                    await self._fill_buffer()
                    available = len(self._buffer) - self._buffer_offset
            finally:
                self._finish_read_call()

        if size is None or size < 0:
            actual_read_size = available
        else:
            actual_read_size = min(size, available)

        data_to_return = bytes(
            memoryview(self._buffer)[
                self._buffer_offset : self._buffer_offset + actual_read_size
            ]
        )
        self._buffer_offset += actual_read_size
        self._position += actual_read_size

        if self._buffer_offset >= len(self._buffer):
            del self._buffer[:]
            self._buffer_offset = 0

        return data_to_return

    async def readinto1(self, b: Union[bytearray, memoryview]) -> int:
        """Read directly into the buffer with at most one data-producing fill.

        Like ``read1()`` but writes straight into the caller's buffer, avoiding
        the intermediate ``bytes`` object. A single compressed chunk can decode
        to nothing (e.g. while consuming the gzip header), so fills repeat
        until at least one byte is available; the result is still capped at one
        buffer's worth of decoded data. Returns the number of bytes written
        (0 only at EOF), so ``while await f.readinto1(buf): ...`` is safe.
        """
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")
        if self._read_call_active or self._read_broken:
            self._check_read_call_usable(True)
        view = memoryview(b)
        if view.readonly:
            raise TypeError("readinto1() argument must be writable")
        view = view.cast("B")

        total = len(view)
        if total == 0:
            return 0

        available = len(self._buffer) - self._buffer_offset
        if available <= 0 and not self._eof:
            self._read_call_active = True
            try:
                while available <= 0 and not self._eof:
                    await self._fill_buffer()
                    available = len(self._buffer) - self._buffer_offset
            finally:
                self._finish_read_call()
        return self._copy_into_view(view, 0)

    async def readline(self, limit: int = -1) -> bytes:
        """Read and return one line from the binary stream."""
        if self._mode_op != "r":
            raise OSError("File not open for reading")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")
        if self._read_call_active or self._read_broken:
            self._check_read_call_usable(True)
        if limit is None or limit < 0:
            # Any negative limit means "no limit", matching io.IOBase. Values
            # below -1 must not reach the arithmetic below, where they would
            # move the buffer offset backwards.
            limit = -1
        if limit == 0:
            return b""

        # Keep the full candidate line in the shared buffer until a newline,
        # explicit limit, or clean EOF makes the result publishable. A refill
        # failure therefore leaves both the bytes and tell() untouched for the
        # same explicit salvage/recovery contract as read(-1).
        buf = self._buffer
        start = self._buffer_offset
        if start > self.BUFFER_COMPACTION_THRESHOLD:
            del buf[:start]
            self._buffer_offset = 0
            start = 0
        search_from = start
        reserved = False
        try:
            while True:
                buf_len = len(buf)
                newline_index = buf.find(b"\n", search_from)
                if newline_index != -1:
                    end = newline_index + 1
                    if limit != -1:
                        end = min(end, start + limit)
                elif limit != -1 and buf_len - start >= limit:
                    end = start + limit
                elif self._eof:
                    # A poisoned, unterminated remainder is not a clean final
                    # line. A newline-terminated or explicitly bounded result
                    # took one of the branches above and remains salvageable.
                    if self._read_broken:
                        self._check_read_usable()
                    end = buf_len
                else:
                    search_from = buf_len
                    if not reserved:
                        self._read_call_active = True
                        reserved = True
                    await self._fill_buffer()
                    continue

                result = bytes(memoryview(buf)[start:end])
                consumed = end - start
                self._buffer_offset = end
                self._position += consumed
                if end >= len(buf):
                    del buf[:]
                    self._buffer_offset = 0
                return result
        finally:
            if reserved:
                self._finish_read_call()

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
        """Write bytes-like lines in bounded batches without adding separators."""
        if not self._writing_mode:
            raise OSError("File not open for writing")
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

        pending = bytearray()
        iterator = iter(lines)
        while True:
            try:
                line = next(iterator)
            except StopIteration:
                break
            except BaseException:
                if pending:
                    await self.write(pending)
                raise

            try:
                data = self._coerce_byteslike(line)
            except BaseException:
                if pending:
                    await self.write(pending)
                raise

            length = len(data)
            if length >= self._chunk_size:
                if pending:
                    await self.write(pending)
                    pending.clear()
                await self.write(data)
            else:
                if pending and len(pending) + length > self._chunk_size:
                    await self.write(pending)
                    pending.clear()
                pending.extend(data)

        if pending:
            await self.write(pending)

    def readable(self) -> bool:
        return self._mode_op == "r"

    def writable(self) -> bool:
        return self._writing_mode

    def seekable(self) -> bool:
        if self._file is None or self._writing_mode:
            return True
        return self._underlying_seekable or self._cache_rewindable_reads

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
            raise ValueError("File not opened. Call await open() or use async with.")
        if self._write_broken:
            raise OSError(
                "write stream is broken after a prior write failure; "
                "the gzip member is unusable"
            )

        # Exact bytes already satisfy the immutable-snapshot contract. Keep
        # the overwhelmingly common path here so each small write does not
        # pay a second Python method call merely to repeat the type check.
        payload = data if type(data) is bytes else self._coerce_byteslike(data)
        length = len(payload)
        encoder = self._encoder
        if encoder is None:
            raise RuntimeError("gzip writer encoder is not initialized")

        # A handle belongs to one task at a time. Keep the guard active through
        # sink I/O and position publication, after the codec token is released;
        # flush() uses the same guard for its underlying-file await.
        self._check_write_call_available()
        self._write_call_active = True
        try:
            # The writer already owns an exact snapshot. The private feed entry
            # preserves call-time validation without normalizing it a second time.
            operation = encoder._feed_snapshot(payload)
            try:
                if length >= _ZLIB_OFFLOAD_THRESHOLD:
                    async for compressed in _drive_operation(
                        operation,
                        workload=payload,
                    ):
                        await self._write_all(compressed)
                else:
                    # Small writes bound the inline work by the caller's payload;
                    # a similarly small compressed read could expand enormously
                    # and must use the checkpointing async driver instead.
                    for compressed in operation:
                        await self._write_all(compressed)
            except BaseException:
                self._write_broken = True
                encoder.discard()
                raise

            # Exceptional context exit can close an owned sink while this
            # task is suspended in it. A sink that completes that await after
            # close must not make this torn member look successfully written.
            if self._is_closed or self._write_broken:
                raise OSError(
                    "write aborted because the gzip file was closed while "
                    "the call was active"
                )

            # The codec owns uncompressed-byte accounting. Expose its authoritative
            # ledger only after every emitted byte reached the sink.
            self._position = encoder.input_size

            return length
        finally:
            self._write_call_active = False
            if self._active_call_waiter is not None:
                self._notify_active_call_finished()
            if self._is_closed and self._write_broken:
                encoder.discard()

    @staticmethod
    def _coerce_byteslike(data: Any) -> bytes:
        """Return an exact immutable snapshot of any valid buffer input."""
        if type(data) is bytes:
            return data
        try:
            # memoryview reads bytes subclasses through their raw buffer and
            # therefore cannot invoke hostile __bytes__, __len__, or indexing
            # overrides. tobytes() also flattens non-contiguous and multi-byte
            # views into the exact bytes type required by the public codec.
            return memoryview(data).tobytes()
        except TypeError as exc:
            raise TypeError(
                f"write() argument must be a bytes-like object, not {type(data).__name__}"
            ) from exc

    async def _write_all(self, data: bytes) -> None:
        """Write every byte to the underlying sink or raise on no progress."""
        if self._file is None:
            raise ValueError("File not opened. Call await open() or use async with.")

        offset = 0
        length = len(data)
        while offset < length:
            written = await self._file.write(data if offset == 0 else data[offset:])
            if not isinstance(written, int) or isinstance(written, bool):
                raise OSError(
                    "underlying file write() returned an invalid byte count "
                    f"({written!r})"
                )
            remaining = length - offset
            if written <= 0:
                raise OSError("underlying file write() made no progress")
            if written > remaining:
                raise OSError(
                    "underlying file write() returned more bytes than requested "
                    f"({written} > {remaining})"
                )
            offset += written

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
            raise ValueError("File not opened. Call await open() or use async with.")
        if self._read_call_active or self._read_broken:
            self._check_read_call_usable(True)

        if size is None:
            size = -1
        if size < 0:
            size = -1

        # If size is -1, read all data in chunks to avoid memory issues
        if size == -1:
            # Return buffered data + read remaining (no recursion)
            # Use list + b"".join() — it pre-computes total size and does
            # one allocation, which beats bytearray.extend() reallocation.
            chunks = []
            total_read = 0
            buf = self._buffer
            offset = self._buffer_offset
            if offset < len(buf):
                chunk = bytes(memoryview(buf)[offset:])
                chunks.append(chunk)
                total_read += len(chunk)
            # Release the bytearray's allocation before decoding the remainder.
            # The immutable prefix above is the sole successful-read copy; it is
            # restored only if the failure contract makes those bytes reachable.
            del buf[:]
            self._buffer_offset = 0

            # Append decompressor output directly to the join list. Each piece
            # is already a distinct bytes object, so this avoids copying every
            # byte through self._buffer (extend + bytes()) only to copy again
            # in the final join — the dominant cost for large read-all calls.
            if not self._eof:
                self._read_call_active = True
                try:
                    try:
                        while not self._eof:
                            for piece in await self._decompress_next():
                                chunks.append(piece)
                                total_read += len(piece)
                    except BaseException:
                        # Validation failures expose decoded bytes for explicit
                        # salvage; transient source errors remain retryable. A
                        # terminal non-validation poison cannot expose them, so
                        # avoid copying an arbitrarily large failed read back.
                        if self._read_validation_failed or not self._read_broken:
                            for piece in chunks:
                                buf.extend(piece)
                        raise
                finally:
                    self._finish_read_call()

            self._position += total_read
            return b"".join(chunks)
        else:
            buf = self._buffer
            offset = self._buffer_offset
            available = len(buf) - offset

            # Fast path: buffer already has enough data
            if available >= size:
                end = offset + size
                data_to_return = bytes(memoryview(buf)[offset:end])
                self._buffer_offset = end
                self._position += size
                if end >= len(buf):
                    del buf[:]
                    self._buffer_offset = 0
                return data_to_return

            # Fill until we have enough. Keep the guard through publication so
            # another task cannot consume the newly filled buffer first.
            self._read_call_active = True
            try:
                available = await self._fill_until(size)

                # Return what we have
                actual_read_size = min(size, available)
                offset = self._buffer_offset
                data_to_return = bytes(
                    memoryview(self._buffer)[offset : offset + actual_read_size]
                )
                self._buffer_offset += actual_read_size
                self._position += actual_read_size

                if self._buffer_offset >= len(self._buffer):
                    del self._buffer[:]
                    self._buffer_offset = 0

                return data_to_return
            finally:
                self._finish_read_call()

    async def _decompress_next(self) -> List[bytes]:
        """Read the next compressed chunk and return its decompressed pieces.

        This is the shared file/codec bridge. It advances EOF state, retains
        the most recently completed header notification from the shared
        decoder, and delegates member traversal, finalization, validation, and
        output limits to that decoder.

        Each decompressor call already returns a fresh ``bytes`` object, so the
        pieces are handed back as-is: ``read(-1)`` appends them straight to its
        join list (avoiding a round-trip through ``self._buffer``), while
        ``_fill_buffer`` extends the buffer with them for the partial-read
        paths. Returns an empty list at or after EOF.
        """
        if self._eof or self._file is None:
            return []

        compressed_chunk = await self._read_compressed_chunk()
        decoder = self._decoder
        if decoder is None:
            raise RuntimeError("gzip reader decoder is not initialized")

        if not compressed_chunk:
            # Underlying EOF is the one point at which the decoder can prove
            # that all accepted members and trailers were complete.
            self._eof = True
            try:
                try:
                    pieces = list(decoder.finish())
                finally:
                    self._sync_decoder_mtime(decoder)
                return pieces
            except asyncio.CancelledError:
                self._poison_read(decoder)
                raise
            except gzip.BadGzipFile as error:
                self._poison_read(decoder, validation_failed=True)
                raise gzip.BadGzipFile(_decompression_error_message(error)) from error
            except _engine.ZLIB_ERRORS as error:
                self._poison_read(decoder, validation_failed=True)
                raise gzip.BadGzipFile(
                    f"Error finalizing gzip decompression: {error}"
                ) from error
            except OSError:
                self._poison_read(decoder)
                raise
            except Exception as error:
                self._poison_read(decoder)
                raise OSError(
                    f"Unexpected error during decompression finalization: {error}"
                ) from error

        try:
            operation = decoder.feed(compressed_chunk)
            try:
                return [
                    piece
                    async for piece in _drive_operation(
                        cast(_AsyncDrivableOperation, operation),
                        workload=compressed_chunk,
                        offload_threshold=_DECODE_OFFLOAD_THRESHOLD,
                    )
                ]
            finally:
                self._sync_decoder_mtime(decoder)
        except asyncio.CancelledError:
            # The driver waits for the executor worker to finish before it
            # closes the operation. Only then is it safe to discard the shared
            # decoder and expose cancellation to a caller that may reopen.
            self._poison_read(decoder)
            raise
        except gzip.BadGzipFile as error:
            self._poison_read(decoder, validation_failed=True)
            raise gzip.BadGzipFile(_decompression_error_message(error)) from error
        except OSError:
            self._poison_read(decoder)
            raise
        except Exception as error:
            self._poison_read(decoder)
            raise OSError(f"Unexpected error during decompression: {error}") from error

    def _sync_decoder_mtime(self, decoder: GzipDecoder) -> None:
        """Observe the most recently completed header from ``decoder``."""
        if decoder._header_generation != self._decoder_header_generation:
            self._decoder_header_generation = decoder._header_generation
            self._mtime = decoder._last_header_mtime

    def _check_read_call_usable(self, allow_buffered: bool = False) -> None:
        """Reject overlapping calls before they can reserve the decoder."""
        if self._read_call_active:
            raise ConcurrentOperationError(
                "gzip reader already has an active read call"
            )
        self._check_read_usable(allow_buffered=allow_buffered)

    def _finish_read_call(self) -> None:
        """Release a read reservation, discarding only after an abortive exit."""
        self._read_call_active = False
        if self._active_call_waiter is not None:
            self._notify_active_call_finished()
        if self._is_closed and self._decoder is not None:
            self._decoder.discard()

    async def _wait_for_active_call(self) -> None:
        """Wait until the single read or write reservation is released."""
        if not (self._read_call_active or self._write_call_active):
            return
        waiter = self._active_call_waiter
        if waiter is None or waiter.done():
            waiter = asyncio.get_running_loop().create_future()
            self._active_call_waiter = waiter
        await asyncio.shield(waiter)

    def _notify_active_call_finished(self) -> None:
        """Wake a context exit waiting to perform normal finalization."""
        waiter = self._active_call_waiter
        if waiter is None:
            return
        self._active_call_waiter = None
        if not waiter.done():
            waiter.set_result(None)

    def _check_read_usable(self, *, allow_buffered: bool = False) -> None:
        """Reject unsafe access, optionally allowing pre-failure decoded bytes."""
        if not self._read_broken:
            return
        if self._read_validation_failed and allow_buffered:
            if len(self._buffer) - self._buffer_offset > 0:
                return
        if self.seekable():
            recovery = "seek to 0 to recover, or close and reopen the gzip file"
        else:
            recovery = "close and reopen the gzip file"
        raise OSError(
            f"read stream is broken after failed or cancelled decompression; {recovery}"
        )

    def _poison_read(
        self,
        decoder: GzipDecoder,
        *,
        validation_failed: bool = False,
    ) -> None:
        """Make a failed decoder terminal while retaining pre-failure output."""
        self._read_broken = True
        self._read_validation_failed = validation_failed
        self._eof = True
        decoder.discard()

    def _check_write_call_available(self) -> None:
        """Reject overlapping writer calls before they mutate codec state."""
        if self._write_call_active:
            raise ConcurrentOperationError(
                "gzip writer already has an active write or flush call"
            )

    async def _fill_buffer(self) -> None:
        """Decompress the next compressed chunk into the read buffer.

        Thin wrapper over :meth:`_decompress_next` used by the partial-read
        paths (``read(size)``, ``readline``, ``peek``, ``seek``) that need the
        decoded bytes accumulated in ``self._buffer``.
        """
        for piece in await self._decompress_next():
            self._buffer.extend(piece)

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
            raise ValueError("File not opened. Call await open() or use async with.")
        seek_method = getattr(self._file, "seek", None)
        if self._underlying_seekable and callable(seek_method):
            result = seek_method(0, os.SEEK_SET)
            if hasattr(result, "__await__"):
                await result
            else:
                # synchronous seek already performed
                pass
        elif self._cache_rewindable_reads:
            self._replay_offset = 0
        else:
            raise OSError("Underlying file is not seekable")
        if self._decoder is not None:
            self._decoder.discard()
        self._decoder = GzipDecoder(
            output_chunk_size=max(self._chunk_size, self.DEFAULT_CHUNK_SIZE),
            max_decompressed_size=self._max_decompressed_size,
        )
        self._decoder_header_generation = 0
        self._read_broken = False
        self._read_validation_failed = False
        del self._buffer[:]
        self._buffer_offset = 0
        self._eof = False
        self._position = 0

    async def _probe_underlying_seekable(self) -> bool:
        """Return whether the underlying file should be rewound with seek()."""
        if self._file is None:
            return False

        seek_method = getattr(self._file, "seek", None)
        if not callable(seek_method):
            return False

        seekable_method = getattr(self._file, "seekable", None)
        if not callable(seekable_method):
            return True

        try:
            result = seekable_method()
            if hasattr(result, "__await__"):
                result = await result
        except Exception:
            return False
        return bool(result)

    async def _read_compressed_chunk(self) -> bytes:
        """Read the next compressed chunk from cache replay or the underlying file."""
        if self._file is None:
            return b""

        if self._replay_offset is not None:
            end = min(
                self._replay_offset + self._chunk_size, len(self._compressed_cache)
            )
            chunk = bytes(self._compressed_cache[self._replay_offset : end])
            self._replay_offset = end
            if self._replay_offset >= len(self._compressed_cache):
                self._replay_offset = None
            return chunk

        try:
            chunk = cast(bytes, await self._file.read(self._chunk_size))
        except OSError:
            # Re-raise I/O errors as-is
            raise
        except Exception as e:
            raise OSError(f"Error reading from file: {e}") from e

        if chunk and self._cache_rewindable_reads:
            cap = self._max_rewind_cache_size
            if cap is not None and len(self._compressed_cache) + len(chunk) > cap:
                self._compressed_cache.clear()
                self._cache_rewindable_reads = False
            else:
                self._compressed_cache.extend(chunk)
        return chunk

    async def _cleanup_failed_enter(self) -> None:
        """Close internally opened resources after __aenter__ setup failures.

        If the underlying close() raises (e.g., because the half-open
        file is already in a bad state), the instance still has to end
        up with _file cleared — otherwise the next caller can reach a
        handle we no longer own.
        """
        file = self._file
        owns_file = self._owns_file
        # Clear the handle up front (even for external fileobjs we must not
        # close) so a failed open() never leaves the instance looking open —
        # otherwise a retry would hit the "File is already open" guard and
        # write() could emit compressed data for a stream with no header.
        self._file = None
        self._owns_file = False
        encoder = self._encoder
        self._encoder = None
        if encoder is not None:
            encoder.discard()
        decoder = self._decoder
        self._decoder = None
        if decoder is not None:
            decoder.discard()
        if file is None or not owns_file:
            return

        close_method = getattr(file, "close", None)
        if callable(close_method):
            result = close_method()
            if hasattr(result, "__await__"):
                await result

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

        if self._writing_mode and self._write_broken:
            # Pretending the flush succeeded would tell the caller their
            # bytes are safely on disk when the member is already torn.
            raise OSError(
                "write stream is broken after a prior write failure; "
                "the gzip member is unusable"
            )

        if self._writing_mode and self._file is not None:
            encoder = self._encoder
            if encoder is None:
                raise RuntimeError("gzip writer encoder is not initialized")
            self._check_write_call_available()
            self._write_call_active = True
            try:
                await self._flush_writer(encoder)
            finally:
                self._write_call_active = False
                if self._active_call_waiter is not None:
                    self._notify_active_call_finished()
                if self._is_closed and self._write_broken:
                    encoder.discard()

    async def _flush_writer(self, encoder: GzipEncoder) -> None:
        """Drive one reserved encoder flush and normalize its failures."""
        operation = encoder.flush()
        try:
            for flushed_data in operation:
                await self._write_all(flushed_data)

            # Also flush the underlying file if it has a flush method.
            flush_method = getattr(self._file, "flush", None)
            if callable(flush_method):
                result = flush_method()
                if hasattr(result, "__await__"):
                    await result

            # See write(): exceptional context exit can close the sink while
            # this reserved call is awaiting it. Never report that as a
            # successful durability boundary for an unterminated member.
            if self._is_closed or self._write_broken:
                raise OSError(
                    "flush aborted because the gzip file was closed while "
                    "the call was active"
                )
        except asyncio.CancelledError:
            self._write_broken = True
            encoder.discard()
            raise
        except OSError as error:
            self._write_broken = True
            encoder.discard()
            if str(error).startswith("Unexpected error during compression flush:"):
                detail = error.__cause__ if error.__cause__ is not None else error
                raise OSError(f"Unexpected error during flush: {detail}") from error
            raise
        except Exception as error:
            self._write_broken = True
            encoder.discard()
            raise OSError(f"Unexpected error during flush: {error}") from error
        except BaseException:
            self._write_broken = True
            encoder.discard()
            raise

    async def close(self) -> None:
        """Flushes any remaining compressed data and closes the file."""
        if self._is_closed:
            return
        if self._read_call_active:
            self._check_read_call_usable()
        if self._writing_mode:
            self._check_write_call_available()

        # Mark as closed immediately to prevent concurrent close attempts
        self._is_closed = True

        close_file = (
            self._file
            if self._file is not None and (self._owns_file or self._closefd)
            else None
        )
        write_failed = False
        try:
            if self._writing_mode and self._file is not None and not self._write_broken:
                encoder = self._encoder
                if encoder is None:
                    raise RuntimeError("gzip writer encoder is not initialized")
                for final_data in encoder.finish():
                    await self._write_all(final_data)
        except BaseException:
            write_failed = True
            self._write_broken = True
            if self._encoder is not None:
                self._encoder.discard()
            raise
        finally:
            if self._writing_mode and self._write_broken and self._encoder is not None:
                # A torn member must never receive a seemingly valid trailer.
                self._encoder.discard()
            if not self._writing_mode and self._decoder is not None:
                self._decoder.discard()
            if close_file is not None:
                # Close only if we own it or closefd=True. Preserve a prior
                # final-write exception if close() also fails.
                try:
                    await self._close_underlying(close_file)
                except BaseException:
                    if not write_failed:
                        raise

    async def _abort_active_call_on_exit(self) -> None:
        """Close resources without touching a codec operation owned elsewhere."""
        if self._is_closed:
            return
        self._is_closed = True
        if self._writing_mode:
            self._write_broken = True
        else:
            self._read_broken = True
            self._read_validation_failed = False
            self._eof = True

        close_file = (
            self._file
            if self._file is not None and (self._owns_file or self._closefd)
            else None
        )
        if close_file is not None:
            await self._close_underlying(close_file)

    @staticmethod
    async def _close_underlying(file: Any) -> None:
        """Close an owned underlying object, awaiting async close methods."""
        close_method = getattr(file, "close", None)
        if callable(close_method):
            result = close_method()
            if hasattr(result, "__await__"):
                await result

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
