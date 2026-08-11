# pyrefly: ignore
# pyrefly: disable=all
import gzip
import io
import os
import zlib

import pytest

from aiogzip import AsyncGzipBinaryFile


class NonSeekableAsyncReader:
    """Async reader without a seek method, forcing the rewind replay cache."""

    def __init__(self, data: bytes):
        self._buffer = io.BytesIO(data)

    async def read(self, size=-1):
        return self._buffer.read(size)

    async def close(self):
        pass


class TestFileobjSupport:
    """Tests for wrapping an existing async file-like object via fileobj."""

    async def test_fileobj_roundtrip(self, tmp_path):
        p = tmp_path / "via_fileobj.gz"

        import aiofiles

        async with aiofiles.open(p, "wb") as raw:
            async with AsyncGzipBinaryFile(None, "wb", fileobj=raw, closefd=False) as f:
                await f.write(b"hello fileobj")

        async with aiofiles.open(p, "rb") as raw_r:
            async with AsyncGzipBinaryFile(
                None, "rb", fileobj=raw_r, closefd=False
            ) as f:
                data = await f.read()
                assert data == b"hello fileobj"

    async def test_short_writing_fileobj_is_retried_until_complete(self):
        class ShortWriter:
            def __init__(self, max_write):
                self.max_write = max_write
                self.buffer = bytearray()
                self.calls = 0

            async def write(self, data):
                self.calls += 1
                written = min(self.max_write, len(data))
                self.buffer.extend(data[:written])
                return written

            async def close(self):
                pass

        payload = os.urandom(512 * 1024)
        writer = ShortWriter(max_write=7)
        async with AsyncGzipBinaryFile(
            None, "wb", fileobj=writer, closefd=False, mtime=0
        ) as f:
            await f.write(payload)

        assert writer.calls > 3
        assert gzip.decompress(bytes(writer.buffer)) == payload

    async def test_zero_progress_write_breaks_active_member(self):
        class StallingWriter:
            def __init__(self):
                self.calls = 0

            async def write(self, data):
                self.calls += 1
                if self.calls == 2:
                    return 0
                return len(data)

            async def close(self):
                pass

        writer = StallingWriter()
        f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False)
        await f.open()
        with pytest.raises(OSError, match="made no progress"):
            await f.write(os.urandom(512 * 1024))
        assert f._write_broken is True
        with pytest.raises(OSError, match="broken"):
            await f.write(b"more")
        await f.close()

    async def test_sink_failure_after_one_codec_chunk_keeps_position_uncommitted(self):
        class FailAfterOneDataChunk:
            def __init__(self):
                self.buffer = bytearray()
                self.calls = 0
                self.fail_on_call = None

            async def write(self, data):
                self.calls += 1
                if self.calls == self.fail_on_call:
                    raise OSError("second codec chunk failed")
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = FailAfterOneDataChunk()
        f = AsyncGzipBinaryFile(
            None,
            "wb",
            fileobj=writer,
            closefd=False,
            chunk_size=1024,
        )
        await f.open()
        header_size = len(writer.buffer)
        writer.fail_on_call = writer.calls + 2

        with pytest.raises(OSError, match="second codec chunk failed"):
            await f.write(os.urandom(512 * 1024))

        assert len(writer.buffer) >= header_size + 1024
        assert await f.tell() == 0
        assert f._write_broken is True
        size_before_close = len(writer.buffer)
        await f.close()
        assert len(writer.buffer) == size_before_close

    async def test_cancelled_underlying_flush_breaks_member_without_trailer(self):
        import asyncio

        class BlockingFlushWriter:
            def __init__(self):
                self.buffer = bytearray()
                self.flush_started = asyncio.Event()

            async def write(self, data):
                self.buffer.extend(data)
                return len(data)

            async def flush(self):
                self.flush_started.set()
                await asyncio.Event().wait()

            async def close(self):
                pass

        writer = BlockingFlushWriter()
        f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False)
        await f.open()
        await f.write(b"pending data")

        task = asyncio.create_task(f.flush())
        await writer.flush_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert f._write_broken is True
        size_before_close = len(writer.buffer)
        await f.close()
        assert len(writer.buffer) == size_before_close

    async def test_cancelled_sink_write_breaks_member_without_trailer(self):
        import asyncio

        class BlockingDataWriter:
            def __init__(self):
                self.buffer = bytearray()
                self.calls = 0
                self.write_started = asyncio.Event()

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.write_started.set()
                    await asyncio.Event().wait()
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = BlockingDataWriter()
        f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False, mtime=0)
        await f.open()
        header = bytes(writer.buffer)
        task = asyncio.create_task(f.write(os.urandom(512 * 1024)))
        await writer.write_started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert f._write_broken is True
        await f.close()
        assert bytes(writer.buffer) == header

    @pytest.mark.parametrize("invalid_count", [None, -1, True, 1000])
    async def test_invalid_write_count_fails_open(self, invalid_count):
        class InvalidWriter:
            async def write(self, data):
                return invalid_count

            async def close(self):
                pass

        f = AsyncGzipBinaryFile(None, "wb", fileobj=InvalidWriter(), closefd=False)
        with pytest.raises(OSError, match="invalid byte count|no progress|requested"):
            await f.open()

    @pytest.mark.parametrize("invalid_count", [None, -1, True, 10**9])
    async def test_invalid_data_write_count_poisoning_is_call_local(
        self, invalid_count
    ):
        class InvalidDataWriter:
            def __init__(self):
                self.calls = 0
                self.buffer = bytearray()

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    return invalid_count
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = InvalidDataWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False)
        await stream.open()
        header = bytes(writer.buffer)

        with pytest.raises(OSError, match="invalid byte count|no progress|requested"):
            await stream.write(os.urandom(512 * 1024))
        assert await stream.tell() == 0
        assert stream._write_broken is True
        with pytest.raises(OSError, match="broken"):
            await stream.write(b"later")

        await stream.close()
        assert bytes(writer.buffer) == header

    async def test_position_and_return_value_commit_after_sink_completion(self):
        import asyncio

        class BlockingDataWriter:
            def __init__(self):
                self.calls = 0
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.started.set()
                    await self.release.wait()
                return len(data)

            async def close(self):
                pass

        payload = os.urandom(512 * 1024)
        writer = BlockingDataWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False)
        await stream.open()
        task = asyncio.create_task(stream.write(payload))
        await writer.started.wait()
        assert await stream.tell() == 0

        writer.release.set()
        assert await task == len(payload)
        assert await stream.tell() == len(payload)
        assert stream._encoder is not None
        assert await stream.tell() == stream._encoder.input_size
        await stream.close()

    async def test_overlapping_write_gap_is_rejected_without_poisoning(
        self, monkeypatch
    ):
        import asyncio

        import aiogzip._binary as binary_module

        class BufferWriter:
            def __init__(self):
                self.buffer = bytearray()

            async def write(self, data):
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        operation_released = asyncio.Event()
        operation_reserved = asyncio.Event()
        advance_operation = asyncio.Event()
        publish_position = asyncio.Event()

        async def controlled_drive(operation, **kwargs):
            operation_reserved.set()
            await advance_operation.wait()
            for piece in operation:
                yield piece
            operation_released.set()
            await publish_position.wait()

        monkeypatch.setattr(binary_module, "_drive_operation", controlled_drive)
        payload = b"x" * (256 * 1024)
        writer = BufferWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False, mtime=0)
        await stream.open()

        first = asyncio.create_task(stream.write(payload))
        await operation_reserved.wait()
        with pytest.raises(RuntimeError, match="active write or flush"):
            await stream.close()
        assert stream.closed is False
        assert stream._write_broken is False

        advance_operation.set()
        await operation_released.wait()
        with pytest.raises(RuntimeError, match="active write or flush"):
            await stream.write(b"overlap")
        assert stream._write_broken is False

        publish_position.set()
        assert await first == len(payload)
        assert await stream.write(b"after") == 5
        await stream.close()
        assert gzip.decompress(bytes(writer.buffer)) == payload + b"after"

    async def test_write_during_underlying_flush_is_rejected_without_poisoning(self):
        import asyncio

        class BlockingFlushWriter:
            def __init__(self):
                self.buffer = bytearray()
                self.flush_started = asyncio.Event()
                self.release_flush = asyncio.Event()

            async def write(self, data):
                self.buffer.extend(data)
                return len(data)

            async def flush(self):
                self.flush_started.set()
                await self.release_flush.wait()

            async def close(self):
                pass

        writer = BlockingFlushWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False, mtime=0)
        await stream.open()
        await stream.write(b"before flush")

        flushing = asyncio.create_task(stream.flush())
        await writer.flush_started.wait()
        with pytest.raises(RuntimeError, match="active write or flush"):
            await stream.write(b"overlap")
        with pytest.raises(RuntimeError, match="active write or flush"):
            await stream.close()
        assert stream.closed is False
        assert stream._write_broken is False

        writer.release_flush.set()
        await flushing
        assert await stream.write(b" after flush") == 12
        await stream.close()
        assert gzip.decompress(bytes(writer.buffer)) == b"before flush after flush"

    async def test_flush_is_distinct_from_ordinary_small_write(self):
        class RecordingWriter:
            def __init__(self):
                self.buffer = bytearray()
                self.calls = 0

            async def write(self, data):
                self.calls += 1
                self.buffer.extend(data)
                return len(data)

            async def flush(self):
                pass

            async def close(self):
                pass

        writer = RecordingWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False, mtime=0)
        await stream.open()
        calls_after_header = writer.calls
        assert await stream.write(b"small pending payload") == 21
        assert writer.calls == calls_after_header

        await stream.flush()
        assert writer.calls > calls_after_header
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        assert decompressor.decompress(bytes(writer.buffer)) == b"small pending payload"
        assert decompressor.eof is False
        await stream.close()

    async def test_non_seekable_fileobj_supports_backward_seek(self):
        payload = b"abcdefghijklmnopqrstuvwxyz"
        compressed = gzip.compress(payload)

        reader = NonSeekableAsyncReader(compressed)
        async with AsyncGzipBinaryFile(None, "rb", fileobj=reader, closefd=False) as f:
            assert f.seekable()
            assert await f.read(10) == payload[:10]
            assert await f.seek(5) == 5
            assert await f.read(4) == payload[5:9]

    async def test_non_seekable_rewind_cache_can_be_capped(self):
        payload = os.urandom(1024)
        compressed = gzip.compress(payload)

        reader = NonSeekableAsyncReader(compressed)
        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            max_rewind_cache_size=32,
        ) as f:
            assert await f.read() == payload
            assert not f.seekable()
            with pytest.raises(OSError, match="not seekable|rewind cache"):
                await f.seek(0)

    def test_max_rewind_cache_size_validated(self):
        with pytest.raises(ValueError, match="max_rewind_cache_size"):
            AsyncGzipBinaryFile("test.gz", "rb", max_rewind_cache_size=0)

        with pytest.raises(ValueError, match="max_rewind_cache_size"):
            AsyncGzipBinaryFile("test.gz", "rb", max_rewind_cache_size=-1)

    async def test_fileobj_with_failing_seek_uses_replay_cache(self):
        payload = b"abcdefghijklmnopqrstuvwxyz"
        compressed = gzip.compress(payload)

        class FailingSeekReader(NonSeekableAsyncReader):
            async def seek(self, offset, whence=os.SEEK_SET):
                raise OSError("not actually seekable")

            def seekable(self):
                return False

        reader = FailingSeekReader(compressed)
        async with AsyncGzipBinaryFile(None, "rb", fileobj=reader, closefd=False) as f:
            assert f.seekable()
            assert await f.read(10) == payload[:10]
            assert await f.seek(5) == 5
            assert await f.read(4) == payload[5:9]

    async def test_fileobj_with_raising_seekable_falls_back_to_replay_cache(self):
        """seekable() raising should fall back to replay caching, not crash."""
        payload = b"abcdefghijklmnopqrstuvwxyz"
        compressed = gzip.compress(payload)

        class RaisingSeekableReader(NonSeekableAsyncReader):
            async def seek(self, offset, whence=os.SEEK_SET):
                raise OSError("seek also fails")

            def seekable(self):
                raise RuntimeError("seekable() is broken")

        reader = RaisingSeekableReader(compressed)
        async with AsyncGzipBinaryFile(None, "rb", fileobj=reader, closefd=False) as f:
            assert f.seekable()
            assert await f.read(10) == payload[:10]
            assert await f.seek(0) == 0
            assert await f.read() == payload

    async def test_non_seekable_rewind_cache_unbounded_when_none(self):
        """max_rewind_cache_size=None preserves the pre-1.5 unbounded behavior."""
        payload = os.urandom(256 * 1024)
        compressed = gzip.compress(payload)

        reader = NonSeekableAsyncReader(compressed)
        async with AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=False,
            max_rewind_cache_size=None,
        ) as f:
            assert await f.read() == payload
            assert f.seekable()
            assert await f.seek(0) == 0
            assert await f.read() == payload
