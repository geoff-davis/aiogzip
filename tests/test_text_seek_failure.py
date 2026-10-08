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
import concurrent.futures
import gzip
import os
import random
import threading

import aiofiles
import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile, ConcurrentOperationError
from aiogzip._binary import _ReadHealth
from aiogzip._source_io import _NativeSourceCall

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


# Rollback with real decoder, newline and pending-line state. Mixed line
# endings and multibyte characters over 64-byte chunks leave incomplete bytes
# in the incremental decoder, a pending CR and batched pending lines at
# various points; a failure that consumed nothing must restore all of it.
# The first line puts a CRLF across the first 64-byte chunk boundary.
ENDINGS = ("\n", "\r\n", "\r")
RICH_LINES = ["#" * 63 + "\r\n"] + [
    f"{i:03d} {'é€😀'[i % 3] * (i % 7)}{ENDINGS[i % 3]}" for i in range(240)
]
RICH_TEXT = "".join(RICH_LINES)
RICH_WIRE = gzip.compress(RICH_TEXT.encode("utf-8"), mtime=0)


def _text_state(f):
    return (
        f._decoder.getstate(),
        f._decoder_byte_position,
        f._trailing_cr,
        f._seen_newline_types,
        f._text_buffer,
        f._text_buffer_offset,
        list(f._pending_lines),
        f._pending_idx,
        f._buffer_origin.byte_offset,
        f._buffer_origin.chars_to_skip,
        f.buffer._position,
    )


async def _iterate_to(f, lines):
    consumed = ""
    if lines:
        async for line in f:
            consumed += line
            if consumed.count("\n") >= lines:
                break
    return consumed


EXPECTED_RICH = RICH_TEXT.replace("\r\n", "\n").replace("\r", "\n")
LAST_LINE_START = len("".join(RICH_LINES[:-1]).encode("utf-8"))


async def test_plain_seek_failure_restores_or_breaks_with_real_state(monkeypatch):
    """A plain seek reuses live state only from a clean boundary.

    With incomplete decoder bytes or a pending CR it rewinds first, so a
    failure on its first replay read has moved the cursor and breaks the
    reader; from a clean boundary nothing moved and everything is restored.
    """
    original = AsyncGzipBinaryFile.read
    seen = set()
    for lines in range(0, 230, 3):
        async with _text(Source(RICH_WIRE), encoding="utf-8") as f:
            consumed = await _iterate_to(f, lines)
            state, newlines = _text_state(f), f.newlines
            dirty = state[0] != (b"", 0) or state[2]
            calls = 0

            async def fail_first(self, size=-1):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("injected failure before any input")
                return await original(self, size)

            monkeypatch.setattr(AsyncGzipBinaryFile, "read", fail_first)
            with pytest.raises(OSError, match="before any input"):
                await f.seek(LAST_LINE_START)
            monkeypatch.undo()
            if f.buffer._read_health is _ReadHealth.HEALTHY:
                seen.add(("restored", bool(state[7] < len(state[6]))))
                assert not dirty
                assert _text_state(f) == state
                assert f.newlines == newlines
                rest = "".join([line async for line in f])
                assert consumed + rest == EXPECTED_RICH
            else:
                seen.add(("broken", "dirty" if dirty else "clean"))
                assert dirty or f.buffer._eof
                await _assert_rich_refused_until_rewind(f)
    # The sweep must reach both outcomes, including pending-line batches and
    # incomplete decoder or CR state.
    assert {("restored", True), ("restored", False), ("broken", "dirty")} <= seen


