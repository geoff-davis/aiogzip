"""R03: inspect() and verify() settle their own native open, reads and close.

The scanner used to await ``aiofiles.open()`` and native ``read()``/``close()``
directly. Cancelling the caller then abandoned the executor job: a late open
left a file nobody closed, and cleanup closed the source while a worker was
still reading it. Native work is now settled before cancellation propagates,
as for the file handles (BC1, BC3, BC9); borrowed sources keep their
ownership rules.
"""

import asyncio
import concurrent.futures
import functools
import gzip
import threading

import aiofiles
import pytest

import aiogzip

PAYLOAD = b"inspection settlement\n" * 4000
OPERATIONS = [aiogzip.inspect, aiogzip.verify]


class _GatedExecutor(concurrent.futures.ThreadPoolExecutor):
    """Default executor that parks the next submission of a named function.

    Every submission is logged by name and target, with its start, end and
    error, so tests can check that cleanup waited for the worker's last
    access.
    """

    def __init__(self, loop):
        super().__init__(max_workers=4)
        self.loop = loop
        self.gate: str | None = None
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.log: list[tuple[str, str, object]] = []
        self.idle = threading.Condition(self.lock)
        self.running = 0

    def _record(self, *entry):
        with self.lock:
            self.log.append(entry)

    def submit(self, fn, /, *args, **kwargs):
        target = fn.func if isinstance(fn, functools.partial) else fn
        name = getattr(target, "__name__", "")
        owner = getattr(target, "__self__", None)
        park = self.gate == name
        if park:
            self.gate = None

        def run():
            with self.lock:
                self.running += 1
            try:
                if park:
                    self.loop.call_soon_threadsafe(self.entered.set)
                    if not self.release.wait(10):
                        raise TimeoutError("gate never released")
                self._record("start", name, owner)
                try:
                    result = fn(*args, **kwargs)
                except BaseException as error:
                    self._record("error", name, error)
                    raise
                self._record("end", name, result if name == "open" else owner)
                return result
            finally:
                with self.lock:
                    self.running -= 1
                    self.idle.notify_all()

        return super().submit(run)

    def wait_idle(self):
        with self.idle:
            assert self.idle.wait_for(lambda: self.running == 0, 10)

    def entries(self, kind, name):
        with self.lock:
            return [value for k, n, value in self.log if (k, n) == (kind, name)]


@pytest.fixture
async def gated():
    loop = asyncio.get_running_loop()
    executor = _GatedExecutor(loop)
    loop.set_default_executor(executor)
    yield executor
    executor.release.set()


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "data.gz"
    target.write_bytes(gzip.compress(PAYLOAD, mtime=0))
    return target


async def _cancel_parked(gated, coroutine, cancels):
    task = asyncio.create_task(coroutine)
    await asyncio.wait_for(gated.entered.wait(), 10)
    for _ in range(cancels):
        task.cancel()
        await asyncio.sleep(0.01)
    # Settlement keeps the task waiting for the parked worker.
    assert not task.done()
    gated.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    return task


def _closed_after_last_read(gated, source):
    """The source was closed once, after its last read finished cleanly."""
    with gated.lock:
        log = list(gated.log)
    closes = [
        i for i, (k, n, v) in enumerate(log) if (k, n, v) == ("start", "close", source)
    ]
    reads = [i for i, (k, n, v) in enumerate(log) if n == "read" and v is source]
    assert len(closes) == 1, log
    assert not [e for k, n, e in log if k == "error"], log
    assert all(i < closes[0] for i in reads), log


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("cancels", [1, 3])
async def test_cancelled_open_closes_the_late_file_once(
    path, gated, operation, cancels
):
    gated.gate = "open"
    await _cancel_parked(gated, operation(path), cancels)
    gated.wait_idle()
    (raw,) = gated.entries("end", "open")
    assert raw.closed
    assert gated.entries("start", "close") == [raw]
    assert gated.entries("start", "read") == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("cancels", [1, 3])
async def test_cancelled_read_closes_only_after_the_worker(
    path, gated, operation, cancels
):
    gated.gate = "read"
    await _cancel_parked(gated, operation(path), cancels)
    gated.wait_idle()
    (raw,) = gated.entries("end", "open")
    assert raw.closed
    _closed_after_last_read(gated, raw)


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_cancelled_close_finishes_before_the_caller_resumes(
    path, gated, operation
):
    gated.gate = "close"
    task = await _cancel_parked(gated, operation(path), 1)
    assert task.cancelled()
    (raw,) = gated.entries("end", "open")
    # The caller resumed only after the native close returned.
    assert gated.entries("end", "close") == [raw]
    assert raw.closed


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("closefd", [False, True])
async def test_cancelled_read_of_a_borrowed_native_source(
    path, gated, operation, closefd
):
    async with aiofiles.open(path, "rb") as source:
        raw = source._file
        gated.gate = "read"
        await _cancel_parked(gated, operation(None, fileobj=source, closefd=closefd), 1)
        gated.wait_idle()
        if closefd:
            assert raw.closed
            _closed_after_last_read(gated, raw)
        else:
            # A borrowed source stays open and is never closed by the scan.
            assert not raw.closed
            assert gated.entries("start", "close") == []
            assert not gated.entries("error", "read")


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_uncancelled_scan_still_succeeds(path, gated, operation):
    result = await operation(path)
    assert result.uncompressed_size == len(PAYLOAD)
    gated.wait_idle()
    (raw,) = gated.entries("end", "open")
    assert raw.closed
    _closed_after_last_read(gated, raw)
