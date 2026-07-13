"""Private async-iterable gzip streaming implementations."""

from typing import Any, AsyncIterable, AsyncIterator, Optional

from ._common import _validate_chunk_size, _validate_optional_positive_int
from ._inspection import _IncrementalGzipDecoder


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
