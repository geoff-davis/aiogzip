"""WP0 package reproductions; strict xfails are removed with their repairs.

These test desired invariants, not golden acceptance of unsafe historical behavior.
Only test-owned tasks are cancelled. Native gates always have a watchdog and cleanup.
"""

import asyncio
import gzip
import io
import random
import threading

import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
    _binary,
    _codec_async,
    compress_chunks,
    decompress_chunks,
)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F1: cancelled helper hides live native work",
)
async def test_native_cleanup_follows_final_worker_access(monkeypatch):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    settled = threading.Event()
    helpers = []
    events = []
    original = _codec_async._run_in_thread

    async def observed_worker(method, data):
        helpers.append(asyncio.current_task())
        return await original(method, data)

    class Operation:
        def _advance_raw(self):
            loop.call_soon_threadsafe(entered.set)
            try:
                if not release.wait(5):
                    raise RuntimeError("native gate watchdog expired")
                events.append("last native access")
                return b"output"
            finally:
                settled.set()

        def close(self):
            events.append("cleanup")

    monkeypatch.setattr(_codec_async, "_run_in_thread", observed_worker)
    stream = _codec_async._drive_operation(
        Operation(), workload=b"x", offload_threshold=1
    )
    caller = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        caller.cancel()
        helpers[0].cancel()
        # A callback barrier lets cancellation propagate without wall-clock sleeps.
        for _ in range(8):
            await asyncio.sleep(0)
        premature = "cleanup" in events
    finally:
        release.set()
        await asyncio.gather(caller, *helpers, return_exceptions=True)
        assert await asyncio.to_thread(settled.wait, 5)
        await stream.aclose()
    assert not premature, events
    assert events == ["last native access", "cleanup"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F2: consumed member A can disappear on cancel",
)
async def test_consumed_member_cannot_be_replaced_by_successful_suffix():
    consumed = asyncio.Event()
    release = asyncio.Event()
    a, b = b"member A\n", b"member B\n"

    class Source:
        def __init__(self):
            self.members = [gzip.compress(a, mtime=0), gzip.compress(b, mtime=0)]

        async def read(self, size=-1):
            if not self.members:
                return b""
            chunk = self.members.pop(0)
            if len(self.members) == 1:
                consumed.set()
                await release.wait()
            return chunk

    async with AsyncGzipBinaryFile(None, "rb", fileobj=Source(), closefd=False) as f:
        caller = asyncio.create_task(f.read())
        try:
            await asyncio.wait_for(consumed.wait(), 5)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
        finally:
            release.set()
            await asyncio.gather(caller, return_exceptions=True)
        try:
            result = await f.read()
        except OSError:
            return  # Terminal failure is an allowed conservative correction.
        assert result == a + b, f"accepted suffix-only stream: {result!r}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F3: overlapping opens acquire two resources",
)
async def test_overlapping_open_has_one_resource_owner(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    acquired = []

    class Resource:
        def __init__(self):
            self.closes = 0

        async def seekable(self):
            return False

        async def close(self):
            self.closes += 1

    async def acquire(*args, **kwargs):
        resource = Resource()
        acquired.append(resource)
        entered.set()
        await release.wait()
        return resource

    monkeypatch.setattr(_binary.aiofiles, "open", acquire)
    f = AsyncGzipBinaryFile("unused.gz", "rb")
    first = asyncio.create_task(f.open())
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        second = asyncio.create_task(f.open())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await f.close()
        counts = [resource.closes for resource in acquired]
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )
        await f.close()
        # Close the baseline's orphan explicitly; do not leak a test resource.
        for resource in acquired:
            if not resource.closes:
                await resource.close()
    assert len(acquired) == 1 and counts == [1], counts


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F4: every tiny hint copies the pending suffix",
)
async def test_pending_batch_drain_has_linear_copy_work(tmp_path):
    class CountedBatch(list):
        copied = 0
        visited = 0

        def __getitem__(self, key):
            result = super().__getitem__(key)
            if isinstance(key, slice):
                self.copied += len(result)
            else:
                self.visited += 1
            return result

    count = 2048
    path = tmp_path / "lines.gz"
    path.write_bytes(gzip.compress(b"x\n" * count, mtime=0))
    async with AsyncGzipTextFile(path, "rt", newline="\n") as f:
        assert await f.readlines(1) == ["x\n"]
        assert await f.readlines(1) == ["x\n"]  # Split the buffered remainder.
        pending = CountedBatch(f._pending_lines)
        f._pending_lines = pending
        assert len(pending) >= count - 1  # Ensure the intended batch is exercised.
        for _ in range(count - 2):
            assert await f.readlines(1) == ["x\n"]
        assert await f.readlines(1) == []
        # Count suffix-copy elements plus indexed visits. O(N+B), B=N here;
        # four units per line allows one selected slice and one bounded scan.
        assert pending.copied + pending.visited <= 4 * count


@pytest.mark.parametrize("wrapper", [compress_chunks, decompress_chunks])
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F7: empty ready items bypass checkpoints",
)
async def test_empty_source_allows_sibling_progress_before_exhaustion(wrapper):
    ticks = 0
    ticks_before_last = None
    stop = False

    async def ticker():
        nonlocal ticks
        while not stop:
            ticks += 1
            await asyncio.sleep(0)

    async def source():
        nonlocal ticks_before_last
        for _ in range(20_000):
            yield b""
        ticks_before_last = ticks
        yield (
            gzip.compress(b"payload", mtime=0)
            if wrapper is decompress_chunks
            else b"payload"
        )

    sibling = asyncio.create_task(ticker())
    try:
        output = b"".join([chunk async for chunk in wrapper(source())])
    finally:
        stop = True
        await sibling
    assert (
        output if wrapper is decompress_chunks else gzip.decompress(output)
    ) == b"payload"
    assert ticks_before_last is not None and ticks_before_last > 0


@pytest.mark.parametrize("compressible", [True, False])
async def test_partial_read_preserves_data_across_compression_ratios(compressible):
    """Gate public data correctness; read-ahead belongs in measured diagnostics."""
    payload = (
        b"x" * (16 * 1024 * 1024)
        if compressible
        else random.Random(0).randbytes(2 * AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE)
    )
    wire = gzip.compress(payload, mtime=0)
    if compressible:
        assert len(wire) < AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE
    else:
        assert len(wire) > AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE

    class Source:
        def __init__(self):
            self.data = io.BytesIO(wire)

        async def read(self, size=-1):
            chunk = self.data.read(size)
            return chunk

    source = Source()
    async with AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=False) as f:
        assert await f.read(1) == payload[:1]
        assert await f.read() == payload[1:]
