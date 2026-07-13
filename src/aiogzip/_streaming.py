"""Private async-iterable gzip streaming implementations."""

import asyncio
import warnings
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Iterator,
    Optional,
    Union,
    cast,
)

from . import _engine
from ._common import (
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
from ._inspection import _IncrementalGzipDecoder


class _IncrementalGzipEncoder:
    """Incrementally encode exactly one gzip member with bounded output."""

    def __init__(
        self,
        *,
        compresslevel: int,
        mtime: Optional[Union[int, float]],
        original_filename: Optional[Union[str, bytes]],
        fast_compress: bool,
        strict_size: bool,
        output_chunk_size: int,
    ) -> None:
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
                stacklevel=3,
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
        self._failed = False
        self._active = False

    @property
    def input_size(self) -> int:
        return self._input_size

    @property
    def crc32(self) -> int:
        return self._crc

    def _output_chunks(self, data: bytes) -> Iterator[bytes]:
        for offset in range(0, len(data), self._output_chunk_size):
            yield data[offset : offset + self._output_chunk_size]

    def _check_available(self) -> None:
        if self._finished:
            raise ValueError("gzip encoder is already finalized")
        if self._failed:
            raise OSError("gzip encoder is unusable after a prior failure")

    def start(self) -> Iterator[bytes]:
        """Start the member and return bounded chunks of its gzip header."""
        self._check_available()
        if self._started:
            raise ValueError("gzip encoder is already started")
        self._started = True
        header = _build_gzip_header(self._filename, self._mtime, self._compresslevel)
        return self._output_chunks(header)

    def feed(self, data: bytes) -> AsyncIterator[bytes]:
        """Consume one uncompressed bytes chunk and yield compressed output."""
        self._check_available()
        if not self._started:
            raise ValueError("gzip encoder must be started before feeding data")
        if not isinstance(data, bytes):
            raise TypeError("gzip encoder input must be bytes")
        if self._strict_size and self._input_size + len(data) > 0xFFFFFFFF:
            raise OSError(
                f"uncompressed member size would exceed the gzip ISIZE "
                f"field's 4 GiB limit ({self._input_size} + {len(data)} > "
                f"{0xFFFFFFFF}); drop strict_size to allow ISIZE "
                f"truncation or split the payload into multiple members"
            )
        return self._feed(data)

    def finish(self) -> AsyncIterator[bytes]:
        """Finalize deflate exactly once and emit the gzip trailer."""
        self._check_available()
        if not self._started:
            raise ValueError("gzip encoder must be started before finalizing")
        return self._finish()

    def discard(self) -> None:
        """Irreversibly release codec state without emitting final bytes."""
        self._failed = True
        self._engine = None

    async def _feed(self, data: bytes) -> AsyncIterator[bytes]:
        if self._active:
            raise RuntimeError("gzip encoder cannot be advanced concurrently")
        self._active = True
        completed = False
        try:
            try:
                if len(data) >= _engine.ZLIB_OFFLOAD_THRESHOLD:
                    compressed = await _engine.run_zlib_in_thread(
                        self._engine.compress, data
                    )
                else:
                    compressed = cast(bytes, self._engine.compress(data))
            except asyncio.CancelledError:
                raise
            except _engine.ZLIB_ERRORS as error:
                raise OSError(f"Error compressing data: {error}") from error
            except Exception as error:
                raise OSError(
                    f"Unexpected error during compression: {error}"
                ) from error

            self._crc = _engine.crc32(data, self._crc) & 0xFFFFFFFF
            self._input_size += len(data)
            for output in self._output_chunks(compressed):
                yield output
            completed = True
        except BaseException:
            self._failed = True
            self._engine = None
            raise
        finally:
            self._active = False
            if not completed:
                self._failed = True
                self._engine = None

    async def _finish(self) -> AsyncIterator[bytes]:
        if self._active:
            raise RuntimeError("gzip encoder cannot be advanced concurrently")
        self._active = True
        completed = False
        try:
            try:
                remaining = cast(bytes, self._engine.flush())
            except _engine.ZLIB_ERRORS as error:
                raise OSError(f"Error finalizing compressed data: {error}") from error
            except Exception as error:
                raise OSError(
                    f"Unexpected error during compression finalization: {error}"
                ) from error
            trailer = _build_gzip_trailer(self._crc, self._input_size)
            self._finished = True
            for output in self._output_chunks(remaining):
                yield output
            for output in self._output_chunks(trailer):
                yield output
            completed = True
        except BaseException:
            self._failed = True
            raise
        finally:
            self._active = False
            self._engine = None
            if not completed:
                self._failed = True


def _decompress_chunks(
    source: AsyncIterable[bytes],
    *,
    output_chunk_size: int,
    max_decompressed_size: Optional[int],
) -> AsyncIterator[bytes]:
    """Validate call-time arguments and return the decompression generator."""
    if not callable(getattr(source, "__aiter__", None)):
        raise TypeError("source must be an asynchronous iterable of bytes")
    _validate_chunk_size(output_chunk_size)
    _validate_optional_positive_int(max_decompressed_size, "max_decompressed_size")
    return _decompress_chunks_impl(
        source,
        output_chunk_size=output_chunk_size,
        max_decompressed_size=max_decompressed_size,
    )


async def _decompress_chunks_impl(
    source: AsyncIterable[bytes],
    *,
    output_chunk_size: int,
    max_decompressed_size: Optional[int],
) -> AsyncIterator[bytes]:
    """Pull compressed input only as bounded decompressed output is requested."""
    decoder = _IncrementalGzipDecoder(
        max_decompressed_size=max_decompressed_size,
        output_chunk_size=output_chunk_size,
        collect_member_info=False,
    )
    iterator = source.__aiter__()
    if not callable(getattr(iterator, "__anext__", None)):
        raise TypeError("source.__aiter__() must return an asynchronous iterator")
    failed = False
    try:
        while True:
            try:
                compressed = await iterator.__anext__()
            except StopAsyncIteration:
                break
            if not isinstance(compressed, bytes):
                raise TypeError("decompress_chunks() source items must be bytes")
            if not compressed:
                continue
            async for output in decoder.feed(compressed):
                yield output

        async for output in decoder.finish():
            yield output
    except BaseException:
        failed = True
        raise
    finally:
        decoder.discard()
        close = getattr(iterator, "aclose", None)
        if callable(close):
            try:
                result: Any = close()
                if hasattr(result, "__await__"):
                    await result
            except BaseException:
                if not failed:
                    raise
