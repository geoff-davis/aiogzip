"""Cross-surface state-contract tests for binary and text file handles."""

import asyncio
import gzip
import io

import pytest
from conftest import FramedAsyncReader

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
    ConcurrentOperationError,
)

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

    if text_mode:
        assert stream.buffer._read_poison_observer is None

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
            assert await stream.readlines() == [complete.decode()]
            with pytest.raises(OSError, match="broken.*close and reopen"):
                await stream.readlines()
            assert await stream.read() == partial.decode()
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


async def test_rejected_binary_readlines_does_not_touch_active_call_state():
    class BlockingTrailerReader:
        def __init__(self, body, trailer):
            self._frames = (body, trailer, b"")
            self._index = 0
            self.trailer_read_started = asyncio.Event()
            self.release_trailer = asyncio.Event()

        async def read(self, size=-1):
            if self._index == 1:
                self.trailer_read_started.set()
                await self.release_trailer.wait()
            frame = self._frames[self._index]
            self._index += 1
            return frame

        def seekable(self):
            return False

        async def close(self):
            pass

    lines = [f"line {index:05d} payload\n".encode() for index in range(10_000)]
    compressed = gzip.compress(b"".join(lines), mtime=0)
    source = BlockingTrailerReader(compressed[:-8], compressed[-8:])
    stream = AsyncGzipBinaryFile(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(compressed),
    )

    await stream.open()
    active = asyncio.create_task(stream.readlines())
    try:
        await source.trailer_read_started.wait()
        buffer_before = stream._buffer
        offset_before = stream._buffer_offset
        position_before = stream._position

        with pytest.raises(ConcurrentOperationError, match="active read"):
            await stream.readlines()

        assert stream._buffer is buffer_before
        assert stream._buffer_offset == offset_before
        assert stream._position == position_before

        source.release_trailer.set()
        assert await active == lines
    finally:
        source.release_trailer.set()
        if not active.done():
            await active
        await stream.close()


@pytest.mark.parametrize("text_mode", [False, True])
async def test_default_chunk_validation_salvage_sequence_is_error_data_error(
    text_mode,
):
    payload = "small validation salvage" if text_mode else b"small validation salvage"
    raw = payload.encode() if text_mode else payload
    corrupt = bytearray(gzip.compress(raw, mtime=0))
    corrupt[-8] ^= 1
    source = FramedAsyncReader(bytes(corrupt), seekable=False)
    if text_mode:
        stream = AsyncGzipTextFile(None, "rt", fileobj=source, closefd=False)
    else:
        stream = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=False)

    await stream.open()
    try:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.read(len(payload) + 1)
        assert await stream.read(len(payload) + 1) == payload
        with pytest.raises(OSError, match="broken.*close and reopen"):
            await stream.read(1)
    finally:
        await stream.close()


@pytest.mark.parametrize("surface", ["binary", "text-fast", "text-generic"])
async def test_default_chunk_readlines_salvage_sequence_is_error_data_error(
    surface,
):
    raw_lines = [b"first recovery line\n", b"second recovery line\n"]
    corrupt = bytearray(gzip.compress(b"".join(raw_lines), mtime=0))
    corrupt[-8] ^= 1
    source = FramedAsyncReader(bytes(corrupt), seekable=False)
    if surface == "binary":
        stream = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=False)
        expected = raw_lines
    else:
        newline = None if surface == "text-fast" else ""
        stream = AsyncGzipTextFile(
            None,
            "rt",
            newline=newline,
            fileobj=source,
            closefd=False,
        )
        expected = [line.decode() for line in raw_lines]

    await stream.open()
    try:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.readlines()
        assert await stream.readlines() == expected
        with pytest.raises(OSError, match="broken.*close and reopen"):
            await stream.readlines()
    finally:
        await stream.close()


async def test_validation_salvage_does_not_finalize_a_trailing_cr():
    payload = b"uncertain terminator\r"
    corrupt = bytearray(gzip.compress(payload, mtime=0))
    corrupt[-8] ^= 1
    stream = AsyncGzipTextFile(
        None,
        "rt",
        newline="",
        fileobj=FramedAsyncReader(bytes(corrupt), seekable=False),
        closefd=False,
    )

    await stream.open()
    try:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.readline()
        with pytest.raises(OSError, match="broken.*close and reopen"):
            await stream.readline()

        assert stream.newlines is None
        assert await stream.read() == payload.decode()
        assert stream.newlines is None
    finally:
        await stream.close()


