"""Parity matrix T1-T5: text paths kept inline and their reference paths.

| Id | Inline path | Reference path |
| --- | --- | --- |
| T1 | ``write()`` encoder/sink body | ``_write_batch_reserved`` under ``_write_call`` |
| T2 | Origin capture in ``_read_chunk_and_decode`` | ``_capture_buffer_origin`` |
| T3 | ``_decode_next_chunk`` (sized reads, fast lines) | ``_read_chunk_and_decode`` (buffered readline) |
| T4 | Pending-line consumption in ``__anext__`` | ``readline()`` |
| T5 | Bounded fast path in ``readline()`` | ``_take_buffered_line`` |
"""

import asyncio
import gzip
import io
import os
import random
import sys

import pytest
from conftest import FramedAsyncReader

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile, ConcurrentOperationError

NEWLINES = [None, "", "\n", "\r", "\r\n"]
FAST_NEWLINES = [None, "\n", "\r"]  # _FAST_READLINE_NEWLINES: set _line_term
TEXT = "alpha\nbeta\r\ngamma\rdelta 日本\n\nlast 🚀 no newline"
_RANDOM = random.Random(0)
# Text that compresses poorly, so writes and reads reach the transport.
NOISY = "".join(
    "".join(_RANDOM.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=60)) + "\n"
    for _ in range(5000)
)


def _translated_on_write(text, newline):
    if newline is None:
        return text.replace("\n", os.linesep)
    if newline in ("\n", "\r", "\r\n"):
        return text.replace("\n", newline)
    return text


def _decoded(text, newline, encoding="utf-8"):
    return io.TextIOWrapper(
        io.BytesIO(text.encode(encoding)), encoding=encoding, newline=newline
    ).read()


def _wire(text, encoding="utf-8"):
    return gzip.compress(text.encode(encoding), mtime=0)


def _reader(data, chunk_size=7, **options):
    options.setdefault("closefd", False)
    return AsyncGzipTextFile(
        None,
        "rt",
        fileobj=FramedAsyncReader(data),
        chunk_size=chunk_size,
        **options,
    )


def _corrupt_crc(data):
    corrupt = bytearray(data)
    corrupt[-8] ^= 1
    return bytes(corrupt)


# T1: text write


class _Sink:
    def __init__(self):
        self.data = bytearray()
        self.fail = False
        self.gate = None
        self.entered = asyncio.Event()

    async def write(self, data):
        if self.gate is not None:
            self.entered.set()
            await self.gate.wait()
        if self.fail:
            raise OSError("sink write failed")
        self.data += data
        return len(data)

    def close(self):
        pass


async def _write_inline(f, text):
    return await f.write(text)


async def _write_reserved(f, text):
    # write()'s own validation, then the shared reserved batch body.
    if not f._writing_mode:
        raise OSError("File not open for writing")
    if f._is_closed:
        raise ValueError("I/O operation on closed file.")
    if f._binary_file is None:
        raise ValueError("File not opened. Call await open() or use async with.")
    with f._write_call:
        return await f._write_batch_reserved(text)


WRITERS = {"inline": _write_inline, "reserved": _write_reserved}


async def _writer(sink=None, **options):
    sink = sink or _Sink()
    f = AsyncGzipTextFile(None, "wt", fileobj=sink, closefd=False, mtime=0, **options)
    await f.open()
    return f, sink


def _text_state(f):
    return (
        f._encoder.getstate(),
        f._encoder_used,
        f._write_call_active,
        f.buffer._position,
    )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "shift_jis"])
@pytest.mark.parametrize("newline", NEWLINES)
async def test_t1_writes_encode_identically(newline, encoding):
    pieces = ["", "first\n", "日本\r\n", "", "x\ry\n" * 50, "tail"]
    outputs = []
    for writer in WRITERS.values():
        f, sink = await _writer(newline=newline, encoding=encoding)
        returns = [await writer(f, piece) for piece in pieces]
        state = _text_state(f)
        await f.close()
        outputs.append((returns, state, gzip.decompress(bytes(sink.data))))
    assert outputs[0] == outputs[1]
    # A stateful encoding emits its BOM once across both paths.
    expected = _translated_on_write("".join(pieces), newline)
    assert outputs[0][2].decode(encoding) == expected


