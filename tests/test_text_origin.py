"""WP7: the text replay origin is one checkpoint object with independent copies."""

import ast
import dataclasses
import gzip
import io
from pathlib import Path

import pytest
from conftest import FramedAsyncReader

import aiogzip._text as text_module
from aiogzip import AsyncGzipTextFile
from aiogzip._text import _TextBufferOrigin

SRC = Path(__file__).resolve().parents[1] / "src" / "aiogzip"
OLD = {
    "_buffer_origin_offset",
    "_buffer_origin_decoder_state",
    "_buffer_origin_trailing_cr",
    "_buffer_origin_seen_newline_types",
    "_buffer_origin_chars_to_skip",
}


class _Source:
    def __init__(self, data: bytes) -> None:
        self._data = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._data.read(size)


def _origin(**changes):
    values = dict(
        byte_offset=10,
        decoder_state=(b"\xe6", 0),
        trailing_cr=True,
        seen_newline_types=3,
        chars_to_skip=7,
    )
    values.update(changes)
    return _TextBufferOrigin(**values)


# Structure


def test_old_origin_fields_are_gone():
    slots = AsyncGzipTextFile.__slots__
    assert "_buffer_origin" in slots
    assert not OLD & set(slots)
    for path in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                assert node.attr not in OLD, f"{path.name}:{node.lineno}"


def test_origin_is_a_slotted_dataclass_with_the_five_fields():
    assert dataclasses.is_dataclass(_TextBufferOrigin)
    assert "__slots__" in _TextBufferOrigin.__dict__
    assert [f.name for f in dataclasses.fields(_TextBufferOrigin)] == [
        "byte_offset",
        "decoder_state",
        "trailing_cr",
        "seen_newline_types",
        "chars_to_skip",
    ]


# Copy independence


def _fields(origin):
    return (
        origin.byte_offset,
        origin.decoder_state,
        origin.trailing_cr,
        origin.seen_newline_types,
        origin.chars_to_skip,
    )


async def test_rollback_state_is_independent_of_the_live_origin():
    data = gzip.compress(b"line\n" * 100)
    async with AsyncGzipTextFile(None, "rt", fileobj=_Source(data)) as stream:
        await stream.readline()
        live = stream._buffer_origin
        _buffer, _offset, saved = stream._readlines_rollback_state()
        # An immutable field tuple, not an object sharing state with the origin.
        assert type(saved) is tuple
        assert saved == _fields(live)
        before = _fields(live)
        live.chars_to_skip += 5
        live.byte_offset = 99
        live.trailing_cr = not live.trailing_cr
        assert saved == before


def test_restore_copies_fields_into_the_live_object():
    live = _origin(byte_offset=0, chars_to_skip=0)
    saved = _fields(_origin())
    live.restore(saved)
    assert live == _origin()
    live.chars_to_skip = 100
    assert saved == _fields(_origin())


def test_decoder_state_values_are_immutable():
    # Shared, not copied, because the codecs getstate() contract returns an
    # immutable (bytes, int).
    import codecs

    encodings = ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "iso2022_jp")
    for encoding in (*encodings, "shift_jis", "gb18030"):
        decoder = codecs.getincrementaldecoder(encoding)()
        decoder.decode(b"\x1b$B" if encoding == "iso2022_jp" else b"\xe6")
        state = decoder.getstate()
        assert type(state) is tuple
        assert [type(part) for part in state] == [bytes, int]


# Handle-level ownership


async def test_handle_keeps_one_live_origin_and_no_pending_origin_at_rest():
    data = gzip.compress(b"line\n" * 100)
    async with AsyncGzipTextFile(None, "rt", fileobj=_Source(data)) as stream:
        live = stream._buffer_origin
        assert stream._pending_read_origin is None
        await stream.readline()
        await stream.read(50)
        assert stream._buffer_origin is live  # updated in place
        assert stream._pending_read_origin is None


