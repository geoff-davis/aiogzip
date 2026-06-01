"""Tests for the batched line-iteration path in AsyncGzipTextFile.

The fast path bulk-splits a decoded chunk into whole lines in one pass. These
tests guard the two things most likely to break: (1) it must split on the SAME
terminators as Python's text-mode readline (NOT str.splitlines, which also
breaks on \\v, \\f, \\x1c-\\x1e, \\x85, U+2028, U+2029), and (2) tell()/seek()
and read() must stay correct when interleaved with iteration.

stdlib ``gzip.open(..., 'rt')`` is used as the oracle for line splitting.
"""

import gzip

import pytest

from aiogzip import AsyncGzipTextFile

# Rich text exercising: blank lines, no trailing newline, every newline style,
# multibyte UTF-8, and the control/Unicode chars that str.splitlines would
# wrongly treat as line breaks but text-mode readline must keep inline.
SPECIALS = "\x0b\x0c\x1c\x1d\x1e\x85  "
RICH_TEXT = (
    "héllo\n"
    "wörld\r\n"
    "café\r"
    "\n"  # blank line
    f"specials {SPECIALS} stay inline\n"
    "ünïcode line that is fairly long " * 4 + "\n"
    "last line without newline"
)


@pytest.fixture
def rich_gz(tmp_path):
    path = tmp_path / "rich.gz"
    path.write_bytes(gzip.compress(RICH_TEXT.encode("utf-8")))
    return path


def oracle_lines(path, newline):
    with gzip.open(path, "rt", encoding="utf-8", newline=newline) as f:
        return f.readlines()


@pytest.mark.parametrize("newline", [None, "\n", "\r", "\r\n", ""])
@pytest.mark.parametrize("chunk_size", [4, 7, 64, 1 << 20])
class TestMatchesStdlibOracle:
    @pytest.mark.asyncio
    async def test_async_iteration_matches_oracle(self, rich_gz, newline, chunk_size):
        expected = oracle_lines(rich_gz, newline)
        async with AsyncGzipTextFile(
            rich_gz, "rt", newline=newline, chunk_size=chunk_size
        ) as f:
            got = [line async for line in f]
        assert got == expected

    @pytest.mark.asyncio
    async def test_readline_loop_matches_oracle(self, rich_gz, newline, chunk_size):
        expected = oracle_lines(rich_gz, newline)
        got = []
        async with AsyncGzipTextFile(
            rich_gz, "rt", newline=newline, chunk_size=chunk_size
        ) as f:
            while True:
                line = await f.readline()
                if not line:
                    break
                got.append(line)
        assert got == expected


