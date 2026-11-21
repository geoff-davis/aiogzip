"""``IterableReader``: an ``AsyncIterable[bytes]`` as a readable fileobj (#201)."""

import asyncio
import gzip

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import aiogzip
from aiogzip import IterableReader, _iterable_reader

TEXT = "".join(f"línea {i} — ✓ 日本語\r\n" for i in range(3000))
PAYLOAD = TEXT.encode("utf-8")
BLOB = gzip.compress(PAYLOAD[:40_000]) + gzip.compress(PAYLOAD[40_000:])
CHUNK = 4096


class Source:
    """An async iterator over fixed-size items that records what happened."""

    def __init__(self, data=BLOB, size=CHUNK, *, fail_at=None, block_at=None):
        self.items = [data[i : i + size] for i in range(0, len(data), size)]
        self.pulled = 0
        self.closed = 0
        self.fail_at = fail_at
        self.block_at = block_at
        self.blocked = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.pulled == self.fail_at:
            raise ConnectionResetError("connection reset")
        if self.pulled == self.block_at:
            self.blocked.set()
            await asyncio.Event().wait()
        if self.pulled >= len(self.items):
            raise StopAsyncIteration
        self.pulled += 1
        return self.items[self.pulled - 1]

    async def aclose(self):
        self.closed += 1


async def _items(*items):
    for item in items:
        yield item


