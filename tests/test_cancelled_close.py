"""R15: a cancelled close settles the owned native close (BC13).

aiofiles' ``close()`` is an executor job, and asyncio cancels a job that is
still queued when its awaiting task is cancelled. A cancelled ``close()`` or
context exit could therefore latch the handle closed while the file was never
closed. The owned native close now runs through the same settlement as every
other native call: it is never prevented, and cancellation propagates only
after it has finished, with a close failure as its cause.
"""

import asyncio
import concurrent.futures
import functools
import gzip
import io
import os
import threading

import aiofiles
import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile
from aiogzip._source_io import _NativeSourceCall

PAYLOAD = b"cancelled close\n" * 4000
KINDS = ["binary", "text"]
MODES = ["r", "w"]
SOURCES = ["path", "closefd", "borrowed"]
STAGES = ["queued", "running"]


class _Gate:
    def __init__(self, stage):
        self.stage = stage
        self.entered = asyncio.Event()
        self.release = threading.Event()


class _CloseExecutor(concurrent.futures.ThreadPoolExecutor):
    """One-worker default executor that can hold a named call.

    A ``queued`` gate parks a blocker on the only worker just before the named
    call is submitted, so the call waits in the queue, where asyncio could
    cancel it. A ``running`` gate parks the call inside its worker; a native
    read, write or seek parked there has not entered the file yet, so
    cancellation may still prevent it (an aiofiles close is never prevented).
    Every call
    is logged by name and target; ``fail`` injects a one-shot failure (a close
    still runs first, as a buffered close that fails on flush does), and
    ``fail_before`` raises without running the call, leaving a file open.
    """

    def __init__(self, loop):
        super().__init__(max_workers=1)
        self.loop = loop
        self.gates: dict[str, _Gate] = {}
        self.armed: list[_Gate] = []
        self.fail: dict[str, BaseException] = {}
        self.fail_before: dict[str, BaseException] = {}
        self.lock = threading.Lock()
        self.idle = threading.Condition(self.lock)
        self.running = 0
        self.log: list[tuple[str, str, object]] = []

    def arm(self, name, stage="running"):
        gate = _Gate(stage)
        self.gates[name] = gate
        self.armed.append(gate)
        return gate

    def _hold(self, gate):
        self.loop.call_soon_threadsafe(gate.entered.set)
        if not gate.release.wait(10):
            raise TimeoutError("gate never released")

    def _tracked(self, body):
        def run():
            with self.lock:
                self.running += 1
            try:
                return body()
            finally:
                with self.lock:
                    self.running -= 1
                    self.idle.notify_all()

        return run

    def submit(self, fn, /, *args, **kwargs):
        target = fn.func if isinstance(fn, functools.partial) else fn
        if isinstance(target, _NativeSourceCall):
            name, owner = target.method, target.source
        else:
            name = getattr(target, "__name__", "")
            owner = getattr(target, "__self__", None)
        gate = self.gates.pop(name, None)
        failure = self.fail.pop(name, None)
        early = self.fail_before.pop(name, None)
        if gate is not None and gate.stage == "queued":
            super().submit(self._tracked(functools.partial(self._hold, gate)))

        def call():
            if gate is not None and gate.stage == "running":
                self._hold(gate)
            with self.lock:
                self.log.append(("start", name, owner))
            try:
                if early is not None:
                    raise early
                if failure is not None and name != "close":
                    raise failure
                result = fn(*args, **kwargs)
                if failure is not None:
                    raise failure
            except BaseException as error:
                with self.lock:
                    self.log.append(("error", name, error))
                raise
            with self.lock:
                self.log.append(("end", name, owner))
            return result

        return super().submit(self._tracked(call))

    def release_all(self):
        for gate in self.armed:
            gate.release.set()

    def wait_idle(self):
        with self.idle:
            assert self.idle.wait_for(lambda: self.running == 0, 10)

    def entries(self, kind, name):
        with self.lock:
            return [value for k, n, value in self.log if (k, n) == (kind, name)]

    def index(self, kind, name):
        with self.lock:
            return [i for i, (k, n, _) in enumerate(self.log) if (k, n) == (kind, name)]


