"""WP6 transition matrix: binary read health across the C0 transition table.

Each case asserts the complete state a transition leaves (health, EOF, retained
buffer, logical position, whether the decoder is live or discarded, active call
and closure), poison-observer events, the immediate and later results, and the
recovery path. Deeper behavioral coverage stays in the source-settlement,
native-work, file-state and regression suites.
"""

import asyncio
import gzip
import io
import random
import threading

import aiofiles.threadpool
import pytest

from aiogzip import AsyncGzipBinaryFile, ConcurrentOperationError
from aiogzip._binary import _ReadHealth

HEALTHY = _ReadHealth.HEALTHY
SALVAGE = _ReadHealth.VALIDATION_SALVAGE
BROKEN = _ReadHealth.BROKEN

PAYLOAD = b"transition matrix payload\n" * 200
WIRE = gzip.compress(PAYLOAD, mtime=0)
# Incompressible and many source chunks long, so a fresh reader returns a prefix
# before reaching a limit set just below the full size (compressible input can
# arrive in one source read and inflate eagerly).
LARGE = random.Random(0).randbytes(1_500_000)
ABORTED = "read aborted because the gzip file was closed while the call was active"


class Source:
    """Async source over bytes; seekable on request, with an optional failure."""

    def __init__(self, data=WIRE, *, seekable=False, fail=None, checkpoint=False):
        self.buffer = io.BytesIO(data)
        self._seekable = seekable
        self.fail = fail
        self.entered = asyncio.Event()
        self.gate = None
        if checkpoint:
            self.tell = self.buffer.tell

    async def seekable(self):
        return self._seekable

    async def seek(self, offset, whence=0):
        if not self._seekable:
            raise OSError("not seekable")
        return self.buffer.seek(offset, whence)

    async def read(self, size=-1):
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        fail, self.fail = self.fail, None
        if fail == "no-effect":
            raise OSError("transient source error")
        if fail == "consumed":
            self.buffer.read(size)
            raise OSError("source failed after consuming input")
        return self.buffer.read(size)


def opened(source, **options):
    return AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=False, **options)


def snapshot(stream):
    decoder = stream._decoder
    return dict(
        health=stream._read_health,
        eof=stream._eof,
        buffered=len(stream._buffer) - stream._buffer_offset,
        position=stream._position,
        decoder_live=decoder is not None and not decoder._discarded,
        active=stream._read_call_active,
        closed=stream.closed,
    )


def state(
    health, *, eof, buffered=0, position=0, decoder_live, active=False, closed=False
):
    return dict(
        health=health,
        eof=eof,
        buffered=buffered,
        position=position,
        decoder_live=decoder_live,
        active=active,
        closed=closed,
    )


FRESH = state(HEALTHY, eof=False, decoder_live=True)


def observe(stream):
    events = []
    stream._read_poison_observer = events.append
    return events


async def assert_terminal(stream):
    with pytest.raises(OSError, match="broken"):
        await stream.read(1)


def spy_abort(monkeypatch):
    calls = []
    original = AsyncGzipBinaryFile._break_read_on_abort

    def spy(self):
        calls.append(self)
        return original(self)

    monkeypatch.setattr(AsyncGzipBinaryFile, "_break_read_on_abort", spy)
    return calls


def corrupt_crc(data=WIRE):
    corrupt = bytearray(data)
    corrupt[-8] ^= 1
    return bytes(corrupt)


# Healthy operation


async def test_healthy_read_reaches_validated_eof_then_close_discards():
    stream = opened(Source())
    await stream.open()
    events = observe(stream)
    assert snapshot(stream) == FRESH
    assert await stream.read() == PAYLOAD
    # Validated EOF is healthy: EOF is orthogonal to health.
    validated = state(HEALTHY, eof=True, position=len(PAYLOAD), decoder_live=True)
    assert snapshot(stream) == validated
    assert await stream.read() == b""
    await stream.close()
    assert snapshot(stream) == dict(validated, decoder_live=False, closed=True)
    assert events == []


# Decoder failures


@pytest.mark.parametrize(
    "wire,match,retained",
    [
        (corrupt_crc(), "CRC check failed", len(PAYLOAD)),
        # Missing trailer: the deflate stream completes, so the retained salvage
        # is the whole payload on any zlib build.
        (WIRE[:-8], "truncated trailer", len(PAYLOAD)),
        (b"not a gzip member", "Error decompressing", 0),
    ],
    ids=["integrity", "truncated", "malformed-header"],
)
async def test_decoder_failures_retain_exact_salvage_then_fail(wire, match, retained):
    stream = opened(Source(wire))
    await stream.open()
    events = observe(stream)
    with pytest.raises(gzip.BadGzipFile, match=match):
        await stream.read()
    failed = state(SALVAGE, eof=True, buffered=retained, decoder_live=False)
    assert snapshot(stream) == failed
    assert events == [True]
    if retained:
        # Salvage is recovery data, an exact payload prefix, never clean EOF.
        assert await stream.read() == PAYLOAD[:retained]
        assert snapshot(stream) == dict(failed, buffered=0, position=retained)
    await assert_terminal(stream)
    assert snapshot(stream)["health"] is SALVAGE
    await stream.close()
    assert snapshot(stream)["closed"] is True
    assert snapshot(stream)["health"] is SALVAGE


