"""readinto()/readinto1() parity with read()/read1().

These cover the direct-fill implementation that writes into the caller's buffer
instead of allocating an intermediate ``bytes`` object: byte-for-byte equality
with ``read()`` across chunk sizes (including ``chunk_size=1``), partial final
fills at EOF, and both ``bytearray`` and ``memoryview`` (incl. slice) targets.
"""

import array
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
    """A read-only target is rejected with TypeError naming the right method."""
    _write(temp_file, b"abc")
    async with AsyncGzipBinaryFile(temp_file, "rb") as f:
        with pytest.raises(TypeError, match=r"readinto\(\) argument must be writable"):
            await f.readinto(memoryview(b"immutable"))
        with pytest.raises(TypeError, match=r"readinto1\(\) argument must be writable"):
            await f.readinto1(memoryview(b"immutable"))


@pytest.mark.asyncio
async def test_readinto_itemsize_gt_one_buffer_matches_stdlib(temp_file):
    """Writable buffers with itemsize > 1 (array.array) fill like stdlib gzip.

    The view must be cast to bytes: without the cast, the slice assignment
    raises ValueError and the count would be in elements rather than bytes.
    """
    item = array.array("i", [0]).itemsize
    payload = os.urandom(100 * item)
    _write(temp_file, payload)

    expected = array.array("i", bytes(100 * item))
    with gzip.open(temp_file, "rb") as sf:
        n_std = sf.readinto(expected)

    arr = array.array("i", bytes(100 * item))
    async with AsyncGzipBinaryFile(temp_file, "rb") as f:
        n = await f.readinto(arr)
    assert n == n_std == 100 * item  # byte count, not element count
    assert arr == expected

    arr1 = array.array("i", bytes(100 * item))
    async with AsyncGzipBinaryFile(temp_file, "rb") as f:
        n1 = await f.readinto1(arr1)
    assert n1 > 0
    assert arr1.tobytes()[:n1] == payload[:n1]


@pytest.mark.asyncio
async def test_readinto_error_leaves_position_and_buffer_intact(temp_file):
    """A decompression error mid-request must not consume already-decoded data.

    readinto() fills the internal buffer before copying anything into the
    caller's view, so when a refill raises (truncated stream here) the
    position is unchanged and the good prefix is still readable — the same
    salvage semantics as read().
    """
    payload = b"payload data " * 4096
    _write(temp_file, payload)
    blob = open(temp_file, "rb").read()
    with open(temp_file, "wb") as fh:
        fh.write(blob[: len(blob) // 2])  # truncate mid-stream

    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=64) as f:
        with pytest.raises(OSError):
            await f.readinto(bytearray(len(payload)))
        # Nothing was consumed by the failed call...
        assert await f.tell() == 0
        # ...and the decoded prefix is still available to salvage.
        assert await f.read(10) == payload[:10]


@pytest.mark.parametrize("chunk_size", [1, 2, 3])
@pytest.mark.asyncio
async def test_readinto1_and_read1_zero_only_at_eof(temp_file, chunk_size):
    """readinto1()/read1() return 0/b'' only at EOF, like stdlib gzip.

    With a tiny chunk_size a single fill can decode nothing (it is still
    consuming the gzip header), so the fill must repeat until at least one
    byte is available; otherwise the standard ``while n := readinto1(buf)``
    consumer loop terminates before any data.
    """
    payload = b"hello world"
    _write(temp_file, payload)

    out = bytearray()
    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
        buf = bytearray(4)
        while True:
            n = await f.readinto1(buf)
            if n == 0:
                break
            out += buf[:n]
    assert bytes(out) == payload

    out1 = b""
    async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
        while True:
            chunk = await f.read1(4)
            if not chunk:
                break
            out1 += chunk
    assert out1 == payload


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

    Both repeat fills until at least one byte decodes (a fill can consume
    compressed input, e.g. the gzip header, without producing output), so a
    zero/empty result means EOF for both and they stay in lockstep.
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
