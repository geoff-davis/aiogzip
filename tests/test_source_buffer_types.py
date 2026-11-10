"""A custom source may return any bytes-like chunk from ``read()`` (#174).

2.0.0 passed the chunk straight to the codec, which accepts only ``bytes``, so
a source returning ``bytearray`` or ``memoryview`` (accepted in 1.x) broke the
reader with a decompression error.
"""

import gzip
import io
import os

import pytest

import aiogzip
from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

PAYLOAD = os.urandom(50_000) + b"line one\nline two\n" * 2000
COMPRESSED = gzip.compress(PAYLOAD[:20_000]) + gzip.compress(PAYLOAD[20_000:])


class _BytesSubclass(bytes):
    pass


class _Source:
    def __init__(self, data, convert, seekable=True):
        self._buffer = io.BytesIO(data)
        self._convert = convert
        if seekable:
            self.seek = self._seek
            self.tell = self._tell

    async def read(self, size=-1):
        return self._convert(self._buffer.read(size))

    async def _seek(self, offset, whence=os.SEEK_SET):
        return self._buffer.seek(offset, whence)

    async def _tell(self):
        return self._buffer.tell()

    async def close(self):
        pass


CONVERSIONS = [bytes, bytearray, memoryview, _BytesSubclass]


@pytest.mark.parametrize("convert", CONVERSIONS)
@pytest.mark.parametrize("seekable", [True, False])
@pytest.mark.parametrize("chunk_size", [7, 4096, 256 * 1024])
async def test_binary_reader_accepts_bytes_like_chunks(convert, seekable, chunk_size):
    source = _Source(COMPRESSED, convert, seekable)
    async with AsyncGzipBinaryFile(
        None, "rb", fileobj=source, chunk_size=chunk_size
    ) as f:
        first = await f.read(100)
        rest = await f.read()
        assert first + rest == PAYLOAD
        # A rewind replays the cache (non-seekable) or re-reads the source.
        assert await f.seek(10) == 10
        assert await f.read(20) == PAYLOAD[10:30]


@pytest.mark.parametrize("convert", CONVERSIONS)
async def test_text_reader_accepts_bytes_like_chunks(convert):
    data = gzip.compress("héllo\nwörld\n".encode())
    async with AsyncGzipTextFile(None, "rt", fileobj=_Source(data, convert)) as f:
        assert [line async for line in f] == ["héllo\n", "wörld\n"]


@pytest.mark.parametrize("convert", CONVERSIONS)
async def test_inspect_and_verify_accept_bytes_like_chunks(convert):
    result = await aiogzip.verify(None, fileobj=_Source(COMPRESSED, convert))
    assert result.member_count == 2
    info = await aiogzip.inspect(None, fileobj=_Source(COMPRESSED, convert))
    assert len(info.members) == 2


async def test_mutating_a_returned_bytearray_does_not_change_the_data():
    class Reusing(_Source):
        def __init__(self, data):
            super().__init__(data, bytearray, seekable=False)
            self._last = None

        async def read(self, size=-1):
            if self._last is not None:
                self._last[:] = bytes(len(self._last))
            self._last = await super().read(size)
            return self._last

    async with AsyncGzipBinaryFile(
        None, "rb", fileobj=Reusing(COMPRESSED), chunk_size=512
    ) as f:
        assert await f.read() == PAYLOAD
        assert await f.seek(0) == 0
        assert await f.read() == PAYLOAD
