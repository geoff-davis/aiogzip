"""Private asyncio driver for synchronous codec operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from functools import partial
from typing import Final

from . import _engine

_DONE: Final = object()


def _next_or_done(operation: Iterator[bytes], _workload: bytes) -> bytes | object:
    """Advance an operation without leaking StopIteration through a Future."""
    try:
        return next(operation)
    except StopIteration:
        return _DONE


async def _offloaded_next(
    operation: Iterator[bytes], workload: bytes
) -> bytes | object:
    advance = partial(_next_or_done, operation)
    worker = asyncio.create_task(_engine.run_zlib_in_thread(advance, workload))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Executor cancellation does not stop a running codec call. Wait until
        # it can no longer mutate the operation before the caller discards it.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if worker.done() and not worker.cancelled():
            try:
                worker.result()
            except BaseException:
                pass
        raise


async def _drive_operation(
    operation: Iterator[bytes],
    *,
    workload: bytes = b"",
    offload_first_only: bool = False,
) -> AsyncIterator[bytes]:
    """Pull one bounded codec chunk at a time, inline or in an executor."""
    completed = False
    advancing_first = True
    try:
        while True:
            should_offload = len(workload) >= _engine.ZLIB_OFFLOAD_THRESHOLD and (
                advancing_first or not offload_first_only
            )
            if should_offload:
                result = await _offloaded_next(operation, workload)
            else:
                result = _next_or_done(operation, b"")
            advancing_first = False
            if result is _DONE:
                completed = True
                return
            assert isinstance(result, bytes)
            yield result
    except BaseException:
        try:
            close = getattr(operation, "close", None)
            if callable(close):
                close()
        except BaseException:
            pass
        raise
    finally:
        if not completed:
            try:
                close = getattr(operation, "close", None)
                if callable(close):
                    close()
            except BaseException:
                pass
