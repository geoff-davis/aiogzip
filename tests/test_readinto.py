"""readinto()/readinto1() parity with read()/read1().

These cover the direct-fill implementation that writes into the caller's buffer
instead of allocating an intermediate ``bytes`` object: byte-for-byte equality
with ``read()`` across chunk sizes (including ``chunk_size=1``), partial final
fills at EOF, and both ``bytearray`` and ``memoryview`` (incl. slice) targets.
"""

import gzip
import os

import pytest

from aiogzip import AsyncGzipBinaryFile

CHUNK_SIZES = [1, 2, 3, 7, 64, 1024]
BUF_SIZES = [1, 5, 64, 4096]

PAYLOADS = {
    "empty": b"",
    "tiny": b"hi",
    "text": b"The quick brown fox jumps over the lazy dog.\n" * 50,
    "binary": os.urandom(5000),
    "exact_buf": os.urandom(4096),
}


def _write(path, payload):
    with gzip.open(path, "wb") as f:
        f.write(payload)


async def _read_via_readinto(path, chunk_size, buf_size):
    """Drain the file through a fixed-size readinto() loop, checking tell()."""
    out = bytearray()
    async with AsyncGzipBinaryFile(path, "rb", chunk_size=chunk_size) as f:
        buf = bytearray(buf_size)
        while True:
            n = await f.readinto(buf)
            if n == 0:
                break
            assert 0 < n <= buf_size
            out += buf[:n]
            # tell() must agree with the number of bytes consumed so far.
            assert await f.tell() == len(out)
        # A second readinto past EOF keeps returning 0.
        assert await f.readinto(buf) == 0
    return bytes(out)


@pytest.mark.parametrize("name", list(PAYLOADS))
@pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
@pytest.mark.parametrize("buf_size", BUF_SIZES)
@pytest.mark.asyncio
async def test_readinto_matches_read(temp_file, name, chunk_size, buf_size):
    """readinto() loop reconstructs the payload byte-for-byte, like read()."""
    payload = PAYLOADS[name]
    _write(temp_file, payload)

    via_readinto = await _read_via_readinto(temp_file, chunk_size, buf_size)
    assert via_readinto == payload

    # Cross-check against read(-1) on a fresh handle.
    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
        assert via_readinto == await f.read(-1)


@pytest.mark.parametrize("chunk_size", [1, 7, 64])
@pytest.mark.asyncio
async def test_readinto_partial_final_fill_at_eof(temp_file, chunk_size):
    """A buffer larger than the remaining bytes gets a short final fill."""
    payload = b"0123456789ABCDE"  # 15 bytes
    _write(temp_file, payload)

    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
        # Consume the first 10 bytes with an exactly-sized buffer.
        head = bytearray(10)
        assert await f.readinto(head) == 10
        assert bytes(head) == payload[:10]

        # A 100-byte buffer can only be partially filled with the 5 left.
        tail = bytearray(100)
        n = await f.readinto(tail)
        assert n == 5
        assert bytes(tail[:5]) == payload[10:]
        # Bytes beyond the fill are untouched.
        assert bytes(tail[5:]) == bytes(95)
        # EOF reached.
        assert await f.readinto(tail) == 0


@pytest.mark.parametrize("chunk_size", [1, 7, 64])
@pytest.mark.asyncio
async def test_readinto_memoryview_target(temp_file, chunk_size):
    """readinto() works with a memoryview target, identical to a bytearray."""
    payload = os.urandom(2000)
    _write(temp_file, payload)

    out = bytearray()
    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
        backing = bytearray(64)
        view = memoryview(backing)
        while True:
            n = await f.readinto(view)
            if n == 0:
                break
            out += view[:n]
    assert bytes(out) == payload


@pytest.mark.parametrize("chunk_size", [1, 7, 64])
@pytest.mark.asyncio
async def test_readinto_memoryview_slice_target(temp_file, chunk_size):
    """readinto() fills only the slice region of a larger buffer."""
    payload = os.urandom(2000)
    _write(temp_file, payload)

    out = bytearray()
    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
        backing = bytearray(100)
        while True:
            window = memoryview(backing)[10:30]  # 20-byte writable window
            n = await f.readinto(window)
            if n == 0:
                break
            assert n <= 20
            # The bytes before the window are never written (stay zero).
            assert bytes(backing[:10]) == bytes(10)
            out += backing[10 : 10 + n]
    assert bytes(out) == payload


@pytest.mark.asyncio
async def test_readinto_readonly_buffer_raises(temp_file):
    """A read-only target is rejected with TypeError, before any read."""
    _write(temp_file, b"abc")
    async with AsyncGzipBinaryFile(temp_file, "rb") as f:
        with pytest.raises(TypeError, match="writable"):
            await f.readinto(memoryview(b"immutable"))
        with pytest.raises(TypeError, match="writable"):
            await f.readinto1(memoryview(b"immutable"))


@pytest.mark.asyncio
async def test_readinto_empty_target_returns_zero(temp_file):
    """A zero-length target returns 0 without consuming or filling."""
    _write(temp_file, b"abcdef")
    async with AsyncGzipBinaryFile(temp_file, "rb") as f:
        assert await f.readinto(bytearray(0)) == 0
        assert await f.tell() == 0
        # The stream is still fully readable afterwards.
        assert await f.read() == b"abcdef"


@pytest.mark.asyncio
async def test_readinto_on_closed_file_raises(temp_file):
    """readinto()/readinto1() on a closed file raise the same error as read()."""
    _write(temp_file, b"abc")
    f = AsyncGzipBinaryFile(temp_file, "rb")
    await f.__aenter__()
    await f.close()
    with pytest.raises(ValueError, match="closed"):
        await f.readinto(bytearray(4))
    with pytest.raises(ValueError, match="closed"):
        await f.readinto1(bytearray(4))


@pytest.mark.asyncio
async def test_readinto_in_write_mode_raises(temp_file):
    """readinto() in write mode raises, like read()."""
    async with AsyncGzipBinaryFile(temp_file, "wb") as f:
        with pytest.raises(OSError, match="not open for reading"):
            await f.readinto(bytearray(4))
        with pytest.raises(OSError, match="not open for reading"):
            await f.readinto1(bytearray(4))


@pytest.mark.parametrize("chunk_size", [1, 7, 64, 1024])
@pytest.mark.parametrize("buf_size", [1, 5, 64])
@pytest.mark.asyncio
async def test_readinto1_matches_read1(temp_file, chunk_size, buf_size):
    """readinto1() returns the same bytes/length as read1(), one fill at a time.

    read1()/readinto1() do at most one underlying fill, so with a small
    chunk_size they can legitimately return 0 mid-stream (a fill that decoded
    nothing yet) — that is not EOF, so the loop runs until the payload is fully
    collected rather than stopping on a zero.
    """
    payload = os.urandom(3000)
    _write(temp_file, payload)

    # read1 reference handle and readinto1 handle, stepped in lockstep.
    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as fr:
        async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as fi:
            out = bytearray()
            buf = bytearray(buf_size)
            while len(out) < len(payload):
                expected = await fr.read1(buf_size)
                n = await fi.readinto1(buf)
                assert n == len(expected)
                assert bytes(buf[:n]) == expected
                out += buf[:n]
            assert bytes(out) == payload
            # Both are drained now: further calls report EOF.
            assert await fr.read1(buf_size) == b""
            assert await fi.readinto1(buf) == 0
