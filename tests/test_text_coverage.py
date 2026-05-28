# pyrefly: ignore
# pyrefly: disable=all
"""Targeted tests for previously-uncovered AsyncGzipTextFile behaviour.

Focus areas (real logic, not defensive guards):
- the buffer-accumulating readline()/iteration fallback used for the newline
  modes whose terminator can straddle a chunk boundary ('\\r\\n' and ''),
- the .newlines property / newline-style tracking (including CRLF split across
  a chunk boundary),
- seek-cookie validation and forward plain-position seeking.
"""

import gzip
import os
import tempfile

import pytest

from aiogzip import AsyncGzipTextFile

# Mixed content with every newline style, a CRLF positioned to straddle a small
# chunk boundary, a trailing standalone CR, an empty line, and a final line with
# no terminator.
MIXED = (
    "alpha\n"
    "beta\r\n"
    "gamma\rdelta\n"
    "\n" + "z" * 300 + "\r\n" + "epsilon\r" + "omega_no_terminator"
)


def _write_raw(path: str, text: str) -> None:
    with gzip.open(path, "wb") as f:
        f.write(text.encode("utf-8"))


@pytest.fixture
def mixed_file():
    path = tempfile.mktemp(suffix=".gz")
    _write_raw(path, MIXED)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# --- fallback newline modes ('\r\n' and '') exercise the non-fast path -------


@pytest.mark.parametrize("newline", ["\r\n", ""])
@pytest.mark.parametrize("chunk_size", [1, 8, 64])
@pytest.mark.asyncio
async def test_iteration_fallback_matches_gzip(mixed_file, newline, chunk_size):
    async with AsyncGzipTextFile(
        mixed_file, "rt", newline=newline, chunk_size=chunk_size
    ) as f:
        got = [line async for line in f]
    with gzip.open(mixed_file, "rt", newline=newline) as g:
        expected = list(g)
    assert got == expected


@pytest.mark.parametrize("newline", ["\r\n", ""])
@pytest.mark.parametrize("chunk_size", [1, 8, 64])
@pytest.mark.asyncio
async def test_readline_fallback_matches_gzip(mixed_file, newline, chunk_size):
    out = []
    async with AsyncGzipTextFile(
        mixed_file, "rt", newline=newline, chunk_size=chunk_size
    ) as f:
        while True:
            line = await f.readline()
            if not line:
                break
            out.append(line)
    with gzip.open(mixed_file, "rt", newline=newline) as g:
        expected = list(g)
    assert out == expected


@pytest.mark.parametrize("newline", ["\n", "\r"])
@pytest.mark.asyncio
async def test_bounded_readline_single_char_newline(tmp_path, newline):
    """Bounded readline (limit != -1) uses _find_line_terminator even for the
    single-char newline modes that an unbounded readline would fast-path."""
    path = tmp_path / "bounded.gz"
    _write_raw(str(path), f"line-one{newline}line-two{newline}")
    async with AsyncGzipTextFile(path, "rt", newline=newline) as f:
        assert await f.readline(100) == f"line-one{newline}"  # terminator within limit
        assert await f.readline(4) == "line"  # truncated before terminator


@pytest.mark.asyncio
async def test_incomplete_multibyte_at_eof_fallback_mode():
    """A truncated multibyte sequence at EOF in a fallback newline mode must be
    handled by the final decode (errors='replace')."""
    path = tempfile.mktemp(suffix=".gz")
    # "ok\r\n" then the first 2 bytes of a 4-byte emoji -> incomplete at EOF.
    with gzip.open(path, "wb") as f:
        f.write(b"ok\r\n\xf0\x9f")
    try:
        async with AsyncGzipTextFile(
            path, "rt", newline="\r\n", errors="replace", chunk_size=3
        ) as f:
            lines = [line async for line in f]
        assert lines[0] == "ok\r\n"
        assert lines[-1]  # replacement char(s) for the truncated bytes
    finally:
        os.unlink(path)


# --- .newlines property / seen-tracking --------------------------------------


@pytest.mark.parametrize("chunk_size", [1, 4, 64])
@pytest.mark.asyncio
async def test_newlines_property_matches_gzip(mixed_file, chunk_size):
    """Universal mode should report the same observed newline styles as gzip,
    including when a CRLF is split across a chunk boundary (chunk_size=1)."""
    async with AsyncGzipTextFile(mixed_file, "rt", chunk_size=chunk_size) as f:
        await f.read()
        got = f.newlines
    with gzip.open(mixed_file, "rt") as g:
        g.read()
        expected = g.newlines
    assert got == expected
    # MIXED contains \n, \r\n and \r, so all three styles must be present.
    assert set(got) == {"\n", "\r", "\r\n"}


@pytest.mark.parametrize("chunk_size", [1, 3])
@pytest.mark.asyncio
async def test_newlines_tracked_during_universal_iteration(mixed_file, chunk_size):
    """Iterating in universal mode decodes chunk-by-chunk, exercising the
    trailing-CR / split-CRLF seen-tracking branches that read(-1) skips."""
    async with AsyncGzipTextFile(mixed_file, "rt", chunk_size=chunk_size) as f:
        async for _line in f:
            pass
        got = f.newlines
    with gzip.open(mixed_file, "rt") as g:
        list(g)
        expected = g.newlines
    assert got == expected
    assert set(got) == {"\n", "\r", "\r\n"}


@pytest.mark.asyncio
async def test_newlines_none_before_any_newline_read(tmp_path):
    path = tmp_path / "nonl.gz"
    _write_raw(str(path), "no newline here")
    async with AsyncGzipTextFile(path, "rt") as f:
        assert f.newlines is None
        await f.read()
        assert f.newlines is None


# --- seek cookie validation and forward plain-position seek ------------------


@pytest.mark.asyncio
async def test_seek_invalid_cookie_raises(mixed_file):
    async with AsyncGzipTextFile(mixed_file, "rt") as f:
        await f.read(3)
        with pytest.raises(OSError, match="invalid text cookie"):
            await f.seek(-987654321)  # negative but not a real cookie


@pytest.mark.asyncio
async def test_seek_cookie_from_other_stream_rejected(tmp_path):
    """A cookie minted by one open handle must be rejected by another (the
    per-stream nonce guards against it)."""
    p1 = tmp_path / "a.gz"
    p2 = tmp_path / "b.gz"
    _write_raw(str(p1), "ab\ncd")
    _write_raw(str(p2), "ab\ncd")
    async with AsyncGzipTextFile(p1, "rt") as f1:
        # readline leaves "cd" buffered, so tell() returns an opaque cookie
        # (not a plain position).
        await f1.readline()
        cookie = await f1.tell()
    assert cookie < 0, "expected an opaque cookie while text is buffered"
    async with AsyncGzipTextFile(p2, "rt") as f2:
        with pytest.raises(OSError, match="invalid text cookie"):
            await f2.seek(cookie)


@pytest.mark.asyncio
async def test_seek_forward_plain_position_then_read(tmp_path):
    """Forward seek to a plain (ASCII) position replays from the start; covers
    the peek/EOF branches of _seek_to_plain_position."""
    text = "0123456789abcdefghijklmnopqrstuvwxyz"
    path = tmp_path / "ascii.gz"
    _write_raw(str(path), text)
    async with AsyncGzipTextFile(path, "rt", chunk_size=4) as f:
        assert await f.seek(10) == 10
        assert await f.read() == text[10:]
    # Seeking to exactly EOF then reading returns "".
    async with AsyncGzipTextFile(path, "rt", chunk_size=4) as f:
        assert await f.seek(len(text)) == len(text)
        assert await f.read() == ""
