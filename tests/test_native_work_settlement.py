"""WP1 ownership boundaries, using gated real executor work and bounded cleanup."""

import asyncio
import gc
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor

import pytest

from aiogzip import _codec_async
from aiogzip.codec import _CodecProgress


class NativeFailure(Exception):
    pass


@pytest.mark.parametrize("target", ["caller", "waiter", "both"])
@pytest.mark.parametrize("repetitions", [1, 3])
@pytest.mark.parametrize("fails", [False, True])
async def test_cancel_retains_native_input_and_cleanup_order(
    monkeypatch, target, repetitions, fails
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    events, waiters = [], []
    original_waiter = _codec_async._completion_waiter
    original_submit = loop.run_in_executor
    failure = NativeFailure("native failure after mutation")

    def submit(executor, method, *args):
        future = original_submit(executor, method, *args)
        future.add_done_callback(lambda _: events.append("published"))
        return future

    def observed(work):
        waiter = original_waiter(work)
        waiters.append(waiter)
        return waiter

    class Input(bytearray):
        pass

    class Operation:
        def _advance_raw(self):
            events.append("entered")
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("native watchdog expired")
            events.append("last access")
            if fails:
                raise failure
            return b"output"

        def close(self):
            events.append("cleanup")

    monkeypatch.setattr(loop, "run_in_executor", submit)
    monkeypatch.setattr(_codec_async, "_completion_waiter", observed)
    payload = Input(b"x")
    reference = weakref.ref(payload)
    finalizer = weakref.finalize(payload, events.append, "input released")
    stream = _codec_async._drive_operation(
        Operation(), workload=payload, offload_threshold=1
    )
    del payload
    caller = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(repetitions):
            if target in ("caller", "both"):
                caller.cancel("caller cancelled")
            if target in ("waiter", "both"):
                waiters[-1].cancel("helper cancelled")
            for _ in range(4):
                await asyncio.sleep(0)
            assert not caller.done()
            assert "published" not in events
            assert "cleanup" not in events
            assert reference() is not None
        release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await caller
        if fails:
            exception = caught.value
            chain = []
            while exception is not None and exception not in chain:
                chain.append(exception)
                exception = exception.__cause__ or exception.__context__
            assert failure in chain
        assert events[:4] == ["entered", "last access", "published", "cleanup"]
    finally:
        release.set()
        await asyncio.gather(caller, *waiters, return_exceptions=True)
        await stream.aclose()
    # Exception tracebacks legitimately retain inputs until diagnostics are released.
    if not fails:
        del caller, waiters, stream, caught
        await asyncio.sleep(0)  # Release gather/waiter callback references.
        gc.collect()
        assert reference() is None
        assert not finalizer.alive
        assert events[-1] == "input released"


@pytest.mark.parametrize("target", ["caller", "waiter", "both"])
async def test_queued_native_work_settles_before_cleanup(monkeypatch, target):
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    release = threading.Event()
    blocked, submitted = asyncio.Event(), asyncio.Event()
    events, waiters = [], []
    original_waiter = _codec_async._completion_waiter

    def observed(work):
        waiter = original_waiter(work)
        waiters.append(waiter)
        return waiter

    monkeypatch.setattr(_codec_async, "_completion_waiter", observed)
    original_submit = loop.run_in_executor

    def blocker():
        loop.call_soon_threadsafe(blocked.set)
        if not release.wait(5):
            raise RuntimeError("queue watchdog expired")

    occupying = original_submit(executor, blocker)

    def submit(_executor, method, *args):
        future = original_submit(executor, method, *args)
        submitted.set()
        return future

    class Operation:
        def _advance_raw(self):
            events.append("last access")
            return b"output"

        def close(self):
            events.append("cleanup")

    monkeypatch.setattr(loop, "run_in_executor", submit)
    stream = _codec_async._drive_operation(
        Operation(), workload=b"x", offload_threshold=1
    )
    caller = None
    try:
        await asyncio.wait_for(blocked.wait(), 5)
        caller = asyncio.create_task(anext(stream))
        await asyncio.wait_for(submitted.wait(), 5)
        if target in ("caller", "both"):
            caller.cancel()
        if target in ("waiter", "both"):
            waiters[0].cancel()
        for _ in range(4):
            await asyncio.sleep(0)
        assert not caller.done()
        assert not events
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert events == ["last access", "cleanup"]
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await occupying
        await stream.aclose()
        executor.shutdown(wait=True)


@pytest.mark.parametrize(
    "outcome", ["output", "progress", "done", "error", "output-error"]
)
async def test_native_results_and_failures(outcome):
    events = []
    failure = NativeFailure("native failure")

    class Operation:
        calls = 0

        def _advance_raw(self):
            self.calls += 1
            events.append("advance")
            if outcome == "error" or (outcome == "output-error" and self.calls == 2):
                raise failure
            if self.calls > 1 or outcome == "done":
                raise StopIteration
            if outcome == "progress":
                return _CodecProgress(1)
            return b"output"

        def close(self):
            events.append("cleanup")

    output = []
    stream = _codec_async._drive_operation(
        Operation(), workload=b"x", offload_threshold=1
    )
    if "error" in outcome:
        with pytest.raises(NativeFailure) as caught:
            async for chunk in stream:
                output.append(chunk)
        assert caught.value is failure
        assert events[-1] == "cleanup"
        assert events.count("cleanup") == 1
    else:
        output = [chunk async for chunk in stream]
        assert "cleanup" not in events
    assert output == ([b"output"] if outcome in ("output", "output-error") else [])


@pytest.mark.parametrize("structured", ["timeout", "taskgroup"])
async def test_structured_cancellation_waits_for_native_work(structured):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    events = []
    timer = None

    class Operation:
        def _advance_raw(self):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("structured cancellation watchdog expired")
            events.append("last access")
            return b"output"

        def close(self):
            events.append("cleanup")

    async def consume():
        stream = _codec_async._drive_operation(
            Operation(), workload=b"x", offload_threshold=1
        )
        try:
            await anext(stream)
        finally:
            await stream.aclose()

    async def trigger(timeout=None):
        nonlocal timer
        await asyncio.wait_for(entered.wait(), 5)
        timer = threading.Timer(0.05, release.set)
        timer.start()
        if timeout is not None:
            timeout.reschedule(loop.time())
        else:
            raise NativeFailure("sibling failure")

    try:
        if structured == "timeout":
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(None) as timeout:
                    trigger_task = asyncio.create_task(trigger(timeout))
                    try:
                        await consume()
                    finally:
                        await trigger_task
        else:
            with pytest.raises(ExceptionGroup) as caught:
                async with asyncio.TaskGroup() as group:
                    group.create_task(consume())
                    group.create_task(trigger())
            assert isinstance(caught.value.exceptions[0], NativeFailure)
        assert events == ["last access", "cleanup"]
    finally:
        release.set()
        if timer is not None:
            timer.join()


async def test_driver_does_not_create_a_cancellable_helper(monkeypatch):
    calls = []

    def unexpected_helper(coroutine):
        coroutine.close()
        raise AssertionError("driver must own the executor future directly")

    class Operation:
        def _advance_raw(self):
            calls.append("native access")
            raise StopIteration

        def close(self):
            calls.append("cleanup")

    monkeypatch.setattr(asyncio, "create_task", unexpected_helper)
    stream = _codec_async._drive_operation(
        Operation(), workload=b"x", offload_threshold=1
    )
    assert [part async for part in stream] == []
    assert calls == ["native access"]


async def test_submission_failure_closes_without_native_access(monkeypatch):
    calls = []

    def rejected(*args):
        raise RuntimeError("executor unavailable")

    class Operation:
        def _advance_raw(self):
            calls.append("native access")
            return b"output"

        def close(self):
            calls.append("cleanup")

    monkeypatch.setattr(asyncio.get_running_loop(), "run_in_executor", rejected)
    stream = _codec_async._drive_operation(
        Operation(), workload=b"x", offload_threshold=1
    )
    with pytest.raises(RuntimeError, match="executor unavailable"):
        await anext(stream)
    assert calls == ["cleanup"]


@pytest.mark.parametrize("cancellations", [1, 3])
@pytest.mark.parametrize("fails", [False, True])
async def test_cancelled_settlement_leaves_no_loop_report(cancellations, fails):
    """A worker failure chained as the cancellation's cause is not reported again.

    Python 3.14's ``asyncio.shield`` made the loop log such a failure as an
    "exception in shielded future" once the shield had been cancelled.
    """
    loop = asyncio.get_running_loop()
    reports = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: reports.append(context))
    entered = asyncio.Event()
    release = threading.Event()
    failure = NativeFailure("native failure after cancellation")

    def native():
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("native watchdog expired")
        if fails:
            raise failure
        return b"output"

    caller = asyncio.create_task(
        _codec_async._settle_before_cancel(loop.run_in_executor(None, native))
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(cancellations):
            caller.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await caller
        assert caught.value.__cause__ is (failure if fails else None)
        for _ in range(4):
            await asyncio.sleep(0)
        del caller, caught
        gc.collect()
        await asyncio.sleep(0)
        assert reports == []
    finally:
        release.set()
        loop.set_exception_handler(previous)


async def test_cancelled_completion_waiter_detaches_from_work():
    work = asyncio.get_running_loop().create_future()
    for _ in range(3):
        _codec_async._completion_waiter(work).cancel()
    await asyncio.sleep(0)
    assert not work._callbacks
    waiter = _codec_async._completion_waiter(work)
    work.set_exception(NativeFailure("retrieved by the owner only"))
    await waiter
    assert waiter.result() is None
    with pytest.raises(NativeFailure):
        work.result()