class TestStandalone:
    async def test_read_returns_the_rest_of_an_item_without_waiting(self):
        source = Source(b"abcdefghij", 4)
        reader = IterableReader(source)
        assert await reader.read(3) == b"abc"
        assert source.pulled == 1
        assert await reader.read(100) == b"d"
        assert source.pulled == 1
        assert await reader.read(4) == b"efgh"
        assert reader.tell() == 8
        assert await reader.read(100) == b"ij"
        assert await reader.read(100) == b""
        assert await reader.read(100) == b""
        assert reader.tell() == 10

    async def test_a_whole_bytes_item_is_returned_without_a_copy(self):
        item = b"x" * 1000
        reader = IterableReader(_items(item))
        assert await reader.read(1000) is item

    @pytest.mark.parametrize("size", [-1, None, -5])
    async def test_unsized_read_drains_the_source(self, size):
        reader = IterableReader(Source(b"abcdefghij", 3))
        assert await reader.read(2) == b"ab"
        assert await reader.read(size) == b"cdefghij"
        assert await reader.read(size) == b""
        assert reader.tell() == 10

    async def test_read_zero_touches_nothing(self):
        source = Source(b"abc", 1)
        reader = IterableReader(source)
        assert await reader.read(0) == b""
        assert source.pulled == 0 and reader.tell() == 0

    async def test_item_types_and_empty_items(self):
        class Sub(bytes):
            def __len__(self):
                return 0

        reader = IterableReader(
            _items(b"", bytearray(b"ab"), b"", memoryview(b"cdef")[::2], Sub(b"g"))
        )
        assert await reader.read() == b"abceg"
        assert type(await reader.read()) is bytes

    @pytest.mark.parametrize("item", ["text", 3, None, [b"x"]])
    async def test_invalid_item_makes_the_reader_unusable(self, item):
        reader = IterableReader(_items(b"ok", item, b"never"))
        assert await reader.read(10) == b"ok"
        with pytest.raises(TypeError, match="source items must be bytes"):
            await reader.read(10)
        with pytest.raises(OSError, match="unusable") as caught:
            await reader.read(10)
        assert isinstance(caught.value.__cause__, TypeError)
        with pytest.raises(ValueError, match="unusable"):
            reader.tell()
        assert "failed" in repr(reader)

    @pytest.mark.parametrize(
        ("source", "hint"),
        [
            (b"bytes", "aiogzip.decompress"),
            ([b"a"], "synchronous iterable"),
            (iter([b"a"]), "synchronous iterable"),
            (3, "not int"),
            (None, "not NoneType"),
        ],
    )
    def test_constructor_rejects_other_sources(self, source, hint):
        with pytest.raises(TypeError, match="asynchronous iterable of bytes") as e:
            IterableReader(source)
        assert hint in str(e.value)

    async def test_aiter_must_return_an_iterator(self):
        class Bad:
            def __aiter__(self):
                return object()

        reader = IterableReader(Bad())
        with pytest.raises(TypeError, match="must return an asynchronous iterator"):
            await reader.read(1)

    @pytest.mark.parametrize("size", ["1", 1.0, b"1"])
    async def test_size_must_be_an_int(self, size):
        reader = IterableReader(_items(b"abc"))
        with pytest.raises(TypeError, match="size must be an int or None"):
            await reader.read(size)
        assert await reader.read(3) == b"abc"

    async def test_overlapping_reads_are_rejected(self):
        source = Source(b"abc", 1, block_at=0)
        reader = IterableReader(source)
        task = asyncio.ensure_future(reader.read(1))
        await source.blocked.wait()
        with pytest.raises(RuntimeError, match="already in progress"):
            await reader.read(1)
        assert reader.tell() == 0  # the rejected call changed nothing
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_close_is_idempotent_and_closes_the_iterator(self):
        source = Source(b"abcdef", 2)
        reader = IterableReader(source)
        assert await reader.read(1) == b"a"
        assert not reader.closed
        await reader.close()
        await reader.aclose()
        assert reader.closed and source.closed == 1
        with pytest.raises(ValueError, match="closed"):
            await reader.read(1)
        with pytest.raises(ValueError, match="closed"):
            reader.tell()
        assert "closed" in repr(reader)

    async def test_close_before_the_first_read_closes_the_source(self):
        source = Source()
        reader = IterableReader(source)
        await reader.aclose()
        assert source.closed == 1 and source.pulled == 0

    async def test_close_without_aclose_on_the_source(self):
        class Plain:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        reader = IterableReader(Plain())
        assert await reader.read() == b""
        await reader.close()
        assert reader.closed

    @pytest.mark.parametrize("started", [False, True])
    @pytest.mark.parametrize("failure", [OSError("cleanup failed"), None])
    async def test_failed_or_cancelled_cleanup_is_retried(self, started, failure):
        gate = asyncio.Event()
        attempts = []

        class Flaky(Source):
            async def aclose(self):
                attempts.append(len(attempts))
                if len(attempts) == 1:
                    if failure is not None:
                        raise failure
                    await gate.wait()
                self.closed += 1

        source = Flaky(b"abcdef", 2)
        reader = IterableReader(source)
        if started:
            assert await reader.read(1) == b"a"
        if failure is not None:
            with pytest.raises(OSError, match="cleanup failed"):
                await reader.close()
        else:
            task = asyncio.ensure_future(reader.close())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert reader.closed and source.closed == 0
        with pytest.raises(ValueError, match="closed"):
            await reader.read(1)
        await reader.close()
        await reader.close()
        assert source.closed == 1 and attempts == [0, 1]

    async def test_generator_based_aclose_is_awaited(self):
        import types

        ran = []

        class Old(Source):
            @types.coroutine
            def aclose(self):
                yield
                ran.append(True)

        reader = IterableReader(Old())
        await reader.close()
        assert ran == [True]

    async def test_cleanup_that_failed_under_a_handle_can_be_retried(self):
        """The handle closes once; the reader still owes the source a close."""
        attempts = []

        class Flaky(Source):
            async def aclose(self):
                attempts.append(True)
                if len(attempts) == 1:
                    raise OSError("cleanup failed")
                self.closed += 1

        source = Flaky(size=1000)
        reader = IterableReader(source)
        handle = aiogzip.open(None, "rb", fileobj=reader, closefd=True)
        await handle.open()
        await handle.read(10)
        with pytest.raises(OSError, match="cleanup failed"):
            await handle.close()
        assert handle.closed and reader.closed and source.closed == 0
        await reader.close()
        assert source.closed == 1 and len(attempts) == 2

    async def test_a_run_of_empty_items_yields_to_the_event_loop(self):
        count = 4 * _iterable_reader._EMPTY_ITEMS_CHECKPOINT
        reader = IterableReader(_items(*([b""] * count), b"x"))
        turns = 0
        done = False

        async def other():
            nonlocal turns
            while not done:
                turns += 1
                await asyncio.sleep(0)

        ticker = asyncio.ensure_future(other())
        assert await reader.read(1) == b"x"
        done = True
        await ticker
        assert turns >= 4

    def test_it_satisfies_the_read_protocol_and_cannot_seek(self):
        reader = IterableReader(_items())
        assert isinstance(reader, aiogzip.WithAsyncRead)
        assert not hasattr(reader, "seek")
        assert not hasattr(reader, "__dict__")


