"""RC1 R09: context-exit aborts keep cancellation counts and report cleanup.

* An abort cancels the task that owns an active custom source or sink call
  exactly once. That request is consumed however the call ends, so a source
  or sink that swallows the cancellation (a contract violation) cannot leave
  the task's ``cancelling()`` count raised and make an enclosing
  ``asyncio.timeout()`` report its expiry as an outside cancellation
  (Opus RC1-06).
* A failure while the context exit aborts and closes is attached to the
  primary exception as a note instead of being dropped (Opus RC1-07).
"""

from __future__ import annotations

import asyncio

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

NOTE = "Context-exit cleanup also failed: OSError('close failed')"


class _SwallowingSource:
    """A custom source whose read swallows cancellation (contract violation)."""

    def __init__(self, ending: str, *, close_fails: bool = False) -> None:
        self.ending = ending
        self.close_fails = close_fails
        self.entered = asyncio.Event()
        self.closes = 0

    async def read(self, size: int = -1) -> bytes:
        self.entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            if self.ending == "propagate":
                raise
            if self.ending == "raise":
                raise OSError("source failed") from None
            return b""
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closes += 1
        if self.close_fails:
            raise OSError("close failed")


class _SwallowingSink:
    """A custom sink whose write swallows cancellation (contract violation)."""

    def __init__(self, ending: str) -> None:
        self.ending = ending
        self.entered = asyncio.Event()
        self.closes = 0
        self.writes = 0

    async def write(self, data: bytes) -> int:
        self.writes += 1
        if self.writes == 1 or self.entered.is_set():
            # Never block the header write, and block only once.
            return len(data)
        self.entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            if self.ending == "propagate":
                raise
            if self.ending == "raise":
                raise OSError("sink failed") from None
            return len(data)
        raise AssertionError("unreachable")

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        self.closes += 1


def _reader(source, text: bool):
    if text:
        return AsyncGzipTextFile(None, "rt", fileobj=source, closefd=True)
    return AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)


def _writer(sink, text: bool):
    if text:
        return AsyncGzipTextFile(None, "wt", fileobj=sink, closefd=True)
    return AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True)


async def _abort_during(stream, entered: asyncio.Event, call):
    """Run ``call`` in its own task and abort it by a failing context body."""
    observed: dict[str, object] = {}

    async def owner():
        try:
            await call()
        except Exception as error:  # the aborted call's own outcome
            observed["error"] = error
        observed["cancelling"] = asyncio.current_task().cancelling()
        # An enclosing timeout must still classify its own expiry.
        try:
            async with asyncio.timeout(0.01):
                await asyncio.sleep(5)
        except TimeoutError:
            observed["timeout"] = "TimeoutError"
        except asyncio.CancelledError:
            observed["timeout"] = "CancelledError"
            asyncio.current_task().uncancel()

    task = None
    with pytest.raises(RuntimeError, match="body"):
        async with stream:
            task = asyncio.create_task(owner())
            await asyncio.wait_for(entered.wait(), 5)
            raise RuntimeError("body")
    assert task is not None
    await asyncio.wait_for(task, 5)
    return observed


ENDINGS = ["propagate", "return", "raise"]


class TestAbortConsumesItsCancellation:
    @pytest.mark.parametrize("text", [False, True])
    @pytest.mark.parametrize("ending", ENDINGS)
    async def test_custom_source(self, text, ending):
        source = _SwallowingSource(ending)
        stream = _reader(source, text)
        observed = await _abort_during(stream, source.entered, lambda: stream.read())
        assert observed["cancelling"] == 0
        assert observed["timeout"] == "TimeoutError"
        assert source.closes == 1

    @pytest.mark.parametrize("text", [False, True])
    @pytest.mark.parametrize("ending", ENDINGS)
    async def test_custom_sink(self, text, ending):
        sink = _SwallowingSink(ending)
        stream = _writer(sink, text)

        async def write_then_flush():
            await stream.write("x" if text else b"x")
            await stream.flush()

        observed = await _abort_during(stream, sink.entered, write_then_flush)
        assert observed["cancelling"] == 0
        assert observed["timeout"] == "TimeoutError"
        assert sink.closes == 1

    async def test_an_outside_cancellation_stays_with_the_caller(self):
        source = _SwallowingSource("return")
        stream = _reader(source, False)
        reader = None

        async def read_once():
            try:
                await stream.read()
            except Exception:
                pass
            return asyncio.current_task().cancelling()

        with pytest.raises(RuntimeError, match="body"):
            async with stream:
                reader = asyncio.create_task(read_once())
                await asyncio.wait_for(source.entered.wait(), 5)
                reader.cancel("outside")
                raise RuntimeError("body")
        assert reader is not None
        # The swallowed outside request stays counted; only the abort's own
        # request was consumed.
        assert await asyncio.wait_for(reader, 5) == 1


class TestContextExitCleanupNotes:
    @pytest.mark.parametrize("text", [False, True])
    async def test_body_error_keeps_a_failed_abort_close_as_a_note(self, text):
        source = _SwallowingSource("propagate", close_fails=True)
        stream = _reader(source, text)
        reader = None
        with pytest.raises(RuntimeError, match="body") as caught:
            async with stream:
                reader = asyncio.create_task(stream.read())
                await asyncio.wait_for(source.entered.wait(), 5)
                raise RuntimeError("body")
        assert getattr(caught.value, "__notes__", []) == [NOTE]
        assert reader is not None
        with pytest.raises(OSError, match="read aborted"):
            await asyncio.wait_for(reader, 5)

    async def test_body_error_without_cleanup_failure_has_no_note(self):
        source = _SwallowingSource("propagate")
        stream = _reader(source, False)
        reader = None
        with pytest.raises(RuntimeError, match="body") as caught:
            async with stream:
                reader = asyncio.create_task(stream.read())
                await asyncio.wait_for(source.entered.wait(), 5)
                raise RuntimeError("body")
        assert not getattr(caught.value, "__notes__", [])
        assert reader is not None
        await asyncio.gather(reader, return_exceptions=True)

    @pytest.mark.parametrize("text", [False, True])
    async def test_cancelled_clean_exit_keeps_a_failed_abort_close_as_a_note(
        self, text
    ):
        source = _SwallowingSource("propagate", close_fails=True)
        stream = _reader(source, text)
        reader = None
        exiting = asyncio.Event()
        raised: list[BaseException] = []

        async def owner():
            nonlocal reader
            try:
                async with stream:
                    reader = asyncio.create_task(stream.read())
                    await source.entered.wait()
                    exiting.set()
                # The clean exit waits for the active read until cancelled.
            except asyncio.CancelledError as cancellation:
                # Awaiting a cancelled task raises a fresh CancelledError, so
                # keep the one the context exit raised.
                raised.append(cancellation)
                raise

        task = asyncio.create_task(owner())
        await asyncio.wait_for(exiting.wait(), 5)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert len(raised) == 1
        assert getattr(raised[0], "__notes__", []) == [NOTE]
        assert reader is not None
        await asyncio.gather(reader, return_exceptions=True)
