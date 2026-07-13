"""Async gzip file reader/writer public API."""

from pathlib import Path
from typing import Any, AsyncIterable, AsyncIterator, Literal, Optional, Union, overload

from ._binary import AsyncGzipBinaryFile
from ._common import (
    _MAX_CHUNK_SIZE,
    GZIP_FLAG_FCOMMENT,
    GZIP_FLAG_FEXTRA,
    GZIP_FLAG_FHCRC,
    GZIP_FLAG_FNAME,
    GZIP_METHOD_DEFLATE,
    GZIP_OS_UNKNOWN,
    GZIP_WBITS,
    WithAsyncRead,
    WithAsyncReadWrite,
    WithAsyncWrite,
    ZlibEngine,
)
from ._engine import EngineInfo, engine_info
from ._inspection import (
    GzipInfo,
    GzipMemberInfo,
    VerificationResult,
    _scan_gzip,
)
from ._streaming import _compress_chunks, _decompress_chunks
from ._text import AsyncGzipTextFile

__version__ = "1.10.1"

# Mode strings that select a text stream (they contain a 't'). The factory
# parses modes character-by-character and is permutation-tolerant, so these
# enumerate the conventional spellings (mirroring typeshed's open/gzip.open
# overloads); unusual permutations fall through to the str fallback overload.
_TextMode = Literal[
    "rt",
    "wt",
    "at",
    "xt",
    "tr",
    "tw",
    "ta",
    "tx",
    "rt+",
    "wt+",
    "at+",
    "xt+",
    "tr+",
    "tw+",
    "ta+",
    "tx+",
    "r+t",
    "w+t",
    "a+t",
    "x+t",
    "t+r",
    "t+w",
    "t+a",
    "t+x",
    "+rt",
    "+wt",
    "+at",
    "+xt",
    "+tr",
    "+tw",
    "+ta",
    "+tx",
]

# Mode strings that select a binary stream (no 't'); the 'b' is optional.
_BinaryMode = Literal[
    "r",
    "w",
    "a",
    "x",
    "rb",
    "wb",
    "ab",
    "xb",
    "br",
    "bw",
    "ba",
    "bx",
    "r+",
    "w+",
    "a+",
    "x+",
    "+r",
    "+w",
    "+a",
    "+x",
    "rb+",
    "wb+",
    "ab+",
    "xb+",
    "br+",
    "bw+",
    "ba+",
    "bx+",
    "r+b",
    "w+b",
    "a+b",
    "x+b",
    "b+r",
    "b+w",
    "b+a",
    "b+x",
    "+rb",
    "+wb",
    "+ab",
    "+xb",
    "+br",
    "+bw",
    "+ba",
    "+bx",
]

_Filename = Union[str, bytes, Path, None]
_FileObj = Optional[Union[WithAsyncRead, WithAsyncWrite, WithAsyncReadWrite]]
_ReadFileObj = Optional[Union[WithAsyncRead, WithAsyncReadWrite]]
_WriteFileObj = Optional[Union[WithAsyncWrite, WithAsyncReadWrite]]


@overload
def AsyncGzipFile(
    filename: _Filename,
    mode: _TextMode,
    *,
    chunk_size: int = ...,
    encoding: Optional[str] = ...,
    errors: Optional[str] = ...,
    newline: Optional[str] = ...,
    compresslevel: int = ...,
    mtime: Optional[Union[int, float]] = ...,
    original_filename: Optional[Union[str, bytes]] = ...,
    fileobj: _FileObj = ...,
    closefd: Optional[bool] = ...,
    max_decompressed_size: Optional[int] = ...,
    max_rewind_cache_size: Optional[int] = ...,
    strict_size: bool = ...,
    fast_compress: bool = ...,
) -> AsyncGzipTextFile: ...


@overload
def AsyncGzipFile(
    filename: _Filename,
    mode: _BinaryMode = ...,
    *,
    chunk_size: int = ...,
    compresslevel: int = ...,
    mtime: Optional[Union[int, float]] = ...,
    original_filename: Optional[Union[str, bytes]] = ...,
    fileobj: _FileObj = ...,
    closefd: Optional[bool] = ...,
    max_decompressed_size: Optional[int] = ...,
    max_rewind_cache_size: Optional[int] = ...,
    strict_size: bool = ...,
    fast_compress: bool = ...,
) -> AsyncGzipBinaryFile: ...


@overload
def AsyncGzipFile(
    filename: _Filename,
    mode: str,
    **kwargs: Any,
) -> Union[AsyncGzipBinaryFile, AsyncGzipTextFile]: ...


