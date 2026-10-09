"""Gzip stream inspection result types and private scanner internals."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple, Union, cast

import aiofiles

from ._codec_async import (
    _DECODE_OFFLOAD_THRESHOLD,
    _drive_operation,
    _settle_before_cancel,
)
from ._common import (
    WithAsyncRead,
    WithAsyncReadWrite,
    _validate_chunk_size,
    _validate_filename,
    _validate_optional_bool,
    _validate_optional_positive_int,
)
from ._metadata import GzipInfo, GzipMemberInfo, VerificationResult
from ._opening import _acquire_path, _initial_call
from ._source_io import _is_native_source, _NativeSourceCall
from .codec import GzipDecoder, _AsyncDrivableOperation, _snapshot_bytes_input

__all__ = ["GzipInfo", "GzipMemberInfo", "VerificationResult"]

_Filename = Union[str, bytes, Path, None]
_ReadFileObj = Optional[Union[WithAsyncRead, WithAsyncReadWrite]]


def _note_cleanup_failure(failure: BaseException, cleanup: BaseException) -> None:
    """Note a source cleanup failure on the exception that keeps precedence.

    A repeated cancellation during cleanup is not itself a failure, but
    settlement may raise it from one (a failed native close); note that cause,
    as the file handles' context exit does.
    """
    if isinstance(cleanup, asyncio.CancelledError):
        cause = cleanup.__cause__
        if cause is None or isinstance(cause, asyncio.CancelledError):
            return
        cleanup = cause
    failure.add_note(f"Source cleanup also failed: {cleanup!r}")


async def _read_native(source: Any, size: int) -> Any:
    """Read a native aiofiles source; a cancelled read settles before it raises.

    Cleanup must never close a source still being read. Unlike
    ``_initial_call``, a successful read awaits the executor directly, with no
    shield; only a cancellation pays for settlement, which also stops a read
    the worker has not yet entered from touching the source at all.
    """
    loop = asyncio.get_running_loop()
    if source._loop is not loop:
        raise RuntimeError("aiofiles source belongs to a different event loop")
    call = _NativeSourceCall(source._file, "read", (size,), loop, track_position=False)
    try:
        return await loop.run_in_executor(source._executor, call)
    except asyncio.CancelledError as cancellation:
        try:
            await _settle_before_cancel(call.completion(cancel_pending=True))
        except asyncio.CancelledError:
            pass  # Settlement has finished; keep the first cancellation.
        if not call.prevented:
            try:
                call.result()
            except BaseException as failure:
                raise cancellation from failure
        raise cancellation


@dataclass(frozen=True)
class _ScanResult:
    members: Tuple[GzipMemberInfo, ...]
    member_count: int
    compressed_size: int
    uncompressed_size: int


async def _scan_gzip(
    filename: _Filename,
    *,
    fileobj: _ReadFileObj,
    closefd: Optional[bool],
    max_decompressed_size: Optional[int],
    chunk_size: int,
    collect_members: bool,
) -> _ScanResult:
    """Read and validate a complete gzip source without retaining payload."""
    validated_closefd = _validate_optional_bool(closefd, "closefd")
    _validate_filename(filename, fileobj)
    _validate_chunk_size(chunk_size)
    _validate_optional_positive_int(max_decompressed_size, "max_decompressed_size")

    source: Any
    owns_source = fileobj is None
    if fileobj is None:
        assert filename is not None
        # A cancelled native open settles and closes a late file (as BC3).
        source = await _acquire_path(filename, "rb", aiofiles.open)
    else:
        source = fileobj
    should_close = owns_source or validated_closefd is True

    decoder: Optional[GzipDecoder] = None
    failure: Optional[BaseException] = None
    try:
        decoder = GzipDecoder(
            max_decompressed_size=max_decompressed_size,
            output_chunk_size=chunk_size,
            collect_member_info=collect_members,
        )
        while True:
            try:
                if _is_native_source(source, "read"):
                    chunk = await _read_native(source, chunk_size)
                else:
                    chunk = await source.read(chunk_size)
            except OSError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise OSError(f"Error reading from file: {error}") from error
            if not isinstance(chunk, bytes):
                raise TypeError("binary gzip source read() must return bytes")
            snapshot = _snapshot_bytes_input(chunk)
            if not snapshot:
                break
            async for _ in _drive_operation(
                cast(_AsyncDrivableOperation, decoder.feed(snapshot)),
                workload=snapshot,
                offload_threshold=_DECODE_OFFLOAD_THRESHOLD,
            ):
                pass
        async for _ in _drive_operation(
            cast(_AsyncDrivableOperation, decoder.finish())
        ):
            pass
        return _ScanResult(
            members=decoder.members,
            member_count=decoder.member_count,
            compressed_size=decoder.compressed_size,
            uncompressed_size=decoder.uncompressed_size,
        )
    except BaseException as error:
        failure = error
        raise
    finally:
        if decoder is not None:
            decoder.discard()
        if should_close:
            close_method = getattr(source, "close", None)
            if callable(close_method):
                try:
                    if _is_native_source(source, "close"):
                        # A cancelled native close still runs and settles.
                        await _initial_call(source, "close")
                    else:
                        result = close_method()
                        if hasattr(result, "__await__"):
                            await result
                except BaseException as cleanup:
                    if failure is None:
                        raise
                    # An outside cancellation or interrupt outranks an ordinary
                    # scan failure, which stays its context; otherwise the
                    # primary failure is kept and the cleanup failure noted.
                    if isinstance(failure, Exception) and not isinstance(
                        cleanup, Exception
                    ):
                        if cleanup.__context__ is None:
                            cleanup.__context__ = failure
                        raise
                    _note_cleanup_failure(failure, cleanup)