@pytest.mark.parametrize(
    "newline,ending",
    [("", "\n"), ("\r\n", "\r\n"), ("\n", "\n")],
    ids=["generic-universal", "generic-crlf", "fast-lf"],
)
async def test_no_origin_object_is_created_per_line(monkeypatch, newline, ending):
    created = []

    class Counting(_TextBufferOrigin):
        __slots__ = ()

        def __init__(self, *args, **kwargs):
            created.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(text_module, "_TextBufferOrigin", Counting)
    lines = 20_000
    text = "".join(f"row {i}{ending}" for i in range(lines)).encode()
    data = gzip.compress(text)
    stream = AsyncGzipTextFile(None, "rt", fileobj=_Source(data), newline=newline)
    await stream.open()
    created.clear()  # construction creates the live origin
    count = 0
    async for _ in stream:
        count += 1
    await stream.close()
    assert count == lines
    # Refills update the live origin in place and rollback keeps a field tuple.
    # A line crossing a chunk boundary may publish one pending origin, so the
    # count scales with refills, never with lines.
    refills = len(text) // stream._chunk_size + 1
    assert len(created) <= refills + 2
    assert len(created) * 1000 < lines


async def test_tell_and_seek_round_trip_across_compaction():
    # No public read path currently refills a buffer that still holds unread
    # text past the threshold, so drive the compaction branch through the
    # refill it guards; the stream state stays consistent.
    lines = [f"行 {i:06d} line\n" for i in range(30_000)]
    data = gzip.compress("".join(lines).encode())
    stream = AsyncGzipTextFile(
        None, "rt", fileobj=_Source(data), newline="", chunk_size=65536
    )
    await stream.open()
    try:
        consumed = 0
        while stream._text_buffer_offset <= stream._TEXT_COMPACTION_THRESHOLD:
            assert await stream.readline() == lines[consumed]
            consumed += 1
        assert stream._buffered_text_len() > 0
        before = await stream.tell()
        offset = stream._text_buffer_offset
        skip = stream._buffer_origin.chars_to_skip
        live = stream._buffer_origin

        assert await stream._read_chunk_and_decode()

        # Compacted: the consumed prefix moved into the origin's skip count.
        assert stream._text_buffer_offset == 0
        assert stream._buffer_origin.chars_to_skip == skip + offset
        assert stream._buffer_origin is live
        after = await stream.tell()
        assert after == before  # same logical position, same cookie

        rest = await stream.read()
        assert rest == "".join(lines[consumed:])
        for cookie in (before, after):
            assert await stream.seek(cookie) == cookie
            assert await stream.read() == rest
    finally:
        await stream.close()


# Explicit-endian UTF-16 (§11.2): no BOM, so every origin starts mid-stream with
# a plain decoder state. Odd chunk sizes split code units and surrogate pairs.

UTF16_PAYLOAD = "日本\r\n🚀x\r" + "q" * 37 + "\n終🚀\r\nend"


def _utf16_stream(encoding, newline, chunk_size):
    data = UTF16_PAYLOAD.encode(encoding)
    return AsyncGzipTextFile(
        None,
        "rt",
        fileobj=FramedAsyncReader(gzip.compress(data, mtime=0)),
        closefd=False,
        newline=newline,
        encoding=encoding,
        chunk_size=chunk_size,
    )


@pytest.mark.parametrize("chunk_size", [3, 5, 7])
@pytest.mark.parametrize("newline", [None, "", "\r\n"])
@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
async def test_explicit_endian_utf16_lines_and_cookies(encoding, newline, chunk_size):
    reference = io.TextIOWrapper(
        io.BytesIO(UTF16_PAYLOAD.encode(encoding)), encoding=encoding, newline=newline
    )
    expected = list(reference)
    async with _utf16_stream(encoding, newline, chunk_size) as stream:
        for line in expected:
            cookie = await stream.tell()
            assert await stream.readline() == line
            await stream.seek(cookie)
            assert await stream.readline() == line
        assert await stream.read() == ""
        assert stream.newlines == reference.newlines


@pytest.mark.parametrize("chunk_size", [3, 5])
@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
async def test_explicit_endian_utf16_sized_read_cookies(encoding, chunk_size):
    text = UTF16_PAYLOAD
    async with _utf16_stream(encoding, "", chunk_size) as stream:
        position = 0
        while position < len(text):
            cookie = await stream.tell()
            piece = await stream.read(2)
            assert piece == text[position : position + 2]
            await stream.seek(cookie)
            assert await stream.read() == text[position:]
            await stream.seek(cookie)
            assert await stream.read(2) == piece
            position += len(piece)
