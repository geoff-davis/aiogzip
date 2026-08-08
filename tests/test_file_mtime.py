# pyrefly: ignore
# pyrefly: disable=all
"""Live gzip-member mtime behavior for binary and text file wrappers."""

import asyncio
import gzip
import io
import os
import zlib

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile, _codec_async


def _member(body: bytes, mtime: int) -> bytes:
    return gzip.compress(body, mtime=mtime)


class _FramedAsyncReader:
    """Async memory source that preserves caller-selected read boundaries."""

    def __init__(self, *frames: bytes, seekable: bool = True) -> None:
        self._frames = tuple(frames)
        self._frame_index = 0
        self._frame_offset = 0
        self._seekable = seekable

    async def read(self, size: int = -1) -> bytes:
        if self._frame_index >= len(self._frames):
            return b""
        frame = self._frames[self._frame_index]
        remaining = len(frame) - self._frame_offset
        take = remaining if size < 0 else min(size, remaining)
        start = self._frame_offset
        self._frame_offset += take
        if self._frame_offset == len(frame):
            self._frame_index += 1
            self._frame_offset = 0
        return frame[start : start + take]

    def seekable(self) -> bool:
        return self._seekable

    async def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if not self._seekable:
            raise OSError("not seekable")
        if offset != 0 or whence != os.SEEK_SET:
            raise OSError("test reader only supports rewind")
        self._frame_index = 0
        self._frame_offset = 0
        return 0

    async def close(self) -> None:
        pass


