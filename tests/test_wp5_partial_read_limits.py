"""G07 public limit boundaries on small reads of highly compressible members."""

import gzip

import pytest
from conftest import FramedAsyncReader

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


@pytest.mark.parametrize("seekable", [False, True])
@pytest.mark.parametrize(
    "surface",
    ["read", "read1", "readinto", "peek", "readline", "text-read", "text-readline"],
)
@pytest.mark.parametrize("delta", [-1, 0, 1])
async def test_partial_read_respects_complete_payload_limit(seekable, surface, delta):
    payload = b"x" * (1024 * 1024)
    wire = gzip.compress(payload[: len(payload) // 2], mtime=11) + gzip.compress(
        payload[len(payload) // 2 :], mtime=22
    )
    assert len(wire) < AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE
    source = FramedAsyncReader(wire, seekable=seekable)
    text = surface.startswith("text-")
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    async with cls(
        None,
        "rt" if text else "rb",
        fileobj=source,
        closefd=False,
        max_decompressed_size=len(payload) + delta,
    ) as stream:

        async def first():
            if surface == "readinto":
                buffer = bytearray(7)
                count = await stream.readinto(buffer)
                return bytes(buffer[:count])
            return await getattr(stream, surface.removeprefix("text-"))(7)

        if delta < 0:
            # Both members fit one source read. The limit must not be bypassed
            # by requesting a tiny logical result or mistaken for validated EOF.
            with pytest.raises(OSError, match="max_decompressed_size"):
                await first()
            return
        result = await first()
        expected = payload.decode() if text else payload
        assert result == expected[: len(result)]
        assert result
        rest = await stream.read()
        assert (rest if surface == "peek" else result + rest) == expected
        assert stream.mtime == 22
