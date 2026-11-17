"""Private one-shot gzip helpers for a payload already in memory.

Each call drives one codec through the shared asyncio driver, so the offload
thresholds, the cooperative checkpoints and the rule that a cancelled call
waits for its native step are the ones the chunk streams use.
"""

from typing import Any, Optional, Union, cast

from ._codec_async import (
    _DECODE_OFFLOAD_THRESHOLD,
    _drive_operation,
)
from ._common import _MAX_CHUNK_SIZE
from .codec import (
    GzipDecoder,
    GzipEncoder,
    _AsyncDrivableOperation,
    _OutputCollector,
    _snapshot_bytes_input,
)


def _snapshot(data: Any, name: str) -> bytes:
    """Return an exact immutable copy of the caller's payload, taken once."""
    if isinstance(data, bytes):
        return _snapshot_bytes_input(data)
    if not isinstance(data, (bytearray, memoryview)):
        raise TypeError(
            f"{name}() argument must be bytes, bytearray or memoryview, "
            f"not {type(data).__name__}"
        )
    # tobytes() flattens a non-contiguous or multi-byte view.
    return memoryview(data).tobytes()


async def _collect(
    output: _OutputCollector,
    operation: object,
    workload: bytes = b"",
    **options: Any,
) -> None:
    driver = _drive_operation(
        cast(_AsyncDrivableOperation, operation), workload=workload, **options
    )
    try:
        async for chunk in driver:
            output.add(chunk)
    finally:
        # A failure in this loop's own body leaves the driver suspended.
        # Close it here so the operation is released before the codec is
        # discarded, not by the event loop's generator hook later.
        await driver.aclose()


async def _compress(
    data: Union[bytes, bytearray, memoryview],
    *,
    compresslevel: int,
    mtime: Optional[Union[int, float]],
    original_filename: Optional[Union[str, bytes]],
    fast_compress: bool,
    strict_size: bool,
) -> bytes:
    snapshot = _snapshot(data, "compress")
    # The encoder validates the options, and attributes a zlib-ng fallback
    # warning to the code that awaited compress().
    encoder = GzipEncoder(
        compresslevel=compresslevel,
        mtime=mtime,
        original_filename=original_filename,
        fast_compress=fast_compress,
        strict_size=strict_size,
        output_chunk_size=_MAX_CHUNK_SIZE,
    )
    output = _OutputCollector()
    try:
        await _collect(output, encoder.start())
        if snapshot:
            await _collect(output, encoder.feed(snapshot), snapshot)
        await _collect(output, encoder.finish())
    finally:
        encoder.discard()
    return output.join()


async def _decompress(
    data: Union[bytes, bytearray, memoryview],
    *,
    max_decompressed_size: Optional[int],
    max_members: Optional[int],
) -> bytes:
    snapshot = _snapshot(data, "decompress")
    decoder = GzipDecoder(
        max_decompressed_size=max_decompressed_size, max_members=max_members
    )
    output = _OutputCollector()
    try:
        if snapshot:
            await _collect(
                output,
                decoder.feed(snapshot),
                snapshot,
                offload_threshold=_DECODE_OFFLOAD_THRESHOLD,
            )
        await _collect(output, decoder.finish())
    finally:
        decoder.discard()
    return output.join()
