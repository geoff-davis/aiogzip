# pyrefly: ignore
# pyrefly: disable=all
"""Correctness tests for the O(n) readline/iteration fast path.

These exercise the local-accumulation path added for long lines, and verify it
matches stdlib gzip's TextIOWrapper line splitting across newline modes, chunk
sizes, and boundary conditions (CRLF split across chunks, trailing CR, last
line without a terminator). The fallback modes ('\\r\\n', '') and limited
readline are covered too.
"""

import gzip
import os
import tempfile

import pytest

from aiogzip import AsyncGzipTextFile

# Content deliberately mixes terminator styles, includes a multi-chunk-long
# line, a CRLF straddling a likely chunk boundary, a trailing standalone CR,
# empty lines, and a final line with no terminator.
CONTENT = (
    "alpha\n"
    "beta\r\n"
    "gamma\rdelta\n"
    "\n"
    + ("x" * 200_000)  # one very long line -> spans many small chunks
    + "\n"
    + "y" * 4093
    + "\r\n"  # CRLF positioned to straddle a 4096-char chunk boundary
    + "epsilon\r"
    + "zeta_no_terminator"
)

NEWLINE_MODES = [None, "", "\n", "\r", "\r\n"]
CHUNK_SIZES = [64, 4096, 64 * 1024]


def _write(path: str) -> None:
    # Write exact bytes so terminators are preserved verbatim.
    with gzip.open(path, "wb") as f:
        f.write(CONTENT.encode("utf-8"))


@pytest.fixture
def longline_file():
    path = tempfile.mktemp(suffix=".gz")
    _write(path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


async def _aiogzip_iter(path, newline, chunk_size):
    out = []
    async with AsyncGzipTextFile(
        path, "rt", newline=newline, chunk_size=chunk_size
    ) as f:
        async for line in f:
            out.append(line)
    return out


async def _aiogzip_readline(path, newline, chunk_size):
    out = []
    async with AsyncGzipTextFile(
        path, "rt", newline=newline, chunk_size=chunk_size
    ) as f:
        while True:
            line = await f.readline()
            if not line:
                break
            out.append(line)
    return out


def _gzip_lines(path, newline):
    with gzip.open(path, "rt", newline=newline) as f:
        return list(f)


@pytest.mark.parametrize("newline", NEWLINE_MODES)
@pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
@pytest.mark.asyncio
async def test_iteration_matches_gzip(longline_file, newline, chunk_size):
    expected = _gzip_lines(longline_file, newline)
    got = await _aiogzip_iter(longline_file, newline, chunk_size)
    assert got == expected


@pytest.mark.parametrize("newline", NEWLINE_MODES)
@pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
@pytest.mark.asyncio
async def test_readline_matches_gzip(longline_file, newline, chunk_size):
    expected = _gzip_lines(longline_file, newline)
    got = await _aiogzip_readline(longline_file, newline, chunk_size)
    assert got == expected


@pytest.mark.parametrize("newline", [None, "\n", "\r"])
@pytest.mark.asyncio
async def test_single_long_line_no_terminator(newline):
    """The accumulate-to-EOF branch of the fast path: one line, no terminator."""
    path = tempfile.mktemp(suffix=".gz")
    line = "q" * (5 * 1024 * 1024)
    with gzip.open(path, "wb") as f:
        f.write(line.encode("utf-8"))
    try:
        async with AsyncGzipTextFile(path, "rt", newline=newline, chunk_size=4096) as f:
            got = await f.readline()
            assert got == line
            assert await f.readline() == ""  # EOF
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_limit_readline_still_bounded(longline_file):
    """readline(limit) keeps the existing bounded behaviour (fallback path)."""
    async with AsyncGzipTextFile(longline_file, "rt", chunk_size=64) as f:
        first = await f.readline(3)
        assert first == "alp"  # truncated at limit, no terminator consumed
        rest = await f.readline()
        assert rest == "ha\n"


@pytest.mark.asyncio
async def test_tell_seek_around_fast_readline(longline_file):
    """tell() after a fast-path readline must round-trip through seek()."""
    async with AsyncGzipTextFile(longline_file, "rt", chunk_size=128) as f:
        await f.readline()  # alpha\n
        await f.readline()  # beta\r\n -> normalized
        cookie = await f.tell()
        after1 = await f.read()
        await f.seek(cookie)
        after2 = await f.read()
        assert after1 == after2
        assert after1  # non-empty (long line follows)