@pytest.mark.parametrize("writer", WRITERS)
async def test_t1_sink_failure_restores_encoder_state(writer):
    f, sink = await _writer(encoding="utf-16")
    before = _text_state(f)
    sink.fail = True
    with pytest.raises(OSError, match="sink write failed"):
        await WRITERS[writer](f, NOISY)
    after = _text_state(f)
    assert after[:3] == before[:3]  # encoder state and use flag rolled back


async def _blocked_text_write(writer):
    f, sink = await _writer()
    sink.gate = asyncio.Event()
    task = asyncio.create_task(WRITERS[writer](f, NOISY))
    await asyncio.wait_for(sink.entered.wait(), 5)
    return f, sink, task


async def _t1_cancel_outcome(writer):
    f, sink, task = await _blocked_text_write(writer)
    task.cancel()
    sink.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    return _text_state(f)[:3], f.buffer._write_broken


async def test_t1_cancellation_matches():
    assert await _t1_cancel_outcome("inline") == await _t1_cancel_outcome("reserved")


async def _t1_overlap_outcome(writer):
    f, sink, task = await _blocked_text_write(writer)
    errors = []
    for other in WRITERS.values():
        with pytest.raises(ConcurrentOperationError) as raised:
            await other(f, "second")
        errors.append(type(raised.value))
    with pytest.raises(ConcurrentOperationError):
        await f.close()
    sink.gate.set()
    result = await task
    await f.close()
    return errors, result, gzip.decompress(bytes(sink.data))


async def test_t1_overlap_and_close_during_write_match():
    assert await _t1_overlap_outcome("inline") == await _t1_overlap_outcome("reserved")


@pytest.mark.parametrize("writer", WRITERS)
async def test_t1_closed_and_invalid_input_match(writer):
    f, sink = await _writer()
    with pytest.raises(TypeError):
        await WRITERS[writer](f, b"bytes")
    assert _text_state(f)[2] is False
    await f.close()
    with pytest.raises(ValueError, match="closed"):
        await WRITERS[writer](f, "late")


# T2: inline origin capture


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le"])
@pytest.mark.parametrize("newline", NEWLINES)
async def test_t2_inline_origin_matches_the_helper(newline, encoding, monkeypatch):
    stream = _reader(_wire(TEXT * 5, encoding), newline=newline, encoding=encoding)
    original_read = AsyncGzipBinaryFile.read
    checked = []

    async def read(self, size=-1):
        # Called right after the refill captured its origin inline (or not,
        # when text was still buffered). Compare with the helper's result.
        caller = sys._getframe(1).f_code.co_name
        if (
            self is stream._binary_file
            and caller == "_read_chunk_and_decode"
            and stream._buffered_text_len() == 0
        ):
            origin = stream._buffer_origin
            inline = (
                origin.byte_offset,
                origin.decoder_state,
                origin.trailing_cr,
                origin.seen_newline_types,
                origin.chars_to_skip,
            )
            stream._capture_buffer_origin()
            helper = (
                origin.byte_offset,
                origin.decoder_state,
                origin.trailing_cr,
                origin.seen_newline_types,
                origin.chars_to_skip,
            )
            checked.append(inline == helper)
        return await original_read(self, size)

    monkeypatch.setattr(AsyncGzipBinaryFile, "read", read)
    async with stream:
        await stream.read()  # T3 checks the content
        await stream.seek(0)
        while await stream.readline():
            pass
    assert all(checked)
    if newline not in FAST_NEWLINES:
        assert checked  # generic modes refill through the inline capture


# T3: _decode_next_chunk vs _read_chunk_and_decode


