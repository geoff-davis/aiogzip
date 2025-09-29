# src/aiogzip/__init__.py
"""AsyncGzipFile - Asynchronous gzip file reader/writer."""

__version__ = "0.1.0"

from .aiogzip import AsyncGzipBinaryFile, AsyncGzipFile, AsyncGzipTextFile

__all__ = [
    "AsyncGzipFile",
    "AsyncGzipBinaryFile",
    "AsyncGzipTextFile",
]