class TestBinaryLiveMtime:
    async def test_initial_mtime_is_none_and_first_header_precedes_trailer(self):
        body = b"payload before its trailer"
        raw = _member(body, 123)
        reader = _FramedAsyncReader(raw[:-8], raw[-8:])

        async with AsyncGzipBinaryFile(
            None, "rb", fileobj=reader, closefd=False, chunk_size=len(raw)
        ) as stream:
            assert stream.mtime is None
            assert await stream.read(1) == body[:1]
            assert stream.mtime == 123

    async def test_zero_mtime_is_not_confused_with_no_header(self):
        body = b"zero"
        raw = _member(body, 0)
        reader = _FramedAsyncReader(raw)

        async with AsyncGzipBinaryFile(
            None, "rb", fileobj=reader, closefd=False, chunk_size=len(raw)
        ) as stream:
            assert stream.mtime is None
            assert await stream.read() == body
            assert stream.mtime == 0

    async def test_concatenated_members_update_at_controlled_boundaries(self):
        body = b"same-sized member body"
        members = [_member(body, mtime) for mtime in (100, 200, 200)]
        reader = _FramedAsyncReader(*members)

        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            chunk_size=max(map(len, members)),
        ) as stream:
            for expected_mtime in (100, 200, 200):
                assert await stream.read(len(body)) == body
                assert stream.mtime == expected_mtime
            assert await stream.read() == b""

    async def test_one_compressed_read_with_several_members_uses_last_header(self):
        bodies = (b"first", b"second", b"third")
        raw = b"".join(
            _member(body, mtime)
            for body, mtime in zip(bodies, (11, 22, 33), strict=True)
        )
        reader = _FramedAsyncReader(raw)

        async with AsyncGzipBinaryFile(
            None, "rb", fileobj=reader, closefd=False, chunk_size=len(raw)
        ) as stream:
            assert await stream.read(1) == b"f"
            assert stream.mtime == 33
            assert await stream.read() == b"irstsecondthird"

    @pytest.mark.parametrize("corruption", ["body", "trailer"])
    async def test_valid_later_header_survives_body_or_trailer_error(self, corruption):
        first_body = b"first member"
        first = _member(first_body, 101)
        if corruption == "body":
            second = _member(b"", 202)[:10] + b"\x07"
        else:
            second = bytearray(_member(b"second member", 202))
            second[-8] ^= 0xFF
            second = bytes(second)
        reader = _FramedAsyncReader(first, second)

        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            chunk_size=max(len(first), len(second)),
        ) as stream:
            assert await stream.read(len(first_body)) == first_body
            assert stream.mtime == 101
            with pytest.raises(gzip.BadGzipFile):
                await stream.read()
            assert stream.mtime == 202

    @pytest.mark.parametrize(
        "later",
        [
            b"not a gzip header",
            _member(b"unused", 999)[:9],
        ],
        ids=["invalid", "incomplete"],
    )
    async def test_invalid_or_incomplete_next_header_retains_prior_mtime(self, later):
        body = b"valid member"
        first = _member(body, 303)
        reader = _FramedAsyncReader(first, later)

        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            chunk_size=max(len(first), len(later)),
        ) as stream:
            assert await stream.read(len(body)) == body
            assert stream.mtime == 303
            with pytest.raises(gzip.BadGzipFile):
                await stream.read()
            assert stream.mtime == 303

    async def test_nul_padding_does_not_change_mtime(self):
        body = b"padded"
        raw = _member(body, 404)
        reader = _FramedAsyncReader(raw, b"\x00" * 19)

        async with AsyncGzipBinaryFile(
            None, "rb", fileobj=reader, closefd=False, chunk_size=len(raw)
        ) as stream:
            assert await stream.read() == body
            assert stream.mtime == 404

    @pytest.mark.parametrize("seekable", [True, False], ids=["source", "cache"])
    async def test_rewind_retains_then_replaces_mtime(self, seekable):
        body = b"fixed-size member"
        first = _member(body, 501)
        second = _member(body, 502)
        reader = _FramedAsyncReader(first, second, seekable=seekable)

        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            chunk_size=max(len(first), len(second)),
            max_rewind_cache_size=len(first) + len(second),
        ) as stream:
            assert await stream.read(len(body)) == body
            assert stream.mtime == 501
            assert await stream.read(len(body)) == body
            assert stream.mtime == 502

            assert await stream.seek(0) == 0
            assert stream.mtime == 502
            assert await stream.read(len(body)) == body
            assert stream.mtime == 501
            assert await stream.read(len(body)) == body
            assert stream.mtime == 502

    @pytest.mark.parametrize(
        "method",
        ["read", "read1", "readline", "peek", "readinto", "seek", "read-all"],
    )
    async def test_binary_read_surfaces_share_header_observation(self, method):
        body = b"line one\nline two\n"
        raw = _member(body, 606)
        reader = _FramedAsyncReader(raw)

        async with AsyncGzipBinaryFile(
            None, "rb", fileobj=reader, closefd=False, chunk_size=len(raw)
        ) as stream:
            assert stream.mtime is None
            if method == "read":
                assert await stream.read(1) == body[:1]
            elif method == "read1":
                assert await stream.read1(1) == body[:1]
            elif method == "readline":
                assert await stream.readline() == b"line one\n"
            elif method == "peek":
                assert (await stream.peek(1)).startswith(body[:1])
            elif method == "readinto":
                target = bytearray(1)
                assert await stream.readinto(target) == 1
                assert target == body[:1]
            elif method == "seek":
                assert await stream.seek(1) == 1
            else:
                assert await stream.read() == body
            assert stream.mtime == 606

    async def test_cancellation_after_header_completion_synchronizes_mtime(
        self, monkeypatch
    ):
        threshold = _codec_async._DECODE_OFFLOAD_THRESHOLD
        body = os.urandom(2 * threshold)
        raw = _member(body, 707)
        assert len(raw) > threshold
        reader = _FramedAsyncReader(raw)
        advanced = asyncio.Event()
        release = asyncio.Event()

        async def advance_then_block(method, data):
            result = method(data)
            advanced.set()
            await release.wait()
            return result

        monkeypatch.setattr(_codec_async, "_run_in_thread", advance_then_block)
        stream = AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            chunk_size=threshold,
        )
        await stream.open()
        try:
            task = asyncio.create_task(stream.read())
            await advanced.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.mtime == 707
            assert stream._read_broken is True
        finally:
            await stream.close()

    async def test_cancellation_before_header_completion_does_not_update(
        self, monkeypatch
    ):
        threshold = _codec_async._DECODE_OFFLOAD_THRESHOLD
        incomplete = b"\x1f\x8b\x08\x08" + b"\x00" * 6 + b"x" * (threshold - 10)
        reader = _FramedAsyncReader(incomplete)
        started = asyncio.Event()
        release = asyncio.Event()

        async def block_before_advance(method, data):
            started.set()
            await release.wait()
            return method(data)

        monkeypatch.setattr(_codec_async, "_run_in_thread", block_before_advance)
        stream = AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            chunk_size=threshold,
        )
        await stream.open()
        try:
            task = asyncio.create_task(stream.read())
            await started.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.mtime is None
            assert stream._read_broken is True
        finally:
            await stream.close()


