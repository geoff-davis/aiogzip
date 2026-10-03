"""G07 public limit boundaries on small reads of highly compressible members."""

import gzip

import pytest
from conftest import FramedAsyncReader

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


async def small_read(stream, surface):
    if surface == "readinto":
        buffer = bytearray(7)
        size = await stream.readinto(buffer)
        return bytes(buffer[:size])
    return await getattr(stream, surface.removeprefix("text-"))(7)


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
            with pytest.raises(OSError):
                await stream.read(1)
            return
        result = await first()
        expected = payload.decode() if text else payload
        assert result == expected[: len(result)]
        assert result
        rest = await stream.read()
        assert (rest if surface == "peek" else result + rest) == expected
        assert stream.mtime == 22


@pytest.mark.parametrize("seekable", [False, True])
@pytest.mark.parametrize("layout", ["one-item", "members", "trailer"])
@pytest.mark.parametrize(
    "surface",
    ["read", "read1", "readinto", "peek", "readline", "text-read", "text-readline"],
)
async def test_partial_read_validation_metadata_and_salvage(seekable, layout, surface):
    # A text refill requests 256 KiB from the binary reader. Whole members of
    # that size let both text and binary calls stop at the same source boundary.
    size = AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE
    first, second = b"a" * size, b"b" * size
    wire1 = gzip.compress(first, mtime=11)
    wire2 = bytearray(gzip.compress(second, mtime=22))
    wire2[-8] ^= 1
    wire2 = bytes(wire2)
    assert len(wire1 + wire2) < size
    frames = {
        "one-item": (wire1 + wire2,),
        "members": (wire1, wire2),
        "trailer": (wire1, wire2[:-8], wire2[-8:]),
    }[layout]
    text = surface.startswith("text-")
    cls = AsyncGzipTextFile if text else AsyncGzipBinaryFile
    a, b = (first.decode(), second.decode()) if text else (first, second)
    async with cls(
        None,
        "rt" if text else "rb",
        fileobj=FramedAsyncReader(*frames, seekable=seekable),
        closefd=False,
    ) as stream:
        assert stream.mtime is None
        if layout == "one-item":
            with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
                await small_read(stream, surface)
            assert stream.mtime == 22
            assert await stream.read() == a + b
        else:
            result = await small_read(stream, surface)
            assert result == a[: len(result)]
            assert stream.mtime == 11
            consumed = 0 if surface == "peek" else len(result)
            assert await stream.read(len(a) - consumed) == a[consumed:]
            if layout == "members":
                with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
                    await small_read(stream, surface)
                assert stream.mtime == 22
                assert await stream.read() == b
            else:
                result = await small_read(stream, surface)
                assert result == b[: len(result)]
                assert stream.mtime == 22
                consumed = 0 if surface == "peek" else len(result)
                assert await stream.read(len(b) - consumed) == b[consumed:]
                with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
                    await stream.read(1)
        # A reported integrity failure is never a validated empty EOF.
        with pytest.raises(OSError, match="broken"):
            await stream.read(1)


@pytest.mark.parametrize("fault", ["limit", "crc"])
async def test_failed_readinto_does_not_modify_destination(fault):
    payload = b"x" * (1024 * 1024)
    wire = bytearray(gzip.compress(payload, mtime=0))
    if fault == "crc":
        wire[-8] ^= 1
    async with AsyncGzipBinaryFile(
        None,
        "rb",
        fileobj=FramedAsyncReader(bytes(wire)),
        closefd=False,
        max_decompressed_size=len(payload) - 1 if fault == "limit" else None,
    ) as stream:
        target = bytearray(b"!" * 7)
        with pytest.raises(OSError):
            await stream.readinto(target)
        assert target == b"!" * 7
