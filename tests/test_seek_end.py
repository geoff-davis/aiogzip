"""End-relative seeks when EOF is already known (BC12).

A ``peek()`` large enough to reach EOF leaves its output unread in the read
buffer. ``seek(offset, SEEK_END)`` must count that output exactly once, from
any read position, on physical and cached-rewind sources, and must never skip
trailer validation or the decompression limit.
"""

import gzip
import io
import os
import struct

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

SMALL = b"0123456789"
LARGE = os.urandom(200_000)


class _NonSeekableReader:
    """Async reader without ``seek``, so rewinds replay the input cache."""

    def __init__(self, data: bytes):
        self._buffer = io.BytesIO(data)

    async def read(self, size=-1):
        return self._buffer.read(size)

    async def close(self):
        pass


def _open(kind, compressed, tmp_path, **kwargs):
    if kind == "path":
        target = tmp_path / "data.gz"
        target.write_bytes(compressed)
        return AsyncGzipBinaryFile(target, "rb", **kwargs)
    return AsyncGzipBinaryFile(
        None, "rb", fileobj=_NonSeekableReader(compressed), closefd=False, **kwargs
    )


def _bad_crc(payload):
    compressed = bytearray(gzip.compress(payload))
    crc = struct.unpack("<I", compressed[-8:-4])[0]
    compressed[-8:-4] = struct.pack("<I", crc ^ 1)
    return bytes(compressed)


def _expected(size, offset):
    return min(max(size + offset, 0), size)


class TestHighPriorityEdgeCases:
    @pytest.mark.parametrize("kind", ["path", "cached"])
    @pytest.mark.parametrize("payload", [SMALL, LARGE], ids=["small", "large"])
    @pytest.mark.parametrize("consumed", [0, 1, 4])
    @pytest.mark.parametrize("offset", [0, -3, 5, -(10**7)])
    async def test_seek_end_after_peek_reaches_eof(
        self, kind, payload, consumed, offset, tmp_path
    ):
        async with _open(kind, gzip.compress(payload), tmp_path) as f:
            assert await f.read(consumed) == payload[:consumed]
            peeked = await f.peek(len(payload) + 1)
            assert peeked == payload[consumed:]
            end = _expected(len(payload), offset)
            assert await f.seek(offset, os.SEEK_END) == end
            assert await f.tell() == end
            assert await f.read() == payload[end:]

    @pytest.mark.parametrize("kind", ["path", "cached"])
    async def test_partially_read_peek_output_is_counted_once(self, kind, tmp_path):
        async with _open(kind, gzip.compress(SMALL), tmp_path) as f:
            await f.peek(100)
            assert await f.read(2) == SMALL[:2]
            assert await f.seek(0, os.SEEK_END) == len(SMALL)
            assert await f.seek(0, os.SEEK_END) == len(SMALL)
            assert await f.seek(-1, os.SEEK_END) == len(SMALL) - 1
            assert await f.read() == SMALL[-1:]

    async def test_seek_end_after_peek_across_members(self, tmp_path):
        compressed = gzip.compress(b"first-") + gzip.compress(b"second")
        async with _open("path", compressed, tmp_path) as f:
            await f.peek(100)
            assert await f.seek(-3, os.SEEK_END) == 9
            assert await f.read() == b"ond"

    @pytest.mark.parametrize("kind", ["path", "cached"])
    async def test_seek_end_drain_raises_a_later_trailer_failure(self, kind, tmp_path):
        # peek() succeeds from the first chunks and leaves unread output; the
        # bad CRC is reached only by the seek's own drain.
        async with _open(kind, _bad_crc(LARGE), tmp_path, chunk_size=64) as f:
            peeked = await f.peek(1)
            assert peeked and LARGE.startswith(peeked)
            with pytest.raises(gzip.BadGzipFile):
                await f.seek(0, os.SEEK_END)
            with pytest.raises(OSError, match="broken"):
                await f.seek(0, os.SEEK_END)

    @pytest.mark.parametrize("kind", ["path", "cached"])
    async def test_seek_end_drain_raises_a_later_limit_failure(self, kind, tmp_path):
        compressed = gzip.compress(LARGE)
        async with _open(
            kind, compressed, tmp_path, chunk_size=64, max_decompressed_size=100_000
        ) as f:
            peeked = await f.peek(1)
            assert peeked and LARGE.startswith(peeked)
            with pytest.raises(OSError, match="max_decompressed_size"):
                await f.seek(0, os.SEEK_END)
            with pytest.raises(OSError, match="broken"):
                await f.seek(0, os.SEEK_END)

    @pytest.mark.parametrize("kind", ["path", "cached"])
    async def test_seek_end_after_a_peek_hit_the_trailer_failure(self, kind, tmp_path):
        # Control: the failure lands in peek(); the poisoned reader refuses.
        async with _open(kind, _bad_crc(SMALL), tmp_path) as f:
            with pytest.raises(gzip.BadGzipFile):
                await f.peek(100)
            with pytest.raises(OSError, match="broken"):
                await f.seek(0, os.SEEK_END)

    @pytest.mark.parametrize("kind", ["path", "cached"])
    async def test_seek_end_after_a_peek_hit_the_limit(self, kind, tmp_path):
        compressed = gzip.compress(b"0" * 4096)
        async with _open(kind, compressed, tmp_path, max_decompressed_size=1024) as f:
            with pytest.raises(OSError, match="max_decompressed_size"):
                await f.peek(100)
            with pytest.raises(OSError, match="broken"):
                await f.seek(0, os.SEEK_END)

    async def test_text_seek_end_reports_the_true_end(self, tmp_path):
        target = tmp_path / "text.gz"
        text = "alpha\nbeta\ngamma\n"
        target.write_bytes(gzip.compress(text.encode()))
        async with AsyncGzipTextFile(target, "rt", newline="") as f:
            assert await f.readline() == "alpha\n"
            end = await f.seek(0, os.SEEK_END)
            assert end == await f.tell()
            assert await f.read() == ""
            assert end == len(text.encode())
            await f.seek(0)
            assert await f.read() == text
