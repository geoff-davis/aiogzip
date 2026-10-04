"""Private acquisition and initialization settlement; no published handle state."""

import asyncio
from typing import Any, cast

import aiofiles
import aiofiles.threadpool

from ._codec_async import _settle_before_cancel
from ._source_io import _is_native_source

_STANDARD_OPEN = aiofiles.open


async def _initial_call(file: Any, method: str, *args: Any) -> Any:
    """Settle supported native initialization/cleanup before releasing its owner."""
    if _is_native_source(file, method):
        loop = asyncio.get_running_loop()
        if file._loop is not loop:
            raise RuntimeError("aiofiles source belongs to a different event loop")
        work = loop.run_in_executor(file._executor, getattr(file._file, method), *args)
        return await _settle_before_cancel(work)
    result = getattr(file, method)(*args)
    if method == "write" or hasattr(result, "__await__"):
        return await result
    return result


async def _acquire_path(filename: Any, mode: str, opener: Any) -> Any:
    """Retain a native acquisition result even if the opening task is cancelled."""
    if opener is not _STANDARD_OPEN:
        # Custom replacements retain their existing cooperative async contract.
        return await opener(filename, mode)
    loop = asyncio.get_running_loop()
    # aiofiles exposes this runtime delegate but omits it from its type stubs.
    sync_open = cast(Any, aiofiles.threadpool).sync_open
    work = loop.run_in_executor(None, sync_open, filename, mode)
    try:
        raw = await _settle_before_cancel(work)
    except asyncio.CancelledError as cancellation:
        # Settlement has completed. Never lose a successfully acquired resource
        # merely because its asyncio caller must report cancellation.
        try:
            raw = work.result()
        except BaseException as failure:
            raise cancellation from failure
        try:
            await _settle_before_cancel(loop.run_in_executor(None, raw.close))
        except BaseException as cleanup:
            cancellation.add_note(f"Opening cleanup also failed: {cleanup!r}")
        raise
    try:
        return aiofiles.threadpool.wrap(raw, loop=loop)
    except BaseException as failure:
        try:
            await _settle_before_cancel(loop.run_in_executor(None, raw.close))
        except BaseException as cleanup:
            # Outside cancellation/interrupts outrank an ordinary failure.
            if isinstance(failure, Exception) and not isinstance(cleanup, Exception):
                if cleanup.__context__ is None:
                    cleanup.__context__ = failure
                raise
            failure.add_note(f"Opening cleanup also failed: {cleanup!r}")
        raise


async def _write_initial_header(file: Any, data: bytes) -> None:
    """Finish the opening header before publication, including short writes."""
    offset = 0
    while offset < len(data):
        written = await _initial_call(file, "write", data[offset:])
        if not isinstance(written, int) or isinstance(written, bool):
            raise OSError(
                f"underlying file write() returned an invalid byte count ({written!r})"
            )
        if written <= 0:
            raise OSError("underlying file write() made no progress")
        remaining = len(data) - offset
        if written > remaining:
            raise OSError(
                "underlying file write() returned more bytes than requested "
                f"({written} > {remaining})"
            )
        offset += written


async def _initial_seekable(file: Any) -> bool:
    if not callable(getattr(file, "seek", None)):
        return False
    if not callable(getattr(file, "seekable", None)):
        return True
    try:
        result = await _initial_call(file, "seekable")
    except Exception:
        return False
    return bool(result)
