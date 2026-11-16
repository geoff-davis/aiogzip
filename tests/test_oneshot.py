"""One-shot ``compress()`` and ``decompress()`` for a payload in memory (#200).

``aiogzip.compress()`` and ``aiogzip.decompress()`` are coroutines;
``aiogzip.codec.compress()`` and ``aiogzip.codec.decompress()`` are their
synchronous twins. Both pairs drive one codec, so each property here is
checked on both.
"""

import asyncio
import gzip
import inspect
import linecache
import os
import threading
import tracemalloc
import warnings

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import aiogzip
from aiogzip import _codec_async as driver
from aiogzip import _engine, codec

MIB = 1024 * 1024
LIMIT_PREFIX = "decompressed output exceeded max_decompressed_size"

_payloads = st.one_of(
    st.binary(max_size=4096),
    st.builds(
        lambda token, n: (token * (n // len(token) + 1))[:n],
        st.binary(min_size=1, max_size=8),
        st.integers(min_value=0, max_value=600_000),
    ),
)
_settings = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


async def _async_pair(data, compress_options, decompress_options):
    blob = await aiogzip.compress(data, **compress_options)
    return blob, await aiogzip.decompress(blob, **decompress_options)


class TestParityWithGzip:
    @_settings
    @given(
        payload=_payloads,
        level=st.integers(min_value=-1, max_value=9),
        fast=st.booleans(),
    )
    def test_compress_output_is_what_gzip_reads(self, payload, level, fast):
        options = {"compresslevel": level, "mtime": 0, "fast_compress": fast}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sync_blob = codec.compress(payload, **options)
            async_blob = asyncio.run(aiogzip.compress(payload, **options))
        assert gzip.decompress(sync_blob) == payload
        assert async_blob == sync_blob

    @_settings
    @given(
        members=st.lists(_payloads, min_size=0, max_size=4),
        level=st.integers(min_value=0, max_value=9),
        padding=st.integers(min_value=0, max_value=600),
    )
    def test_decompress_matches_gzip_on_members_and_padding(
        self, members, level, padding
    ):
        blob = b"".join(gzip.compress(m, compresslevel=level) for m in members)
        if members:
            blob += bytes(padding)
        expected = gzip.decompress(blob)
        assert expected == b"".join(members)
        assert codec.decompress(blob) == expected
        assert asyncio.run(aiogzip.decompress(blob)) == expected

    @_settings
    @given(payload=_payloads, cut=st.integers(min_value=1, max_value=40))
    def test_truncation_is_rejected_as_gzip_rejects_it(self, payload, cut):
        whole = gzip.compress(payload)
        blob = whole[: -(cut % (len(whole) - 1) + 1)]
        assert blob
        with pytest.raises((EOFError, gzip.BadGzipFile)):
            gzip.decompress(blob)
        with pytest.raises(gzip.BadGzipFile):
            codec.decompress(blob)
        with pytest.raises(gzip.BadGzipFile):
            asyncio.run(aiogzip.decompress(blob))

    async def test_empty_input_and_empty_payload(self):
        assert gzip.decompress(b"") == b""
        assert codec.decompress(b"") == b""
        assert await aiogzip.decompress(b"") == b""
        blob = await aiogzip.compress(b"", mtime=0)
        assert blob == codec.compress(b"", mtime=0)
        assert gzip.decompress(blob) == b""

    async def test_corrupt_payload_raises_bad_gzip_file(self):
        blob = bytearray(gzip.compress(os.urandom(4096)))
        blob[len(blob) // 2] ^= 0xFF
        with pytest.raises(gzip.BadGzipFile):
            codec.decompress(bytes(blob))
        with pytest.raises(gzip.BadGzipFile):
            await aiogzip.decompress(blob)

    async def test_not_gzip_names_the_format(self):
        zstd = b"\x28\xb5\x2f\xfd" + bytes(16)
        with pytest.raises(gzip.BadGzipFile, match="looks like Zstandard"):
            await aiogzip.decompress(zstd)
        with pytest.raises(gzip.BadGzipFile, match="looks like Zstandard"):
            codec.decompress(zstd)


class TestOptions:
    async def test_mtime_zero_is_reproducible(self):
        first = await aiogzip.compress(b"payload", mtime=0)
        assert first == await aiogzip.compress(b"payload", mtime=0)
        assert first == codec.compress(b"payload", mtime=0)
        assert first[4:8] == bytes(4)

    async def test_default_mtime_is_the_current_time(self):
        blob = await aiogzip.compress(b"payload")
        assert int.from_bytes(blob[4:8], "little") > 1_700_000_000
        assert int.from_bytes(codec.compress(b"x")[4:8], "little") > 1_700_000_000

    @pytest.mark.parametrize("name", ["report.csv", b"report.csv"])
    async def test_original_filename_is_stored(self, name):
        for blob in (
            await aiogzip.compress(b"x", original_filename=name, mtime=0),
            codec.compress(b"x", original_filename=name, mtime=0),
        ):
            decoder = aiogzip.GzipDecoder(collect_member_info=True)
            assert b"".join([*decoder.feed(blob), *decoder.finish()]) == b"x"
            assert decoder.members[0].original_filename == "report.csv"

    async def test_no_filename_by_default(self):
        blob = await aiogzip.compress(b"x", mtime=0)
        decoder = aiogzip.GzipDecoder(collect_member_info=True)
        b"".join([*decoder.feed(blob), *decoder.finish()])
        assert decoder.members[0].original_filename is None

    async def test_compresslevel_changes_the_output(self):
        payload = b"abcdefgh" * 5000
        stored = await aiogzip.compress(payload, compresslevel=0, mtime=0)
        best = await aiogzip.compress(payload, compresslevel=9, mtime=0)
        assert len(best) < len(payload) < len(stored)
        assert codec.compress(payload, compresslevel=0, mtime=0) == stored

    @pytest.mark.parametrize(
        ("options", "error"),
        [
            ({"compresslevel": 10}, ValueError),
            ({"compresslevel": "6"}, TypeError),
            ({"mtime": -1}, ValueError),
            ({"fast_compress": 1}, TypeError),
            ({"strict_size": None}, TypeError),
            ({"original_filename": 3}, TypeError),
        ],
    )
    async def test_invalid_compress_option(self, options, error):
        with pytest.raises(error):
            codec.compress(b"x", **options)
        call = aiogzip.compress(b"x", **options)  # raises when awaited
        with pytest.raises(error):
            await call

    @pytest.mark.parametrize(
        ("limit", "error"),
        [(0, ValueError), (-1, ValueError), ("1", TypeError), (1.5, TypeError)],
    )
    async def test_invalid_limit(self, limit, error):
        blob = gzip.compress(b"x")
        with pytest.raises(error):
            codec.decompress(blob, max_decompressed_size=limit)
        with pytest.raises(error):
            await aiogzip.decompress(blob, max_decompressed_size=limit)

    def test_options_are_keyword_only(self):
        with pytest.raises(TypeError):
            codec.compress(b"x", 6)
        with pytest.raises(TypeError):
            codec.decompress(b"x", 10)
        with pytest.raises(TypeError):
            aiogzip.compress(b"x", 6)
        with pytest.raises(TypeError):
            aiogzip.decompress(b"x", 10)


class _Hostile(bytes):
    """A bytes subclass whose overrides would corrupt a naive snapshot."""

    def __bytes__(self):
        raise AssertionError("__bytes__ called")

    def __len__(self):
        return 0

    def __getitem__(self, item):
        raise AssertionError("__getitem__ called")

    def __iter__(self):
        raise AssertionError("__iter__ called")


class TestInputTypes:
    async def test_async_accepts_bytes_bytearray_and_memoryview(self):
        payload = os.urandom(1000)
        expected = await aiogzip.compress(payload, mtime=0)
        for data in (bytearray(payload), memoryview(payload), _Hostile(payload)):
            blob = await aiogzip.compress(data, mtime=0)
            assert blob == expected
        for data in (bytearray(expected), memoryview(expected), _Hostile(expected)):
            assert await aiogzip.decompress(data) == payload

    async def test_views_are_flattened(self):
        payload = bytes(range(256)) * 4
        strided = memoryview(payload)[::2]
        blob = await aiogzip.compress(strided, mtime=0)
        assert gzip.decompress(blob) == payload[::2]
        words = memoryview(payload).cast("I")
        assert gzip.decompress(await aiogzip.compress(words, mtime=0)) == payload
        compressed = gzip.compress(b"x" * 100)
        doubled = bytes(b for byte in compressed for b in (byte, 0))
        assert await aiogzip.decompress(memoryview(doubled)[::2]) == b"x" * 100

    @pytest.mark.parametrize("data", ["text", 3, None, [1, 2], 1.5])
    async def test_async_rejects_other_types(self, data):
        with pytest.raises(TypeError, match=r"compress\(\) argument must be bytes"):
            await aiogzip.compress(data)
        with pytest.raises(TypeError, match=r"decompress\(\) argument must be bytes"):
            await aiogzip.decompress(data)

    @pytest.mark.parametrize(
        "data", [bytearray(b"x"), memoryview(b"x"), "text", None, 3]
    )
    def test_codec_twins_take_bytes_only(self, data):
        with pytest.raises(TypeError, match="gzip codec input must be bytes"):
            codec.compress(data)
        with pytest.raises(TypeError, match="gzip codec input must be bytes"):
            codec.decompress(data)

    def test_codec_twins_snapshot_a_bytes_subclass(self):
        payload = os.urandom(500)
        blob = codec.compress(_Hostile(payload), mtime=0)
        assert blob == codec.compress(payload, mtime=0)
        assert codec.decompress(_Hostile(blob)) == payload

    def test_type_is_checked_before_the_options(self):
        with pytest.raises(TypeError, match="gzip codec input must be bytes"):
            codec.compress("text", compresslevel=99)

    async def test_mutable_input_is_copied_before_the_first_suspension(self):
        payload = os.urandom(2 * MIB)
        buffer = bytearray(payload)
        task = asyncio.ensure_future(aiogzip.compress(buffer, mtime=0))
        await asyncio.sleep(0)
        assert not task.done()  # suspended in the executor step
        buffer[:] = bytes(len(buffer))
        assert gzip.decompress(await task) == payload

        blob = await aiogzip.compress(payload, compresslevel=0, mtime=0)
        buffer = bytearray(blob)
        task = asyncio.ensure_future(aiogzip.decompress(buffer))
        await asyncio.sleep(0)
        assert not task.done()
        buffer[:] = bytes(len(buffer))
        assert await task == payload


def _past_limit(size):
    return rf"{LIMIT_PREFIX} \({size + 1} > {size} bytes\)"


class TestLimit:
    @pytest.mark.parametrize("size", [1, 1000, 300_000, 3 * MIB])
    async def test_at_the_limit_and_one_byte_past_it(self, size):
        at_limit = gzip.compress(bytes(size))
        past = gzip.compress(bytes(size + 1))
        assert codec.decompress(at_limit, max_decompressed_size=size) == bytes(size)
        assert await aiogzip.decompress(at_limit, max_decompressed_size=size) == bytes(
            size
        )
        with pytest.raises(OSError, match=_past_limit(size)) as caught:
            codec.decompress(past, max_decompressed_size=size)
        assert type(caught.value) is OSError
        with pytest.raises(OSError, match=_past_limit(size)) as caught:
            await aiogzip.decompress(past, max_decompressed_size=size)
        assert type(caught.value) is OSError

    async def test_limit_counts_all_members(self):
        blob = gzip.compress(bytes(600)) + gzip.compress(bytes(600))
        assert len(await aiogzip.decompress(blob, max_decompressed_size=1200)) == 1200
        with pytest.raises(OSError, match=LIMIT_PREFIX):
            await aiogzip.decompress(blob, max_decompressed_size=1199)
        with pytest.raises(OSError, match=LIMIT_PREFIX):
            codec.decompress(blob, max_decompressed_size=1199)

    @pytest.mark.parametrize("use_async", [False, True])
    async def test_expansion_past_the_limit_is_never_held(self, use_async):
        """A 64 MiB bomb with a 1 MiB limit allocates about the limit."""
        bomb = gzip.compress(bytes(64 * MIB), compresslevel=1)
        assert len(bomb) < MIB // 2
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            before = tracemalloc.get_traced_memory()[0]
            with pytest.raises(OSError, match=_past_limit(MIB)):
                if use_async:
                    await aiogzip.decompress(bomb, max_decompressed_size=MIB)
                else:
                    codec.decompress(bomb, max_decompressed_size=MIB)
            peak = tracemalloc.get_traced_memory()[1] - before
        finally:
            tracemalloc.stop()
        # The parts collected so far (at most the limit) plus working buffers.
        assert peak < 3 * MIB

    @pytest.mark.parametrize("use_async", [False, True])
    async def test_output_at_the_limit_is_joined_once(self, use_async):
        """Peak for an accepted 16 MiB result is the parts plus one joined copy."""
        size = 16 * MIB
        blob = gzip.compress(bytes(size), compresslevel=1)
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            before = tracemalloc.get_traced_memory()[0]
            if use_async:
                result = await aiogzip.decompress(blob, max_decompressed_size=size)
            else:
                result = codec.decompress(blob, max_decompressed_size=size)
            peak = tracemalloc.get_traced_memory()[1] - before
        finally:
            tracemalloc.stop()
        assert len(result) == size
        assert peak < 2 * size + 3 * MIB

    @pytest.mark.parametrize("use_async", [False, True])
    async def test_many_tiny_members_cost_no_memory_per_member(self, use_async):
        """100,000 one-byte members: a chunk each, but no object kept for each."""
        count = 100_000
        blob = gzip.compress(b"x") * count
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            before = tracemalloc.get_traced_memory()[0]
            if use_async:
                result = await aiogzip.decompress(blob, max_decompressed_size=count)
            else:
                result = codec.decompress(blob, max_decompressed_size=count)
            peak = tracemalloc.get_traced_memory()[1] - before
        finally:
            tracemalloc.stop()
        assert result == b"x" * count
        # The decoder's fixed working buffers, under 1 MiB. One bytes object
        # for each member would add more than 3 MiB.
        assert peak < 2 * MIB


class TestOutputCollector:
    @_settings
    @given(
        sizes=st.lists(
            st.sampled_from([0, 1, 7, 4096, 65535, 65536, 65537, 200_000]),
            max_size=40,
        )
    )
    def test_join_is_the_concatenation_in_order(self, sizes):
        chunks = [bytes([index % 251]) * size for index, size in enumerate(sizes)]
        collector = codec._OutputCollector()
        for chunk in chunks:
            collector.add(chunk)
        assert collector.join() == b"".join(chunks)

    def test_small_chunks_are_stored_in_large_pieces(self):
        collector = codec._OutputCollector()
        for _ in range(300_000):
            collector.add(b"x")
        assert len(collector._parts) == 300_000 // codec._COLLECT_SMALL_CHUNK
        assert all(len(p) == codec._COLLECT_SMALL_CHUNK for p in collector._parts)
        assert collector.join() == b"x" * 300_000

    def test_one_large_chunk_is_returned_without_a_copy(self):
        chunk = os.urandom(codec._COLLECT_SMALL_CHUNK)
        collector = codec._OutputCollector()
        collector.add(chunk)
        assert collector.join() is chunk

    def test_empty(self):
        assert codec._OutputCollector().join() == b""


class _Offloads:
    """Count the executor hops the shared driver makes."""

    def __init__(self, monkeypatch):
        self.sizes = []
        original = driver._run_in_thread

        async def counting(method, data):
            self.sizes.append(len(data))
            return await original(method, data)

        monkeypatch.setattr(driver, "_run_in_thread", counting)


class TestOffload:
    async def test_small_compress_runs_inline(self, monkeypatch):
        offloads = _Offloads(monkeypatch)
        payload = os.urandom(driver._ZLIB_OFFLOAD_THRESHOLD - 1)
        assert gzip.decompress(await aiogzip.compress(payload)) == payload
        assert offloads.sizes == []

    async def test_large_compress_is_offloaded_once(self, monkeypatch):
        offloads = _Offloads(monkeypatch)
        payload = os.urandom(driver._ZLIB_OFFLOAD_THRESHOLD)
        assert gzip.decompress(await aiogzip.compress(payload)) == payload
        assert offloads.sizes == [len(payload)]

    async def test_decompress_uses_the_decode_threshold(self, monkeypatch):
        offloads = _Offloads(monkeypatch)
        payload = os.urandom(driver._DECODE_OFFLOAD_THRESHOLD + 4096)
        small = gzip.compress(payload[: driver._DECODE_OFFLOAD_THRESHOLD // 2], 0)
        assert len(small) < driver._DECODE_OFFLOAD_THRESHOLD
        await aiogzip.decompress(small)
        assert offloads.sizes == []
        large = gzip.compress(payload, compresslevel=0)
        assert len(large) >= driver._DECODE_OFFLOAD_THRESHOLD
        assert await aiogzip.decompress(large) == payload
        assert offloads.sizes == [len(large)]

    async def test_empty_payload_makes_no_executor_hop(self, monkeypatch):
        offloads = _Offloads(monkeypatch)
        assert await aiogzip.decompress(await aiogzip.compress(b"")) == b""
        assert offloads.sizes == []

    async def test_inline_decompression_yields_to_the_event_loop(self):
        """A small bomb inflates inline; other tasks still run during it."""
        size = 32 * MIB
        blob = gzip.compress(bytes(size), compresslevel=1)
        assert len(blob) < driver._DECODE_OFFLOAD_THRESHOLD
        turns = 0
        done = False

        async def other_task():
            nonlocal turns
            while not done:
                turns += 1
                await asyncio.sleep(0)

        ticker = asyncio.ensure_future(other_task())
        result = await aiogzip.decompress(blob)
        done = True
        await ticker
        assert len(result) == size
        # One checkpoint for each 1 MiB of inline output.
        assert turns >= size // driver._INLINE_OUTPUT_BYTES_CHECKPOINT - 1

    async def test_codec_twins_never_touch_the_event_loop(self, monkeypatch):
        offloads = _Offloads(monkeypatch)
        payload = os.urandom(2 * MIB)

        def run():
            return codec.decompress(codec.compress(payload))

        assert await asyncio.to_thread(run) == payload
        assert offloads.sizes == []


class TestCancellation:
    @pytest.mark.parametrize("operation", ["compress", "decompress"])
    async def test_cancelled_call_waits_for_its_native_step(
        self, operation, monkeypatch
    ):
        payload = os.urandom(2 * MIB)
        blob = gzip.compress(payload, compresslevel=0)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        original = driver._raw_next_or_done

        def blocking(op, workload):
            if threading.current_thread() is threading.main_thread():
                return original(op, workload)
            started.set()
            assert release.wait(30)
            try:
                return original(op, workload)
            finally:
                finished.set()

        monkeypatch.setattr(driver, "_raw_next_or_done", blocking)
        if operation == "compress":
            call = aiogzip.compress(payload)
        else:
            call = aiogzip.decompress(blob)
        task = asyncio.ensure_future(call)
        assert await asyncio.to_thread(started.wait, 30)
        task.cancel()
        for _ in range(20):
            await asyncio.sleep(0)
        assert not task.done()
        assert not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    async def test_collection_failure_closes_the_operation_first(self):
        """If keeping a chunk fails, the operation is closed before return."""
        from aiogzip import _oneshot

        failure = MemoryError("no room")

        class Full:
            def add(self, chunk):
                raise failure

        decoder = codec.GzipDecoder()
        operation = decoder.feed(gzip.compress(b"payload"))
        with pytest.raises(MemoryError) as caught:
            await _oneshot._collect(Full(), operation)
        assert caught.value is failure
        # Closed already, not on a later turn of the event loop: the decoder
        # has no active operation and is unusable.
        with pytest.raises(OSError, match="unusable"):
            decoder.finish()

    async def test_codec_is_discarded_when_a_call_fails(self, monkeypatch):
        made = []

        class Recording(codec.GzipDecoder):
            def __init__(self, **options):
                super().__init__(**options)
                made.append(self)

        from aiogzip import _oneshot

        monkeypatch.setattr(_oneshot, "GzipDecoder", Recording)
        with pytest.raises(gzip.BadGzipFile):
            await aiogzip.decompress(b"not gzip at all")
        assert await aiogzip.decompress(gzip.compress(b"ok")) == b"ok"
        assert len(made) == 2
        for decoder in made:
            with pytest.raises(OSError, match="unusable"):
                decoder.feed(b"")


class TestFallbackWarning:
    """Without zlib-ng, ``fast_compress=True`` warns at the caller's line."""

    @pytest.fixture(autouse=True)
    def _no_zlib_ng(self, monkeypatch):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)

    async def test_warning_names_the_calling_line(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            for _ in range(3):
                blob = await aiogzip.compress(b"x", fast_compress=True, mtime=0)
            for _ in range(3):
                assert codec.compress(b"x", fast_compress=True, mtime=0) == blob
        first, second = [
            w for w in caught if "zlib-ng is not available" in str(w.message)
        ]
        assert first.category is second.category is UserWarning
        assert first.filename == second.filename == __file__
        assert "await aiogzip.compress(" in linecache.getline(
            first.filename, first.lineno
        )
        assert "codec.compress(" in linecache.getline(second.filename, second.lineno)
        assert blob == codec.compress(b"x", mtime=0)

    async def test_no_warning_without_the_request(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            await aiogzip.decompress(await aiogzip.compress(b"x"))
            codec.decompress(codec.compress(b"x"))


class TestSurface:
    def test_names_are_exported(self):
        assert {"compress", "decompress"} <= set(aiogzip.__all__)
        assert {"compress", "decompress"} <= set(codec.__all__)
        assert inspect.iscoroutinefunction(aiogzip.compress)
        assert inspect.iscoroutinefunction(aiogzip.decompress)
        assert not inspect.iscoroutinefunction(codec.compress)
        assert not inspect.iscoroutinefunction(codec.decompress)
        assert aiogzip.compress is not codec.compress
        assert aiogzip.decompress is not codec.decompress

    async def test_round_trip_through_each_pairing(self):
        payload = os.urandom(5000) + bytes(5000)
        blob, restored = await _async_pair(payload, {"mtime": 0}, {})
        assert restored == payload
        assert codec.decompress(blob) == payload
        assert await aiogzip.decompress(codec.compress(payload)) == payload
        chunks = [c async for c in aiogzip.decompress_chunks(_one(blob))]
        assert b"".join(chunks) == payload


async def _one(item):
    yield item
