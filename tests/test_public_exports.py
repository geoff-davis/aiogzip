from __future__ import annotations

import aiogzip


def test_all_exports_exist():
    """Every symbol in __all__ should be present on the top-level module."""
    for name in aiogzip.__all__:
        assert hasattr(aiogzip, name), f"Missing exported symbol: {name}"


def test_key_re_exports_are_stable():
    """Public re-exports should resolve to expected objects."""
    from aiogzip import (
        AsyncGzipBinaryFile,
        AsyncGzipFile,
        AsyncGzipTextFile,
        WithAsyncRead,
        WithAsyncReadWrite,
        WithAsyncWrite,
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

    assert AsyncGzipBinaryFile is aiogzip.AsyncGzipBinaryFile
    assert AsyncGzipTextFile is aiogzip.AsyncGzipTextFile
    assert AsyncGzipFile is aiogzip.AsyncGzipFile
    assert WithAsyncRead is aiogzip.WithAsyncRead
    assert WithAsyncWrite is aiogzip.WithAsyncWrite
    assert WithAsyncReadWrite is aiogzip.WithAsyncReadWrite
    assert _validate_filename is aiogzip._validate_filename
    assert _validate_chunk_size is aiogzip._validate_chunk_size
    assert _validate_compresslevel is aiogzip._validate_compresslevel
    assert _normalize_mtime is aiogzip._normalize_mtime
    assert _validate_original_filename is aiogzip._validate_original_filename
    assert _derive_header_filename is aiogzip._derive_header_filename
    assert _build_gzip_header is aiogzip._build_gzip_header
    assert _build_gzip_trailer is aiogzip._build_gzip_trailer
    assert _try_parse_gzip_header_mtime is aiogzip._try_parse_gzip_header_mtime
    assert _parse_mode_tokens is aiogzip._parse_mode_tokens
