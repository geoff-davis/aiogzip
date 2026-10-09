"""Private asyncio driver for synchronous codec operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
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


@dataclass(slots=True)
class _StreamBudget:
    """Cooperative work retained across operations of one iterable stream."""

    source_items: int = 0
    source_bytes: int = 0
    output_bytes: int = 0
    output_chunks: int = 0
    no_output_bytes: int = 0
    no_output_steps: int = 0

    def reset(self) -> None:
        self.source_items = self.source_bytes = 0
        self.output_bytes = self.output_chunks = 0
        self.no_output_bytes = self.no_output_steps = 0


async def _run_in_thread(method: Callable[[bytes], _T], data: bytes) -> _T:
    """Retain one executor call until its last native access has completed."""
    loop = asyncio.get_running_loop()
    return await _settle_before_cancel(loop.run_in_executor(None, method, data))


def _completion_waiter(work: asyncio.Future[_T]) -> asyncio.Future[None]:
    """Return a private future that completes when ``work`` does.

    Unlike ``asyncio.shield``, the waiter never retrieves ``work``'s outcome,
    so the caller alone observes it. Since Python 3.14, a cancelled shield
    makes the loop log a later failure of the inner future even after the
    caller retrieved and chained it.
    """
    waiter: asyncio.Future[None] = work.get_loop().create_future()

    def wake(_: asyncio.Future[_T]) -> None:
        if not waiter.done():
            waiter.set_result(None)

    work.add_done_callback(wake)
    waiter.add_done_callback(lambda _: work.remove_done_callback(wake))
    return waiter


async def _settle_before_cancel(work: asyncio.Future[_T]) -> _T:
    """Delay cancellation until privately owned work reaches its terminal state.

    Never cancel ``work``: an executor wrapper's cancellation cannot prove that
    its thread stopped. Queued work is allowed to run and settle, too. Retain a
    simultaneous worker failure as the cancellation's cause, and retrieve every
    result so no exception is left unobserved.
    """
    cancellation: asyncio.CancelledError | None = None
    while not work.done():
        try:
            await _completion_waiter(work)
        except asyncio.CancelledError as cancelled:
            if cancellation is None:
                cancellation = cancelled
    if cancellation is None:
        return work.result()
    try:
        work.result()
    except BaseException as failure:
        raise cancellation from failure
    raise cancellation


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
    budget: _StreamBudget | None = None,
    first_result: object = None,
) -> AsyncIterator[bytes]:
    """Pull bounded chunks; ``None`` means no inline result was supplied."""
    completed = False
    advancing_first = first_result is None
    failed = False
    inline_output_bytes = 0
    inline_output_chunks = 0
    no_output_bytes = 0
    no_output_steps = 0
    if budget is not None:
        inline_output_bytes = budget.output_bytes
        inline_output_chunks = budget.output_chunks
        no_output_bytes = budget.no_output_bytes
        no_output_steps = budget.no_output_steps
    try:
        while True:
            should_offload = advancing_first and len(workload) >= offload_threshold
            if should_offload:
                result = await _offloaded_next(operation, workload)
                # Iterable streams deliberately do not count executor waits
                # as budget checkpoints, even though those waits yield. Their
                # counters reset only at an explicit cooperative checkpoint.
                if budget is None:
                    inline_output_bytes = 0
                    inline_output_chunks = 0
                    no_output_bytes = 0
                    no_output_steps = 0
            elif first_result is not None:
                # A small compression feed may already have advanced inline.
                # Account for that result exactly once before advancing again.
                result = first_result
                first_result = None
            else:
                result = _raw_next_or_done(operation, b"")
            advancing_first = False
            if result is _DONE:
                completed = True
                return
            if isinstance(result, _CodecProgress):
                if not should_offload or budget is not None:
                    no_output_bytes += result.compressed_bytes
                    no_output_steps += 1
            else:
                assert isinstance(result, bytes)
                no_output_bytes = 0
                no_output_steps = 0
                if not should_offload or budget is not None:
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
                if budget is not None:
                    budget.reset()
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
        if budget is not None:
            budget.output_bytes = inline_output_bytes
            budget.output_chunks = inline_output_chunks
            budget.no_output_bytes = no_output_bytes
            budget.no_output_steps = no_output_steps
        if not completed:
            try:
                operation.close()
            except BaseException:
                if not failed:
                    raise