class TestTextLiveMtime:
    async def test_text_delegates_initial_zero_and_concatenated_mtime(self):
        # Sized reads plus compressed source frames expose both header
        # transitions without depending on readline()'s deliberate prefetch.
        first_body = b"a" * 300_000
        second_body = b"b" * 300_000
        first = _member(first_body, 0)
        second = _member(second_body, 802)
        reader = _FramedAsyncReader(first, second)

        async with AsyncGzipTextFile(
            None,
            "rt",
            fileobj=reader,
            closefd=False,
            chunk_size=1000,
        ) as stream:
            assert stream.mtime is None
            assert await stream.read(len(first_body)) == first_body.decode()
            assert stream.mtime == 0
            assert await stream.read(len(second_body)) == second_body.decode()
            assert stream.mtime == 802
            assert stream.mtime == stream.buffer.mtime

        assert "_mtime" not in AsyncGzipTextFile.__slots__

    async def test_text_rewind_retains_then_replaces_mtime(self):
        body = b"x" * 300_000
        first = _member(body, 811)
        second = _member(body, 812)
        reader = _FramedAsyncReader(first, second)

        async with AsyncGzipTextFile(
            None,
            "rt",
            fileobj=reader,
            closefd=False,
            chunk_size=1000,
        ) as stream:
            assert await stream.read(len(body)) == body.decode()
            assert stream.mtime == 811
            assert await stream.read(len(body)) == body.decode()
            assert stream.mtime == 812
            assert await stream.seek(0) == 0
            assert stream.mtime == 812
            assert await stream.read(len(body)) == body.decode()
            assert stream.mtime == 811

    @pytest.mark.parametrize("corruption", ["body", "trailer"])
    async def test_text_corruption_exposes_completed_header(self, corruption):
        if corruption == "body":
            raw = _member(b"", 821)[:10] + b"\x07"
        else:
            damaged = bytearray(_member(b"text", 821))
            damaged[-8] ^= 0xFF
            raw = bytes(damaged)
        reader = _FramedAsyncReader(raw)

        async with AsyncGzipTextFile(
            None, "rt", fileobj=reader, closefd=False, chunk_size=len(raw)
        ) as stream:
            assert stream.mtime is None
            with pytest.raises(gzip.BadGzipFile):
                await stream.read()
            assert stream.mtime == 821


def test_stdlib_mtime_oracle_for_final_value_and_rewind():
    body = b"oracle member"
    raw = _member(body, 901) + _member(body, 902)

    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
        assert stream.mtime is None
        assert stream.read() == body * 2
        assert stream.mtime == 902
        assert stream.seek(0) == 0
        assert stream.mtime == 902
        assert stream.read(1) == body[:1]
        assert stream.mtime == 901


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [("body", zlib.error), ("trailer", gzip.BadGzipFile)],
)
def test_stdlib_mtime_oracle_for_valid_header_then_corruption(
    corruption, expected_error
):
    if corruption == "body":
        raw = _member(b"", 903)[:10] + b"\x07"
    else:
        damaged = bytearray(_member(b"oracle", 903))
        damaged[-8] ^= 0xFF
        raw = bytes(damaged)

    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
        with pytest.raises(expected_error):
            stream.read()
        assert stream.mtime == 903
