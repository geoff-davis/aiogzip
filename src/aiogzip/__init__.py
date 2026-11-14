"""Async gzip file reader/writer public API."""

from typing import Any, AsyncIterable, AsyncIterator, Literal, Optional, Union, overload

from ._binary import AsyncGzipBinaryFile, ConcurrentOperationError
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
    _Filename,
    _WithAsyncBinaryWrite,
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
from .codec import CodecOperation, GzipDecoder, GzipEncoder

__version__ = "2.0.3.dev0"

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

_FileObj = Optional[
    Union[WithAsyncRead, WithAsyncWrite, WithAsyncReadWrite, _WithAsyncBinaryWrite]
]
_ReadFileObj = Optional[Union[WithAsyncRead, WithAsyncReadWrite]]
_WriteFileObj = Optional[
    Union[WithAsyncWrite, WithAsyncReadWrite, _WithAsyncBinaryWrite]
]


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

    ``open()`` is the recommended entry point and has identical behavior.
    ``AsyncGzipFile`` is the older name, kept for existing code.

    The call checks its arguments and opens nothing; the file is opened by
    ``async with`` or ``await f.open()``. Each parameter is described in
    full under "Parameters" in the API reference.

    Args:
        filename: Path of the gzip file, as ``str``, ``bytes`` or
            ``os.PathLike``, or ``None`` when ``fileobj`` is given.
        mode: One of ``r``, ``w``, ``x`` or ``a``, with an optional ``b``
            (binary) or ``t`` (text). The default is ``"rb"``, and a mode
            with neither ``b`` nor ``t`` is binary. Raises ``TypeError`` if
            it is not a string and ``ValueError`` if it is not a valid mode.
        **kwargs: Passed by keyword to the class: ``chunk_size``,
            ``compresslevel``, ``mtime``, ``original_filename``,
            ``fileobj``, ``closefd``, ``max_decompressed_size``,
            ``max_rewind_cache_size``, ``strict_size`` and
            ``fast_compress``, and in a text mode ``encoding``, ``errors``
            and ``newline``. Each has the meaning, default and exceptions
            documented on ``AsyncGzipBinaryFile`` and ``AsyncGzipTextFile``.
            In a binary mode, ``encoding``, ``errors`` or ``newline`` other
            than ``None`` raises ``ValueError``. An unknown keyword raises
            ``TypeError``.

    Returns:
        An ``AsyncGzipTextFile`` if ``mode`` contains ``t``, otherwise an
            ``AsyncGzipBinaryFile``.
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

    The call checks its arguments and opens nothing; the file is opened by
    ``async with`` or ``await f.open()``. Each parameter is described in
    full under "Parameters" in the API reference.

    Args:
        filename: Path of the gzip file, as ``str``, ``bytes`` or
            ``os.PathLike``, or ``None`` when ``fileobj`` is given.
        mode: One of ``r``, ``w``, ``x`` or ``a``, with an optional ``b``
            (binary) or ``t`` (text). The default is ``"rb"``, and a mode
            with neither ``b`` nor ``t`` is binary. Raises ``TypeError`` if
            it is not a string and ``ValueError`` if it is not a valid mode.
        **kwargs: Passed by keyword to the class: ``chunk_size``,
            ``compresslevel``, ``mtime``, ``original_filename``,
            ``fileobj``, ``closefd``, ``max_decompressed_size``,
            ``max_rewind_cache_size``, ``strict_size`` and
            ``fast_compress``, and in a text mode ``encoding``, ``errors``
            and ``newline``. Each has the meaning, default and exceptions
            documented on ``AsyncGzipBinaryFile`` and ``AsyncGzipTextFile``.
            In a binary mode, ``encoding``, ``errors`` or ``newline`` other
            than ``None`` raises ``ValueError``. An unknown keyword raises
            ``TypeError``.

    Returns:
        An ``AsyncGzipTextFile`` if ``mode`` contains ``t``, otherwise an
            ``AsyncGzipBinaryFile``.
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
    """Read and decompress an entire gzip stream into memory.

    The keyword parameters have the meaning, default, range and exceptions
    documented on ``AsyncGzipBinaryFile``. An invalid argument raises when
    the call is awaited.

    Args:
        filename: Path of the gzip file, or ``None`` when ``fileobj`` is
            given.
        chunk_size: The number of compressed bytes requested from the file
            or ``fileobj`` in each read, from 1 to 134217728 (128 MiB). The
            default is 262144 (256 KiB). It does not limit memory.
        fileobj: An already-open asynchronous file object, with an
            ``async read(size)`` method, to read in place of a path.
        closefd: ``True`` closes ``fileobj`` when the read ends; ``None``
            (the default) and ``False`` leave it open.
        max_decompressed_size: The largest number of decompressed bytes to
            accept; a larger stream raises ``OSError``. The default,
            ``None``, sets no limit. Set it for untrusted input.
        max_rewind_cache_size: The largest number of compressed bytes kept
            for rewinding a source that cannot seek. The default is
            134217728 (128 MiB), and ``None`` sets no limit.

    Returns:
        The whole decompressed payload.
    """
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
    """Compress and write an entire bytes-like payload to a gzip stream.

    The keyword parameters have the meaning, default, range and exceptions
    documented on ``AsyncGzipBinaryFile``. An invalid argument raises when
    the call is awaited.

    Args:
        filename: Path of the gzip file to create or truncate, or ``None``
            when ``fileobj`` is given.
        data: The payload, as ``bytes``, ``bytearray`` or ``memoryview``.
        chunk_size: Checked as for the file classes: from 1 to 134217728
            (128 MiB). The default is 262144 (256 KiB).
        compresslevel: The compression level, from ``-1`` to ``9``. The
            default is ``6``.
        mtime: The timestamp stored in the gzip header, from ``0`` to
            ``4294967295``. The default, ``None``, stores the current time;
            pass ``0`` for reproducible output.
        original_filename: The name stored in the gzip header. The default,
            ``None``, takes it from ``filename``; ``""`` stores no name.
        fileobj: An already-open asynchronous file object, with an
            ``async write(data)`` method, to write to in place of a path.
        closefd: ``True`` closes ``fileobj`` when the write ends; ``None``
            (the default) and ``False`` leave it open.
        strict_size: With ``True``, a payload larger than 4294967295 bytes
            raises ``OSError``. The default is ``False``.
        fast_compress: With ``True``, compress with zlib-ng if the
            ``aiogzip[fast]`` extra is installed. The default is ``False``.
    """
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
    "CodecOperation",
    "ConcurrentOperationError",
    "EngineInfo",
    "GzipInfo",
    "GzipDecoder",
    "GzipEncoder",
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
