"""Private async-iterable gzip streaming implementations."""

from typing import (
    Any,
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Optional,
    Union,
    cast,
)

from . import _engine
from ._codec_async import (
    _DECODE_OFFLOAD_THRESHOLD,
    _DONE,
    _ZLIB_OFFLOAD_THRESHOLD,
    _cooperative_checkpoint,
    _drive_operation,
    _raw_next_or_done,
    _StreamBudget,
)
from ._common import (
    _validate_bool,
    _validate_chunk_size,
    _validate_optional_positive_int,
)
from ._opening import _settle_cleanup_failure
from .codec import (
    GzipDecoder,
    GzipEncoder,
    _AsyncDrivableOperation,
    _snapshot_bytes_input,
)

# Source budgets complement shared codec work/output budgets. Count empty
# items too, and checkpoint before asking the source for another item.
_INLINE_SOURCE_BYTES_CHECKPOINT = 16 * 1024 * 1024
_SOURCE_ITEMS_CHECKPOINT = 256
# Compression of a small item runs inline, and its cost follows the input,
# not the output: highly compressible input reaches no output checkpoint.
# Bound the input compressed inline between turns to two offload thresholds,
# so the longest stretch stays of the order of one inline feed.
_INLINE_COMPRESS_BYTES_CHECKPOINT = 2 * _ZLIB_OFFLOAD_THRESHOLD


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
    failure: Optional[BaseException] = None
    budget = _StreamBudget()
    # The driver in use, closed below: an early aclose() would otherwise
    # leave it to the event loop's asynchronous-generator hook.
    driver: Optional[AsyncGenerator[bytes, None]] = None
    try:
        while True:
            if (
                budget.source_items >= _SOURCE_ITEMS_CHECKPOINT
                or budget.source_bytes >= _INLINE_SOURCE_BYTES_CHECKPOINT
            ):
                await _cooperative_checkpoint()
                budget.reset()
            try:
                compressed = await iterator.__anext__()
            except StopAsyncIteration:
                break
            if not isinstance(compressed, bytes):
                raise TypeError("decompress_chunks() source items must be bytes")
            snapshot = _snapshot_bytes_input(compressed)
            budget.source_items += 1
            budget.source_bytes += len(snapshot)
            if not snapshot:
                continue
            driver = _drive_operation(
                cast(_AsyncDrivableOperation, decoder.feed(snapshot)),
                workload=snapshot,
                offload_threshold=_DECODE_OFFLOAD_THRESHOLD,
                budget=budget,
            )
            async for output in driver:
                yield output

        driver = _drive_operation(
            cast(_AsyncDrivableOperation, decoder.finish()), budget=budget
        )
        async for output in driver:
            yield output
    except BaseException as error:
        failure = error
        raise
    finally:
        decoder.discard()
        try:
            if driver is not None:
                await driver.aclose()
        finally:
            await _close_async_iterator(iterator, failure)


class _ChunkStreamEncoder(GzipEncoder):
    """The encoder as built by ``compress_chunks()``, two frames deeper."""

    _fallback_warning_stacklevel = 4


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
    validated_fast_compress = _validate_bool(fast_compress, "fast_compress")
    validated_strict_size = _validate_bool(strict_size, "strict_size")
    if not callable(getattr(source, "__aiter__", None)):
        raise TypeError("source must be an asynchronous iterable of bytes")
    options: dict[str, Any] = {
        "compresslevel": compresslevel,
        "mtime": mtime,
        "original_filename": original_filename,
        "fast_compress": validated_fast_compress,
        "strict_size": validated_strict_size,
        "output_chunk_size": output_chunk_size,
    }
    encoder_type = GzipEncoder
    if validated_fast_compress and not _engine.have_fast_engine():
        # The encoder warns about the fallback itself. From here its caller
        # is two frames further out, so the warning names the code that
        # called compress_chunks() and Python's once-per-location filter
        # applies. Capturing and re-issuing the warning needed
        # catch_warnings(), which resets every module's warning registry.
        encoder_type = _ChunkStreamEncoder
    encoder = encoder_type(**options)
    return _compress_chunks_impl(source, encoder)


async def _compress_chunks_impl(
    source: AsyncIterable[bytes], encoder: GzipEncoder
) -> AsyncIterator[bytes]:
    """Emit one gzip member without reading ahead from the async source."""
    iterator = source.__aiter__()
    if not callable(getattr(iterator, "__anext__", None)):
        encoder.discard()
        raise TypeError("source.__aiter__() must return an asynchronous iterator")
    failure: Optional[BaseException] = None
    budget = _StreamBudget()
    # The driver in use, closed below: an early aclose() would otherwise
    # leave it to the event loop's asynchronous-generator hook.
    driver: Optional[AsyncGenerator[bytes, None]] = None
    try:
        driver = _drive_operation(
            cast(_AsyncDrivableOperation, encoder.start()), budget=budget
        )
        async for output in driver:
            yield output

        while True:
            if (
                budget.source_items >= _SOURCE_ITEMS_CHECKPOINT
                or budget.source_bytes >= _INLINE_SOURCE_BYTES_CHECKPOINT
                or budget.inline_input_bytes >= _INLINE_COMPRESS_BYTES_CHECKPOINT
            ):
                await _cooperative_checkpoint()
                budget.reset()
            try:
                uncompressed = await iterator.__anext__()
            except StopAsyncIteration:
                break
            if not isinstance(uncompressed, bytes):
                raise TypeError("compress_chunks() source items must be bytes")
            snapshot = _snapshot_bytes_input(uncompressed)
            budget.source_items += 1
            budget.source_bytes += len(snapshot)
            if not snapshot:
                continue
            operation = encoder._feed_snapshot(snapshot)
            first_result = None
            if len(snapshot) < _ZLIB_OFFLOAD_THRESHOLD:
                budget.inline_input_bytes += len(snapshot)
                # Most small compression feeds complete without output. Avoid
                # constructing an async driver for that already-finished work.
                try:
                    first_result = _raw_next_or_done(operation, b"")
                except BaseException:
                    try:
                        operation.close()
                    except BaseException:
                        pass
                    raise
                if first_result is _DONE:
                    continue
            driver = _drive_operation(
                operation,
                workload=snapshot,
                budget=budget,
                first_result=first_result,
            )
            async for output in driver:
                yield output

        driver = _drive_operation(
            cast(_AsyncDrivableOperation, encoder.finish()), budget=budget
        )
        async for output in driver:
            yield output
    except BaseException as error:
        failure = error
        raise
    finally:
        encoder.discard()
        try:
            if driver is not None:
                await driver.aclose()
        finally:
            await _close_async_iterator(iterator, failure)


async def _close_async_iterator(
    iterator: Any, failure: Optional[BaseException]
) -> None:
    """Close a source iterator, keeping the precedence of an active failure.

    A cancellation or interrupt that arrives during the close outranks an
    ordinary stream failure or the consumer's early close; any other cleanup
    failure is noted on the active failure.
    """
    close = getattr(iterator, "aclose", None)
    if not callable(close):
        return
    try:
        result: Any = close()
        if hasattr(result, "__await__"):
            await result
    except BaseException as cleanup:
        if failure is None:
            raise
        _settle_cleanup_failure(
            failure, cleanup, "Source", outranked=(Exception, GeneratorExit)
        )