async def test_decompression_limit_is_broken_without_salvage():
    stream = opened(Source(), max_decompressed_size=len(PAYLOAD) // 2)
    await stream.open()
    events = observe(stream)
    with pytest.raises(OSError, match="max_decompressed_size"):
        await stream.read()
    broken = state(BROKEN, eof=True, decoder_live=False)
    assert snapshot(stream) == broken
    assert events == [False]
    await assert_terminal(stream)
    assert snapshot(stream) == broken
    await stream.close()
    assert snapshot(stream) == dict(broken, closed=True)


# Source outcomes


async def test_no_effect_source_error_keeps_the_reader_healthy():
    stream = opened(Source(fail="no-effect", checkpoint=True))
    await stream.open()
    events = observe(stream)
    with pytest.raises(OSError, match="transient"):
        await stream.read()
    assert snapshot(stream) == FRESH
    assert await stream.read() == PAYLOAD
    assert snapshot(stream) == state(
        HEALTHY, eof=True, position=len(PAYLOAD), decoder_live=True
    )
    assert events == []
    await stream.close()


@pytest.mark.parametrize("checkpoint", [False, True])
async def test_consumed_or_uncertain_source_error_breaks_the_reader(checkpoint):
    stream = opened(Source(fail="consumed", checkpoint=checkpoint, seekable=True))
    await stream.open()
    events = observe(stream)
    with pytest.raises(OSError, match="consuming input"):
        await stream.read()
    broken = state(BROKEN, eof=True, decoder_live=False)
    assert snapshot(stream) == broken
    assert events == [False]
    # Never relabeled as salvage to let a retry pass.
    await assert_terminal(stream)
    assert snapshot(stream) == broken
    # Physical rewind is the recovery path.
    assert await stream.seek(0) == 0
    assert snapshot(stream) == FRESH
    assert await stream.read() == PAYLOAD
    await stream.close()


# Native cancellation


@pytest.mark.parametrize("repetitions", [1, 3])
async def test_native_cancellation_settles_and_keeps_the_reader_healthy(
    tmp_path, repetitions
):
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    path = tmp_path / "native.gz"
    path.write_bytes(WIRE)

    class Reader(io.BufferedReader):
        gated = False

        def read(self, size=-1):
            if not self.gated:
                self.gated = True
                data = super().read(len(WIRE) // 2)
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("native read watchdog expired")
                return data
            return super().read(size)

    raw = Reader(io.FileIO(path, "rb"))
    stream = opened(aiofiles.threadpool.wrap(raw, loop=loop))
    caller = None
    try:
        await stream.open()
        events = observe(stream)
        caller = asyncio.create_task(stream.read())
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(repetitions):
            caller.cancel()
            await asyncio.sleep(0)
            assert not caller.done()
            assert snapshot(stream) == dict(FRESH, active=True)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        # Settled native input is retained, not lost or poisoned.
        assert snapshot(stream) == FRESH
        assert events == []
        assert await stream.read() == PAYLOAD
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await stream.close()
        raw.close()


# Overlap, closure and opening


async def test_overlap_rejection_does_not_touch_health():
    source = Source()
    source.gate = asyncio.Event()
    stream = opened(source)
    await stream.open()
    first = asyncio.create_task(stream.read())
    await asyncio.wait_for(source.entered.wait(), 5)
    assert stream._read_call_active is True
    with pytest.raises(ConcurrentOperationError):
        await stream.read(1)
    assert snapshot(stream) == dict(FRESH, active=True)
    source.gate.set()
    assert await first == PAYLOAD
    assert snapshot(stream) == state(
        HEALTHY, eof=True, position=len(PAYLOAD), decoder_live=True
    )
    await stream.close()


async def test_close_of_a_broken_reader_keeps_health_and_eof():
    stream = opened(Source(), max_decompressed_size=1)
    await stream.open()
    with pytest.raises(OSError, match="max_decompressed_size"):
        await stream.read()
    await stream.close()
    assert snapshot(stream) == state(BROKEN, eof=True, decoder_live=False, closed=True)


async def test_close_during_open_is_rejected_and_health_stays_healthy():
    gate, probing = asyncio.Event(), asyncio.Event()

    class SlowProbe(Source):
        async def seekable(self):
            probing.set()
            await gate.wait()
            return False

    stream = opened(SlowProbe())
    opening = asyncio.create_task(stream.open())
    await asyncio.wait_for(probing.wait(), 5)
    assert stream._opening is True
    with pytest.raises(ConcurrentOperationError):
        await stream.close()
    assert stream._read_health is HEALTHY
    gate.set()
    await opening
    assert snapshot(stream) == FRESH
    await stream.close()
    assert snapshot(stream) == dict(FRESH, decoder_live=False, closed=True)


# Rewind and recovery


@pytest.mark.parametrize("seekable", [True, False], ids=["physical", "cached"])
async def test_rewind_recovers_a_broken_reader_to_fresh_health(seekable):
    source = Source(gzip.compress(LARGE, mtime=0), seekable=seekable)
    stream = opened(source, max_decompressed_size=len(LARGE) - 1)
    await stream.open()
    with pytest.raises(OSError, match="max_decompressed_size"):
        await stream.read()
    broken = snapshot(stream)
    assert (broken["health"], broken["eof"], broken["decoder_live"]) == (
        BROKEN,
        True,
        False,
    )
    old_decoder = stream._decoder
    assert await stream.seek(0) == 0
    assert snapshot(stream) == FRESH
    assert stream._decoder is not old_decoder
    assert await stream.read(100) == LARGE[:100]
    assert snapshot(stream)["health"] is HEALTHY
    assert snapshot(stream)["position"] == 100
    await stream.close()


async def test_failed_rewind_leaves_the_reader_broken():
    stream = opened(
        Source(seekable=False),
        max_decompressed_size=len(PAYLOAD) // 2,
        max_rewind_cache_size=16,
    )
    await stream.open()
    with pytest.raises(OSError, match="max_decompressed_size"):
        await stream.read()
    broken = snapshot(stream)
    with pytest.raises(OSError):
        await stream.seek(0)
    assert snapshot(stream) == broken
    assert broken == state(BROKEN, eof=True, decoder_live=False)
    await assert_terminal(stream)
    await stream.close()


async def test_absolute_rewind_of_a_healthy_reader_restarts_cleanly():
    stream = opened(Source(seekable=True))
    await stream.open()
    assert await stream.read(100) == PAYLOAD[:100]
    assert await stream.seek(0) == 0
    assert snapshot(stream) == FRESH
    assert await stream.read() == PAYLOAD
    await stream.close()


# Exceptional exit with active work


async def test_exceptional_exit_with_active_custom_work_breaks_the_reader(monkeypatch):
    calls = spy_abort(monkeypatch)
    source = Source()
    source.gate = asyncio.Event()
    stream = opened(source)
    reader = None
    with pytest.raises(RuntimeError, match="body"):
        async with stream:
            reader = asyncio.create_task(stream.read())
            await asyncio.wait_for(source.entered.wait(), 5)
            assert stream._read_call_active is True
            raise RuntimeError("body")
    aborted = state(BROKEN, eof=True, decoder_live=False, closed=True)
    assert snapshot(stream) == aborted
    assert calls == [stream]
    source.gate.set()
    with pytest.raises(OSError, match=ABORTED):
        await reader
    assert snapshot(stream) == aborted


async def test_exceptional_exit_with_active_native_work_breaks_the_reader(
    monkeypatch, tmp_path
):
    calls = spy_abort(monkeypatch)
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    path = tmp_path / "abort.gz"
    path.write_bytes(WIRE)

    class Reader(io.BufferedReader):
        def read(self, size=-1):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("native read watchdog expired")
            return super().read(size)

    raw = Reader(io.FileIO(path, "rb"))
    stream = opened(aiofiles.threadpool.wrap(raw, loop=loop))
    reader = None
    try:
        with pytest.raises(RuntimeError, match="body"):
            async with stream:
                reader = asyncio.create_task(stream.read())
                await asyncio.wait_for(entered.wait(), 5)
                assert stream._read_call_active is True

                async def finish():
                    await asyncio.sleep(0.05)
                    release.set()

                loop.create_task(finish())
                raise RuntimeError("body")
        # The native reservation is released before the abort marks the handle
        # closed. At C0 that ordering left the closed reader's decoder live;
        # WP6's abort close now discards it whenever no reservation remains.
        aborted = state(BROKEN, eof=True, decoder_live=False, closed=True)
        assert snapshot(stream) == aborted
        assert calls == [stream]
        with pytest.raises(OSError, match=ABORTED):
            await reader
        assert snapshot(stream) == aborted
    finally:
        release.set()
        if reader is not None:
            await asyncio.gather(reader, return_exceptions=True)
        raw.close()
