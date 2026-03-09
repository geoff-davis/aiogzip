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
            assert await f.seek(-3, os.SEEK_END) == len(payload) - 3
            assert await f.read() == payload[-3:]
