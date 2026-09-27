"""Boundary, replay and salvage contracts for fragment-based text line reads."""

import gzip
import io

import pytest
from conftest import FramedAsyncReader

from aiogzip import AsyncGzipTextFile


@pytest.mark.parametrize("newline", [None, "", "\r\n"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso2022_jp"])
@pytest.mark.parametrize("following", ["\nrest", "日rest", ""])
async def test_carriage_return_exactly_at_decode_boundary(newline, encoding, following):
    chunk_size = 7
    prefix = next(
        "日" * 5 + "x" * count
        for count in range(30)
        if len(("日" * 5 + "x" * count + "\r").encode(encoding)) % chunk_size == 0
    )
    payload = prefix + "\r" + following
    reference = io.TextIOWrapper(
        io.BytesIO(payload.encode(encoding)), encoding=encoding, newline=newline
    )
    expected = list(reference)
    async with AsyncGzipTextFile(
        None,
        "rt",
        fileobj=FramedAsyncReader(gzip.compress(payload.encode(encoding), mtime=0)),
        closefd=False,
        newline=newline,
        encoding=encoding,
        chunk_size=chunk_size,
    ) as stream:
        assert [line async for line in stream] == expected
        assert stream.newlines == reference.newlines


@pytest.mark.parametrize("newline", [None, "", "\n", "\r", "\r\n"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso2022_jp"])
@pytest.mark.parametrize("chunk_size", [7, 64])
@pytest.mark.parametrize("surface", ["readline", "anext", "readlines", "bounded"])
async def test_fragment_lines_match_stdlib_and_replay_cookies(
    newline, encoding, chunk_size, surface
):
    payload = "日" * 1000 + "\r\n" + "q" * 1023 + "\rZ\n" + "終" * 1000 + "\r"
    data = payload.encode(encoding)
    reference = io.TextIOWrapper(io.BytesIO(data), encoding=encoding, newline=newline)
    expected = []
    while line := reference.readline(257 if surface == "bounded" else -1):
        expected.append(line)
    source = FramedAsyncReader(gzip.compress(data, mtime=0))
    async with AsyncGzipTextFile(
        None,
        "rt",
        fileobj=source,
        closefd=False,
        newline=newline,
        encoding=encoding,
        chunk_size=chunk_size,
    ) as stream:
        if surface == "readlines":
            actual = []
            while batch := await stream.readlines(99):
                actual.extend(batch)
            assert actual == expected
        else:

            async def consume():
                if surface == "anext":
                    return await anext(stream)
                return await stream.readline(257 if surface == "bounded" else -1)

            for line in expected:
                cookie = await stream.tell()
                assert await consume() == line
                await stream.seek(cookie)
                assert await consume() == line
            assert await stream.read() == ""
        assert stream.newlines == reference.newlines


@pytest.mark.parametrize("newline", ["", "\r\n"])
@pytest.mark.parametrize("tail", ["unterminated", "uncertain\r"])
async def test_longline_validation_salvage_keeps_complete_lines_and_partial_tail(
    newline, tail
):
    line = "日" * 2000 + "\r\n"
    payload = line + tail
    corrupt = bytearray(gzip.compress(payload.encode(), mtime=0))
    corrupt[-8] ^= 1
    source = FramedAsyncReader(bytes(corrupt[:-8]), bytes(corrupt[-8:]))
    async with AsyncGzipTextFile(
        None,
        "rt",
        fileobj=source,
        closefd=False,
        newline=newline,
        chunk_size=31,
    ) as stream:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.readlines()
        assert await stream.readline() == line
        with pytest.raises(OSError, match="broken"):
            await stream.readline()
        assert await stream.read() == tail
        if newline == "":
            assert stream.newlines == "\r\n"


@pytest.mark.parametrize("newline", ["", "\r\n"])
@pytest.mark.parametrize("shared_prefix", [False, True])
@pytest.mark.parametrize("bounded", [False, True])
async def test_terminal_source_error_does_not_restore_discarded_text(
    newline, shared_prefix, bounded
):
    class FailOnceSource(FramedAsyncReader):
        failed = False

        async def read(self, size=-1):
            if self.read_calls == 2 and not self.failed:
                self.failed = True
                # The source has no tell() no-effect guarantee, so
                # ordinary reads must remain terminal until an explicit rewind.
                raise OSError("unknown source effect")
            return await super().read(size)

    line = "x" * 500 + "\r\n"
    payload = (("head\r\n" if shared_prefix else "") + line).encode()
    source = FailOnceSource(
        *[
            gzip.compress(payload[i : i + 64], mtime=0)
            for i in range(0, len(payload), 64)
        ]
    )
    async with AsyncGzipTextFile(
        None,
        "rt",
        fileobj=source,
        closefd=False,
        newline=newline,
        chunk_size=64,
    ) as stream:
        if shared_prefix:
            assert await stream.readline() == "head\r\n"
        with pytest.raises(OSError, match="unknown source effect"):
            await stream.readline(10000 if bounded else -1)
        cookie = await stream.tell()
        with pytest.raises(OSError, match="broken"):
            await stream.readline()
        await stream.seek(cookie)
        # Terminal poison discards text, including the old shared prefix.
        # The decoder frontier follows the two successful 64-byte reads;
        # recreating the pre-call text would change the existing tell contract.
        assert await stream.readline() == payload[128:].decode()
