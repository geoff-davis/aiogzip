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


@pytest.mark.parametrize("target", ["caller", "helper", "both"])
@pytest.mark.parametrize("repetitions", [1, 3])
@pytest.mark.parametrize("fails", [False, True])
async def test_cancel_retains_native_input_and_cleanup_order(
    monkeypatch, target, repetitions, fails
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    events, helpers = [], []
    original_run = _codec_async._run_in_thread
    original_submit = loop.run_in_executor
    failure = NativeFailure("native failure after mutation")

    def submit(executor, method, *args):
        future = original_submit(executor, method, *args)
        future.add_done_callback(lambda _: events.append("published"))
        return future

    async def observed(method, data):
        helpers.append(asyncio.current_task())
        return await original_run(method, data)

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
    monkeypatch.setattr(_codec_async, "_run_in_thread", observed)
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
            if target in ("helper", "both"):
                helpers[0].cancel("helper cancelled")
            for _ in range(4):
                await asyncio.sleep(0)
            assert not caller.done()
            assert not helpers[0].done()
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
        await asyncio.gather(caller, *helpers, return_exceptions=True)
        await stream.aclose()
    # Exception tracebacks legitimately retain inputs until diagnostics are released.
    if not fails:
        del caller, helpers, stream, caught
        await asyncio.sleep(0)  # Release gather/shield callback references.
        gc.collect()
        assert reference() is None
        assert not finalizer.alive
        assert events[-1] == "input released"


@pytest.mark.parametrize("target", ["caller", "helper", "both"])
async def test_queued_native_work_settles_before_cleanup(monkeypatch, target):
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    release = threading.Event()
    blocked, submitted = asyncio.Event(), asyncio.Event()
    events, helpers = [], []
    original_run = _codec_async._run_in_thread

    async def observed(method, data):
        helpers.append(asyncio.current_task())
        return await original_run(method, data)

    monkeypatch.setattr(_codec_async, "_run_in_thread", observed)
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
        if target in ("helper", "both"):
            helpers[0].cancel()
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


async def test_helper_cancelled_before_submission_never_starts(monkeypatch):
    calls = []
    original_create = asyncio.create_task

    def create_cancelled(coroutine):
        helper = original_create(coroutine)
        helper.cancel()
        return helper

    class Operation:
        def _advance_raw(self):
            calls.append("native access")
            return b"output"

        def close(self):
            calls.append("cleanup")

    monkeypatch.setattr(asyncio, "create_task", create_cancelled)
    stream = _codec_async._drive_operation(
        Operation(), workload=b"x", offload_threshold=1
    )
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)
    assert calls == ["cleanup"]