async def test_cancelled_text_sized_read_does_not_publish_restored_pieces(monkeypatch):
    stream = AsyncGzipTextFile(
        None,
        "rt",
        fileobj=FramedAsyncReader(gzip.compress(b"unused", mtime=0)),
        closefd=False,
    )
    calls = 0

    async def cancel_after_one_piece(file):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "decoded before cancellation", True
        binary_file = file._binary_file
        assert binary_file is not None
        decoder = binary_file._decoder
        assert decoder is not None
        binary_file._poison_read(decoder)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        AsyncGzipTextFile,
        "_decode_next_chunk",
        cancel_after_one_piece,
    )

    await stream.open()
    try:
        with pytest.raises(asyncio.CancelledError):
            await stream.read(100)
        assert stream._read_poisoned is True
        assert stream._buffered_text_len() == 0
        with pytest.raises(OSError, match="broken.*close and reopen"):
            await stream.read(1)
    finally:
        await stream.close()


async def test_failed_backward_seek_reports_the_post_rewind_position():
    payload = b"0123456789" * 2000
    valid = gzip.compress(payload, mtime=0)
    corrupt = bytearray(valid)
    corrupt[-8] ^= 1

    class CorruptAfterRewindReader:
        def __init__(self):
            self._buffer = io.BytesIO(valid)
            self.rewound = False

        async def read(self, size=-1):
            return self._buffer.read(size)

        async def seek(self, offset, whence=io.SEEK_SET):
            if offset == 0 and whence == io.SEEK_SET:
                self._buffer = io.BytesIO(bytes(corrupt))
                self.rewound = True
            return self._buffer.seek(offset, whence)

        def seekable(self):
            return True

        async def close(self):
            pass

    source = CorruptAfterRewindReader()
    stream = AsyncGzipBinaryFile(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(valid),
    )
    await stream.open()
    try:
        assert await stream.read(5000) == payload[:5000]
        assert await stream.tell() == 5000

        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.seek(1000)

        assert source.rewound is True
        assert await stream.tell() == 0
    finally:
        await stream.close()


async def test_cookie_recovery_clears_the_text_poison_mirror(tmp_path):
    payload = "alpha\nbeta\ngamma\n"
    path = tmp_path / "cookie-poison-recovery.gz"
    path.write_bytes(gzip.compress(payload.encode(), mtime=0))
    stream = AsyncGzipTextFile(path, "rt", chunk_size=4)

    await stream.open()
    try:
        assert await stream.read(1) == payload[:1]
        cookie = await stream.tell()
        assert cookie < 0

        binary_file = stream.buffer
        decoder = binary_file._decoder
        assert decoder is not None
        binary_file._poison_read(decoder, validation_failed=True)
        assert binary_file._read_broken is True
        assert stream._read_poisoned is True

        assert await stream.seek(cookie) == cookie
        assert binary_file._read_broken is False
        assert stream._read_poisoned is False
        assert await stream.read() == payload[1:]
    finally:
        await stream.close()


@pytest.mark.parametrize("reject_binary_write", [False, True])
async def test_text_inline_write_matches_reserved_helper(
    tmp_path,
    monkeypatch,
    reject_binary_write,
):
    data = "first line\n日本語"
    translated = data.replace("\n", "\r\n")
    original_binary_write = AsyncGzipBinaryFile.write

    async def exercise(path, *, public):
        stream = AsyncGzipTextFile(
            path,
            "wt",
            encoding="iso2022_jp",
            newline="\r\n",
            mtime=0,
        )
        await stream.open()
        encoder = stream._encoder
        assert encoder is not None
        binary_file = stream.buffer

        if reject_binary_write:

            async def reject_target_write(file, payload):
                if file is binary_file:
                    raise OSError("controlled binary rejection")
                return await original_binary_write(file, payload)

            monkeypatch.setattr(
                AsyncGzipBinaryFile,
                "write",
                reject_target_write,
            )

        result = None
        error = None
        try:
            if public:
                result = await stream.write(data)
            else:
                with stream._write_call:
                    result = await stream._write_reserved(data, translated)
        except OSError as exc:
            error = (type(exc), str(exc))

        state = (
            encoder.getstate(),
            stream._encoder_used,
            stream._write_call_active,
        )
        monkeypatch.setattr(
            AsyncGzipBinaryFile,
            "write",
            original_binary_write,
        )
        await stream.close()
        return result, error, state, gzip.decompress(path.read_bytes())

    public = await exercise(tmp_path / "public-write.gz", public=True)
    reserved = await exercise(tmp_path / "reserved-write.gz", public=False)

    assert public == reserved


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
