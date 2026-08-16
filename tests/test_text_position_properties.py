"""Stateful text-position and newline invariants across refill boundaries."""

import asyncio
import gzip
import io

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aiogzip import AsyncGzipTextFile


class _MemoryReader:
    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    async def seek(self, offset: int, whence: int = 0) -> int:
        return self._buffer.seek(offset, whence)

    def seekable(self) -> bool:
        return True

    async def close(self) -> None:
        pass


_RICH_TEXT = "ascii-é-漢字\r\nnext\rbare\n" * 4000 + "tail-without-newline"


def test_line_buffer_compaction_preserves_cookie_origin():
    async def exercise() -> None:
        lines = [f"line {index:05d} payload\n" for index in range(50_000)]
        stream = AsyncGzipTextFile(
            None,
            "rt",
            newline="\n",
            fileobj=_MemoryReader(gzip.compress("".join(lines).encode(), mtime=0)),
            closefd=False,
            chunk_size=4096,
        )
        await stream.open()
        try:
            for expected in lines[:30_000]:
                assert await stream.readline() == expected
            cookie = await stream.tell()
            assert len(stream._text_buffer) < 2 * stream._TEXT_COMPACTION_THRESHOLD

            remainder = await stream.read()
            assert remainder == "".join(lines[30_000:])
            assert await stream.seek(cookie) == cookie
            assert await stream.read() == remainder
        finally:
            await stream.close()

    asyncio.run(exercise())


@given(
    chunk_size=st.sampled_from([1, 2, 3, 7, 31, 257, 2048]),
    read_sizes=st.lists(
        st.integers(min_value=1000, max_value=3000),
        min_size=12,
        max_size=12,
    ),
)
@settings(
    max_examples=16,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_sized_read_tell_seek_roundtrips_across_compaction(chunk_size, read_sizes):
    async def exercise() -> None:
        compressed = gzip.compress(_RICH_TEXT.encode(), mtime=0)
        stream = AsyncGzipTextFile(
            None,
            "rt",
            newline=None,
            fileobj=_MemoryReader(compressed),
            closefd=False,
            chunk_size=chunk_size,
        )
        expected = _RICH_TEXT.replace("\r\n", "\n").replace("\r", "\n")
        offset = 0
        await stream.open()
        try:
            for size in read_sizes:
                piece = await stream.read(size)
                assert piece == expected[offset : offset + len(piece)]
                offset += len(piece)

                cookie = await stream.tell()
                probe = await stream.read(37)
                assert probe == expected[offset : offset + len(probe)]
                assert await stream.seek(cookie) == cookie
                assert await stream.read(len(probe)) == probe
                offset += len(probe)

            assert await stream.read() == expected[offset:]
        finally:
            await stream.close()

    asyncio.run(exercise())


@given(
    chunk_size=st.sampled_from([1, 2, 3, 5, 16, 257]),
    read_size=st.integers(min_value=1, max_value=19),
    body=st.lists(
        st.sampled_from(["a", "é", "\n", "\r", "\r\n"]),
        min_size=1,
        max_size=100,
    ),
)
@settings(max_examples=40, deadline=None)
def test_newline_classification_matches_stdlib_for_sized_reads(
    chunk_size, read_size, body
):
    async def exercise() -> None:
        text = "".join(body) + "\r"
        raw = text.encode()
        oracle = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", newline=None)
        expected = oracle.read()
        expected_newlines = oracle.newlines

        stream = AsyncGzipTextFile(
            None,
            "rt",
            newline=None,
            fileobj=_MemoryReader(gzip.compress(raw, mtime=0)),
            closefd=False,
            chunk_size=chunk_size,
        )
        await stream.open()
        try:
            parts = []
            while True:
                part = await stream.read(read_size)
                if not part:
                    break
                parts.append(part)
            assert "".join(parts) == expected
            assert stream.newlines == expected_newlines
        finally:
            await stream.close()

    asyncio.run(exercise())