@pytest.fixture
async def executor():
    loop = asyncio.get_running_loop()
    pool = _CloseExecutor(loop)
    loop.set_default_executor(pool)
    yield pool
    pool.release_all()


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "data.gz"
    target.write_bytes(gzip.compress(PAYLOAD, mtime=0))
    return target


class _Opened:
    """A handle with its raw file and whether the handle owns its close."""

    def __init__(self, handle, raw, owned, borrowed):
        self.handle = handle
        self.raw = raw
        self.owned = owned
        self.borrowed = borrowed

    @property
    def binary(self):
        return getattr(self.handle, "_binary_file", self.handle)


async def _open(kind, mode, source, path, *, enter=True):
    file_mode = mode + ("b" if kind == "binary" else "t")
    cls = AsyncGzipBinaryFile if kind == "binary" else AsyncGzipTextFile
    borrowed = None
    if source == "path":
        handle = cls(path, file_mode)
    else:
        borrowed = await aiofiles.open(path, mode + "b")
        handle = cls(None, file_mode, fileobj=borrowed, closefd=source == "closefd")
    if enter:
        await handle.__aenter__()
    binary = getattr(handle, "_binary_file", handle)
    raw = binary._file._file if enter else (borrowed._file if borrowed else None)
    return _Opened(handle, raw, source != "borrowed", borrowed)


async def _use(opened, kind, mode):
    if mode == "r":
        await opened.handle.read(10)
    else:
        await opened.handle.write(b"abc" if kind == "binary" else "abc")


async def _finish(opened, via):
    if via == "close":
        await opened.handle.close()
    elif via == "clean-exit":
        await opened.handle.__aexit__(None, None, None)
    else:
        error = KeyError("body")
        await opened.handle.__aexit__(KeyError, error, None)


async def _cancel_held(task, gate, cancels):
    await asyncio.wait_for(gate.entered.wait(), 10)
    for _ in range(cancels):
        task.cancel()
        await asyncio.sleep(0.01)
    # Settlement keeps the task waiting for the held native close.
    assert not task.done()
    gate.release.set()
    try:
        await task
    except BaseException as error:
        return error
    return None


def _close_borrowed(opened):
    if opened.borrowed is not None and not opened.borrowed._file.closed:
        opened.borrowed._file.close()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("via", ["close", "clean-exit", "error-exit"])
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("cancels", [1, 3])
@pytest.mark.parametrize("source", ["path", "closefd"])
async def test_cancelled_close_settles_the_owned_native_close(
    path, executor, kind, mode, via, stage, cancels, source
):
    opened = await _open(kind, mode, source, path)
    await _use(opened, kind, mode)
    gate = executor.arm("close", stage)
    task = asyncio.create_task(_finish(opened, via))
    if stage == "queued":
        await asyncio.wait_for(gate.entered.wait(), 10)
        assert executor.entries("start", "close") == []
    error = await _cancel_held(task, gate, cancels)
    assert isinstance(error, asyncio.CancelledError)
    assert error.__cause__ is None
    # The caller resumed only after the one native close returned.
    assert executor.entries("end", "close") == [opened.raw]
    assert opened.raw.closed
    assert opened.handle.closed
    # A closed handle never closes again.
    await opened.handle.close()
    executor.wait_idle()
    assert executor.entries("start", "close") == [opened.raw]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("via", ["close", "clean-exit", "error-exit"])
async def test_cancelled_close_leaves_a_borrowed_file_open(
    path, executor, kind, mode, via
):
    opened = await _open(kind, mode, "borrowed", path)
    try:
        await _use(opened, kind, mode)
        task = asyncio.create_task(_finish(opened, via))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        executor.wait_idle()
        assert opened.handle.closed
        assert executor.entries("start", "close") == []
        assert not opened.raw.closed
    finally:
        _close_borrowed(opened)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", MODES)
