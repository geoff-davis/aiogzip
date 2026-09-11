"""Private asyncio driver for synchronous codec operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from functools import partial
from typing import Final, TypeVar

from .codec import _AsyncDrivableOperation, _CodecProgress

_DONE: Final = object()
# Below this size, the executor hop costs more than one bounded codec step.
_ZLIB_OFFLOAD_THRESHOLD = 256 * 1024
# A decoder advancement consumes at most one 256 KiB input window. Framework
# measurements show that dispatching every 256–512 KiB source item costs more
# than that bounded work, while larger accepted inputs still benefit from
# first-step offload.
_DECODE_OFFLOAD_THRESHOLD = 1024 * 1024
_INLINE_OUTPUT_BYTES_CHECKPOINT = 1024 * 1024
_INLINE_OUTPUT_CHUNKS_CHECKPOINT = 4096
_NO_OUTPUT_BYTES_CHECKPOINT = 128 * 1024
_NO_OUTPUT_STEPS_CHECKPOINT = 8

_T = TypeVar("_T")


async def _run_in_thread(method: Callable[[bytes], _T], data: bytes) -> _T:
    """Retain one executor call until its last native access has completed."""
    loop = asyncio.get_running_loop()
    return await _settle_before_cancel(loop.run_in_executor(None, method, data))


async def _settle_before_cancel(work: asyncio.Future[_T]) -> _T:
    """Delay cancellation until privately owned work reaches its terminal state.

    Never cancel ``work``: an executor wrapper's cancellation cannot prove that
    its thread stopped. Queued work is allowed to run and settle, too. Retain a
    simultaneous worker failure as the cancellation's cause, and retrieve every
    result so no exception is left unobserved.
    """
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError as cancellation:
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            work.result()
        except BaseException as failure:
            if failure is not cancellation:
                raise cancellation from failure
        raise


async def _cooperative_checkpoint() -> None:
    """Yield once to other ready tasks after bounded inline work."""
    await asyncio.sleep(0)


def _raw_next_or_done(
    operation: _AsyncDrivableOperation,
    _workload: bytes,
) -> bytes | _CodecProgress | object:
    """Advance an operation without leaking StopIteration through a Future."""
    try:
        return operation._advance_raw()
    except StopIteration:
        return _DONE


async def _offloaded_next(
    operation: _AsyncDrivableOperation,
    workload: bytes,
) -> bytes | _CodecProgress | object:
    advance = partial(_raw_next_or_done, operation)
    # No separately cancellable helper: the driver retains the executor future
    # through _run_in_thread until native completion, even during shutdown.
    return await _run_in_thread(advance, workload)


async def _drive_operation(
    operation: _AsyncDrivableOperation,
    *,
    workload: bytes = b"",
    offload_threshold: int = _ZLIB_OFFLOAD_THRESHOLD,
) -> AsyncIterator[bytes]:
    """Pull one bounded codec chunk at a time, inline or in an executor."""
    completed = False
    advancing_first = True
    failed = False
    inline_output_bytes = 0
    inline_output_chunks = 0
    no_output_bytes = 0
    no_output_steps = 0
    try:
        while True:
            should_offload = advancing_first and len(workload) >= offload_threshold
            if should_offload:
                result = await _offloaded_next(operation, workload)
                inline_output_bytes = 0
                inline_output_chunks = 0
                no_output_bytes = 0
                no_output_steps = 0
            else:
                result = _raw_next_or_done(operation, b"")
            advancing_first = False
            if result is _DONE:
                completed = True
                return
            if isinstance(result, _CodecProgress):
                if not should_offload:
                    no_output_bytes += result.compressed_bytes
                    no_output_steps += 1
            else:
                assert isinstance(result, bytes)
                no_output_bytes = 0
                no_output_steps = 0
                if not should_offload:
                    inline_output_bytes += len(result)
                    inline_output_chunks += 1

            should_checkpoint = (
                inline_output_bytes >= _INLINE_OUTPUT_BYTES_CHECKPOINT
                or inline_output_chunks >= _INLINE_OUTPUT_CHUNKS_CHECKPOINT
                or no_output_bytes >= _NO_OUTPUT_BYTES_CHECKPOINT
                or no_output_steps >= _NO_OUTPUT_STEPS_CHECKPOINT
            )
            if should_checkpoint:
                await _cooperative_checkpoint()
                inline_output_bytes = 0
                inline_output_chunks = 0
                no_output_bytes = 0
                no_output_steps = 0

            if isinstance(result, bytes):
                yield result
    except BaseException:
        failed = True
        raise
    finally:
        if not completed:
            try:
                operation.close()
            except BaseException:
                if not failed:
                    raise
