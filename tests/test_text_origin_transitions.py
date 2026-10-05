"""WP7: pending-origin lifecycle and exact rollback state for the text origin.

Cookie replay through every producer is covered by the BC6 suite in
test_wp5_longline_preflight.py; these tests assert the checkpoint objects
themselves.
"""

import asyncio
import gzip
import io
import random

import pytest
from conftest import FramedAsyncReader

from aiogzip import AsyncGzipTextFile
from aiogzip._text import _TextBufferOrigin

LINE = "日" * 1000 + "\n"
PAYLOAD = LINE + "tail\n"

# Producer -> (newline, operation). Each starts with no buffered prefix, so the
# read publishes a pending origin from the named producer.
PRODUCERS = {
    "sized-read": ("\n", lambda s: s.read(len(LINE))),
    "fast-line": ("\n", lambda s: s.readline()),
    "buffered-readline": ("", lambda s: s.readline()),
}


def _gate(monkeypatch, stream, gates, *, fail=False):
    """Block binary reads number ``gates``; optionally fail the last one."""
    binary = stream._binary_file
    original = type(binary).read
    reached = {n: asyncio.Event() for n in gates}
    release = {n: asyncio.Event() for n in gates}
    calls = 0

    async def read(handle, size=-1):
        nonlocal calls
        calls += 1
        if calls in reached:
            reached[calls].set()
            await release[calls].wait()
            if fail and calls == max(gates):
                raise OSError("injected before binary read")
        return await original(handle, size)

    monkeypatch.setattr(type(binary), "read", read)
    return reached, release


def _spy_restore(monkeypatch, stream):
    """Record the stream's buffer state at the moment the origin is restored."""
    calls = []
    original = _TextBufferOrigin.restore

    def restore(origin, saved):
        if origin is stream._buffer_origin:
            calls.append(
                dict(
                    buffer=stream._text_buffer,
                    offset=stream._text_buffer_offset,
                    pending_lines=list(stream._pending_lines),
                )
            )
        return original(origin, saved)

    monkeypatch.setattr(_TextBufferOrigin, "restore", restore)
    return calls


def _open(newline, payload=PAYLOAD):
    source = FramedAsyncReader(gzip.compress(payload.encode(), mtime=0))
    return AsyncGzipTextFile(
        None, "rt", fileobj=source, closefd=False, chunk_size=100, newline=newline
    )


@pytest.mark.parametrize("producer", list(PRODUCERS))
async def test_pending_origin_is_published_once_and_never_aliases(
    monkeypatch, producer
):
    newline, operation = PRODUCERS[producer]
    async with _open(newline) as stream:
        reached, release = _gate(monkeypatch, stream, (3, 4))
        task = asyncio.create_task(operation(stream))
        try:
            await asyncio.wait_for(reached[3].wait(), 5)
            pending = stream._pending_read_origin
            assert pending is not None
            assert pending is not stream._buffer_origin
            published = pending.snapshot()
            # Mutate the live origin while the pending one is published, then
            # put it back: the pending origin must not move with it.
            live = stream._buffer_origin
            saved_live = live.snapshot()
            live.byte_offset += 12345
            live.chars_to_skip += 678
            live.trailing_cr = not live.trailing_cr
            live.seen_newline_types ^= 7
            assert pending == published
            live.restore(saved_live)
            release[3].set()
            await asyncio.wait_for(reached[4].wait(), 5)
            # The same object, unchanged while the read advanced the decoder.
            assert stream._pending_read_origin is pending
            assert pending == published
            assert pending is not stream._buffer_origin
        finally:
            for event in release.values():
                event.set()
        assert await asyncio.wait_for(task, 5) == LINE
        assert stream._pending_read_origin is None