async def test_uncancelled_close_closes_once(path, executor, kind, mode):
    opened = await _open(kind, mode, "path", path)
    await _use(opened, kind, mode)
    await opened.handle.close()
    await opened.handle.close()
    executor.wait_idle()
    assert executor.entries("end", "close") == [opened.raw]
    assert opened.raw.closed


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("cancels", [1, 3])
async def test_cancelled_trailer_write_still_settles_the_close(
    path, executor, kind, cancels
):
    opened = await _open(kind, "w", "path", path)
    await _use(opened, kind, "w")
    gate = executor.arm("write", "running")
    task = asyncio.create_task(opened.handle.close())
    error = await _cancel_held(task, gate, cancels)
    assert isinstance(error, asyncio.CancelledError)
    executor.wait_idle()
    write_end = executor.index("end", "write")
    close_start = executor.index("start", "close")
    assert len(close_start) == 1 and write_end and write_end[-1] < close_start[0]
    assert executor.entries("end", "close") == [opened.raw]
    assert opened.raw.closed
    assert opened.handle.closed


@pytest.mark.parametrize("kind", KINDS)
async def test_cancelled_flush_then_close_closes_once(path, executor, kind):
    opened = await _open(kind, "w", "path", path)
    await _use(opened, kind, "w")
    gate = executor.arm("write", "running")
    task = asyncio.create_task(opened.handle.flush())
    await asyncio.wait_for(gate.entered.wait(), 10)
    task.cancel()
    # The held sink write has not entered the file, so cancellation prevents
    # it outright rather than waiting.
    assert isinstance(await _outcome(task), asyncio.CancelledError)
    gate.release.set()
    # The cancelled flush breaks the writer. close() releases the file once
    # and never gives the torn member a seemingly valid trailer.
    assert opened.binary._write_broken
    await opened.handle.close()
    with pytest.raises(EOFError):
        gzip.decompress(path.read_bytes())
    executor.wait_idle()
    assert executor.entries("end", "close") == [opened.raw]
    assert opened.raw.closed
    assert opened.handle.closed


class TestFailingNativeClose:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("mode", MODES)
    async def test_failing_close_raises_its_error(self, path, executor, kind, mode):
        opened = await _open(kind, mode, "path", path)
        await _use(opened, kind, mode)
        failure = OSError("injected close failure")
        executor.fail["close"] = failure
        with pytest.raises(OSError) as caught:
            await opened.handle.close()
        assert caught.value is failure
        executor.wait_idle()
        assert executor.entries("start", "close") == [opened.raw]
        assert opened.raw.closed
        assert opened.handle.closed

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("cancels", [1, 3])
    async def test_cancelled_failing_close_is_the_cause(
        self, path, executor, kind, mode, stage, cancels
    ):
        opened = await _open(kind, mode, "path", path)
        await _use(opened, kind, mode)
        failure = OSError("injected close failure")
        executor.fail["close"] = failure
        gate = executor.arm("close", stage)
        task = asyncio.create_task(opened.handle.close())
        error = await _cancel_held(task, gate, cancels)
        assert isinstance(error, asyncio.CancelledError)
        assert error.__cause__ is failure
        executor.wait_idle()
        assert executor.entries("start", "close") == [opened.raw]
        assert opened.raw.closed
        assert opened.handle.closed


async def _start_abort(opened, executor, name, call):
    """Hold an active native call, then exit the context exceptionally."""
    held = executor.arm(name, "running")
    active = asyncio.create_task(call)
    await asyncio.wait_for(held.entered.wait(), 10)
    close_gate = executor.arm("close", "queued")
    error = KeyError("body")
    exiting = asyncio.create_task(opened.handle.__aexit__(KeyError, error, None))
    await asyncio.sleep(0.01)
    # The abort waits for the active call before closing (BC8).
    assert executor.entries("start", "close") == []
    held.release.set()
    return active, exiting, close_gate


