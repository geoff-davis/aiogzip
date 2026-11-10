"""Failure precedence when closing a chunk stream's source (#173, BC23).

``compress_chunks()`` and ``decompress_chunks()`` close their source after a
failure or an early close. A cancellation or interrupt that arrives during
that close must not be discarded: it outranks an ordinary stream failure, as
it does for ``verify()`` (BC14). Any other cleanup failure is noted on the
failure that stands.
"""

import asyncio
import gzip

import pytest

import aiogzip


class _Interrupt(BaseException):
    pass


class _Source:
    def __init__(self, items, on_close):
        self._items = list(items)
        self._on_close = on_close
        self.closing = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)

    async def aclose(self):
        self.closing.set()
        await self._on_close()


async def _block():
    await asyncio.Event().wait()


async def _fail():
    raise RuntimeError("close failed")


async def _interrupt():
    raise _Interrupt


async def _nothing():
    pass


VALID = gzip.compress(b"payload" * 10_000)
# (stream factory, items that fail, the ordinary failure, items that succeed)
STREAMS = {
    "decompress": (
        aiogzip.decompress_chunks,
        [b"not gzip"],
        gzip.BadGzipFile,
        [VALID],
    ),
    "compress": (aiogzip.compress_chunks, ["text"], TypeError, [b"payload" * 10_000]),
}
pytestmark = pytest.mark.parametrize("kind", STREAMS)


async def _drain(stream):
    async for _ in stream:
        pass


async def test_cancellation_during_cleanup_outranks_an_ordinary_failure(kind):
    factory, bad, failure_type, _ = STREAMS[kind]
    source = _Source(bad, _block)
    task = asyncio.create_task(_drain(factory(source)))
    await source.closing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert task.cancelled()
    assert isinstance(caught.value.__context__, failure_type)


async def test_timeout_during_cleanup_is_honoured(kind):
    factory, bad, failure_type, _ = STREAMS[kind]
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await _drain(factory(_Source(bad, _block)))


async def test_interrupt_during_cleanup_outranks_an_ordinary_failure(kind):
    factory, bad, failure_type, _ = STREAMS[kind]
    with pytest.raises(_Interrupt) as caught:
        await _drain(factory(_Source(bad, _interrupt)))
    assert isinstance(caught.value.__context__, failure_type)


async def test_ordinary_cleanup_failure_is_noted_on_the_stream_failure(kind):
    factory, bad, failure_type, _ = STREAMS[kind]
    with pytest.raises(failure_type) as caught:
        await _drain(factory(_Source(bad, _fail)))
    assert caught.value.__notes__ == [
        "Source cleanup also failed: RuntimeError('close failed')"
    ]


async def test_cancellation_keeps_precedence_over_a_cleanup_failure(kind):
    factory, _, _, good = STREAMS[kind]

    class Parked(_Source):
        def __init__(self):
            super().__init__(good, _fail)
            self.parked = asyncio.Event()

        async def __anext__(self):
            self.parked.set()
            await _block()

    source = Parked()
    task = asyncio.create_task(_drain(factory(source)))
    await source.parked.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert caught.value.__notes__ == [
        "Source cleanup also failed: RuntimeError('close failed')"
    ]


async def test_cancellation_during_an_early_close_is_not_lost(kind):
    factory, _, _, good = STREAMS[kind]
    source = _Source(good, _block)
    stream = factory(source)
    await stream.__anext__()
    task = asyncio.create_task(stream.aclose())
    await source.closing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


async def test_ordinary_cleanup_failure_during_an_early_close_is_suppressed(kind):
    factory, _, _, good = STREAMS[kind]
    stream = factory(_Source(good, _fail))
    await stream.__anext__()
    await stream.aclose()


async def test_cleanup_failure_after_success_propagates(kind):
    factory, _, _, good = STREAMS[kind]
    with pytest.raises(RuntimeError, match="close failed"):
        await _drain(factory(_Source(good, _fail)))
