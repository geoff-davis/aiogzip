"""Async gzip file reader/writer public API."""

from pathlib import Path
from typing import Any, Literal, Optional, Union, overload

from ._binary import AsyncGzipBinaryFile
from ._common import (
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
from ._text import AsyncGzipTextFile

__version__ = "1.9.1"

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


__all__ = [
    "__version__",
    "AsyncGzipBinaryFile",
    "AsyncGzipFile",
    "AsyncGzipTextFile",
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
]