async def _outcome(task):
    try:
        return await task
    except BaseException as error:
        return error


class TestAbortClose:
    """Exceptional exit during an active call closes through the abort path."""

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("cancels", [1, 3])
    async def test_cancelled_abort_close_after_an_active_read(
        self, path, executor, kind, cancels
    ):
        opened = await _open(kind, "r", "path", path)
        active, exiting, gate = await _start_abort(
            opened, executor, "read", opened.handle.read()
        )
        error = await _cancel_held(exiting, gate, cancels)
        assert isinstance(error, asyncio.CancelledError)
        assert isinstance(await _outcome(active), OSError)
        executor.wait_idle()
        read_end = executor.index("end", "read")
        close_start = executor.index("start", "close")
        assert len(close_start) == 1 and read_end[-1] < close_start[0]
        assert opened.raw.closed
        # The settled close succeeded, so the handle latches closed and a
        # retry has nothing left to close.
        assert opened.handle.closed
        await opened.handle.close()
        assert executor.entries("start", "close") == [opened.raw]
        assert opened.binary._read_health.name == "BROKEN"

    @pytest.mark.parametrize("kind", KINDS)
    async def test_cancelled_abort_close_after_an_active_write(
        self, path, executor, kind
    ):
        opened = await _open(kind, "w", "path", path)
        data = os.urandom(1 << 20)
        active, exiting, gate = await _start_abort(
            opened,
            executor,
            "write",
            opened.handle.write(data if kind == "binary" else data.hex()),
        )
        error = await _cancel_held(exiting, gate, 1)
        assert isinstance(error, asyncio.CancelledError)
        written = await _outcome(active)
        assert isinstance(written, OSError)
        assert "write aborted" in str(written)
        assert opened.binary._write_broken
        executor.wait_idle()
        write_end = executor.index("end", "write")
        close_start = executor.index("start", "close")
        assert len(close_start) == 1 and write_end[0] < close_start[0]
        assert opened.raw.closed
        assert opened.handle.closed

    @pytest.mark.parametrize("kind", KINDS)
    async def test_cancelled_abort_close_after_an_active_rewind(
        self, path, executor, kind
    ):
        opened = await _open(kind, "r", "path", path)
        await opened.handle.read(100)
        active, exiting, gate = await _start_abort(
            opened, executor, "seek", opened.handle.seek(0)
        )
        error = await _cancel_held(exiting, gate, 1)
        assert isinstance(error, asyncio.CancelledError)
        # BC9: the settled rewind reports the abort and revives nothing.
        result = await _outcome(active)
        assert isinstance(result, OSError)
        assert "read aborted" in str(result)
        assert opened.binary._read_health.name == "BROKEN"
        executor.wait_idle()
        assert executor.entries("end", "close") == [opened.raw]
        assert opened.raw.closed
        assert opened.handle.closed

    async def test_observer_failure_after_a_cancelled_abort_close_is_noted(
        self, path, executor
    ):
        opened = await _open("binary", "r", "path", path)

        def observer():
            raise ValueError("observer failure")

        opened.binary._closed_observer = observer
        active, exiting, gate = await _start_abort(
            opened, executor, "read", opened.handle.read()
        )
        error = await _cancel_held(exiting, gate, 1)
        # The cancellation outranks the ordinary observer failure.
        assert isinstance(error, asyncio.CancelledError)
        notes = getattr(error, "__notes__", [])
        assert any("observer failure" in note for note in notes), notes
        await _outcome(active)
        executor.wait_idle()
        assert opened.raw.closed
        assert opened.handle.closed

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("cancelled", [False, True])
    async def test_failing_abort_close_stays_open_for_a_retry(
        self, path, executor, kind, cancelled
    ):
        opened = await _open(kind, "r", "path", path)
        failure = OSError("injected close failure")
        executor.fail["close"] = failure
        active, exiting, gate = await _start_abort(
            opened, executor, "read", opened.handle.read()
        )
        if cancelled:
            error = await _cancel_held(exiting, gate, 1)
            assert isinstance(error, asyncio.CancelledError)
            assert error.__cause__ is failure
        else:
            gate.release.set()
            await _outcome(exiting)
        await _outcome(active)
        executor.wait_idle()
        assert executor.entries("start", "close") == [opened.raw]
        # A failed abort close leaves the broken handle open; close() retries.
        assert not opened.handle.closed
        await opened.handle.close()
        executor.wait_idle()
        assert executor.entries("start", "close") == [opened.raw, opened.raw]
        assert opened.handle.closed
        assert opened.raw.closed


