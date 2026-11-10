"""``seek()`` rejects a non-integer offset before changing any state (#177).

A float offset once became the read position, after which every read raised
``TypeError`` from a slice until ``seek(0)``.
"""

import gzip
import os

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

PAYLOAD = b"abcdef"


class _Index:
    def __index__(self):
        return 2


@pytest.fixture
def gz_path(tmp_path):
    path = tmp_path / "data.gz"
    path.write_bytes(gzip.compress(PAYLOAD))
    return path


@pytest.mark.parametrize("offset", [2.0, "2", None, 2.5])
@pytest.mark.parametrize("whence", [os.SEEK_SET, os.SEEK_CUR, os.SEEK_END])
async def test_binary_read_seek_rejects_non_integer(gz_path, offset, whence):
    async with AsyncGzipBinaryFile(gz_path, "rb") as f:
        assert await f.read(1) == b"a"
        with pytest.raises(TypeError):
            await f.seek(offset, whence)
        assert await f.tell() == 1
        assert await f.read() == b"bcdef"


async def test_binary_seek_accepts_index_objects(gz_path):
    async with AsyncGzipBinaryFile(gz_path, "rb") as f:
        position = await f.seek(_Index())
        assert position == 2 and type(position) is int
        assert await f.read(1) == b"c"
        assert await f.seek(True) == 1


@pytest.mark.parametrize("offset", [2.0, "2", None])
async def test_binary_write_seek_rejects_non_integer(tmp_path, offset):
    path = tmp_path / "out.gz"
    async with AsyncGzipBinaryFile(path, "wb") as f:
        await f.write(b"ab")
        with pytest.raises(TypeError):
            await f.seek(offset)
        assert await f.tell() == 2
        await f.write(b"cd")
    assert gzip.decompress(path.read_bytes()) == b"abcd"


@pytest.mark.parametrize("offset", [2.0, "2", None])
async def test_text_seek_rejects_non_integer(gz_path, offset):
    async with AsyncGzipTextFile(gz_path, "rt") as f:
        assert await f.read(1) == "a"
        before = await f.tell()
        with pytest.raises(TypeError):
            await f.seek(offset)
        assert await f.tell() == before
        assert await f.read() == "bcdef"
