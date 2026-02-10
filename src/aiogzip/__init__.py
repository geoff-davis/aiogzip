"""Async gzip file reader/writer public API."""

from pathlib import Path
from typing import Any, Union

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
    _build_gzip_header,
    _build_gzip_trailer,
    _derive_header_filename,
    _normalize_mtime,
    _parse_mode_tokens,
    _try_parse_gzip_header_mtime,
    _validate_chunk_size,
    _validate_compresslevel,
    _validate_filename,
    _validate_original_filename,
)
from ._text import AsyncGzipTextFile

__version__ = "1.1.0"


def AsyncGzipFile(
    filename: Union[str, bytes, Path, None], mode: str = "rb", **kwargs: Any
) -> Union[AsyncGzipBinaryFile, AsyncGzipTextFile]:
    """
    Factory function that returns the appropriate AsyncGzip class based on mode.

    This provides backward compatibility with the original AsyncGzipFile interface
    while using the new separated binary and text file classes.

    Args:
        filename: Path to the file
        mode: File mode ('rb', 'wb', 'rt', 'wt', etc.)
        **kwargs: Additional arguments passed to the appropriate class

    Returns:
        AsyncGzipBinaryFile for binary modes ('rb', 'wb', 'ab')
        AsyncGzipTextFile for text modes ('rt', 'wt', 'at')
    """
    if not isinstance(mode, str):
        raise TypeError("mode must be a string")
    text_mode = "t" in mode
    if not text_mode:
        for arg_name in ("encoding", "errors", "newline"):
            if kwargs.get(arg_name) is not None:
                raise ValueError(
                    f"Argument '{arg_name}' not supported in binary mode"
                )
        kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in {"encoding", "errors", "newline"}
        }
    if text_mode:
        return AsyncGzipTextFile(filename, mode, **kwargs)
    else:
        return AsyncGzipBinaryFile(filename, mode, **kwargs)


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
    "_validate_filename",
    "_validate_chunk_size",
    "_validate_compresslevel",
    "_normalize_mtime",
    "_validate_original_filename",
    "_derive_header_filename",
    "_build_gzip_header",
    "_build_gzip_trailer",
    "_try_parse_gzip_header_mtime",
    "_parse_mode_tokens",
]
