"""Private async-iterable gzip streaming implementations."""

import warnings
from typing import Any, AsyncIterable, AsyncIterator, Optional, Union, cast

from . import _engine
from ._codec_async import (
    _DECODE_OFFLOAD_THRESHOLD,
    _cooperative_checkpoint,
    _drive_operation,
)
from ._common import (
    _validate_chunk_size,
    _validate_optional_positive_int,
)
from .codec import (
    GzipDecoder,
    GzipEncoder,
    _AsyncDrivableOperation,
    _snapshot_bytes_input,
)

_INLINE_SOURCE_BYTES_CHECKPOINT = 16 * 1024 * 1024


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
    decoder = GzipDecoder(
        max_decompressed_size=max_decompressed_size,
        output_chunk_size=output_chunk_size,
        collect_member_info=False,
    )
    iterator = source.__aiter__()
    if not callable(getattr(iterator, "__anext__", None)):
        decoder.discard()
        raise TypeError("source.__aiter__() must return an asynchronous iterator")
    failed = False
    inline_source_bytes = 0
    try:
        while True:
            try:
                compressed = await iterator.__anext__()
            except StopAsyncIteration:
                break
            if not isinstance(compressed, bytes):
                raise TypeError("decompress_chunks() source items must be bytes")
            snapshot = _snapshot_bytes_input(compressed)
            if not snapshot:
                continue
            offloaded = len(snapshot) >= _DECODE_OFFLOAD_THRESHOLD
            if offloaded:
                inline_source_bytes = 0
            elif inline_source_bytes >= _INLINE_SOURCE_BYTES_CHECKPOINT:
                await _cooperative_checkpoint()
                inline_source_bytes = 0
            async for output in _drive_operation(
                cast(_AsyncDrivableOperation, decoder.feed(snapshot)),
                workload=snapshot,
                offload_threshold=_DECODE_OFFLOAD_THRESHOLD,
            ):
                yield output
            if not offloaded:
                inline_source_bytes += len(snapshot)

        async for output in _drive_operation(
            cast(_AsyncDrivableOperation, decoder.finish())
        ):
            yield output
    except BaseException:
        failed = True
        raise
    finally:
        decoder.discard()
        await _close_async_iterator(iterator, failed=failed)


def _compress_chunks(
    source: AsyncIterable[bytes],
    *,
    compresslevel: int,
    mtime: Optional[Union[int, float]],
    original_filename: Optional[Union[str, bytes]],
    fast_compress: bool,
    strict_size: bool,
    output_chunk_size: int,
) -> AsyncIterator[bytes]:
    """Validate arguments and return the one-member compression generator."""
    if not callable(getattr(source, "__aiter__", None)):
        raise TypeError("source must be an asynchronous iterable of bytes")
    options: dict[str, Any] = {
        "compresslevel": compresslevel,
        "mtime": mtime,
        "original_filename": original_filename,
        "fast_compress": fast_compress,
        "strict_size": strict_size,
        "output_chunk_size": output_chunk_size,
    }
    if fast_compress and not _engine.have_fast_engine():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            encoder = GzipEncoder(**options)
        for warning in caught:
            warnings.warn(str(warning.message), warning.category, stacklevel=3)
    else:
        encoder = GzipEncoder(**options)
    return _compress_chunks_impl(source, encoder)


async def _compress_chunks_impl(
    source: AsyncIterable[bytes], encoder: GzipEncoder
) -> AsyncIterator[bytes]:
    """Emit one gzip member without reading ahead from the async source."""
    iterator = source.__aiter__()
    if not callable(getattr(iterator, "__anext__", None)):
        encoder.discard()
        raise TypeError("source.__aiter__() must return an asynchronous iterator")
    failed = False
    try:
        async for output in _drive_operation(
            cast(_AsyncDrivableOperation, encoder.start())
        ):
            yield output

        while True:
            try:
                uncompressed = await iterator.__anext__()
            except StopAsyncIteration:
                break
            if not isinstance(uncompressed, bytes):
                raise TypeError("compress_chunks() source items must be bytes")
            snapshot = _snapshot_bytes_input(uncompressed)
            if not snapshot:
                continue
            async for output in _drive_operation(
                encoder._feed_snapshot(snapshot),
                workload=snapshot,
            ):
                yield output

        async for output in _drive_operation(
            cast(_AsyncDrivableOperation, encoder.finish())
        ):
            yield output
    except BaseException:
        failed = True
        raise
    finally:
        encoder.discard()
        await _close_async_iterator(iterator, failed=failed)


async def _close_async_iterator(iterator: Any, *, failed: bool) -> None:
    """Close a source iterator without replacing an active operation error."""
    close = getattr(iterator, "aclose", None)
    if not callable(close):
        return
    try:
        result: Any = close()
        if hasattr(result, "__await__"):
            await result
    except BaseException:
        if not failed:
            raise
