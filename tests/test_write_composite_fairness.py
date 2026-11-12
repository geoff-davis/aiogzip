"""BC30: composite writes yield to the event loop when the sink never suspends.

``writelines()`` and the write-mode zero-fill ``seek()`` loop many inline
writes under one reservation. They checkpoint between writes once a budget of
inline bytes or writes is spent; a single ``write()`` never does. A
cancellation at that checkpoint leaves what a cancellation during a suspended
sink write leaves: a broken writer whose position counts the completed writes.

Loop turns are counted, never timed.
"""

import asyncio
import gzip
import zlib

import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
    ConcurrentOperationError,
)
from aiogzip._codec_async import (
    _INLINE_WRITE_BYTES_CHECKPOINT,
    _INLINE_WRITES_CHECKPOINT,
    _ZLIB_OFFLOAD_THRESHOLD,
    _WriteBudget,
)

LINE = b"0123456789" * 9 + b"abcdefghi\n"  # 100 bytes
LINE_COUNT = 60_000
PAYLOAD = LINE * LINE_COUNT
ZERO_CHUNK = AsyncGzipBinaryFile._SEEK_ZERO_CHUNK_SIZE
SEEK_SIZE = 8 * 1024 * 1024


class _ReadySink:
    """An in-memory sink whose write() never suspends."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.calls = 0
        self.closed = False

    async def write(self, data: bytes) -> int:
        assert not self.closed, "sink written after close"
        self.calls += 1
        self.data += data
        return len(data)

    async def close(self) -> None:
        self.closed = True


class _GatedSink(_ReadySink):
    """A sink that suspends in its ``block_at``-th write until cancelled."""

    def __init__(self, block_at: int) -> None:
        super().__init__()
        self.block_at = block_at
        self.entered = asyncio.Event()

    async def write(self, data: bytes) -> int:
        if self.calls + 1 == self.block_at:
            self.entered.set()
            await asyncio.Event().wait()
        return await super().write(data)


async def _count_turns_during(awaitable):
    turns = 0
    done = False

    async def sibling():
        nonlocal turns
        while not done:
            turns += 1
            await asyncio.sleep(0)

    task = asyncio.ensure_future(sibling())
    await asyncio.sleep(0)
    turns = 0
    try:
        result = await awaitable
    finally:
        seen = turns
        done = True
        await task
    return result, seen


def _make(kind, sink, **options):
    options.setdefault("closefd", False)
    if kind == "text":
        return AsyncGzipTextFile(
            None, "wt", fileobj=sink, mtime=0, encoding="ascii", newline="", **options
        )
    return AsyncGzipBinaryFile(None, "wb", fileobj=sink, mtime=0, **options)


async def _open(kind, sink, **options):
    f = _make(kind, sink, **options)
    await f.open()
    return f


def _lines(kind, count=LINE_COUNT):
    line = LINE.decode("ascii") if kind == "text" else LINE
    return [line] * count


def _one(kind, payload=LINE):
    return payload.decode("ascii") if kind == "text" else payload


def _binary(f):
    return f._binary_file if isinstance(f, AsyncGzipTextFile) else f


def _decoded_prefix(sink):
    return zlib.decompressobj(wbits=31).decompress(bytes(sink.data))


# Fairness


def test_budget_constants_and_accounting():
    assert _INLINE_WRITE_BYTES_CHECKPOINT == 1024 * 1024
    assert _INLINE_WRITES_CHECKPOINT == 256
    budget = _WriteBudget()
    assert not budget.spent()
    # Offloaded writes yield at their executor hop and are not counted.
    budget.add(_ZLIB_OFFLOAD_THRESHOLD)
    assert (budget.inline_bytes, budget.inline_writes) == (0, 0)
    for _ in range(_INLINE_WRITES_CHECKPOINT - 1):
        budget.add(0)
    assert not budget.spent()
    budget.add(0)
    assert budget.spent()
    budget.reset()
    # Four writes just under the offload threshold stay under 1 MiB.
    for _ in range(4):
        budget.add(_ZLIB_OFFLOAD_THRESHOLD - 1)
    assert not budget.spent()
    budget.add(4)
    assert budget.spent()


@pytest.mark.parametrize("kind", ["binary", "text"])
@pytest.mark.parametrize("chunk_size", [1024, None])
async def test_writelines_to_a_ready_sink_yields(kind, chunk_size):
    sink = _ReadySink()
    options = {} if chunk_size is None else {"chunk_size": chunk_size}
    f = await _open(kind, sink, **options)
    _, turns = await _count_turns_during(f.writelines(_lines(kind)))
    assert await f.tell() == len(PAYLOAD)
    await f.close()
    assert gzip.decompress(bytes(sink.data)) == PAYLOAD
    if chunk_size is None:
        # Batches of just under 256 KiB: the byte budget is spent every five.
        assert 3 <= turns <= len(PAYLOAD) // _INLINE_WRITE_BYTES_CHECKPOINT
    else:
        # Ten lines per write: the step budget is spent every 256 writes.
        writes = LINE_COUNT // (chunk_size // len(LINE))
        expected = writes // _INLINE_WRITES_CHECKPOINT
        assert expected - 1 <= turns <= expected + 1


async def test_zero_fill_seek_to_a_ready_sink_yields():
    sink = _ReadySink()
    f = await _open("binary", sink)
    await f.write(b"head")
    position, turns = await _count_turns_during(f.seek(SEEK_SIZE, 1))
    assert position == 4 + SEEK_SIZE
    await f.close()
    assert gzip.decompress(bytes(sink.data)) == b"head" + bytes(SEEK_SIZE)
    expected = SEEK_SIZE // ZERO_CHUNK // _INLINE_WRITES_CHECKPOINT
    assert expected - 1 <= turns <= expected + 1


@pytest.mark.parametrize("kind", ["binary", "text"])
async def test_composites_within_the_budget_do_not_checkpoint(kind):
    sink = _ReadySink()
    f = await _open(kind, sink, chunk_size=1024)
    # 250 writes of 1,000 bytes: under both the step and the byte budget.
    _, turns = await _count_turns_during(f.writelines(_lines(kind, 2500)))
    assert turns == 0
    if kind == "binary":
        target = await f.tell() + (_INLINE_WRITES_CHECKPOINT - 1) * ZERO_CHUNK
        _, turns = await _count_turns_during(f.seek(target))
        assert turns == 0
    await f.close()


@pytest.mark.parametrize("kind", ["binary", "text"])
async def test_the_last_write_of_a_composite_is_not_followed_by_a_checkpoint(kind):
    sink = _ReadySink()
    f = await _open(kind, sink, chunk_size=1024)
    # Exactly 256 writes spend the step budget with nothing left to write.
    lines = _lines(kind, _INLINE_WRITES_CHECKPOINT * 10)
    _, turns = await _count_turns_during(f.writelines(lines))
    assert turns == 0
    if kind == "binary":
        target = await f.tell() + _INLINE_WRITES_CHECKPOINT * ZERO_CHUNK
        _, turns = await _count_turns_during(f.seek(target))
        assert turns == 0
    await f.close()


@pytest.mark.parametrize("kind", ["binary", "text"])
@pytest.mark.parametrize("size", [100, 4096, 64 * 1024])
async def test_plain_write_adds_no_checkpoint(kind, size):
    sink = _ReadySink()
    f = await _open(kind, sink)
    payload = _one(kind, (LINE * (size // len(LINE) + 1))[:size])
    # Enough calls to spend both budgets several times over.
    count = max(4 * _INLINE_WRITES_CHECKPOINT, 4 * 1024 * 1024 // size)

    async def write_all():
        for _ in range(count):
            assert await f.write(payload) == size

    _, turns = await _count_turns_during(write_all())
    assert turns == 0
    assert await f.tell() == count * size
    await f.close()
    assert len(gzip.decompress(bytes(sink.data))) == count * size


async def test_offloaded_writes_do_not_spend_the_budget(monkeypatch):
    import aiogzip._binary as binary_module

    checkpoints = 0
    original = binary_module._cooperative_checkpoint

    async def counting():
        nonlocal checkpoints
        checkpoints += 1
        await original()

    monkeypatch.setattr(binary_module, "_cooperative_checkpoint", counting)
    sink = _ReadySink()
    f = await _open("binary", sink)
    block = bytes(_ZLIB_OFFLOAD_THRESHOLD)
    await f.writelines([block] * 12)
    assert checkpoints == 0
    await f.close()
    assert gzip.decompress(bytes(sink.data)) == block * 12


@pytest.mark.parametrize("kind", ["binary", "text"])
async def test_writelines_to_a_path_round_trips(kind, tmp_path):
    path = tmp_path / "out.gz"
    if kind == "text":
        f = AsyncGzipTextFile(path, "wt", encoding="ascii", newline="", chunk_size=1024)
    else:
        f = AsyncGzipBinaryFile(path, "wb", chunk_size=1024)
    async with f:
        await f.writelines(_lines(kind, 6000))
        if kind == "binary":
            await f.seek(SEEK_SIZE // 8, 1)
    expected = LINE * 6000 + (bytes(SEEK_SIZE // 8) if kind == "binary" else b"")
    assert gzip.decompress(path.read_bytes()) == expected


# Cancellation at the checkpoint


async def _park_at_checkpoint(f, sink, composite):
    """Start a composite on a ready sink and return it parked at a checkpoint.

    A ready sink never suspends, so the composite's first suspension is the
    cooperative checkpoint.
    """
    task = asyncio.ensure_future(composite)
    await asyncio.sleep(0)
    assert not task.done()
    assert _binary(f)._write_call_active is True
    return task


def _composite(kind, f, composite):
    if composite == "seek":
        return f.seek(SEEK_SIZE, 1)
    return f.writelines(_lines(kind))


async def _broken_state(kind, f, sink):
    """The observable state of a writer after a cancelled composite."""
    binary = _binary(f)
    state = {
        "broken": binary._write_broken,
        "binary_call_active": binary._write_call_active,
        "text_call_active": getattr(f, "_write_call_active", False),
        "closed": f.closed,
    }
    refusals = []
    calls = [lambda: f.write(_one(kind)), lambda: f.writelines([_one(kind)]), f.flush]
    if kind == "binary":
        calls.append(lambda: f.seek(1, 1))
    for call in calls:
        with pytest.raises(OSError) as raised:
            await call()
        refusals.append(str(raised.value))
    state["refusals"] = refusals
    size = len(sink.data)
    await f.close()
    # A torn member gets no trailer.
    state["close_wrote"] = len(sink.data) - size
    state["closed_after_close"] = f.closed
    return state


CASES = [("binary", "writelines"), ("text", "writelines"), ("binary", "seek")]


@pytest.mark.parametrize(("kind", "composite"), CASES)
@pytest.mark.parametrize("cancels", [1, 2])
async def test_cancellation_at_the_checkpoint_breaks_the_writer(
    kind, composite, cancels
):
    sink = _ReadySink()
    f = await _open(kind, sink, chunk_size=1024)
    task = await _park_at_checkpoint(f, sink, _composite(kind, f, composite))
    for _ in range(cancels):
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Exactly the writes before the checkpoint were accepted: 256 of them.
    accepted = await f.tell()
    if composite == "seek":
        assert accepted == _INLINE_WRITES_CHECKPOINT * ZERO_CHUNK
        expected = bytes(accepted)
    else:
        assert accepted == _INLINE_WRITES_CHECKPOINT * 1000
        expected = PAYLOAD[:accepted]
    calls = sink.calls
    await asyncio.sleep(0)
    assert sink.calls == calls, "the composite wrote after its cancellation"
    decoded = _decoded_prefix(sink)
    assert decoded == expected[: len(decoded)]

    state = await _broken_state(kind, f, sink)
    assert state["broken"] is True
    assert state["binary_call_active"] is False
    assert state["text_call_active"] is False
    assert state["close_wrote"] == 0
    assert all("write stream is broken" in message for message in state["refusals"])


@pytest.mark.parametrize(("kind", "composite"), CASES)
async def test_cancellation_at_the_checkpoint_matches_a_cancelled_sink_write(
    kind, composite
):
    # The rule being matched: a cancellation during a suspended sink write
    # between two lines or blocks of the same composite.
    # The sink's first write is the header; its second is mid-composite.
    gated = _GatedSink(block_at=2)
    reference = await _open(kind, gated, chunk_size=1024)
    blocked = asyncio.ensure_future(_composite(kind, reference, composite))
    await asyncio.wait_for(gated.entered.wait(), 5)
    reference_position = _binary(reference)._position
    blocked.cancel()
    with pytest.raises(asyncio.CancelledError):
        await blocked
    assert _binary(reference)._position == reference_position
    expected = await _broken_state(kind, reference, gated)

    sink = _ReadySink()
    f = await _open(kind, sink, chunk_size=1024)
    task = await _park_at_checkpoint(f, sink, _composite(kind, f, composite))
    position = _binary(f)._position
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _binary(f)._position == position
    assert await _broken_state(kind, f, sink) == expected


@pytest.mark.parametrize("kind", ["binary", "text"])
async def test_lines_after_a_cancelled_checkpoint_are_not_consumed(kind):
    consumed = 0

    def produce():
        nonlocal consumed
        for line in _lines(kind):
            consumed += 1
            yield line

    sink = _ReadySink()
    f = await _open(kind, sink, chunk_size=1024)
    task = await _park_at_checkpoint(f, sink, f.writelines(produce()))
    seen = consumed
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert consumed == seen
    # 256 batches of ten lines were written. The 257th batch and the line
    # that did not fit in it were read from the iterable but not written, as
    # when a sink write for that batch is cancelled.
    accepted = _INLINE_WRITES_CHECKPOINT * 10
    assert await f.tell() == accepted * len(LINE)
    assert seen == accepted + 11
    await f.close()


# Context exit and overlap while parked at the checkpoint


@pytest.mark.parametrize(("kind", "composite"), CASES)
async def test_exceptional_exit_at_the_checkpoint_aborts_the_composite(kind, composite):
    sink = _ReadySink()
    f = _make(kind, sink, chunk_size=1024, closefd=True)
    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with f:
            task = await _park_at_checkpoint(f, sink, _composite(kind, f, composite))
            raise RuntimeError("body")
    assert f.closed and sink.closed
    size = len(sink.data)
    with pytest.raises(OSError, match="write aborted because the gzip file was closed"):
        await task
    # _ReadySink.write() asserts that nothing is written after close.
    assert len(sink.data) == size
    assert _binary(f)._write_broken is True
    assert _binary(f)._write_call_active is False


@pytest.mark.parametrize(("kind", "composite"), CASES)
async def test_clean_exit_at_the_checkpoint_waits_for_the_composite(kind, composite):
    sink = _ReadySink()
    f = _make(kind, sink, chunk_size=1024, closefd=True)
    async with f:
        task = await _park_at_checkpoint(f, sink, _composite(kind, f, composite))
    assert task.done() and task.exception() is None
    assert sink.closed
    expected = bytes(SEEK_SIZE) if composite == "seek" else PAYLOAD
    assert gzip.decompress(bytes(sink.data)) == expected


@pytest.mark.parametrize(("kind", "composite"), CASES)
async def test_overlapping_calls_at_the_checkpoint_are_rejected(kind, composite):
    sink = _ReadySink()
    f = await _open(kind, sink, chunk_size=1024)
    task = await _park_at_checkpoint(f, sink, _composite(kind, f, composite))
    for call in (
        lambda: f.write(_one(kind)),
        lambda: f.writelines([_one(kind)]),
        f.flush,
        f.close,
    ):
        with pytest.raises(ConcurrentOperationError):
            await call()
    await task
    await f.close()
    expected = bytes(SEEK_SIZE) if composite == "seek" else PAYLOAD
    assert gzip.decompress(bytes(sink.data)) == expected
