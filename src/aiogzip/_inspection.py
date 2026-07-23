"""Gzip stream inspection result types and private scanner internals."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple, Union

import aiofiles

from ._codec_async import _drive_operation
from ._common import (
    WithAsyncRead,
    WithAsyncReadWrite,
    _validate_chunk_size,
    _validate_filename,
    _validate_optional_positive_int,
)
from ._metadata import GzipInfo, GzipMemberInfo, VerificationResult
from .codec import GzipDecoder, _snapshot_bytes_input

__all__ = ["GzipInfo", "GzipMemberInfo", "VerificationResult"]

_Filename = Union[str, bytes, Path, None]
_ReadFileObj = Optional[Union[WithAsyncRead, WithAsyncReadWrite]]


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
    _validate_filename(filename, fileobj)
    _validate_chunk_size(chunk_size)
    _validate_optional_positive_int(max_decompressed_size, "max_decompressed_size")

    source: Any
    owns_source = fileobj is None
    if fileobj is None:
        assert filename is not None
        source = await aiofiles.open(filename, "rb")
    else:
        source = fileobj
    should_close = owns_source or bool(closefd)

    decoder = GzipDecoder(
        max_decompressed_size=max_decompressed_size,
        output_chunk_size=chunk_size,
        collect_member_info=collect_members,
    )
    scan_failed = False
    try:
        while True:
            try:
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
            async for _ in _drive_operation(decoder.feed(snapshot), workload=snapshot):
                pass
        async for _ in _drive_operation(decoder.finish()):
            pass
        return _ScanResult(
            members=decoder.members,
            member_count=decoder.member_count,
            compressed_size=decoder.compressed_size,
            uncompressed_size=decoder.uncompressed_size,
        )
    except BaseException:
        scan_failed = True
        raise
    finally:
        decoder.discard()
        if should_close:
            close_method = getattr(source, "close", None)
            if callable(close_method):
                try:
                    result = close_method()
                    if hasattr(result, "__await__"):
                        await result
                except BaseException:
                    if not scan_failed:
                        raise
