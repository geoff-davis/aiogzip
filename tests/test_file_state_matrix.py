"""Cross-surface state-contract tests for binary and text file handles."""

import gzip
import io

import pytest
from conftest import FramedAsyncReader

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

_BINARY_READ_SURFACES = (
    "read",
    "readinto",
    "read1",
    "readinto1",
    "peek",
    "readline",
    "readlines",
    "anext",
    "seek",
    "tell",
)
_TEXT_READ_SURFACES = ("read", "readline", "readlines", "anext", "seek", "tell")


async def _call_read_surface(stream, surface):
    if surface == "read":
        return await stream.read(1)
    if surface == "readinto":
        return await stream.readinto(bytearray(1))
    if surface == "read1":
        return await stream.read1(1)
    if surface == "readinto1":
        return await stream.readinto1(bytearray(1))
    if surface == "peek":
        return await stream.peek(1)
    if surface == "readline":
        return await stream.readline()
    if surface == "readlines":
        return await stream.readlines()
    if surface == "anext":
        return await anext(stream)
    if surface == "seek":
        return await stream.seek(0)
    if surface == "tell":
        return await stream.tell()
    raise AssertionError(f"unknown surface: {surface}")


@pytest.mark.parametrize("surface", _BINARY_READ_SURFACES)
async def test_unopened_binary_read_surface_has_one_guard_contract(surface):
    stream = AsyncGzipBinaryFile("unused.gz", "rb")

    with pytest.raises(ValueError, match="File not opened"):
        await _call_read_surface(stream, surface)


@pytest.mark.parametrize("surface", _TEXT_READ_SURFACES)
async def test_unopened_text_read_surface_has_one_guard_contract(surface):
    stream = AsyncGzipTextFile("unused.gz", "rt")

    with pytest.raises(ValueError, match="File not opened"):
        await _call_read_surface(stream, surface)


@pytest.mark.parametrize(
    ("file_type", "mode", "surfaces"),
    [
        (AsyncGzipBinaryFile, "rb", _BINARY_READ_SURFACES),
        (AsyncGzipTextFile, "rt", _TEXT_READ_SURFACES),
    ],
)
async def test_failed_open_returns_every_read_surface_to_unopened_state(
    tmp_path, file_type, mode, surfaces
):
    stream = file_type(tmp_path / "missing" / "fixture.gz", mode)
    with pytest.raises(FileNotFoundError):
        await stream.open()

    for surface in surfaces:
        with pytest.raises(ValueError, match="File not opened"):
            await _call_read_surface(stream, surface)


@pytest.mark.parametrize("text_mode", [False, True])
async def test_closed_read_surfaces_have_one_guard_contract(tmp_path, text_mode):
    path = tmp_path / "closed-state.gz"
    path.write_bytes(gzip.compress(b"payload\n", mtime=0))
    if text_mode:
        stream = AsyncGzipTextFile(path, "rt")
        surfaces = _TEXT_READ_SURFACES
    else:
        stream = AsyncGzipBinaryFile(path, "rb")
        surfaces = _BINARY_READ_SURFACES

    await stream.open()
    await stream.close()

    for surface in surfaces:
        if surface == "anext":
            with pytest.raises(StopAsyncIteration):
                await _call_read_surface(stream, surface)
        else:
            with pytest.raises(ValueError, match="closed file"):
                await _call_read_surface(stream, surface)


@pytest.mark.parametrize("surface", _TEXT_READ_SURFACES)
async def test_exposed_buffer_close_closes_every_text_read_surface(tmp_path, surface):
    path = tmp_path / "buffer-closed-state.gz"
    path.write_bytes(gzip.compress(b"payload\n", mtime=0))
    stream = AsyncGzipTextFile(path, "rt")
    await stream.open()
    await stream.buffer.close()

    assert stream.closed is True
    assert stream.buffer._closed_observer is None
    if surface == "anext":
        with pytest.raises(StopAsyncIteration):
            await _call_read_surface(stream, surface)
    else:
        with pytest.raises(ValueError, match="closed file"):
            await _call_read_surface(stream, surface)


