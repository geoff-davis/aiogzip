"""BC11: a failed or cancelled text seek changes nothing or refuses reads.

Before RC1, ``AsyncGzipTextFile.seek()`` moved the binary reader first and
replaced the buffered text, decoder and origin only afterwards. A seek that
failed or was cancelled part way left the old text over a moved binary
position, with the reader still healthy, so the next read returned wrong text
without an error (Opus RC1 review, RC1-01; present in b1 and 1.11.0).

Now a seek that moved the binary read cursor makes the reader terminal until
``seek(0)``. A seek that consumed no input restores the text state, so reads
continue exactly where they were (the BC2 no-effect rule).
"""

import asyncio
import gzip
import os
import random

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile, ConcurrentOperationError
from aiogzip._binary import _ReadHealth

BROKEN = "read stream is broken after failed or cancelled decompression"
LINES = [f"line {i:04d}\n" for i in range(400)]
TEXT = "".join(LINES)
WIRE = gzip.compress(TEXT.encode(), mtime=0)


class Source:
    """Seekable async memory source whose next read can fail.

    ``fail="no_effect"`` raises without consuming; ``fail="consumed"`` consumes
    the requested bytes, then raises.
    """

    def __init__(self, data: bytes = WIRE) -> None:
        self.data = data
        self.pos = 0
        self.fail: str | None = None
        self.fail_after = 0  # successful reads before the armed failure

    def tell(self) -> int:
        return self.pos

    def seekable(self) -> bool:
        return True

    async def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence != os.SEEK_SET:
            raise OSError("absolute seeks only")
        self.pos = offset
        return offset

    async def read(self, size: int = -1) -> bytes:
        if self.fail is not None:
            if self.fail_after:
                self.fail_after -= 1
            else:
                fail, self.fail = self.fail, None
                if fail == "consumed":
                    self.pos += len(self.data[self.pos : self.pos + size])
                raise OSError(f"injected {fail} failure")
        end = len(self.data) if size < 0 else self.pos + size
        out = self.data[self.pos : end]
        self.pos += len(out)
        return out

    async def close(self) -> None:
        pass


def _text(source, **kwargs):
    return AsyncGzipTextFile(None, "rt", fileobj=source, chunk_size=64, **kwargs)


async def _read_lines(f, count):
    return "".join([await f.readline() for _ in range(count)])


async def _assert_refused_until_rewind(f):
    assert f.buffer._read_health is _ReadHealth.BROKEN
    with pytest.raises(OSError, match=BROKEN):
        await f.read(10)
    with pytest.raises(OSError, match=BROKEN):
        await f.readline()
    with pytest.raises(OSError, match=BROKEN):
        await f.buffer.read(10)
    assert await f.seek(0) == 0
    assert await f.read() == TEXT


@pytest.mark.parametrize("fail", ["no_effect", "consumed"])
async def test_failed_cookie_seek_after_rewind_refuses_reads(fail):
    source = Source()
    async with _text(source) as f:
        consumed = await _read_lines(f, 30)
        cookie = await f.tell()
        await _read_lines(f, 40)
        # The rewind succeeds; the replay's first source read fails.
        source.fail = fail
        with pytest.raises(OSError, match=f"injected {fail}"):
            await f.seek(cookie)
        await _assert_refused_until_rewind(f)
        # After recovery the saved cookie is an ordinary position again.
        assert await f.seek(cookie) == cookie
        assert await f.read() == TEXT[len(consumed) :]


@pytest.mark.parametrize("fail", ["no_effect", "consumed"])
async def test_failed_forward_plain_seek_refuses_reads(fail):
    source = Source()
    async with _text(source) as f:
        await _read_lines(f, 3)
        assert await f.seek(0) == 0
        # A plain position replays forward; fail after part of the replay.
        source.fail = fail
        source.fail_after = 3
        with pytest.raises(OSError, match=f"injected {fail}"):
            await f.seek(len(TEXT) - 100)
        await _assert_refused_until_rewind(f)


async def test_failed_rewind_to_start_refuses_reads():
    source = Source()
    async with _text(source) as f:
        await _read_lines(f, 100)
        # seek(0) rewinds, then a later read of the replay fails: a plain
        # target replays after the rewind.
        source.fail = "no_effect"
        source.fail_after = 1
        with pytest.raises(OSError, match="injected no_effect"):
            await f.seek(len(LINES[0]) * 200)
        await _assert_refused_until_rewind(f)


async def test_decompression_limit_during_replay_refuses_reads():
    source = Source()
    async with _text(source, max_decompressed_size=len(TEXT) - 50) as f:
        await _read_lines(f, 3)
        with pytest.raises(OSError, match="exceeded max_decompressed_size"):
            await f.seek(len(TEXT) - 10)
        await _assert_refused_until_rewind_limited(f)


async def _assert_refused_until_rewind_limited(f):
    assert f.buffer._read_health is _ReadHealth.BROKEN
    with pytest.raises(OSError, match=BROKEN):
        await f.readline()
    assert await f.seek(0) == 0
    assert await f.readline() == LINES[0]


async def test_no_effect_failure_that_consumed_nothing_changes_nothing(monkeypatch):
    """A failure before the binary cursor moved restores the text state (BC2)."""
    source = Source()
    async with _text(source) as f:
        before = await _read_lines(f, 10)
        state = (f._decoder.getstate(), f._text_buffer, f._text_buffer_offset)
        original = AsyncGzipBinaryFile.read
        calls = 0

        async def fail_first(self, size=-1):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected failure before any input")
            return await original(self, size)

        monkeypatch.setattr(AsyncGzipBinaryFile, "read", fail_first)
        target = len(TEXT) - 100
        with pytest.raises(OSError, match="before any input"):
            await f.seek(target)
        monkeypatch.undo()
        assert calls == 1
        assert f.buffer._read_health is _ReadHealth.HEALTHY
        assert (f._decoder.getstate(), f._text_buffer, f._text_buffer_offset) == state
        assert await f.read() == TEXT[len(before) :]


