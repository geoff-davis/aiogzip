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
from aiogzip._source_io import _NativeSourceCall

PAYLOAD = b"inspection settlement\n" * 4000
OPERATIONS = [aiogzip.inspect, aiogzip.verify]


class _GatedExecutor(concurrent.futures.ThreadPoolExecutor):
    """Default executor that parks the next submission of a named function.

    ``gate`` parks it inside the source access; ``hold`` parks it while still
    queued, before a settled native call's entry guard. Every submission is logged by name and target, with its start, end and
    error, so tests can check that cleanup waited for the worker's last
    access. ``fail`` makes the next submission of a name raise instead of
    running.
    """

    def __init__(self, loop):
        super().__init__(max_workers=4)
        self.loop = loop
        self.gate: str | None = None
        self.hold: str | None = None
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.log: list[tuple[str, str, object]] = []
        self.idle = threading.Condition(self.lock)
        self.running = 0
        self.fail: dict[str, BaseException] = {}

    def _record(self, *entry):
        with self.lock:
            self.log.append(entry)

    def submit(self, fn, /, *args, **kwargs):
        target = fn.func if isinstance(fn, functools.partial) else fn
        native = isinstance(target, _NativeSourceCall)
        if native:
            name, owner = target.method, target.source
        else:
            name = getattr(target, "__name__", "")
            owner = getattr(target, "__self__", None)
        park = self.gate == name
        if park:
            self.gate = None
        hold = self.hold == name
        if hold:
            self.hold = None
        injected = self.fail.pop(name, None)

        def access(call):
            # The gated, logged source access itself.
            if park:
                self.loop.call_soon_threadsafe(self.entered.set)
                if not self.release.wait(10):
                    raise TimeoutError("gate never released")
            self._record("start", name, owner)
            try:
                if injected is not None:
                    raise injected
                result = call()
            except BaseException as error:
                self._record("error", name, error)
                raise
            self._record("end", name, result if name == "open" else owner)
            return result

        if native:
            # A settled native call guards entry itself; gate and log inside
            # that guard, at the moment the source is actually touched.
            method = getattr(owner, name)
            target.source = _Access(owner, name, lambda *a: access(lambda: method(*a)))

            def body():
                return fn(*args, **kwargs)

        else:

            def body():
                return access(lambda: fn(*args, **kwargs))

        def run():
            with self.lock:
                self.running += 1
            try:
                if hold:
                    # Queued: parked before the call's entry guard.
                    self.loop.call_soon_threadsafe(self.entered.set)
                    if not self.release.wait(10):
                        raise TimeoutError("hold never released")
                return body()
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


class _Access:
    """Stand-in source whose ``name`` method is the gated access."""

    def __init__(self, source, name, method):
        self._source = source
        setattr(self, name, method)

    def __getattr__(self, attribute):
        return getattr(self._source, attribute)


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
    """Cancel a scan parked in the executor; return the exception it raised."""
    raised = []

    async def scan():
        try:
            return await coroutine
        except BaseException as error:
            raised.append(error)
            raise

    task = asyncio.create_task(scan())
    await asyncio.wait_for(gated.entered.wait(), 10)
    for _ in range(cancels):
        task.cancel()
        await asyncio.sleep(0.01)
    # Settlement keeps the task waiting for the parked worker.
    assert not task.done()
    gated.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    (error,) = raised
    return error


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
    error = await _cancel_parked(gated, operation(path), 1)
    assert isinstance(error, asyncio.CancelledError)
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


async def _cancel_queued(gated, coroutine, cancels):
    """Cancel a scan whose read is still queued; it must not wait for it."""
    task = asyncio.create_task(coroutine)
    try:
        await asyncio.wait_for(gated.entered.wait(), 10)
        for _ in range(cancels):
            task.cancel()
            await asyncio.sleep(0)
        # Well inside the parked worker's 10 s watchdog: a scan that waits for
        # the queued read times out here while the worker is still parked.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), 2)
        # The scan finished while its worker was still parked before entry.
        with gated.lock:
            assert gated.running == 1
    finally:
        # Never leave the worker parked, so a failure here cannot hang teardown.
        gated.release.set()
        await asyncio.gather(task, return_exceptions=True)
    gated.wait_idle()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("cancels", [1, 3])
async def test_cancelled_queued_read_never_touches_the_source(
    path, gated, operation, cancels
):
    gated.hold = "read"
    await _cancel_queued(gated, operation(path), cancels)
    (raw,) = gated.entries("end", "open")
    assert raw.closed
    # The prevented read never ran, before or after the close.
    assert gated.entries("start", "read") == []
    assert gated.entries("start", "close") == [raw]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("closefd", [False, True])
async def test_cancelled_queued_read_of_a_borrowed_native_source(
    path, gated, operation, closefd
):
    async with aiofiles.open(path, "rb") as source:
        raw = source._file
        gated.hold = "read"
        await _cancel_queued(gated, operation(None, fileobj=source, closefd=closefd), 1)
        assert gated.entries("start", "read") == []
        assert raw.closed is closefd
        if not closefd:
            # The borrowed cursor did not move: the prevented read never ran.
            assert raw.tell() == 0


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_uncancelled_scan_still_succeeds(path, gated, operation):
    result = await operation(path)
    assert result.uncompressed_size == len(PAYLOAD)
    gated.wait_idle()
    (raw,) = gated.entries("end", "open")
    assert raw.closed
    _closed_after_last_read(gated, raw)