# (via, cancels): an exceptional exit aborts at once, so one cancellation
# lands in the abort's settlement; a clean exit aborts on the first and needs
# a second.
SETTLEMENT_CANCELS = [("error-exit", 1), ("error-exit", 3), ("clean-exit", 2)]


async def _cancel_abort_settlement(
    opened, executor, name, call, via, cancels, close_stage=None
):
    """Cancel a context exit while its abort settles a held active call.

    Return the active call's task, the exiting task and the body error.
    ``close_stage`` also holds the close that follows, before the call is
    released.
    """
    held = executor.arm(name, "running")
    active = asyncio.create_task(call)
    await asyncio.wait_for(held.entered.wait(), 10)
    body = KeyError("body") if via == "error-exit" else None

    async def exit_context():
        # As ``async with`` does, exit while the body's exception is handled.
        if body is None:
            return await opened.handle.__aexit__(None, None, None)
        try:
            raise body
        except KeyError:
            return await opened.handle.__aexit__(KeyError, body, body.__traceback__)

    exiting = asyncio.create_task(exit_context())
    await asyncio.sleep(0.01)
    for _ in range(cancels):
        exiting.cancel()
        await asyncio.sleep(0.01)
    # The abort is still settling the held call and has not closed yet.
    assert not exiting.done()
    assert executor.entries("start", "close") == []
    if close_stage is not None:
        executor.arm("close", close_stage)
    held.release.set()
    return active, exiting, body