async def test_cookie_seek_whose_replay_fails_after_a_rewind_refuses_reads(
    monkeypatch,
):
    source = Source()
    async with _text(source) as f:
        before = await _read_lines(f, 10)
        cookie = await f.tell()
        await _read_lines(f, 10)

        async def fail(self, chars_to_skip, *, strict):
            raise OSError("injected replay failure")

        monkeypatch.setattr(AsyncGzipTextFile, "_replay_characters", fail)
        # The cookie's origin is behind the binary position, so the seek
        # rewinds: the cursor moves and the reader becomes terminal.
        with pytest.raises(OSError, match="injected replay failure"):
            await f.seek(cookie)
        monkeypatch.undo()
        assert f.buffer._read_health is _ReadHealth.BROKEN
        assert await f.seek(0) == 0
        assert await _read_lines(f, 10) == before


async def test_reanchored_cookie_seek_that_consumed_nothing_is_rolled_back(
    monkeypatch,
):
    """A cookie seek re-anchors text even when its binary seek is a no-op.

    A cookie whose origin is the current binary position needs no binary
    movement, but the seek still replaces the buffered text, decoder state
    and origin before replaying. A failure that consumed no input rolls all of
    that back, so reads continue exactly where they were. Such cookies arise
    when a multibyte character spans the binary position; ``_decode_cookie``
    is patched here to produce one deterministically.
    """
    source = Source()
    async with _text(source) as f:
        before = await _read_lines(f, 10)
        assert f._text_buffer_offset < len(f._text_buffer)  # read-ahead held
        state = (
            f._decoder.getstate(),
            f._text_buffer,
            f._text_buffer_offset,
            f._decoder_byte_position,
            f._buffer_origin.byte_offset,
            f._buffer_origin.chars_to_skip,
        )
        position = f.buffer._position

        def cookie_at_cursor(self, cookie):
            return (position, (b"", 0), False, 0, 5)

        async def fail(self, chars_to_skip, *, strict):
            assert self._text_buffer == ""  # re-anchored before the failure
            raise OSError("injected replay failure")

        monkeypatch.setattr(AsyncGzipTextFile, "_decode_cookie", cookie_at_cursor)
        monkeypatch.setattr(AsyncGzipTextFile, "_replay_characters", fail)
        with pytest.raises(OSError, match="injected replay failure"):
            await f.seek(-1)
        monkeypatch.undo()
        assert f.buffer._position == position
        assert f.buffer._read_health is _ReadHealth.HEALTHY
        assert (
            f._decoder.getstate(),
            f._text_buffer,
            f._text_buffer_offset,
            f._decoder_byte_position,
            f._buffer_origin.byte_offset,
            f._buffer_origin.chars_to_skip,
        ) == state
        assert await f.read() == TEXT[len(before) :]


async def test_seek_rejected_by_an_active_buffer_read_changes_nothing():
    gate = asyncio.Event()
    entered = asyncio.Event()

    class Gated(Source):
        hold = False

        async def read(self, size=-1):
            if self.hold:
                self.hold = False
                entered.set()
                await gate.wait()
            return await super().read(size)

    source = Gated()
    async with _text(source) as f:
        await _read_lines(f, 5)
        state = (
            f._decoder.getstate(),
            f._text_buffer,
            f._text_buffer_offset,
            f.buffer._position,
        )
        f.buffer._buffer.clear()  # force the buffer read to the source
        f.buffer._buffer_offset = 0
        source.hold = True
        task = asyncio.create_task(f.buffer.read(10))
        await asyncio.wait_for(entered.wait(), 5)
        cookie_or_plain = [len(TEXT) // 2, 0]
        for target in cookie_or_plain:
            with pytest.raises(ConcurrentOperationError):
                await f.seek(target)
            assert f.buffer._read_health is _ReadHealth.HEALTHY
            assert (
                f._decoder.getstate(),
                f._text_buffer,
                f._text_buffer_offset,
                f.buffer._position,
            ) == state
        gate.set()
        await task
        assert f.buffer._read_health is _ReadHealth.HEALTHY


@pytest.fixture
def big_path(tmp_path):
    rng = random.Random(2)
    lines = [f"{i:06d} {rng.getrandbits(128):032x}\n" for i in range(60000)]
    path = tmp_path / "big.gz"
    with gzip.open(path, "wt", newline="") as handle:
        handle.write("".join(lines))
    return path, lines


@pytest.mark.parametrize("delay", [0.0, 0.0005, 0.001, 0.002, 0.005, 0.01])
async def test_cancelled_seek_on_a_native_file_never_returns_wrong_text(
    big_path, delay
):
    path, lines = big_path
    text = "".join(lines)
    target_line = 45000
    async with AsyncGzipTextFile(path, "rt", chunk_size=4096, newline="") as f:
        consumed = await _read_lines(f, 5)
        task = asyncio.create_task(f.seek(len(lines[0]) * target_line))
        await asyncio.sleep(delay)
        task.cancel()
        try:
            await task
            expected = text[len(lines[0]) * target_line :]
        except asyncio.CancelledError:
            expected = text[len(consumed) :]
        try:
            rest = await f.read(4000)
        except OSError as error:
            assert BROKEN in str(error)
            assert await f.seek(0) == 0
            assert await f.read(4000) == text[:4000]
        else:
            assert rest == expected[:4000]