def AsyncGzipFile(
    filename: _Filename, mode: str = "rb", **kwargs: Any
) -> Union[AsyncGzipBinaryFile, AsyncGzipTextFile]:
    """
    Factory function that returns the appropriate AsyncGzip class based on mode.

    This provides backward compatibility with the original AsyncGzipFile interface
    while using the new separated binary and text file classes.

    Args:
        filename: Path to the file
        mode: File mode; any of 'r', 'w', 'a', 'x' with an optional 'b'
            (binary, the default) or 't' (text) suffix
        **kwargs: Additional arguments passed to the appropriate class

    Returns:
        AsyncGzipBinaryFile for binary modes ('rb', 'wb', 'ab', 'xb')
        AsyncGzipTextFile for text modes ('rt', 'wt', 'at', 'xt')
    """
    if not isinstance(mode, str):
        raise TypeError("mode must be a string")
    text_mode = "t" in mode
    if not text_mode:
        for arg_name in ("encoding", "errors", "newline"):
            if kwargs.get(arg_name) is not None:
                raise ValueError(f"Argument '{arg_name}' not supported in binary mode")
        kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in {"encoding", "errors", "newline"}
        }
    if text_mode:
        return AsyncGzipTextFile(filename, mode, **kwargs)
    else:
        return AsyncGzipBinaryFile(filename, mode, **kwargs)


@overload
def open(
    filename: _Filename,
    mode: _TextMode,
    *,
    chunk_size: int = ...,
    encoding: Optional[str] = ...,
    errors: Optional[str] = ...,
    newline: Optional[str] = ...,
    compresslevel: int = ...,
    mtime: Optional[Union[int, float]] = ...,
    original_filename: Optional[Union[str, bytes]] = ...,
    fileobj: _FileObj = ...,
    closefd: Optional[bool] = ...,
    max_decompressed_size: Optional[int] = ...,
    max_rewind_cache_size: Optional[int] = ...,
    strict_size: bool = ...,
    fast_compress: bool = ...,
) -> AsyncGzipTextFile: ...


@overload
def open(
    filename: _Filename,
    mode: _BinaryMode = ...,
    *,
    chunk_size: int = ...,
    compresslevel: int = ...,
    mtime: Optional[Union[int, float]] = ...,
    original_filename: Optional[Union[str, bytes]] = ...,
    fileobj: _FileObj = ...,
    closefd: Optional[bool] = ...,
    max_decompressed_size: Optional[int] = ...,
    max_rewind_cache_size: Optional[int] = ...,
    strict_size: bool = ...,
    fast_compress: bool = ...,
) -> AsyncGzipBinaryFile: ...


@overload
def open(
    filename: _Filename,
    mode: str,
    **kwargs: Any,
) -> Union[AsyncGzipBinaryFile, AsyncGzipTextFile]: ...


def open(
    filename: _Filename, mode: str = "rb", **kwargs: Any
) -> Union[AsyncGzipBinaryFile, AsyncGzipTextFile]:
    """Open a gzip stream in binary or text mode.

    This is the recommended public entry point. ``AsyncGzipFile`` remains
    available and has identical behavior.
    """
    return AsyncGzipFile(filename, mode, **kwargs)


async def read(
    filename: _Filename,
    *,
    chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
    fileobj: _ReadFileObj = None,
    closefd: Optional[bool] = None,
    max_decompressed_size: Optional[int] = None,
    max_rewind_cache_size: Optional[int] = _MAX_CHUNK_SIZE,
) -> bytes:
    """Read and decompress an entire gzip stream into memory."""
    async with open(
        filename,
        "rb",
        chunk_size=chunk_size,
        fileobj=fileobj,
        closefd=closefd,
        max_decompressed_size=max_decompressed_size,
        max_rewind_cache_size=max_rewind_cache_size,
    ) as stream:
        return await stream.read()


async def write(
    filename: _Filename,
    data: Union[bytes, bytearray, memoryview],
    *,
    chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
    compresslevel: int = 6,
    mtime: Optional[Union[int, float]] = None,
    original_filename: Optional[Union[str, bytes]] = None,
    fileobj: _WriteFileObj = None,
    closefd: Optional[bool] = None,
    strict_size: bool = False,
    fast_compress: bool = False,
) -> None:
    """Compress and write an entire bytes-like payload to a gzip stream."""
    async with open(
        filename,
        "wb",
        chunk_size=chunk_size,
        compresslevel=compresslevel,
        mtime=mtime,
        original_filename=original_filename,
        fileobj=fileobj,
        closefd=closefd,
        strict_size=strict_size,
        fast_compress=fast_compress,
    ) as stream:
        await stream.write(data)


