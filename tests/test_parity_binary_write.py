"""Parity matrix D3: inline ``write()`` reservation and ``_BinaryWriteReservation``.

``AsyncGzipBinaryFile.write`` reserves inline because the context manager
exceeded the small-write budget. The ``reserved`` adapter runs the same
validation and snapshot as ``write()``, then takes the reservation through the
context manager and calls the shared ``_write_reserved`` body. It is a direct
adapter rather than ``writelines([data])``, whose batching never reaches the
codec for empty input; public ``writelines()`` keeps its own coverage.

Every scenario compares, across adapters: the result or exception, sink
bytes, position, broken state, encoder state and reservation state.
"""

import asyncio
import gzip
import random
import zlib

import pytest

from aiogzip import AsyncGzipBinaryFile, ConcurrentOperationError, GzipEncoder


async def _inline(f, data):
    return await f.write(data)


async def _reserved(f, data):
    # write()'s own validation, snapshot and return value, with the
    # reservation taken by the context manager instead of inline.
    if not f._writing_mode:
        raise OSError("File not open for writing")
    if f._is_closed:
        raise ValueError("I/O operation on closed file.")
    if f._file is None:
        raise ValueError("File not opened. Call await open() or use async with.")
    if f._write_broken:
        f._raise_write_broken()
    payload = data if type(data) is bytes else f._coerce_byteslike(data)
    with f._write_call as encoder:
        return await f._write_reserved(payload, encoder)


ADAPTERS = {"inline": _inline, "reserved": _reserved}
# Incompressible and below the offload threshold: zlib emits output during
# the call, so every sink scenario is exercised inline.
PAYLOAD = random.Random(0).randbytes(100_000)


class _Sink:
    """Recording async sink with injectable progress and failures."""

    def __init__(self, mode="ok"):
        self.data = bytearray()
        self.mode = mode
        self.gate = None
        self.entered = asyncio.Event()
        self.closed = False

    async def write(self, data):
        if self.gate is not None:
            self.entered.set()
            await self.gate.wait()
        if self.mode == "fail":
            raise OSError("sink write failed")
        if self.mode == "zero":
            return 0
        if self.mode == "invalid":
            return "many"
        accepted = data[:5] if self.mode == "partial" else data
        self.data += accepted
        return len(accepted)

    def close(self):
        self.closed = True


async def _opened(sink=None):
    sink = sink or _Sink()
    f = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=False, mtime=0)
    await f.open()
    header = len(sink.data)
    return f, sink, header


def _reference_feed(data):
    """Compressed output of one feed operation, as a fresh encoder emits it."""
    encoder = GzipEncoder(mtime=0)
    b"".join(encoder.start())
    return b"".join(encoder.feed(data))


def _state(f, sink, header):
    encoder = f._encoder
    return {
        "sink": bytes(sink.data[header:]),
        "position": f._position,
        "broken": f._write_broken,
        "call_active": f._write_call_active,
        "discarded": encoder._discarded,
        "encoder_active": encoder._active_token is not None,
    }


async def _run(adapter, data, sink_mode="ok", engine=None):
    f, sink, header = await _opened()
    sink.mode = sink_mode
    if engine is not None:
        f._encoder._engine = engine
    try:
        result = ("ok", await ADAPTERS[adapter](f, data))
    except BaseException as error:
        result = ("error", type(error), str(error))
    return result, _state(f, sink, header)


class _FailingEngine:
    def compress(self, data):
        raise zlib.error("injected compression failure")

    def flush(self, mode=zlib.Z_FINISH):
        raise zlib.error("injected flush failure")


SCENARIOS = {
    "success": dict(data=PAYLOAD),
    "empty": dict(data=b""),
    "bytes-like": dict(data=memoryview(bytearray(PAYLOAD))),
    "partial-sink": dict(data=PAYLOAD, sink_mode="partial"),
    "zero-progress-sink": dict(data=PAYLOAD, sink_mode="zero"),
    "invalid-count-sink": dict(data=PAYLOAD, sink_mode="invalid"),
    "sink-failure": dict(data=PAYLOAD, sink_mode="fail"),
    "codec-failure": dict(data=PAYLOAD, engine=_FailingEngine()),
    "invalid-type": dict(data="text"),
}


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_adapters_leave_identical_outcomes(scenario):
    options = SCENARIOS[scenario]
    inline = await _run("inline", **options)
    reserved = await _run("reserved", **options)
    assert inline == reserved
    result, state = inline
    assert state["call_active"] is False
    if result[0] == "ok":
        size = len(bytes(options["data"]))
        assert result[1] == size
        # Published position, and the call's own output, delivered in-call.
        assert state["position"] == size
        assert state["sink"] == _reference_feed(bytes(options["data"]))
        assert bool(state["sink"]) == (size > 0)  # the sink really saw the call
        assert state["broken"] is False
    elif scenario != "invalid-type":
        assert state["broken"] is True
        assert state["discarded"] is True
        assert state["position"] == 0


@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_empty_write_drives_exactly_one_feed_operation(adapter):
    f, sink, header = await _opened()
    encoder = f._encoder
    original = encoder._feed_snapshot
    calls = []

    def feed_snapshot(snapshot):
        calls.append(snapshot)
        return original(snapshot)

    encoder._feed_snapshot = feed_snapshot
    assert await ADAPTERS[adapter](f, b"") == 0
    assert calls == [b""]
    assert encoder._active_token is None


