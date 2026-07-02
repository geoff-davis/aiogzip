# pyrefly: ignore
# pyrefly: disable=all
"""Coverage for gaps found in the second package review: bounded readline
across buffer fills, live-decoder tell() cookies, buffer-accessor tell()
round-trips, os.linesep write translation, text seek/tell across appended
members, and write-side exotic buffers."""

import array
import gzip
import io
import os

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestBoundedReadlineAcrossFills:
    """readline(limit) whose limit spans several buffer fills."""

    async def test_binary_limit_crossing_multiple_fills(self, tmp_path):
        line = bytes(range(65, 90)) * 40 + b"\n"  # 1000 bytes + newline, no \n inside
        p = tmp_path / "long.gz"
        p.write_bytes(gzip.compress(line + b"tail\n"))

        # chunk_size=7 forces ~150 fills; limit lands mid-line.
        async with AsyncGzipBinaryFile(p, "rb", chunk_size=7) as f:
            got = await f.readline(633)
            assert got == line[:633]
            assert await f.tell() == 633
            rest = await f.readline()
            assert got + rest == line
            assert await f.readline() == b"tail\n"

    async def test_binary_limit_exactly_at_newline_across_fills(self, tmp_path):
        line = b"z" * 100 + b"\n"
        p = tmp_path / "exact.gz"
        p.write_bytes(gzip.compress(line + b"next\n"))
        async with AsyncGzipBinaryFile(p, "rb", chunk_size=3) as f:
            assert await f.readline(101) == line
            assert await f.readline() == b"next\n"


class TestLiveDecoderCookies:
    """tell() built from the live decoder state (pending multibyte bytes)."""

    @pytest.mark.parametrize("errors", ["strict", "ignore", "replace"])
    async def test_cookie_with_stranded_decoder_bytes(self, tmp_path, errors):
        # 2-byte chars; chunk_size=3 strands one byte in the decoder each
        # time the text buffer drains on a char boundary.
        content = "éàüöñ" * 4
        p = tmp_path / "live.gz"
        p.write_bytes(gzip.compress(content.encode("utf-8")))

        async with AsyncGzipTextFile(
            p, "rt", newline="", errors=errors, chunk_size=3
        ) as f:
            first = await f.read(1)
            assert first == content[0]
            pos = await f.tell()
            resumed_once = await f.read(5)
            await f.seek(pos)
            assert await f.read(5) == resumed_once
            # Full-stream consistency after the cookie round-trip.
            await f.seek(0)
            assert await f.read() == content


class TestBufferAccessorTellRoundTrip:
    """tell() after raw reads through the .buffer accessor must still be a
    usable resume point: whatever text followed it once must follow again."""

    @pytest.mark.parametrize("errors", ["strict", "replace"])
    async def test_tell_after_buffer_read_resumes_identically(self, tmp_path, errors):
        content = "aé🙂b" * 20
        p = tmp_path / "raw.gz"
        p.write_bytes(gzip.compress(content.encode("utf-8")))

        async with AsyncGzipTextFile(p, "rt", newline="", errors=errors) as f:
            await f.buffer.read(3)  # bypass the decoder mid-codepoint
            pos = await f.tell()
            seen = await f.read(7)
            await f.seek(pos)
            assert await f.read(7) == seen


class TestLinesepWriteTranslation:
    """newline=None write translation, runnable on any OS via monkeypatch."""

    async def test_write_translates_to_crlf_linesep(self, tmp_path, monkeypatch):
        import aiogzip._text as text_mod

        monkeypatch.setattr(text_mod.os, "linesep", "\r\n")
        p = tmp_path / "crlf.gz"
        async with AsyncGzipTextFile(p, "wt", newline=None) as f:
            await f.write("a\nb\n")

        with gzip.open(p, "rb") as check:
            assert check.read() == b"a\r\nb\r\n"

        # Universal-newline read-back folds them to \n again.
        async with AsyncGzipTextFile(p, "rt", newline=None) as f:
            assert await f.read() == "a\nb\n"


class TestAppendModeTextSeek:
    """Text-mode tell()/seek() across an appended gzip member boundary."""

    async def test_tell_seek_across_member_boundary(self, tmp_path):
        p = tmp_path / "multi.gz"
        async with AsyncGzipTextFile(p, "wt") as f:
            await f.write("first member\n")
        async with AsyncGzipTextFile(p, "at") as f:
            await f.write("second member\n")

        async with AsyncGzipTextFile(p, "rt") as f:
            first = await f.readline()
            assert first == "first member\n"
            pos = await f.tell()
            second = await f.readline()
            assert second == "second member\n"
            await f.seek(pos)  # backward across the member boundary state
            assert await f.readline() == "second member\n"
            await f.seek(0)
            assert await f.read() == "first member\nsecond member\n"


class TestWriteExoticBuffers:
    """write() accepts the same buffer shapes the read side already does."""

    async def test_write_array_itemsize_gt_one(self, tmp_path):
        payload = array.array("I", range(256))
        p = tmp_path / "arr.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            written = await f.write(payload)
        assert written == len(payload) * payload.itemsize
        with gzip.open(p, "rb") as check:
            assert check.read() == payload.tobytes()

    async def test_write_non_contiguous_memoryview(self, tmp_path):
        base = bytes(range(200))
        view = memoryview(base)[::2]  # non-contiguous
        p = tmp_path / "stride.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(view)
        with gzip.open(p, "rb") as check:
            assert check.read() == base[::2]


class TestSyncSeekRewind:
    """Backward seek via an external fileobj exposing a *synchronous* seek."""

    async def test_rewind_with_sync_seek_fileobj(self):
        payload = b"0123456789" * 100
        compressed = gzip.compress(payload)

        class SyncSeekReader:
            def __init__(self, data):
                self._bio = io.BytesIO(data)

            async def read(self, size=-1):
                return self._bio.read(size)

            def seek(self, offset, whence=os.SEEK_SET):
                return self._bio.seek(offset, whence)

            def seekable(self):
                return True

            async def close(self):
                pass

        reader = SyncSeekReader(compressed)
        async with AsyncGzipBinaryFile(None, "rb", fileobj=reader) as f:
            assert await f.read(20) == payload[:20]
            await f.seek(5)
            assert await f.read(10) == payload[5:15]