async def inspect(
    filename: _Filename,
    *,
    chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
    fileobj: _ReadFileObj = None,
    closefd: Optional[bool] = None,
    max_decompressed_size: Optional[int] = None,
) -> GzipInfo:
    """Inspect and validate every member in a complete gzip stream.

    This performs a full decompression scan while discarding payload bytes.
    ``mtime`` preserves the literal header value, including zero; filename and
    comment metadata use Latin-1 decoding.
    """
    result = await _scan_gzip(
        filename,
        fileobj=fileobj,
        closefd=closefd,
        max_decompressed_size=max_decompressed_size,
        chunk_size=chunk_size,
        collect_members=True,
    )
    return GzipInfo(
        members=result.members,
        compressed_size=result.compressed_size,
        uncompressed_size=result.uncompressed_size,
    )


async def verify(
    filename: _Filename,
    *,
    chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
    fileobj: _ReadFileObj = None,
    closefd: Optional[bool] = None,
    max_decompressed_size: Optional[int] = None,
) -> VerificationResult:
    """Validate a complete gzip stream and return aggregate counts.

    Successful return means every header, deflate payload, CRC, and ``ISIZE``
    was valid. Invalid input and resource-limit failures raise instead.
    """
    result = await _scan_gzip(
        filename,
        fileobj=fileobj,
        closefd=closefd,
        max_decompressed_size=max_decompressed_size,
        chunk_size=chunk_size,
        collect_members=False,
    )
    return VerificationResult(
        member_count=result.member_count,
        compressed_size=result.compressed_size,
        uncompressed_size=result.uncompressed_size,
    )


def decompress_chunks(
    source: AsyncIterable[bytes],
    *,
    output_chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
    max_decompressed_size: Optional[int] = None,
) -> AsyncIterator[bytes]:
    """Incrementally decompress gzip bytes from an asynchronous iterable.

    Output chunks are non-empty and no larger than ``output_chunk_size``.
    Complete CRC and trailer validation occurs only when the returned iterator
    is consumed to completion.

    Args:
        source: Asynchronous iterable yielding compressed ``bytes``.
        output_chunk_size: Strict upper bound for each yielded chunk.
        max_decompressed_size: Optional cumulative decompressed-byte limit.

    Returns:
        A single-consumer asynchronous iterator of decompressed ``bytes``.

    Raises:
        TypeError: If call-time arguments or a source item have invalid types.
        ValueError: If a size argument is outside its supported range.
        gzip.BadGzipFile: If the consumed gzip stream is malformed or corrupt.
        OSError: If the cumulative output limit is exceeded.
    """
    return _decompress_chunks(
        source,
        output_chunk_size=output_chunk_size,
        max_decompressed_size=max_decompressed_size,
    )


def compress_chunks(
    source: AsyncIterable[bytes],
    *,
    compresslevel: int = 6,
    mtime: Optional[Union[int, float]] = None,
    original_filename: Optional[Union[str, bytes]] = None,
    fast_compress: bool = False,
    strict_size: bool = False,
    output_chunk_size: int = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE,
) -> AsyncIterator[bytes]:
    """Incrementally compress an asynchronous byte iterable as one gzip member.

    The header is emitted before the first source item is requested. Output
    chunks are non-empty and no larger than ``output_chunk_size``.

    Args:
        source: Asynchronous iterable yielding uncompressed ``bytes``.
        compresslevel: Compression level from ``-1`` through ``9``.
        mtime: Optional gzip header timestamp. Use zero for reproducibility.
        original_filename: Optional filename stored in the gzip header.
        fast_compress: Opt into zlib-ng compression when available.
        strict_size: Reject payloads exceeding gzip's 32-bit ``ISIZE`` field.
        output_chunk_size: Strict upper bound for each yielded chunk.

    Returns:
        A single-consumer asynchronous iterator containing one gzip member.

    Raises:
        TypeError: If call-time arguments or a source item have invalid types.
        ValueError: If an option is outside its supported range.
        OSError: If compression fails or ``strict_size`` rejects the payload.
    """
    return _compress_chunks(
        source,
        compresslevel=compresslevel,
        mtime=mtime,
        original_filename=original_filename,
        fast_compress=fast_compress,
        strict_size=strict_size,
        output_chunk_size=output_chunk_size,
    )


__all__ = [
    "__version__",
    "AsyncGzipBinaryFile",
    "AsyncGzipFile",
    "AsyncGzipTextFile",
    "EngineInfo",
    "GzipInfo",
    "GzipMemberInfo",
    "VerificationResult",
    "WithAsyncRead",
    "WithAsyncReadWrite",
    "WithAsyncWrite",
    "ZlibEngine",
    "GZIP_WBITS",
    "GZIP_FLAG_FNAME",
    "GZIP_FLAG_FHCRC",
    "GZIP_FLAG_FEXTRA",
    "GZIP_FLAG_FCOMMENT",
    "GZIP_METHOD_DEFLATE",
    "GZIP_OS_UNKNOWN",
    "open",
    "read",
    "write",
    "engine_info",
    "inspect",
    "verify",
    "decompress_chunks",
    "compress_chunks",
]
