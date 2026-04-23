# pyrefly: ignore
# pyrefly: disable=all
import gzip
import io
import os

import pytest

from aiogzip import AsyncGzipBinaryFile


class TestFileobjSupport:
    """Tests for wrapping an existing async file-like object via fileobj."""

    @pytest.mark.asyncio
    async def test_fileobj_roundtrip(self, tmp_path):
        p = tmp_path / "via_fileobj.gz"

        import aiofiles

        async with aiofiles.open(p, "wb") as raw:
            async with AsyncGzipBinaryFile(None, "wb", fileobj=raw, closefd=False) as f:
                await f.write(b"hello fileobj")

        async with aiofiles.open(p, "rb") as raw_r:
            async with AsyncGzipBinaryFile(
                None, "rb", fileobj=raw_r, closefd=False
            ) as f:
                data = await f.read()
                assert data == b"hello fileobj"

    @pytest.mark.asyncio
    async def test_non_seekable_fileobj_supports_backward_seek(self):
        payload = b"abcdefghijklmnopqrstuvwxyz"
        compressed = gzip.compress(payload)

        class NonSeekableAsyncReader:
            def __init__(self, data: bytes):
                self._buffer = io.BytesIO(data)

            async def read(self, size=-1):
                return self._buffer.read(size)

            async def close(self):
                pass

        reader = NonSeekableAsyncReader(compressed)
        async with AsyncGzipBinaryFile(None, "rb", fileobj=reader, closefd=False) as f:
            assert f.seekable()
            assert await f.read(10) == payload[:10]
            assert await f.seek(5) == 5
            assert await f.read(4) == payload[5:9]

    @pytest.mark.asyncio
    async def test_non_seekable_rewind_cache_can_be_capped(self):
        payload = os.urandom(1024)
        compressed = gzip.compress(payload)

        class NonSeekableAsyncReader:
            def __init__(self, data: bytes):
                self._buffer = io.BytesIO(data)

            async def read(self, size=-1):
                return self._buffer.read(size)

            async def close(self):
                pass

        reader = NonSeekableAsyncReader(compressed)
        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            max_rewind_cache_size=32,
        ) as f:
            assert await f.read() == payload
            assert not f.seekable()
            with pytest.raises(OSError, match="not seekable|rewind cache"):
                await f.seek(0)

    def test_max_rewind_cache_size_validated(self):
        with pytest.raises(ValueError, match="max_rewind_cache_size"):
            AsyncGzipBinaryFile("test.gz", "rb", max_rewind_cache_size=0)

        with pytest.raises(ValueError, match="max_rewind_cache_size"):
            AsyncGzipBinaryFile("test.gz", "rb", max_rewind_cache_size=-1)

    @pytest.mark.asyncio
    async def test_fileobj_with_failing_seek_uses_replay_cache(self):
        payload = b"abcdefghijklmnopqrstuvwxyz"
        compressed = gzip.compress(payload)

        class NonSeekableAsyncReader:
            def __init__(self, data: bytes):
                self._buffer = io.BytesIO(data)

            async def read(self, size=-1):
                return self._buffer.read(size)

            async def seek(self, offset, whence=os.SEEK_SET):
                raise OSError("not actually seekable")

            def seekable(self):
                return False

            async def close(self):
                pass

        reader = NonSeekableAsyncReader(compressed)
        async with AsyncGzipBinaryFile(None, "rb", fileobj=reader, closefd=False) as f:
            assert f.seekable()
            assert await f.read(10) == payload[:10]
            assert await f.seek(5) == 5
            assert await f.read(4) == payload[5:9]

    @pytest.mark.asyncio
    async def test_fileobj_with_raising_seekable_falls_back_to_replay_cache(self):
        """seekable() raising should fall back to replay caching, not crash."""
        payload = b"abcdefghijklmnopqrstuvwxyz"
        compressed = gzip.compress(payload)

        class RaisingSeekableReader:
            def __init__(self, data: bytes):
                self._buffer = io.BytesIO(data)

            async def read(self, size=-1):
                return self._buffer.read(size)

            async def seek(self, offset, whence=os.SEEK_SET):
                raise OSError("seek also fails")

            def seekable(self):
                raise RuntimeError("seekable() is broken")

            async def close(self):
                pass

        reader = RaisingSeekableReader(compressed)
        async with AsyncGzipBinaryFile(None, "rb", fileobj=reader, closefd=False) as f:
            assert f.seekable()
            assert await f.read(10) == payload[:10]
            assert await f.seek(0) == 0
            assert await f.read() == payload

    @pytest.mark.asyncio
    async def test_non_seekable_rewind_cache_unbounded_when_none(self):
        """max_rewind_cache_size=None preserves the pre-1.5 unbounded behavior."""
        payload = os.urandom(256 * 1024)
        compressed = gzip.compress(payload)

        class NonSeekableAsyncReader:
            def __init__(self, data: bytes):
                self._buffer = io.BytesIO(data)

            async def read(self, size=-1):
                return self._buffer.read(size)

            async def close(self):
                pass

        reader = NonSeekableAsyncReader(compressed)
        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            max_rewind_cache_size=None,
        ) as f:
            assert await f.read() == payload
            assert f.seekable()
            assert await f.seek(0) == 0
            assert await f.read() == payload