class TestCancelledAbortSettlement:
    """A cancellation while the abort settles the active call still closes.

    Settlement has finished the active call before the cancellation
    propagates, so the abort releases the file first (BC16). An exceptional
    exit's cancellation keeps the body's exception as its context.
    """

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize(("via", "cancels"), SETTLEMENT_CANCELS)
    @pytest.mark.parametrize("source", ["path", "closefd"])
    async def test_active_read(self, path, executor, kind, via, cancels, source):
        opened = await _open(kind, "r", source, path)
        active, exiting, body = await _cancel_abort_settlement(
            opened, executor, "read", opened.handle.read(), via, cancels
        )
        error = await _outcome(exiting)
        assert isinstance(error, asyncio.CancelledError)
        if body is not None:
            assert error.__context__ is body
        assert not getattr(error, "__notes__", []), error.__notes__
        result = await _outcome(active)
        assert isinstance(result, OSError) and "read aborted" in str(result)
        executor.wait_idle()
        read_end = executor.index("end", "read")
        close_start = executor.index("start", "close")
        assert len(close_start) == 1 and read_end[-1] < close_start[0]
        assert opened.raw.closed
        assert opened.handle.closed
        assert opened.binary._read_health.name == "BROKEN"

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize(("via", "cancels"), SETTLEMENT_CANCELS)
    async def test_active_write(self, path, executor, kind, via, cancels):
        opened = await _open(kind, "w", "path", path)
        data = os.urandom(1 << 20)
        active, exiting, body = await _cancel_abort_settlement(
            opened,
            executor,
            "write",
            opened.handle.write(data if kind == "binary" else data.hex()),
            via,
            cancels,
        )
        error = await _outcome(exiting)
        assert isinstance(error, asyncio.CancelledError)
        if body is not None:
            assert error.__context__ is body
        written = await _outcome(active)
        assert isinstance(written, OSError) and "write aborted" in str(written)
        executor.wait_idle()
        write_end = executor.index("end", "write")
        close_start = executor.index("start", "close")
        assert len(close_start) == 1 and write_end[0] < close_start[0]
        assert opened.raw.closed
        assert opened.handle.closed

    @pytest.mark.parametrize("kind", KINDS)
    async def test_borrowed_file_stays_open(self, path, executor, kind):
        opened = await _open(kind, "r", "borrowed", path)
        active, exiting, body = await _cancel_abort_settlement(
            opened, executor, "read", opened.handle.read(), "error-exit", 1
        )
        error = await _outcome(exiting)
        assert isinstance(error, asyncio.CancelledError)
        assert error.__context__ is body
        await _outcome(active)
        executor.wait_idle()
        assert executor.entries("start", "close") == []
        assert opened.handle.closed
        assert not opened.borrowed._file.closed
        _close_borrowed(opened)

    @pytest.mark.parametrize("kind", KINDS)
    async def test_failing_close_is_the_cause_and_stays_open(
        self, path, executor, kind
    ):
        opened = await _open(kind, "r", "path", path)
        failure = OSError("injected close failure")
        executor.fail["close"] = failure
        active, exiting, body = await _cancel_abort_settlement(
            opened, executor, "read", opened.handle.read(), "error-exit", 1
        )
        error = await _outcome(exiting)
        assert isinstance(error, asyncio.CancelledError)
        assert error.__cause__ is failure
        await _outcome(active)
        executor.wait_idle()
        # The failed close leaves the broken handle open; close() retries.
        assert not opened.handle.closed
        await opened.handle.close()
        executor.wait_idle()
        assert executor.entries("start", "close") == [opened.raw, opened.raw]
        assert opened.handle.closed
        assert opened.raw.closed

    async def test_failing_close_after_a_failed_active_read(self, path, executor):
        read_failure = OSError("injected read failure")

        class FailingReader(io.BufferedReader):
            # Fails inside the native call, as a real read error would.
            fail = False

            def read(self, size=-1, /):
                if self.fail:
                    raise read_failure
                return super().read(size)

        raw = FailingReader(io.FileIO(path, "rb"))
        source = aiofiles.threadpool.wrap(raw, loop=asyncio.get_running_loop())
        handle = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)
        await handle.__aenter__()
        opened = _Opened(handle, raw, True, None)
        close_failure = OSError("injected close failure")
        executor.fail["close"] = close_failure
        raw.fail = True
        active, exiting, _ = await _cancel_abort_settlement(
            opened, executor, "read", opened.handle.read(), "error-exit", 1
        )
        error = await _outcome(exiting)
        # The read's owner reports the read failure; the cancellation is
        # caused by the close failure.
        assert isinstance(error, asyncio.CancelledError)
        assert error.__cause__ is close_failure
        assert not getattr(error, "__notes__", []), error.__notes__
        assert await _outcome(active) is read_failure
        executor.wait_idle()
        assert not opened.handle.closed
        await opened.handle.close()
        assert raw.closed

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("stage", STAGES)
    async def test_cancelled_again_during_the_close(self, path, executor, kind, stage):
        opened = await _open(kind, "r", "path", path)
        active, exiting, _ = await _cancel_abort_settlement(
            opened, executor, "read", opened.handle.read(), "error-exit", 1, stage
        )
        # Cancel the exit once more while the held close is pending.
        error = await _cancel_held(exiting, executor.armed[-1], 1)
        assert isinstance(error, asyncio.CancelledError)
        await _outcome(active)
        executor.wait_idle()
        assert executor.entries("start", "close") == [opened.raw]
        assert opened.raw.closed
        assert opened.handle.closed


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("cancels", [1, 3])
async def test_failed_opening_with_a_cancelled_cleanup_close(
    path, executor, kind, stage, cancels
):
    handle = (
        AsyncGzipBinaryFile(path, "wb")
        if kind == "binary"
        else AsyncGzipTextFile(path, "wt")
    )
    failure = OSError("injected header failure")
    executor.fail["write"] = failure
    gate = executor.arm("close", stage)
    task = asyncio.create_task(handle.__aenter__())
    error = await _cancel_held(task, gate, cancels)
    # The outside cancellation outranks the ordinary opening failure.
    assert isinstance(error, asyncio.CancelledError)
    assert error.__context__ is failure
    executor.wait_idle()
    (raw,) = executor.entries("end", "close")
    assert raw.closed
    assert executor.entries("start", "close") == [raw]
    assert not handle.closed