@pytest.mark.parametrize("producer", list(PRODUCERS))
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_pending_origin_clears_after_failure(monkeypatch, producer, failure):
    newline, operation = PRODUCERS[producer]
    async with _open(newline) as stream:
        reached, release = _gate(monkeypatch, stream, (3,), fail=True)
        task = asyncio.create_task(operation(stream))
        try:
            await asyncio.wait_for(reached[3].wait(), 5)
            assert stream._pending_read_origin is not None
            if failure == "cancel":
                task.cancel()
            else:
                release[3].set()
            with pytest.raises(
                asyncio.CancelledError if failure == "cancel" else OSError
            ):
                await asyncio.wait_for(task, 5)
        finally:
            release[3].set()
        assert stream._pending_read_origin is None
        # The reader recovers the whole line from the restored state.
        assert await stream.readline() == LINE


class _FailOnceReader:
    """No-effect transient failure on one read, after a cursor checkpoint."""

    def __init__(self, data, failing_read):
        self._buffer = io.BytesIO(data)
        self._reads = 0
        self._failing_read = failing_read

    def tell(self):
        return self._buffer.tell()

    async def read(self, size=-1):
        self._reads += 1
        if self._reads == self._failing_read:
            raise OSError("transient source failure")
        return self._buffer.read(size)

    def seekable(self):
        return False


@pytest.mark.parametrize("newline", [None, ""], ids=["fast", "generic"])
async def test_readlines_rollback_restores_offset_origin_and_batch(
    monkeypatch, newline
):
    lines = [f"line {i:04d}\n" for i in range(400)]
    source = _FailOnceReader(gzip.compress("".join(lines).encode(), mtime=0), 6)
    async with AsyncGzipTextFile(
        None, "rt", fileobj=source, closefd=False, chunk_size=64, newline=newline
    ) as stream:
        first = await stream.readline()
        buffer, offset = stream._text_buffer, stream._text_buffer_offset
        origin = stream._buffer_origin.snapshot()
        live = stream._buffer_origin
        restores = _spy_restore(monkeypatch, stream)
        with pytest.raises(OSError, match="transient source failure"):
            await stream.readlines()
        # C0 order: the buffer is rebuilt and the offset restored before the
        # origin is restored, and the line batch is cleared only afterwards.
        outer = restores[-1]
        assert outer["buffer"].startswith(buffer[:offset])
        assert outer["offset"] == offset
        batch_at_restore = outer["pending_lines"]
        # Buffer rebuilt from the original prefix, offset and origin restored,
        # pending-line batch cleared; the live origin object is retained.
        assert stream._text_buffer.startswith(buffer[:offset])
        assert stream._text_buffer_offset == offset
        assert stream._buffer_origin == origin
        assert stream._buffer_origin is live
        assert stream._pending_lines == []
        assert stream._pending_idx == 0
        if newline is None:
            # The fast path had a batch in flight, cleared after the restore.
            assert batch_at_restore
        assert stream._pending_read_origin is None
        assert [first, *await stream.readlines()] == lines


async def test_buffered_readline_restores_origin_then_appends_recovered_text(
    monkeypatch,
):
    # One long generic-newline line spanning many chunks, after a short line.
    letters = random.Random(0).choices("abcdefghijklmnopqrstuvwxyz", k=2000)
    long_line = "".join(letters) + "\n"  # incompressible: spans many chunks
    payload = "head\n" + long_line + "tail\n"
    source = _FailOnceReader(gzip.compress(payload.encode(), mtime=0), 8)
    async with AsyncGzipTextFile(
        None, "rt", fileobj=source, closefd=False, chunk_size=64, newline=""
    ) as stream:
        assert await stream.readline() == "head\n"
        buffer, offset = stream._text_buffer, stream._text_buffer_offset
        origin = stream._buffer_origin.snapshot()
        restores = _spy_restore(monkeypatch, stream)
        with pytest.raises(OSError, match="transient source failure"):
            await stream.readline()
        # At the restore, the buffer and offset are exactly the saved ones:
        # recovered pieces are appended only after the origin is restored.
        assert len(restores) == 1
        assert restores[0]["buffer"] == buffer
        assert restores[0]["offset"] == offset
        assert stream._buffer_origin == origin
        assert stream._text_buffer_offset == offset
        assert stream._text_buffer.startswith(buffer)
        assert len(stream._text_buffer) > len(buffer)
        assert stream._pending_read_origin is None
        assert await stream.readline() == long_line
        assert await stream.readline() == "tail\n"
