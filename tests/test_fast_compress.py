"""Tests for the opt-in fast_compress flag (zlib-ng compression).

Decompression auto-uses zlib-ng (covered in test_engine.py); compression only
uses it when the caller passes fast_compress=True AND zlib-ng is available.
Installing the extra alone must not change default compressed output.
"""

import gzip
import warnings

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipFile, AsyncGzipTextFile, _engine

ZNG_AVAILABLE = _engine._zng is not None

PAYLOAD = b"the quick brown fox jumps over the lazy dog " * 5000


async def _read_back(path):
    async with AsyncGzipBinaryFile(path, "rb") as f:
        return await f.read()


class TestDefaultCompressionUnchanged:
    @pytest.mark.asyncio
    async def test_installing_extra_does_not_change_default_output(
        self, monkeypatch, tmp_path
    ):
        """fast_compress defaults to False, so output must be byte-identical
        whether or not zlib-ng is available."""

        # Same path/name both times: the gzip header embeds the original
        # filename, so differing names would mask a true body comparison.
        path = tmp_path / "default.gz"

        async def write_with(have_zng):
            monkeypatch.setattr(_engine, "_HAVE_ZNG", have_zng)
            async with AsyncGzipBinaryFile(path, "wb", mtime=0) as f:
                await f.write(PAYLOAD)
            return path.read_bytes()

        with_zng = await write_with(True)
        without_zng = await write_with(False)
        assert with_zng == without_zng


@pytest.mark.skipif(not ZNG_AVAILABLE, reason="zlib-ng not installed")
class TestFastCompressEnabled:
    @pytest.mark.asyncio
    async def test_roundtrip_binary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "fast.gz"
        async with AsyncGzipBinaryFile(path, "wb", fast_compress=True) as f:
            await f.write(PAYLOAD)
        assert await _read_back(path) == PAYLOAD

    @pytest.mark.asyncio
    async def test_readable_by_stdlib_gzip(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "fast_interop.gz"
        async with AsyncGzipBinaryFile(path, "wb", fast_compress=True) as f:
            await f.write(PAYLOAD)
        with gzip.open(path, "rb") as f:
            assert f.read() == PAYLOAD

    @pytest.mark.asyncio
    async def test_fast_output_differs_from_default(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        # Same path/name and mtime so only the deflate body can differ.
        path = tmp_path / "same.gz"
        async with AsyncGzipBinaryFile(path, "wb", mtime=0) as f:
            await f.write(PAYLOAD)
        default_bytes = path.read_bytes()
        async with AsyncGzipBinaryFile(path, "wb", mtime=0, fast_compress=True) as f:
            await f.write(PAYLOAD)
        fast_bytes = path.read_bytes()
        # Identical header (same name + mtime); body differs because a
        # different deflate implementation produced it.
        assert default_bytes != fast_bytes

    @pytest.mark.asyncio
    async def test_roundtrip_text(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "fast.txt.gz"
        text = "héllo wörld\nsecond line\n" * 5000
        async with AsyncGzipTextFile(path, "wt", fast_compress=True) as f:
            await f.write(text)
        async with AsyncGzipTextFile(path, "rt") as f:
            assert await f.read() == text

    @pytest.mark.asyncio
    async def test_factory_threads_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "factory.gz"
        async with AsyncGzipFile(path, "wb", fast_compress=True) as f:
            await f.write(PAYLOAD)
        assert await _read_back(path) == PAYLOAD


class TestFastCompressFallback:
    def test_warns_when_unavailable(self, monkeypatch, tmp_path):
        """fast_compress=True without zlib-ng warns once at construction."""
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        with pytest.warns(UserWarning, match="zlib-ng is not available"):
            AsyncGzipBinaryFile(tmp_path / "x.gz", "wb", fast_compress=True)

    @pytest.mark.asyncio
    async def test_falls_back_and_roundtrips(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        path = tmp_path / "fallback.gz"
        with pytest.warns(UserWarning):
            cm = AsyncGzipBinaryFile(path, "wb", fast_compress=True)
        async with cm as f:
            await f.write(PAYLOAD)
        assert await _read_back(path) == PAYLOAD

    def test_no_warning_in_read_mode(self, monkeypatch, tmp_path):
        """fast_compress is meaningless for reads and must not warn there."""
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            AsyncGzipBinaryFile(tmp_path / "r.gz", "rb", fast_compress=True)

    def test_no_warning_when_not_requested(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            AsyncGzipBinaryFile(tmp_path / "n.gz", "wb")
