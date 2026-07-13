"""Tests for the whole-file read() and write() convenience functions."""

import gzip
import io

import pytest

import aiogzip


@pytest.mark.parametrize("payload", [b"", b"hello world", bytes(range(256)) * 20])
async def test_path_roundtrip(tmp_path, payload):
    path = tmp_path / "payload.gz"

    result = await aiogzip.write(path, payload)

    assert result is None
    assert await aiogzip.read(path) == payload


async def test_write_accepts_declared_bytes_like_inputs(tmp_path):
    inputs = [bytearray(b"mutable"), memoryview(b"view")]

    for index, payload in enumerate(inputs):
        path = tmp_path / f"payload-{index}.gz"
        await aiogzip.write(path, payload)
        assert await aiogzip.read(path) == bytes(payload)


async def test_async_file_objects_roundtrip():
    class AsyncBuffer:
        def __init__(self, data=b""):
            self.buffer = io.BytesIO(data)
            self.closed = False

        async def read(self, size=-1):
            return self.buffer.read(size)

        async def write(self, data):
            return self.buffer.write(data)

        async def close(self):
            self.closed = True

    writer = AsyncBuffer()
    await aiogzip.write(None, b"stream payload", fileobj=writer, closefd=True, mtime=0)

    assert writer.closed
    compressed = writer.buffer.getvalue()
    reader = AsyncBuffer(compressed)
    assert await aiogzip.read(None, fileobj=reader, closefd=True) == b"stream payload"
    assert reader.closed


async def test_read_limit_failure_closes_owned_file_object():
    class TrackingReader:
        def __init__(self, data):
            self.buffer = io.BytesIO(data)
            self.closed = False

        async def read(self, size=-1):
            return self.buffer.read(size)

        async def close(self):
            self.closed = True

    reader = TrackingReader(gzip.compress(b"x" * 1024))

    with pytest.raises(OSError, match="max_decompressed_size"):
        await aiogzip.read(
            None,
            fileobj=reader,
            closefd=True,
            max_decompressed_size=100,
        )

    assert reader.closed


async def test_write_finalizes_gzip_stream(tmp_path):
    path = tmp_path / "finalized.gz"
    await aiogzip.write(path, b"complete payload", mtime=0)

    assert gzip.decompress(path.read_bytes()) == b"complete payload"


async def test_explicit_metadata_produces_deterministic_output(tmp_path):
    path = tmp_path / "deterministic.gz"
    kwargs = {"mtime": 0, "original_filename": "payload.bin"}

    await aiogzip.write(path, b"stable payload", **kwargs)
    first = path.read_bytes()
    await aiogzip.write(path, b"stable payload", **kwargs)

    assert path.read_bytes() == first