class TestThroughTheGzipHandle:
    @pytest.mark.parametrize("size", [1, 7, CHUNK, CHUNK + 1, len(BLOB)])
    async def test_binary_read_readline_and_iteration(self, size):
        reader = IterableReader(Source(size=size))
        async with aiogzip.open(None, "rb", fileobj=reader, chunk_size=CHUNK) as f:
            first = await f.readline()
            assert first == PAYLOAD.split(b"\n")[0] + b"\n"
            rest = await f.read()
            assert first + rest == PAYLOAD
            assert await f.tell() == len(PAYLOAD)
        assert reader.tell() == len(BLOB)
        assert not reader.closed  # closefd defaults to leaving it open

    @pytest.mark.parametrize("size", [1, 3, CHUNK, len(BLOB)])
    async def test_text_with_characters_and_crlf_split_across_items(self, size):
        reader = IterableReader(Source(size=size))
        async with aiogzip.open(None, "rt", fileobj=reader, closefd=True) as f:
            lines = [line async for line in f]
        assert "".join(lines) == TEXT.replace("\r\n", "\n")
        assert len(lines) == 3000
        assert reader.closed

        reader = IterableReader(Source(size=size))
        async with aiogzip.open(None, "rt", fileobj=reader, newline="") as f:
            assert await f.read() == TEXT

    async def test_text_iter_batches(self):
        reader = IterableReader(Source(size=1000))
        async with aiogzip.open(None, "rt", fileobj=reader, newline="") as f:
            batches = [batch async for batch in f.iter_batches()]
        assert "".join(line for batch in batches for line in batch) == TEXT

    async def test_backward_seek_replays_from_the_rewind_cache(self):
        source = Source(size=1000)
        reader = IterableReader(source)
        async with aiogzip.open(None, "rb", fileobj=reader) as f:
            head = await f.read(5000)
            pulled = source.pulled
            await f.seek(0)
            assert await f.read(5000) == head
            assert source.pulled == pulled  # replayed, not re-read
            await f.seek(100)
            assert await f.read() == PAYLOAD[100:]

    async def test_rewind_past_the_cache_limit_fails(self):
        reader = IterableReader(Source(size=1000))
        async with aiogzip.open(
            None, "rb", fileobj=reader, max_rewind_cache_size=2000
        ) as f:
            await f.read()
            with pytest.raises(OSError):
                await f.seek(0)

    async def test_source_is_not_read_ahead(self):
        source = Source(size=100)
        reader = IterableReader(source)
        async with aiogzip.open(None, "rb", fileobj=reader, chunk_size=CHUNK) as f:
            await f.read(1)
            assert source.pulled == 1

    async def test_limit_applies(self):
        reader = IterableReader(Source(size=1000))
        async with aiogzip.open(
            None, "rb", fileobj=reader, max_decompressed_size=1000
        ) as f:
            with pytest.raises(OSError, match="exceeded max_decompressed_size"):
                await f.read()

    async def test_whole_file_helper_and_inspection(self):
        data = await aiogzip.read(None, fileobj=IterableReader(Source(size=333)))
        assert data == PAYLOAD
        info = await aiogzip.inspect(None, fileobj=IterableReader(Source(size=333)))
        assert info.member_count == 2
        result = await aiogzip.verify(None, fileobj=IterableReader(Source(size=333)))
        assert result.uncompressed_size == len(PAYLOAD)

    async def test_early_exit_closes_an_async_generator(self):
        events = []

        async def body():
            try:
                for offset in range(0, len(BLOB), 500):
                    yield BLOB[offset : offset + 500]
            finally:
                events.append("cleanup")

        reader = IterableReader(body())
        async with aiogzip.open(None, "rt", fileobj=reader, closefd=True) as f:
            async for _line in f:
                break
        assert events == ["cleanup"]
        assert reader.closed

    async def test_source_exception_breaks_the_stream(self):
        source = Source(size=500, fail_at=3)
        reader = IterableReader(source)
        async with aiogzip.open(None, "rb", fileobj=reader, closefd=True) as f:
            with pytest.raises(ConnectionResetError, match="connection reset"):
                await f.read()
            with pytest.raises(ValueError, match="unusable"):
                reader.tell()
            # Input may be lost, so the handle does not retry the source.
            with pytest.raises(OSError, match="read stream is broken"):
                await f.read()
            assert source.pulled == 3
        assert reader.closed and source.closed == 1

    async def test_cancellation_during_anext_breaks_the_stream(self):
        source = Source(size=500, block_at=2)
        reader = IterableReader(source)
        f = aiogzip.open(None, "rb", fileobj=reader, closefd=True)
        async with f:
            task = asyncio.ensure_future(f.read())
            await source.blocked.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(ValueError, match="unusable"):
                reader.tell()
            with pytest.raises(OSError, match="read stream is broken"):
                await f.read()
            with pytest.raises(OSError, match="unusable"):
                await reader.read(1)
        assert reader.closed and source.closed == 1

    async def test_truncated_source_is_reported_as_bad_gzip(self):
        reader = IterableReader(Source(BLOB[:-5], 1000))
        async with aiogzip.open(None, "rb", fileobj=reader) as f:
            with pytest.raises((gzip.BadGzipFile, EOFError)):
                await f.read()

    async def test_write_mode_rejects_it(self):
        reader = IterableReader(Source())
        with pytest.raises((TypeError, ValueError, OSError, AttributeError)):
            async with aiogzip.open(None, "wb", fileobj=reader) as f:
                await f.write(b"x")

    @settings(
        max_examples=60,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        cuts=st.lists(st.integers(min_value=0, max_value=len(BLOB)), max_size=30),
        read_size=st.sampled_from([1, 17, 1000, -1]),
        chunk_size=st.sampled_from([1, 64, CHUNK, 262144]),
    )
    def test_any_split_of_the_stream_reads_the_same(self, cuts, read_size, chunk_size):
        edges = [0, *sorted(cuts), len(BLOB)]
        items = [BLOB[a:b] for a, b in zip(edges, edges[1:], strict=False)]

        async def run():
            reader = IterableReader(_items(*items))
            parts = []
            async with aiogzip.open(
                None, "rb", fileobj=reader, chunk_size=chunk_size
            ) as f:
                if read_size == 1:
                    parts.append(await f.read(1))
                    parts.append(await f.read())
                else:
                    while chunk := await f.read(read_size):
                        parts.append(chunk)
            assert reader.tell() == len(BLOB)
            return b"".join(parts)

        assert asyncio.run(run()) == PAYLOAD


def test_exported():
    assert "IterableReader" in aiogzip.__all__
    assert aiogzip.IterableReader is IterableReader
    assert IterableReader.__module__ == "aiogzip._iterable_reader"
