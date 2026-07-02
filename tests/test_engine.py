"""Tests for the codec engine abstraction (aiogzip._engine).

Covers engine selection, the zlib-ng decompression default, the compression
opt-in boundary, and — critically — that corrupt streams are wrapped into
OSError/BadGzipFile under *both* engines, since zlib-ng's error type is not
zlib.error.
"""

import gzip
import importlib
import zlib

import pytest

from aiogzip import AsyncGzipBinaryFile, _engine
from aiogzip._common import GZIP_WBITS

ZNG_AVAILABLE = _engine._zng is not None

# Engine states to exercise end-to-end: stdlib always; zlib-ng when installed.
ENGINE_PARAMS = [False]
if ZNG_AVAILABLE:
    ENGINE_PARAMS.append(True)


@pytest.fixture(params=ENGINE_PARAMS, ids=lambda v: "zlib-ng" if v else "stdlib")
def active_engine(request, monkeypatch):
    """Force the active decompression engine on and off for each test."""
    monkeypatch.setattr(_engine, "_HAVE_ZNG", request.param)
    return request.param


class TestEngineSelection:
    def test_zlib_errors_includes_stdlib(self):
        assert zlib.error in _engine.ZLIB_ERRORS

    @pytest.mark.skipif(not ZNG_AVAILABLE, reason="zlib-ng not installed")
    def test_zlib_errors_includes_zlib_ng(self):
        # The whole point of the abstraction: zlib-ng's error is NOT zlib.error.
        assert _engine._zng.error in _engine.ZLIB_ERRORS
        assert not issubclass(_engine._zng.error, zlib.error)

    def test_decompress_engine_name_tracks_availability(self, active_engine):
        expected = "zlib-ng" if active_engine else "stdlib"
        assert _engine.decompress_engine_name() == expected
        assert _engine.have_fast_engine() is active_engine

    def test_crc32_is_stdlib(self):
        assert _engine.crc32 is zlib.crc32


class TestEnvEscapeHatch:
    def test_force_stdlib_via_env(self, monkeypatch):
        """AIOGZIP_ENGINE=stdlib disables zlib-ng even when importable."""
        monkeypatch.setenv("AIOGZIP_ENGINE", "stdlib")
        reloaded = importlib.reload(_engine)
        try:
            assert reloaded.have_fast_engine() is False
            assert reloaded.decompress_engine_name() == "stdlib"
        finally:
            # Restore module state (and the _binary reference to it) for other tests.
            monkeypatch.delenv("AIOGZIP_ENGINE", raising=False)
            importlib.reload(_engine)


class TestCrossEngineDecompress:
    @pytest.mark.parametrize(
        "data",
        [b"", b"hello world", b"A" * 100_000, bytes(range(256)) * 500],
        ids=["empty", "short", "compressible-100k", "binary-128k"],
    )
    def test_inflate_matches_stdlib(self, active_engine, data):
        """Decompressing a stdlib-produced stream yields identical bytes."""
        compressed = gzip.compress(data)
        obj = _engine.decompressobj(GZIP_WBITS)
        out = obj.decompress(compressed) + obj.flush()
        assert out == data


class TestCompressionOptIn:
    def test_default_compression_is_stdlib_bytes(self, monkeypatch):
        """fast=False must produce byte-identical output to stdlib zlib,
        even when zlib-ng is available (installing the extra alone must not
        change produced .gz bytes)."""
        monkeypatch.setattr(_engine, "_HAVE_ZNG", ZNG_AVAILABLE)
        data = b"the quick brown fox jumps over the lazy dog " * 500
        ours = _engine.compressobj(6, -_engine.MAX_WBITS, fast=False)
        ref = zlib.compressobj(6, wbits=-_engine.MAX_WBITS)
        assert ours.compress(data) + ours.flush() == ref.compress(data) + ref.flush()

    @pytest.mark.skipif(not ZNG_AVAILABLE, reason="zlib-ng not installed")
    def test_fast_compression_differs_but_roundtrips(self, monkeypatch):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        data = b"the quick brown fox jumps over the lazy dog " * 500
        fast = _engine.compressobj(6, -_engine.MAX_WBITS, fast=True)
        std = zlib.compressobj(6, wbits=-_engine.MAX_WBITS)
        fast_bytes = fast.compress(data) + fast.flush()
        std_bytes = std.compress(data) + std.flush()
        # Different compressor, generally different bytes...
        assert fast_bytes != std_bytes
        # ...but still valid raw deflate that inflates to the original.
        assert zlib.decompress(fast_bytes, wbits=-_engine.MAX_WBITS) == data

    def test_fast_falls_back_when_unavailable(self, monkeypatch):
        """fast=True without zlib-ng falls back to stdlib bytes silently."""
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        data = b"payload" * 1000
        ours = _engine.compressobj(6, -_engine.MAX_WBITS, fast=True)
        ref = zlib.compressobj(6, wbits=-_engine.MAX_WBITS)
        assert ours.compress(data) + ours.flush() == ref.compress(data) + ref.flush()


class TestEndToEndUnderEngines:
    async def test_roundtrip(self, active_engine, tmp_path):
        path = tmp_path / "rt.gz"
        payload = b"end to end payload " * 10_000  # exceeds offload threshold
        async with AsyncGzipBinaryFile(path, "wb") as f:
            await f.write(payload)
        async with AsyncGzipBinaryFile(path, "rb") as f:
            assert await f.read() == payload

    async def test_interop_with_stdlib_gzip(self, active_engine, tmp_path):
        """aiogzip reads a stdlib-written .gz back identically under any engine."""
        path = tmp_path / "interop.gz"
        payload = bytes(range(256)) * 2000
        with gzip.open(path, "wb") as f:
            f.write(payload)
        async with AsyncGzipBinaryFile(path, "rb") as f:
            assert await f.read() == payload

    async def test_corrupt_stream_wrapped(self, active_engine, tmp_path):
        """A corrupted deflate body must raise BadGzipFile (OSError subclass)
        under both engines — the regression guard for zlib-ng's foreign error
        type bypassing the except handlers."""
        path = tmp_path / "corrupt.gz"
        good = gzip.compress(b"some content that will be corrupted " * 100)
        # Corrupt bytes inside the deflate body (past the 10-byte header).
        corrupt = bytearray(good)
        for i in range(15, 40):
            corrupt[i] ^= 0xFF
        path.write_bytes(bytes(corrupt))
        with pytest.raises(OSError):  # gzip.BadGzipFile is an OSError subclass
            async with AsyncGzipBinaryFile(path, "rb") as f:
                await f.read()
