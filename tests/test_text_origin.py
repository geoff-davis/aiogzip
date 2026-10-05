"""WP7: the text replay origin is one checkpoint object with independent copies."""

import ast
import dataclasses
import gzip
import io
from pathlib import Path

import pytest

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


def test_snapshot_is_independent_of_the_live_origin():
    live = _origin()
    saved = live.snapshot()
    assert saved == live and saved is not live
    live.chars_to_skip += 5
    live.byte_offset = 99
    live.trailing_cr = False
    assert saved == _origin()
    saved.seen_newline_types = 0
    assert live.seen_newline_types == 3


def test_restore_copies_fields_and_keeps_objects_separate():
    live = _origin(byte_offset=0, chars_to_skip=0)
    saved = _origin()
    live.restore(saved)
    assert live == saved and live is not saved
    live.chars_to_skip = 100
    assert saved.chars_to_skip == 7


def test_decoder_state_values_are_immutable():
    # Shared, not copied, because the codecs getstate() contract returns an
    # immutable (bytes, int).
    import codecs

    for encoding in ("utf-8", "utf-16", "iso2022_jp", "shift_jis", "gb18030"):
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
    # Refills update the live origin in place. A line crossing a chunk boundary
    # may take a rollback snapshot and a pending origin, so the count scales with
    # refills, never with lines.
    refills = len(text) // stream._chunk_size + 1
    assert len(created) <= 2 * refills + 2
    assert len(created) * 1000 < lines
