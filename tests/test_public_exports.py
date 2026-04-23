from __future__ import annotations

import aiogzip


def test_all_exports_exist():
    """Every symbol in __all__ should be present on the top-level module."""
    for name in aiogzip.__all__:
        assert hasattr(aiogzip, name), f"Missing exported symbol: {name}"


def test_all_exports_are_public():
    """Private implementation helpers should not be part of the public API."""
    assert all(
        not name.startswith("_") or name == "__version__" for name in aiogzip.__all__
    )


def test_key_re_exports_are_stable():
    """Public re-exports should resolve to expected objects."""
    from aiogzip import (
        AsyncGzipBinaryFile,
        AsyncGzipFile,
        AsyncGzipTextFile,
        WithAsyncRead,
        WithAsyncReadWrite,
        WithAsyncWrite,
    )

    assert AsyncGzipBinaryFile is aiogzip.AsyncGzipBinaryFile
    assert AsyncGzipTextFile is aiogzip.AsyncGzipTextFile
    assert AsyncGzipFile is aiogzip.AsyncGzipFile
    assert WithAsyncRead is aiogzip.WithAsyncRead
    assert WithAsyncWrite is aiogzip.WithAsyncWrite
    assert WithAsyncReadWrite is aiogzip.WithAsyncReadWrite