class TestCloseThatLeavesTheFileOpen:
    """A native close that raises before releasing the file proves nothing."""

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("raised", ["cancelled", "oserror"])
    async def test_abort_close_failing_before_release_stays_open(
        self, path, executor, kind, raised
    ):
        opened = await _open(kind, "r", "path", path)
        # The raw close itself raises, with no outside cancellation.
        failure = (
            asyncio.CancelledError() if raised == "cancelled" else OSError("early")
        )
        executor.fail_before["close"] = failure
        active, exiting, gate = await _start_abort(
            opened, executor, "read", opened.handle.read()
        )
        gate.release.set()
        outcome = await _outcome(exiting)
        if raised == "cancelled":
            assert outcome is failure
        await _outcome(active)
        executor.wait_idle()
        assert not opened.raw.closed
        assert not opened.handle.closed
        # The retry performs the close that never happened.
        await opened.handle.close()
        executor.wait_idle()
        assert executor.entries("end", "close") == [opened.raw]
        assert opened.raw.closed
        assert opened.handle.closed

    @pytest.mark.parametrize("kind", KINDS)
    async def test_cancelled_abort_close_failing_before_release_stays_open(
        self, path, executor, kind
    ):
        opened = await _open(kind, "r", "path", path)
        failure = OSError("early")
        executor.fail_before["close"] = failure
        active, exiting, gate = await _start_abort(
            opened, executor, "read", opened.handle.read()
        )
        error = await _cancel_held(exiting, gate, 1)
        assert isinstance(error, asyncio.CancelledError)
        assert error.__cause__ is failure
        await _outcome(active)
        executor.wait_idle()
        assert not opened.raw.closed
        assert not opened.handle.closed
        await opened.handle.close()
        executor.wait_idle()
        assert opened.raw.closed
        assert opened.handle.closed

    @pytest.mark.parametrize("kind", KINDS)
    async def test_normal_close_failing_before_release_is_unchanged(
        self, path, executor, kind
    ):
        # Unchanged from b2: close() latches closed before finalizing, so a
        # native close that fails without releasing the file raises its
        # error from a closed handle.
        opened = await _open(kind, "r", "path", path)
        failure = OSError("early")
        executor.fail_before["close"] = failure
        with pytest.raises(OSError) as caught:
            await opened.handle.close()
        assert caught.value is failure
        executor.wait_idle()
        assert opened.handle.closed
        assert not opened.raw.closed
        opened.raw.close()


async def _open_in_another_loop(target):
    return await aiofiles.open(target, "rb")


@pytest.mark.parametrize("kind", KINDS)
async def test_close_of_a_source_from_another_loop_is_refused(path, executor, kind):
    source = await asyncio.to_thread(asyncio.run, _open_in_another_loop(path))
    try:
        cls = AsyncGzipBinaryFile if kind == "binary" else AsyncGzipTextFile
        mode = "rb" if kind == "binary" else "rt"
        handle = cls(None, mode, fileobj=source, closefd=True)
        await handle.__aenter__()
        with pytest.raises(RuntimeError, match="different event loop"):
            await handle.close()
        executor.wait_idle()
        # Refused before submission: nothing touched the file.
        assert executor.entries("start", "close") == []
        assert not source._file.closed
    finally:
        source._file.close()