@pytest.fixture
def corrupt(tmp_path):
    target = tmp_path / "corrupt.gz"
    data = bytearray(gzip.compress(PAYLOAD, mtime=0))
    data[-8] ^= 0xFF  # CRC mismatch, detected only at the end of the scan
    target.write_bytes(bytes(data))
    return target


def _only_close(gated):
    (raw,) = gated.entries("end", "open")
    assert gated.entries("start", "close") == [raw]
    return raw


class TestCleanupPrecedence:
    """An outside cancellation outranks an ordinary scan failure (BC14)."""

    @pytest.mark.parametrize("operation", OPERATIONS)
    @pytest.mark.parametrize("cancels", [1, 3])
    async def test_cancelled_close_after_corruption_propagates_cancellation(
        self, corrupt, gated, operation, cancels
    ):
        gated.gate = "close"
        error = await _cancel_parked(gated, operation(corrupt), cancels)
        assert isinstance(error, asyncio.CancelledError)
        assert isinstance(error.__context__, gzip.BadGzipFile)
        gated.wait_idle()
        assert _only_close(gated).closed

    @pytest.mark.parametrize("operation", OPERATIONS)
    async def test_cancelled_close_after_a_read_failure_propagates_cancellation(
        self, path, gated, operation
    ):
        failure = OSError("injected read failure")
        gated.fail["read"] = failure
        gated.gate = "close"
        error = await _cancel_parked(gated, operation(path), 1)
        assert isinstance(error, asyncio.CancelledError)
        assert error.__context__ is failure
        gated.wait_idle()
        assert _only_close(gated).closed

    @pytest.mark.parametrize("operation", OPERATIONS)
    async def test_failing_close_after_corruption_keeps_the_corruption(
        self, corrupt, gated, operation
    ):
        gated.fail["close"] = OSError("injected close failure")
        with pytest.raises(gzip.BadGzipFile) as caught:
            await operation(corrupt)
        notes = getattr(caught.value, "__notes__", [])
        assert any("injected close failure" in note for note in notes), notes
        gated.wait_idle()
        _only_close(gated).close()

    @pytest.mark.parametrize("operation", OPERATIONS)
    async def test_failing_close_after_a_clean_scan_raises(
        self, path, gated, operation
    ):
        failure = OSError("injected close failure")
        gated.fail["close"] = failure
        with pytest.raises(OSError) as caught:
            await operation(path)
        assert caught.value is failure
        gated.wait_idle()
        _only_close(gated).close()

    @pytest.mark.parametrize("operation", OPERATIONS)
    async def test_cancelled_read_keeps_cancellation_when_close_fails(
        self, path, gated, operation
    ):
        gated.fail["close"] = OSError("injected close failure")
        gated.gate = "read"
        error = await _cancel_parked(gated, operation(path), 1)
        notes = getattr(error, "__notes__", [])
        assert any("injected close failure" in note for note in notes), notes
        gated.wait_idle()
        _only_close(gated).close()

    @pytest.mark.parametrize("operation", OPERATIONS)
    @pytest.mark.parametrize("cancels", [1, 3])
    async def test_cancelled_close_whose_worker_fails(
        self, path, gated, operation, cancels
    ):
        failure = OSError("injected close failure")
        gated.fail["close"] = failure
        gated.gate = "close"
        error = await _cancel_parked(gated, operation(path), cancels)
        # The cancellation propagates, caused by the settled worker failure.
        assert isinstance(error, asyncio.CancelledError)
        assert error.__cause__ is failure
        gated.wait_idle()
        _only_close(gated).close()

    @pytest.mark.parametrize("operation", OPERATIONS)
    @pytest.mark.parametrize("cancels", [1, 3])
    async def test_cancelled_read_whose_worker_fails(
        self, path, gated, operation, cancels
    ):
        failure = OSError("injected read failure")
        gated.fail["read"] = failure
        gated.gate = "read"
        error = await _cancel_parked(gated, operation(path), cancels)
        # The cancellation propagates, caused by the settled worker failure.
        assert isinstance(error, asyncio.CancelledError)
        assert error.__cause__ is failure
        gated.wait_idle()
        assert _only_close(gated).closed


async def _open_in_another_loop(target):
    return await aiofiles.open(target, "rb")


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("closefd", [False, True])
async def test_borrowed_source_from_another_loop_is_refused(
    path, gated, operation, closefd
):
    source = await asyncio.to_thread(asyncio.run, _open_in_another_loop(path))
    try:
        with pytest.raises(OSError, match="Error reading from file") as caught:
            await operation(None, fileobj=source, closefd=closefd)
        assert isinstance(caught.value.__cause__, RuntimeError)
        if closefd:
            # The refused close is noted; the loop check is never bypassed.
            notes = getattr(caught.value, "__notes__", [])
            assert any("different event loop" in note for note in notes), notes
        gated.wait_idle()
        assert gated.entries("start", "read") == []
        assert gated.entries("start", "close") == []
    finally:
        source._file.close()