@pytest.mark.parametrize("surface", ["read", "readline", "readlines", "anext"])
async def test_validation_poison_is_not_masked_as_text_eof(surface):
    complete = b"complete line\n"
    partial = b"unterminated salvage"
    corrupt = bytearray(gzip.compress(complete + partial, mtime=0))
    corrupt[-8] ^= 1
    source = FramedAsyncReader(bytes(corrupt[:-8]), bytes(corrupt[-8:]))
    stream = AsyncGzipTextFile(
        None,
        "rt",
        fileobj=source,
        closefd=False,
        chunk_size=len(corrupt),
    )

    await stream.open()
    try:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.read(len(complete + partial) + 1)

        if surface == "read":
            assert await stream.read() == (complete + partial).decode()
        elif surface == "readline":
            assert await stream.readline() == complete.decode()
            with pytest.raises(OSError, match="broken.*close and reopen"):
                await stream.readline()
        elif surface == "readlines":
            with pytest.raises(OSError, match="broken.*close and reopen"):
                await stream.readlines()
            assert await stream.read() == (complete + partial).decode()
        else:
            assert await anext(stream) == complete.decode()
            with pytest.raises(OSError, match="broken.*close and reopen"):
                await anext(stream)
    finally:
        await stream.close()


async def test_binary_readlines_restores_lines_after_validation_failure():
    complete = b"".join(f"line {i}\n".encode() for i in range(1000))
    partial = b"unterminated salvage"
    corrupt = bytearray(gzip.compress(complete + partial, mtime=0))
    corrupt[-8] ^= 1
    source = FramedAsyncReader(bytes(corrupt[:-8]), bytes(corrupt[-8:]))
    stream = AsyncGzipBinaryFile(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(corrupt),
    )

    await stream.open()
    try:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.readlines()

        assert await stream.tell() == 0
        assert await stream.read() == complete + partial
    finally:
        await stream.close()


@pytest.mark.parametrize("newline", [None, ""])
async def test_text_readlines_restores_lines_after_transient_source_error(newline):
    class FailOnceReader:
        def __init__(self, data):
            self._buffer = io.BytesIO(data)
            self._reads = 0
            self.failed = False

        async def read(self, size=-1):
            self._reads += 1
            if self._reads == 5:
                self.failed = True
                raise OSError("transient source failure")
            return self._buffer.read(size)

        def seekable(self):
            return False

        async def close(self):
            pass

    lines = [f"line {i:04d}\n" for i in range(1000)]
    source = FailOnceReader(gzip.compress("".join(lines).encode(), mtime=0))
    stream = AsyncGzipTextFile(
        None,
        "rt",
        newline=newline,
        fileobj=source,
        closefd=False,
        chunk_size=64,
    )

    await stream.open()
    try:
        with pytest.raises(OSError, match="transient source failure"):
            await stream.readlines()
        assert source.failed is True
        assert await stream.readlines() == lines
    finally:
        await stream.close()


async def test_zero_fill_seek_reports_the_broken_writer_contract():
    class FailOnceWriter:
        def __init__(self):
            self.buffer = bytearray()
            self.fail_next = False

        async def write(self, data):
            if self.fail_next:
                self.fail_next = False
                raise OSError("transient sink failure")
            self.buffer.extend(data)
            return len(data)

        async def flush(self):
            pass

        async def close(self):
            pass

    writer = FailOnceWriter()
    stream = AsyncGzipBinaryFile(
        None,
        "wb",
        fileobj=writer,
        closefd=False,
        chunk_size=1024,
        mtime=0,
    )
    await stream.open()
    writer.fail_next = True
    with pytest.raises(OSError, match="transient sink failure"):
        await stream.flush()

    with pytest.raises(OSError, match="write stream is broken.*member is unusable"):
        await stream.seek(1)
    await stream.close()


async def test_missing_encoder_during_reservation_exit_does_not_wedge_writer(tmp_path):
    stream = AsyncGzipBinaryFile(tmp_path / "reservation-exit.gz", "wb", mtime=0)
    await stream.open()
    encoder = stream._encoder
    assert encoder is not None

    with stream._write_call:
        stream._encoder = None

    assert stream._write_call_active is False
    stream._encoder = encoder
    await stream.close()