class TestNoOverSplitting:
    """The control/Unicode chars in SPECIALS must NOT create line breaks."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", [None, "\n", "\r"])
    async def test_specials_stay_inline(self, tmp_path, newline):
        # Use the mode's own terminator so there are exactly two lines, with the
        # specials sitting inside the first one (never used as a separator).
        term = "\r" if newline == "\r" else "\n"
        text = f"before {SPECIALS} after{term}second{term}"
        path = tmp_path / "sp.gz"
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        async with AsyncGzipTextFile(path, "rt", newline=newline, chunk_size=5) as f:
            lines = [line async for line in f]
        assert lines == [f"before {SPECIALS} after{term}", f"second{term}"]
        # And it agrees with the stdlib oracle.
        assert lines == oracle_lines(path, newline)


class TestInterleavedReadAndIterate:
    @pytest.mark.asyncio
    async def test_read_after_partial_iteration(self, rich_gz):
        """read() after consuming some lines returns exactly the remainder."""
        expected_all = "".join(oracle_lines(rich_gz, None))
        async with AsyncGzipTextFile(rich_gz, "rt", newline=None, chunk_size=8) as f:
            first = await f.__anext__()
            second = await f.__anext__()
            rest = await f.read()
        assert first + second + rest == expected_all

    @pytest.mark.asyncio
    async def test_iterate_then_read_sized_then_iterate(self, tmp_path):
        text = "".join(f"line {i}\n" for i in range(200))
        path = tmp_path / "many.gz"
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        async with AsyncGzipTextFile(path, "rt", newline="\n", chunk_size=16) as f:
            a = await f.__anext__()  # "line 0\n"
            mid = await f.read(5)  # next 5 chars: "line "
            b = await f.__anext__()  # rest of the partial line: "1\n"
            tail = await f.read()
        assert a == "line 0\n"
        assert mid == "line "
        assert b == "1\n"
        assert tail == "".join(f"line {i}\n" for i in range(2, 200))


class TestTellSeekDuringIteration:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("chunk_size", [8, 64])
    async def test_tell_seek_roundtrip_midstream(self, rich_gz, chunk_size):
        async with AsyncGzipTextFile(
            rich_gz, "rt", newline=None, chunk_size=chunk_size
        ) as f:
            consumed = ""
            consumed += await f.__anext__()
            consumed += await f.__anext__()
            cookie = await f.tell()
            remainder_first = await f.read()

            await f.seek(cookie)
            remainder_again = await f.read()

        assert remainder_first == remainder_again
        assert consumed + remainder_first == RICH_TEXT.replace("\r\n", "\n").replace(
            "\r", "\n"
        )

    @pytest.mark.asyncio
    async def test_tell_at_start_of_each_line_seekable(self, tmp_path):
        text = "".join(f"row{i}\n" for i in range(50))
        path = tmp_path / "rows.gz"
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        async with AsyncGzipTextFile(path, "rt", newline="\n", chunk_size=16) as f:
            # Read 10 lines, snapshot position, then verify seeking back there
            # re-reads the exact same next line.
            for _ in range(10):
                await f.__anext__()
            cookie = await f.tell()
            next_line = await f.__anext__()
            assert next_line == "row10\n"
            await f.seek(cookie)
            assert await f.__anext__() == "row10\n"


class TestBatchWindowing:
    """The pending batch is capped at _LINE_BATCH_CHARS per refill so a large
    chunk_size full of tiny lines does not materialize the whole chunk at once.
    A tiny cap forces many windowed refills within one buffered chunk."""

    @pytest.mark.asyncio
    async def test_many_small_lines_across_windows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AsyncGzipTextFile, "_LINE_BATCH_CHARS", 16)
        text = "".join(f"{i}\n" for i in range(5000))
        path = tmp_path / "win.gz"
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        # chunk_size far larger than the cap so one buffer holds many windows.
        async with AsyncGzipTextFile(path, "rt", newline="\n", chunk_size=1 << 20) as f:
            lines = [line async for line in f]
        assert lines == oracle_lines(path, "\n")

    @pytest.mark.asyncio
    async def test_line_longer_than_window(self, tmp_path, monkeypatch):
        # A line longer than the batch window must still be emitted whole
        # (exercises the find()-fallback when the window holds no terminator).
        monkeypatch.setattr(AsyncGzipTextFile, "_LINE_BATCH_CHARS", 8)
        text = ("x" * 500) + "\n" + "short\n" + ("y" * 300) + "\n"
        path = tmp_path / "longwin.gz"
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        async with AsyncGzipTextFile(path, "rt", newline="\n", chunk_size=1 << 20) as f:
            lines = [line async for line in f]
        assert lines == ["x" * 500 + "\n", "short\n", "y" * 300 + "\n"]


class TestBoundedReadlineInterleaving:
    @pytest.mark.asyncio
    async def test_bounded_readline_clears_pending_batch(self, tmp_path):
        """A bounded readline(limit) after iteration has populated the batch
        must not let stale pre-split lines be served on the next iteration."""
        text = "abcdefgh\nij\nklmno\npqr\n"
        path = tmp_path / "bnd.gz"
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        async with AsyncGzipTextFile(path, "rt", newline="\n") as f:
            first = await f.__anext__()  # populates the pending batch
            mid = await f.readline(3)  # bounded -> must drop the batch
            nxt = await f.__anext__()  # must be the real next line, not stale
            tail = await f.read()
        assert first == "abcdefgh\n"
        assert mid == "ij\n"
        assert nxt == "klmno\n"
        assert tail == "pqr\n"


class TestLongLineSpanningChunks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", [None, "\n", "\r"])
    async def test_single_line_longer_than_chunk(self, tmp_path, newline):
        term = "\r" if newline == "\r" else "\n"
        long_line = "x" * 10_000 + term
        text = long_line + "short" + term
        path = tmp_path / "long.gz"
        path.write_bytes(gzip.compress(text.encode("utf-8")))
        async with AsyncGzipTextFile(path, "rt", newline=newline, chunk_size=64) as f:
            lines = [line async for line in f]
        assert lines == ["x" * 10_000 + term, "short" + term]
