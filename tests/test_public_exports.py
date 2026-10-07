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
        ConcurrentOperationError,
        EngineInfo,
        GzipInfo,
        GzipMemberInfo,
        VerificationResult,
        WithAsyncRead,
        WithAsyncReadWrite,
        WithAsyncWrite,
        compress_chunks,
        decompress_chunks,
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
    assert ConcurrentOperationError is aiogzip.ConcurrentOperationError
    assert issubclass(ConcurrentOperationError, OSError)
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
    assert decompress_chunks is aiogzip.decompress_chunks
    assert compress_chunks is aiogzip.compress_chunks


def test_metadata_types_keep_private_inspection_aliases():
    """Moving result types must preserve identity at every existing path."""
    from aiogzip import _inspection, _metadata

    assert aiogzip.GzipMemberInfo is _metadata.GzipMemberInfo
    assert aiogzip.GzipInfo is _metadata.GzipInfo
    assert aiogzip.VerificationResult is _metadata.VerificationResult
    assert _inspection.GzipMemberInfo is _metadata.GzipMemberInfo
    assert _inspection.GzipInfo is _metadata.GzipInfo
    assert _inspection.VerificationResult is _metadata.VerificationResult


def _private_classes():
    """Every class named ``_...`` defined in an aiogzip module."""
    import importlib
    import inspect
    import pkgutil

    found = {}
    for info in pkgutil.iter_modules(aiogzip.__path__):
        module = importlib.import_module(f"aiogzip.{info.name}")
        for value in vars(module).values():
            if (
                inspect.isclass(value)
                and value.__name__.startswith("_")
                and value.__module__.startswith("aiogzip.")
            ):
                found[value] = f"{value.__module__}.{value.__qualname__}"
    return found


def test_no_private_type_is_exported():
    """No public name is, or inherits from, a private aiogzip class.

    The 2.0.0b2 work (WP6-WP9) added private state types; none may leak into
    the public surface. ``codec._CodecBase`` is b1's shared base of the two
    public codecs and is the only private class allowed in a public MRO.
    """
    import inspect

    from aiogzip import codec

    private = _private_classes()
    names = set(private.values())
    assert {
        "aiogzip._binary._ReadHealth",
        "aiogzip._codec_async._StreamBudget",
        "aiogzip._source_io._NativeSourceCall",
        "aiogzip._text._TextBufferOrigin",
    } <= names

    allowed_bases = {"aiogzip.codec._CodecBase"}
    for module in (aiogzip, codec):
        for name in module.__all__:
            value = getattr(module, name)
            assert value not in private, f"{module.__name__}.{name}"
            if inspect.isclass(value):
                leaked = {private[b] for b in value.__mro__ if b in private}
                assert leaked <= allowed_bases, f"{module.__name__}.{name}: {leaked}"
