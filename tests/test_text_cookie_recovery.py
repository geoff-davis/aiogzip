"""BC10: a saved text cookie is not a recovery point after a read failure.

Since 55c1e3e a cookie taken on the generic lines path can carry a binary
origin past 0. Restoring it needs a binary seek to that origin, which a reader
that is not healthy refuses; only a literal ``seek(0)`` rewinds a failed
reader. b1's cookie here had origin 0 and rewound. The documented recovery is
``seek(0)``, after which the saved cookie is an ordinary position again.
"""

import contextlib
import gzip
import random
import zlib

import pytest

from aiogzip import AsyncGzipTextFile

BROKEN = (
    "read stream is broken after failed or cancelled decompression; "
    "seek to 0 to recover, or close and reopen the gzip file"
)


def _member(data: bytes, *, bad_crc: bool = False) -> bytes:
    raw = gzip.compress(data, mtime=0)
    if bad_crc:
        crc = zlib.crc32(data) ^ 1
        raw = raw[:-8] + crc.to_bytes(4, "little") + raw[-4:]
    return raw


rng = random.Random(1)
LINES = [f"{rng.getrandbits(120):030x}\n" for _ in range(2000)]
WIRE = _member("".join(LINES).encode()) + _member(b"tail\n", bad_crc=True)


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "cookie.gz"
    target.write_bytes(WIRE)
    return target


def _open(path):
    # shift_jis with newline="" takes the generic lines path; a 64-byte chunk
    # puts the cookie's origin past 0 once readlines crosses a chunk.
    return AsyncGzipTextFile(
        path, "rt", encoding="shift_jis", newline="", chunk_size=64
    )


async def test_bc10_cookie_seek_after_failure_is_refused_today(path):
    """Records the ledgered BC10 behavior; this is not part of the API.

    ``docs/errors.md`` promises only that ``seek(cookie)`` *may* be refused
    after a failure. If a change makes this seek succeed, that is a
    deliberate change to recovery behavior: update or retire ledger BC10 and
    revisit the "may" wording rather than restoring the refusal.
    """
    async with _open(path) as f:
        lines = await f.readlines(100)
        cookie = await f.tell()
        with pytest.raises(gzip.BadGzipFile):
            await f.read()
        with pytest.raises(OSError) as refused:
            await f.seek(cookie)
        assert str(refused.value) == BROKEN
        assert lines == LINES[: len(lines)]


async def test_seek_zero_recovers_and_the_saved_cookie_then_works(path):
    async with _open(path) as f:
        lines = await f.readlines(100)
        cookie = await f.tell()
        with pytest.raises(gzip.BadGzipFile):
            await f.read()
        # The contract allows this attempt to fail or succeed (BC10).
        with contextlib.suppress(OSError):
            await f.seek(cookie)
        assert await f.seek(0) == 0
        assert await f.seek(cookie) == cookie
        assert await f.readline() == LINES[len(lines)]


async def test_saved_cookie_seek_is_unchanged_while_healthy(path):
    async with _open(path) as f:
        lines = await f.readlines(100)
        cookie = await f.tell()
        await f.readline()
        assert await f.seek(cookie) == cookie
        assert await f.readline() == LINES[len(lines)]
