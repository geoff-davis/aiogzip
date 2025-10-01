# src/aiogzip/__init__.py
"""AsyncGzipFile - Asynchronous gzip file reader/writer."""

__version__ = "0.2.0"

from .aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipFile,
    AsyncGzipTextFile,
    WithAsyncRead,
    WithAsyncReadWrite,
    WithAsyncWrite,
)

__all__ = [
    "AsyncGzipFile",
    "AsyncGzipBinaryFile",
    "AsyncGzipTextFile",
    "WithAsyncRead",
    "WithAsyncWrite",
    "WithAsyncReadWrite",
]