async def test_drained_cookie_seek_failure_restores_real_decoder_state(
    monkeypatch,
):
    """A cookie taken with no buffered text sits at the binary cursor.

    Its seek re-anchors text without moving the binary reader, so a replay
    failure must restore real incomplete-character bytes, a pending CR and
    the newline record exactly.
    """
    seen = {"decoder": False, "trailing_cr": False}
    restored = 0
    for lines in range(230):
        async with _text(Source(RICH_WIRE), encoding="utf-8") as f:
            consumed = await f.read(1)
            for _ in range(lines):
                consumed += await f.readline()
            # Drain the buffered text without reading further input.
            consumed += await f.read(len(f._text_buffer) - f._text_buffer_offset)
            assert f._text_buffer_offset == len(f._text_buffer)
            cookie = await f.tell()
            # Clean boundaries give plain positions, covered above.
            if cookie >= 0 or f._decode_cookie(cookie)[0] != f.buffer._position:
                continue
            state, newlines = _text_state(f), f.newlines
            seen["decoder"] |= state[0][0] != b""
            seen["trailing_cr"] |= state[2]

            async def fail(self, chars_to_skip, *, strict):
                raise OSError("injected replay failure")

            monkeypatch.setattr(AsyncGzipTextFile, "_replay_characters", fail)
            with pytest.raises(OSError, match="injected replay failure"):
                await f.seek(cookie)
            monkeypatch.undo()
            assert f.buffer._read_health is _ReadHealth.HEALTHY
            assert _text_state(f) == state
            assert f.newlines == newlines
            rest = "".join([line async for line in f])
            assert consumed + rest == EXPECTED_RICH
            restored += 1
    assert restored
    assert seen == {"decoder": True, "trailing_cr": True}


async def _assert_rich_refused_until_rewind(f):
    assert f.buffer._read_health is _ReadHealth.BROKEN
    with pytest.raises(OSError, match=BROKEN):
        await f.readline()
    assert await f.seek(0) == 0
    assert "".join([line async for line in f]) == EXPECTED_RICH


class _GatedReads(concurrent.futures.ThreadPoolExecutor):
    """Executor that holds the n-th native source read once armed.

    ``where="before_entry"`` holds the call before it may touch the file, so
    cancellation prevents it; ``where="in_read"`` holds it inside the file's
    ``read``, after entry, so its result must be retained.
    """

    def __init__(self, where):
        super().__init__(max_workers=2)
        self.where = where
        self.armed_at = None
        self.entered = threading.Event()
        self.release = threading.Event()

    def submit(self, fn, /, *args, **kwargs):
        if (
            self.armed_at is not None
            and isinstance(fn, _NativeSourceCall)
            and fn.method == "read"
        ):
            self.armed_at -= 1
            if self.armed_at == 0:
                self.armed_at = None
                fn = self._hold(fn)
        return super().submit(fn, *args, **kwargs)

    def _hold(self, call):
        if self.where == "before_entry":

            def held():
                self.entered.set()
                self.release.wait(10)
                return call()

            return held
        raw, gate = call.source, self

        class _Held:
            def __getattr__(self, name):
                return getattr(raw, name)

            def read(self, *args):
                gate.entered.set()
                gate.release.wait(10)
                return raw.read(*args)

        call.source = _Held()
        return call


@pytest.mark.parametrize("where", ["before_entry", "in_read"])
@pytest.mark.parametrize("nth", [1, 3])
async def test_repeatedly_cancelled_native_replay_never_returns_wrong_text(
    big_path, where, nth
):
    """Cancellation lands while a native read of the seek's replay is held."""
    path, lines = big_path
    text = "".join(lines)
    executor = _GatedReads(where)
    try:
        async with aiofiles.open(path, "rb", executor=executor) as raw:
            async with AsyncGzipTextFile(
                None, "rt", fileobj=raw, chunk_size=4096, newline=""
            ) as f:
                consumed = await _read_lines(f, 5)
                cursor = f.buffer._read_cursor()
                executor.armed_at = nth
                task = asyncio.create_task(f.seek(len(lines[0]) * 45000))
                async with asyncio.timeout(10):
                    while not executor.entered.is_set():
                        await asyncio.sleep(0.001)
                task.cancel()
                await asyncio.sleep(0.01)
                task.cancel()
                await asyncio.sleep(0.01)
                if where == "in_read":
                    # Settlement waits for the entered read (BC1).
                    assert not task.done()
                executor.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                moved = f.buffer._read_cursor() != cursor
                # The first replay read cannot have moved the cursor; by the
                # third, earlier replay reads have advanced it.
                assert moved is (nth == 3)
                if moved:
                    assert f.buffer._read_health is _ReadHealth.BROKEN
                    with pytest.raises(OSError, match=BROKEN):
                        await f.read(10)
                    assert await f.seek(0) == 0
                    assert await f.read(4000) == text[:4000]
                else:
                    assert f.buffer._read_health is _ReadHealth.HEALTHY
                    rest = await f.read(4000)
                    assert rest == text[len(consumed) : len(consumed) + 4000]
    finally:
        executor.release.set()
        executor.shutdown(wait=True)
