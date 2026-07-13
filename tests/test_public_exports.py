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
        EngineInfo,
        GzipInfo,
        GzipMemberInfo,
        VerificationResult,
        WithAsyncRead,
        WithAsyncReadWrite,
        WithAsyncWrite,
        engine_info,
        inspect,
        open,
        read,
        verify,
        write,
    )

    assert AsyncGzipBinaryFile is aiogzip.AsyncGzipBinaryFile
    assert AsyncGzipTextFile is aiogzip.AsyncGzipTextFile
    assert AsyncGzipFile is aiogzip.AsyncGzipFile
    assert EngineInfo is aiogzip.EngineInfo
    assert GzipInfo is aiogzip.GzipInfo
    assert GzipMemberInfo is aiogzip.GzipMemberInfo
    assert VerificationResult is aiogzip.VerificationResult
    assert WithAsyncRead is aiogzip.WithAsyncRead
    assert WithAsyncWrite is aiogzip.WithAsyncWrite
    assert WithAsyncReadWrite is aiogzip.WithAsyncReadWrite
    assert open is aiogzip.open
    assert read is aiogzip.read
    assert write is aiogzip.write
    assert engine_info is aiogzip.engine_info
    assert inspect is aiogzip.inspect
    assert verify is aiogzip.verify