@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_snapshot_is_taken_before_the_first_suspension(adapter, monkeypatch):
    f, sink, header = await _opened()
    recorded = []
    barrier = asyncio.Event()
    paused = asyncio.Event()
    original = AsyncGzipBinaryFile._write_reserved

    async def write_reserved(self, payload, encoder):
        recorded.append(payload)
        paused.set()
        await barrier.wait()
        return await original(self, payload, encoder)

    monkeypatch.setattr(AsyncGzipBinaryFile, "_write_reserved", write_reserved)
    caller_buffer = bytearray(PAYLOAD)
    task = asyncio.create_task(ADAPTERS[adapter](f, caller_buffer))
    await asyncio.wait_for(paused.wait(), 5)
    assert type(recorded[0]) is bytes
    assert recorded[0] == PAYLOAD
    caller_buffer[:] = b"\x00" * len(caller_buffer)
    barrier.set()
    assert await task == len(PAYLOAD)
    await f.close()
    assert gzip.decompress(bytes(sink.data)) == PAYLOAD


async def _blocked_write(adapter):
    f, sink, header = await _opened()
    sink.gate = asyncio.Event()
    task = asyncio.create_task(ADAPTERS[adapter](f, PAYLOAD))
    await asyncio.wait_for(sink.entered.wait(), 5)
    return f, sink, header, task


@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_position_is_published_only_after_sink_success(adapter):
    f, sink, header, task = await _blocked_write(adapter)
    assert f._position == 0
    sink.gate.set()
    assert await task == len(PAYLOAD)
    assert f._position == len(PAYLOAD)


async def _cancelled_outcome(adapter, cancels):
    f, sink, header, task = await _blocked_write(adapter)
    for _ in range(cancels):
        task.cancel()
        await asyncio.sleep(0)
    sink.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    return _state(f, sink, header)


@pytest.mark.parametrize("cancels", [1, 2])
async def test_cancellation_during_sink_write_matches(cancels):
    inline = await _cancelled_outcome("inline", cancels)
    reserved = await _cancelled_outcome("reserved", cancels)
    assert inline == reserved
    assert inline["broken"] is True
    assert inline["position"] == 0
    assert inline["call_active"] is False


async def _overlap_outcome(adapter):
    f, sink, header, task = await _blocked_write(adapter)
    errors = []
    for other in ADAPTERS.values():
        with pytest.raises(ConcurrentOperationError) as raised:
            await other(f, b"second")
        errors.append(str(raised.value))
    with pytest.raises(ConcurrentOperationError):
        await f.close()
    sink.gate.set()
    assert await task == len(PAYLOAD)
    return errors, _state(f, sink, header)


async def test_overlap_and_close_during_active_call_match():
    inline = await _overlap_outcome("inline")
    reserved = await _overlap_outcome("reserved")
    assert inline == reserved
    assert inline[1]["position"] == len(PAYLOAD)
    assert inline[1]["broken"] is False


async def _abort_outcome(adapter):
    sink = _Sink()
    f = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True, mtime=0)
    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with f:
            header = len(sink.data)
            sink.gate = asyncio.Event()
            task = asyncio.create_task(ADAPTERS[adapter](f, PAYLOAD))
            await asyncio.wait_for(sink.entered.wait(), 5)
            raise RuntimeError("body")
    sink.gate.set()
    try:
        await task
        result = "ok"
    except BaseException as error:
        result = (type(error), str(error))
    return result, f.closed, sink.closed, _state(f, sink, header)


async def test_context_exit_abort_during_active_call_matches():
    inline = await _abort_outcome("inline")
    reserved = await _abort_outcome("reserved")
    assert inline == reserved
    result, closed, sink_closed, state = inline
    assert result != "ok"
    assert closed and sink_closed
    assert state["broken"] is True and state["discarded"] is True


@pytest.mark.parametrize("outcome", ["success", "failure"])
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_completion_waiter_is_released_on_every_exit(adapter, outcome):
    f, sink, header, task = await _blocked_write(adapter)
    waiter = asyncio.create_task(f._wait_for_active_call())
    await asyncio.sleep(0)
    assert not waiter.done()
    if outcome == "failure":
        sink.mode = "fail"
    sink.gate.set()
    await asyncio.gather(task, return_exceptions=True)
    assert await asyncio.wait_for(waiter, 5) is True
    assert f._write_call_active is False
    assert f._active_call_waiter is None


@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_failure_surfaces_in_the_same_call_and_is_terminal(adapter):
    f, sink, header = await _opened()
    sink.mode = "fail"
    with pytest.raises(OSError, match="sink write failed"):
        await ADAPTERS[adapter](f, PAYLOAD)
    sink.mode = "ok"
    for other in ADAPTERS.values():
        with pytest.raises(OSError, match="write stream is broken"):
            await other(f, b"later")


@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_each_call_delivers_its_own_output_without_cross_call_buffering(
    adapter,
):
    f, sink, header = await _opened()
    reference = GzipEncoder(mtime=0)
    b"".join(reference.start())
    delivered = len(sink.data)
    for piece in (b"one ", b"", PAYLOAD, b"three"):
        await ADAPTERS[adapter](f, piece)
        expected = b"".join(reference.feed(piece))
        assert bytes(sink.data[delivered:]) == expected
        delivered = len(sink.data)
    await f.close()
    assert gzip.decompress(bytes(sink.data)) == b"one " + PAYLOAD + b"three"