async def _assembled(stream, how):
    """Text read by one path, with the newline types it recorded at EOF."""
    async with stream:
        if how == "read":
            text = await stream.read()
        elif how == "sized":
            parts = []
            while part := await stream.read(5):
                parts.append(part)
            text = "".join(parts)
        else:
            parts = []
            while line := await stream.readline():
                parts.append(line)
            text = "".join(parts)
        return text, stream.newlines


@pytest.mark.parametrize(
    "text",
    # The second text's only bare CR is the trailing one, so only EOF can
    # record it in newlines.
    [TEXT + "\r\nend\r", "a\nb\r\nend 日本\r"],
    ids=["mixed", "trailing-cr-only"],
)
@pytest.mark.parametrize("chunking", ["7", "aligned"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize("newline", NEWLINES)
async def test_t3_sized_reads_match_buffered_readline(
    newline, encoding, text, chunking
):
    # Multibyte splits at 7-byte chunks, and a chunk size that divides the
    # payload exactly, so the last data read ends before binary sees EOF and
    # only the empty EOF read resolves a trailing CR.
    data = _wire(text, encoding)
    chunk_size = 7 if chunking == "7" else len(text.encode(encoding)) // 2
    results = {
        how: await _assembled(
            _reader(data, chunk_size, newline=newline, encoding=encoding), how
        )
        for how in ("read", "sized", "readline")
    }
    assert results["read"] == results["sized"] == results["readline"]
    reference = io.TextIOWrapper(
        io.BytesIO(text.encode(encoding)), encoding=encoding, newline=newline
    )
    # The trailing CR is recorded in newlines only when EOF resolves it.
    assert results["read"] == (reference.read(), reference.newlines)


@pytest.mark.parametrize("how", ["read", "sized", "readline"])
async def test_t3_validation_salvage_matches(how):
    text = TEXT * 20 + "\n"
    data = _corrupt_crc(_wire(text))
    stream = _reader(data, chunk_size=64)
    collected = []
    async with stream:
        with pytest.raises(gzip.BadGzipFile):
            if how == "readline":
                while line := await stream.readline():
                    collected.append(line)
            else:
                while part := await stream.read(-1 if how == "read" else 5):
                    collected.append(part)
        # Salvage is served, then the reader is terminal.
        try:
            while True:
                part = await (
                    stream.readline() if how == "readline" else stream.read(4096)
                )
                if not part:
                    break
                collected.append(part)
        except OSError:
            pass
    assert "".join(collected) == _decoded(text, None)


# T4: iteration vs readline


async def _lines_and_cookies(stream, how):
    """Lines, and for each cookie the text a seek to it replays.

    Cookies are opaque and valid only on their issuing handle; two paths may
    encode one position differently, so they are compared by replay.
    """
    lines, cookies = [], []
    async with stream:
        if how == "iterate":
            async for line in stream:
                lines.append(line)
                cookies.append(await stream.tell())
        else:
            while line := await stream.readline():
                lines.append(line)
                cookies.append(await stream.tell())
        replays = []
        for cookie in cookies:
            await stream.seek(cookie)
            replays.append(await stream.read())
    return lines, replays


@pytest.mark.parametrize(
    "text", [TEXT, "", "one line no newline", "\n\n\n", "a\nb\n" * 300]
)
@pytest.mark.parametrize("newline", NEWLINES)
async def test_t4_iteration_matches_readline(newline, text):
    data = _wire(text)
    iterated = await _lines_and_cookies(_reader(data, newline=newline), "iterate")
    read = await _lines_and_cookies(_reader(data, newline=newline), "readline")
    assert iterated == read


async def test_t4_cookies_from_iteration_replay_the_remaining_lines():
    data = _wire("a\nb\n" * 300)
    lines, replays = await _lines_and_cookies(_reader(data, newline="\n"), "iterate")
    for index, replay in enumerate(replays):
        assert replay == "".join(lines[index + 1 :])


async def _t4_salvage(how):
    stream = _reader(_corrupt_crc(_wire("x\n" * 2000)), chunk_size=64, newline="\n")
    events = []
    async with stream:
        for _ in range(5000):
            try:
                if how == "iterate":
                    line = await stream.__anext__()
                else:
                    line = await stream.readline()
                    if not line:
                        raise StopAsyncIteration
                events.append(line)
            except StopAsyncIteration:
                events.append("<end>")
                break
            except OSError as error:
                events.append(type(error).__name__)
                if not isinstance(error, gzip.BadGzipFile):
                    break
    return events


async def test_t4_salvage_then_terminal_matches():
    assert await _t4_salvage("iterate") == await _t4_salvage("readline")


class _GatedSource:
    def __init__(self, data):
        self.buffer = io.BytesIO(data)
        self.gate = None
        self.entered = asyncio.Event()

    def seekable(self):
        return False

    async def read(self, size=-1):
        if self.gate is not None:
            self.entered.set()
            await self.gate.wait()
        return self.buffer.read(size)

    def close(self):
        pass


async def _t4_interrupted(how, interruption):
    source = _GatedSource(_wire(NOISY[:20_000]))
    stream = AsyncGzipTextFile(
        None, "rt", fileobj=source, closefd=False, chunk_size=64, newline="\n"
    )
    await stream.open()

    def call():
        return stream.__anext__() if how == "iterate" else stream.readline()

    # Consume lines until a call has to wait on the source.
    first = []
    source.gate = asyncio.Event()
    while True:
        task = asyncio.create_task(call())
        entered = asyncio.create_task(source.entered.wait())
        done, _ = await asyncio.wait(
            {task, entered}, timeout=5, return_when=asyncio.FIRST_COMPLETED
        )
        if entered in done:
            break
        entered.cancel()
        first.append(task.result())
    outcome = []
    if interruption == "overlap":
        for other in (stream.readline(), stream.__anext__()):
            with pytest.raises(ConcurrentOperationError):
                await other
            outcome.append("overlap-rejected")
        source.gate.set()
        outcome.append(await task)
    else:
        task.cancel()
        source.gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        outcome.append("cancelled")
        try:
            outcome.append(await stream.readline())
        except OSError as error:
            outcome.append(type(error).__name__)
    await stream.close()
    return first, outcome


@pytest.mark.parametrize("interruption", ["cancel", "overlap"])
async def test_t4_interrupted_refill_matches(interruption):
    assert await _t4_interrupted("iterate", interruption) == await _t4_interrupted(
        "readline", interruption
    )


@pytest.mark.parametrize("how", ["iterate", "readline"])
async def test_t4_close_during_iteration(how):
    stream = _reader(_wire("a\nb\nc\n"), newline="\n")
    await stream.open()
    assert await stream.readline() == "a\n"
    await stream.close()
    if how == "iterate":
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
    else:
        with pytest.raises(ValueError, match="closed"):
            await stream.readline()


# T5: bounded readline fast path


@pytest.mark.parametrize("newline", NEWLINES)
@pytest.mark.parametrize("limit", [1, 3, 4, 5, 6, 8, 40])
async def test_t5_bounded_readline_matches_the_helper(newline, limit):
    # After the first line, "ab\r\ncd\n..." is buffered: limit 3 splits the
    # CRLF, 4 ends on it, and 40 equals or exceeds the buffered length.
    data = _wire("first\nab\r\ncd\nef")
    results = []
    for path in ("inline", "helper"):
        stream = _reader(data, chunk_size=4096, newline=newline)
        async with stream:
            await stream.readline()
            buffered = stream._buffered_text_len()
            if path == "inline":
                line = await stream.readline(limit)
            else:
                line = stream._take_buffered_line(limit)
            results.append(
                (line, stream._text_buffer_offset, stream._buffered_text_len())
            )
    inline, helper = results
    if helper[0] is None:
        # The helper declines when a refill is needed; the inline path then
        # reads on, so only a limit at or beyond the buffered text can differ.
        assert limit >= buffered
    else:
        assert inline == helper
