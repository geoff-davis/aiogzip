# pyrefly: ignore
# pyrefly: disable=all
import asyncio

import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
    ConcurrentOperationError,
)


class TestClosefdParameter:
    """Test closefd parameter behavior."""

    async def test_closefd_true_closes_file(self, tmp_path):
        import aiofiles

        p = tmp_path / "test_closefd_true.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipBinaryFile(
            None, "wb", fileobj=file_handle, closefd=True
        ) as f:
            await f.write(b"test data")

        with pytest.raises((ValueError, AttributeError)):
            await file_handle.write(b"more data")

    async def test_closefd_false_keeps_file_open(self, tmp_path):
        import aiofiles

        p = tmp_path / "test_closefd_false.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipBinaryFile(
            None, "wb", fileobj=file_handle, closefd=False
        ) as f:
            await f.write(b"test data")

        await file_handle.write(b"more data")
        await file_handle.close()

        async with aiofiles.open(p, "rb") as f:
            content = await f.read()

        assert len(content) > 0

    async def test_closefd_default_with_fileobj_keeps_file_open(self, tmp_path):
        import aiofiles

        p = tmp_path / "test_closefd_default_fileobj.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipBinaryFile(None, "wb", fileobj=file_handle) as f:
            await f.write(b"test data")

        await file_handle.write(b"more data")
        await file_handle.close()

    async def test_closefd_default_closes_owned_file(self, tmp_path):
        p = tmp_path / "test_closefd_default.gz"

        f = AsyncGzipBinaryFile(p, "wb")
        async with f:
            await f.write(b"test data")

        assert f._is_closed is True

    async def test_closefd_with_text_file(self, tmp_path):
        import aiofiles

        p = tmp_path / "test_text_closefd.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipTextFile(
            None, "wt", fileobj=file_handle, closefd=False
        ) as f:
            await f.write("test text")

        await file_handle.close()

    async def test_closefd_default_with_text_fileobj_keeps_file_open(self, tmp_path):
        import aiofiles

        p = tmp_path / "test_text_closefd_default.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipTextFile(None, "wt", fileobj=file_handle) as f:
            await f.write("test text")

        await file_handle.write(b"more data")
        await file_handle.close()


class TestResourceCleanup:
    """Test proper resource cleanup and concurrent close handling."""

    async def test_double_close_binary(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        await f.close()
        await f.close()

    async def test_double_close_text(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test data")

        await f.close()
        await f.close()

    async def test_text_close_after_partial_multibyte_read_closes_fileobj(
        self, tmp_path
    ):
        import aiofiles

        p = tmp_path / "partial_multibyte.gz"
        async with AsyncGzipTextFile(p, "wt", encoding="utf-8") as f:
            await f.write("a🚀")

        class CloseTrackingReader:
            def __init__(self, real_file):
                self.real_file = real_file
                self.close_called = False

            async def read(self, size=-1):
                return await self.real_file.read(size)

            async def close(self):
                self.close_called = True
                await self.real_file.close()

        real_file = await aiofiles.open(p, "rb")
        reader = CloseTrackingReader(real_file)
        f = AsyncGzipTextFile(
            None,
            "rt",
            encoding="utf-8",
            chunk_size=2,
            fileobj=reader,
            closefd=True,
        )

        await f.__aenter__()
        assert await f.read(1) == "a"
        await f.close()

        assert reader.close_called is True

    async def test_concurrent_close_binary(self, temp_file):
        import asyncio

        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test data")

        await asyncio.gather(
            f.close(),
            f.close(),
            f.close(),
        )

    async def test_concurrent_close_text(self, temp_file):
        import asyncio

        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test data")

        await asyncio.gather(
            f.close(),
            f.close(),
            f.close(),
        )

    async def test_binary_context_exit_preserves_body_error_during_active_write(self):
        import os

        class BlockingWriter:
            def __init__(self):
                self.calls = 0
                self.write_started = asyncio.Event()
                self.release_write = asyncio.Event()
                self.closed = False

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.write_started.set()
                    await self.release_write.wait()
                    if self.closed:
                        raise OSError("underlying file is closed")
                return len(data)

            async def close(self):
                self.closed = True

        writer = BlockingWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=True, mtime=0)
        write_task = None
        with pytest.raises(ValueError, match="body failure"):
            async with stream:
                write_task = asyncio.create_task(stream.write(os.urandom(512 * 1024)))
                await writer.write_started.wait()
                raise ValueError("body failure")

        assert stream.closed is True
        assert writer.closed is True
        assert write_task is not None
        writer.release_write.set()
        with pytest.raises(OSError, match="underlying file is closed"):
            await write_task

    async def test_aborted_active_write_cannot_report_success_after_sink_resumes(self):
        import os

        class CloseIgnoringWriter:
            def __init__(self):
                self.calls = 0
                self.write_started = asyncio.Event()
                self.release_write = asyncio.Event()
                self.closed = False

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.write_started.set()
                    await self.release_write.wait()
                return len(data)

            async def close(self):
                self.closed = True

        writer = CloseIgnoringWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=True, mtime=0)
        write_task = None
        with pytest.raises(ValueError, match="body failure"):
            async with stream:
                write_task = asyncio.create_task(stream.write(os.urandom(512 * 1024)))
                await writer.write_started.wait()
                raise ValueError("body failure")

        assert stream.closed is True
        assert writer.closed is True
        assert write_task is not None
        writer.release_write.set()
        with pytest.raises(OSError, match="write aborted"):
            await write_task
        assert stream._position == 0

    async def test_aborted_active_flush_cannot_report_success_after_sink_resumes(self):
        class CloseIgnoringFlushWriter:
            def __init__(self):
                self.flush_started = asyncio.Event()
                self.release_flush = asyncio.Event()
                self.closed = False

            async def write(self, data):
                return len(data)

            async def flush(self):
                self.flush_started.set()
                await self.release_flush.wait()

            async def close(self):
                self.closed = True

        writer = CloseIgnoringFlushWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=True, mtime=0)
        flush_task = None
        with pytest.raises(ValueError, match="body failure"):
            async with stream:
                await stream.write(b"pending data")
                flush_task = asyncio.create_task(stream.flush())
                await writer.flush_started.wait()
                raise ValueError("body failure")

        assert stream.closed is True
        assert writer.closed is True
        assert flush_task is not None
        writer.release_flush.set()
        with pytest.raises(OSError, match="flush aborted"):
            await flush_task

    @pytest.mark.parametrize(
        "surface",
        [
            "read-all",
            "read-sized",
            "readinto",
            "read1",
            "readinto1",
            "peek",
            "readline",
            "readlines",
            "anext",
            "seek-end",
        ],
    )
    async def test_aborted_active_binary_read_never_publishes_success(self, surface):
        import gzip
        import io
        import os

        class CloseIgnoringReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.read_started = asyncio.Event()
                self.release_read = asyncio.Event()
                self.closed = False

            async def read(self, size=-1):
                self.read_started.set()
                await self.release_read.wait()
                return self.buffer.read(size)

            async def close(self):
                self.closed = True

        payload = b"first line\nsecond line\n"
        reader = CloseIgnoringReader(gzip.compress(payload, mtime=0))
        stream = AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=True,
            chunk_size=1024,
        )

        async def run_surface():
            if surface == "read-all":
                return await stream.read()
            if surface == "read-sized":
                return await stream.read(len(payload))
            if surface == "readinto":
                return await stream.readinto(bytearray(len(payload)))
            if surface == "read1":
                return await stream.read1()
            if surface == "readinto1":
                return await stream.readinto1(bytearray(len(payload)))
            if surface == "peek":
                return await stream.peek(len(payload))
            if surface == "readline":
                return await stream.readline()
            if surface == "readlines":
                return await stream.readlines()
            if surface == "anext":
                return await anext(stream)
            if surface == "seek-end":
                return await stream.seek(0, os.SEEK_END)
            raise AssertionError(f"unknown surface: {surface}")

        read_task = None
        with pytest.raises(ValueError, match="body failure"):
            async with stream:
                read_task = asyncio.create_task(run_surface())
                await reader.read_started.wait()
                raise ValueError("body failure")

        assert stream.closed is True
        assert reader.closed is True
        assert read_task is not None
        reader.release_read.set()
        with pytest.raises(OSError, match="read aborted"):
            await read_task
        assert stream._position == 0

    @pytest.mark.parametrize("surface", ["read", "readline", "readlines", "anext"])
    async def test_aborted_active_text_read_never_publishes_success(self, surface):
        import gzip
        import io

        class CloseIgnoringReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.read_started = asyncio.Event()
                self.release_read = asyncio.Event()

            async def read(self, size=-1):
                self.read_started.set()
                await self.release_read.wait()
                return self.buffer.read(size)

            async def close(self):
                pass

        reader = CloseIgnoringReader(gzip.compress(b"first\nsecond\n", mtime=0))
        stream = AsyncGzipTextFile(
            None,
            "rt",
            fileobj=reader,
            closefd=True,
            chunk_size=1024,
        )

        async def run_surface():
            if surface == "read":
                return await stream.read()
            if surface == "readline":
                return await stream.readline()
            if surface == "readlines":
                return await stream.readlines()
            if surface == "anext":
                return await anext(stream)
            raise AssertionError(f"unknown surface: {surface}")

        read_task = None
        with pytest.raises(ValueError, match="body failure"):
            async with stream:
                read_task = asyncio.create_task(run_surface())
                await reader.read_started.wait()
                raise ValueError("body failure")

        assert stream.closed is True
        assert stream.buffer.closed is True
        assert read_task is not None
        reader.release_read.set()
        with pytest.raises(OSError, match="read aborted"):
            await read_task

    async def test_text_sized_read_preserves_decoded_prefix_after_source_error(self):
        import gzip
        import io
        import os

        class FailNextReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.fail_next = False
                self.failures = 0

            async def read(self, size=-1):
                if self.fail_next:
                    self.fail_next = False
                    self.failures += 1
                    raise OSError("transient source failure")
                return self.buffer.read(size)

            async def close(self):
                pass

        raw = os.urandom(16 * 1024)
        text = raw.decode("latin-1")
        reader = FailNextReader(gzip.compress(raw, mtime=0))
        stream = AsyncGzipTextFile(
            None,
            "rt",
            encoding="latin-1",
            newline="",
            fileobj=reader,
            closefd=False,
            chunk_size=2048,
        )
        await stream.open()
        try:
            head = await stream.read(1000)
            buffered_before = stream._buffered_text_len()
            assert buffered_before > 0

            reader.fail_next = True
            with pytest.raises(OSError, match="transient source failure"):
                await stream.read(8 * 1024)

            assert reader.failures == 1
            assert stream._buffered_text_len() >= buffered_before
            assert head + await stream.read() == text
        finally:
            await stream.close()

    async def test_buffered_text_read_rejects_overlap_without_stealing_prefix(self):
        import gzip
        import io

        class BlockingReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.read_started = asyncio.Event()
                self.release_read = asyncio.Event()

            async def read(self, size=-1):
                self.read_started.set()
                await self.release_read.wait()
                return self.buffer.read(size)

            async def close(self):
                pass

        reader = BlockingReader(gzip.compress(b"tail\n", mtime=0))
        stream = AsyncGzipTextFile(
            None,
            "rt",
            fileobj=reader,
            closefd=False,
            chunk_size=1024,
        )
        await stream.open()
        stream._set_buffer("prefix-")
        line_task = asyncio.create_task(stream.readline())
        await reader.read_started.wait()

        with pytest.raises(ConcurrentOperationError, match="active read"):
            await stream.read(5)
        assert stream._buffered_text_len() == len("prefix-")

        reader.release_read.set()
        assert await line_task == "prefix-tail\n"
        await stream.close()

    async def test_text_close_after_exposed_buffer_close_surfaces_final_bytes(self):
        class BufferWriter:
            def __init__(self):
                self.buffer = bytearray()

            async def write(self, data):
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = BufferWriter()
        stream = AsyncGzipTextFile(
            None,
            "wt",
            encoding="iso2022_jp",
            fileobj=writer,
            closefd=False,
            mtime=0,
        )
        await stream.open()
        await stream.write("日本語")
        await stream.buffer.close()

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await stream.close()
        assert stream.closed is True

    @pytest.mark.parametrize("text_mode", [False, True])
    async def test_cancelled_clean_exit_aborts_active_call_and_closes(self, text_mode):
        import gzip
        import io

        class BlockingReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.read_started = asyncio.Event()
                self.release_read = asyncio.Event()
                self.closed = False

            async def read(self, size=-1):
                self.read_started.set()
                await self.release_read.wait()
                return self.buffer.read(size)

            async def close(self):
                self.closed = True

        reader = BlockingReader(gzip.compress(b"payload", mtime=0))
        cls = AsyncGzipTextFile if text_mode else AsyncGzipBinaryFile
        mode = "rt" if text_mode else "rb"
        stream = cls(
            None,
            mode,
            fileobj=reader,
            closefd=True,
            chunk_size=1024,
        )
        read_task = None

        async def use_stream():
            nonlocal read_task
            async with stream:
                read_task = asyncio.create_task(stream.read())
                await reader.read_started.wait()

        context_task = asyncio.create_task(use_stream())
        await reader.read_started.wait()
        binary_file = stream.buffer if text_mode else stream
        for _ in range(10):
            if binary_file._active_call_waiter is not None:
                break
            await asyncio.sleep(0)
        assert binary_file._active_call_waiter is not None

        context_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await context_task

        assert stream.closed is True
        assert reader.closed is True
        assert read_task is not None
        reader.release_read.set()
        with pytest.raises(OSError, match="read aborted"):
            await read_task

    @pytest.mark.parametrize("text_mode", [False, True])
    async def test_writelines_holds_wrapper_reservation_for_whole_iterable(
        self, text_mode
    ):
        import gzip

        class BufferWriter:
            def __init__(self):
                self.buffer = bytearray()

            async def write(self, data):
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = BufferWriter()
        if text_mode:
            stream = AsyncGzipTextFile(
                None,
                "wt",
                fileobj=writer,
                closefd=False,
                chunk_size=1024,
                mtime=0,
            )
            lines = ["a" * 1024, "b" * 1024]
            expected = "".join(lines).encode()
        else:
            stream = AsyncGzipBinaryFile(
                None,
                "wb",
                fileobj=writer,
                closefd=False,
                chunk_size=1024,
                mtime=0,
            )
            lines = [b"a" * 1024, b"b" * 1024]
            expected = b"".join(lines)

        class InspectingIterable:
            def __iter__(self):
                for line in lines:
                    assert stream._write_call_active is True
                    yield line

        await stream.open()
        await stream.writelines(InspectingIterable())
        await stream.close()
        assert gzip.decompress(bytes(writer.buffer)) == expected

    async def test_binary_seek_zero_fill_holds_one_write_reservation(self, monkeypatch):
        import gzip

        class BufferWriter:
            def __init__(self):
                self.buffer = bytearray()

            async def write(self, data):
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = BufferWriter()

        stream = AsyncGzipBinaryFile(
            None,
            "wb",
            fileobj=writer,
            closefd=False,
            chunk_size=1024,
            mtime=0,
        )
        await stream.open()
        seen = []
        original = AsyncGzipBinaryFile._write_reserved

        async def observe_reservation(file, payload, encoder):
            seen.append(file._write_call_active)
            return await original(file, payload, encoder)

        monkeypatch.setattr(
            AsyncGzipBinaryFile,
            "_write_reserved",
            observe_reservation,
        )
        assert await stream.seek(3 * 1024) == 3 * 1024
        await stream.close()

        assert seen == [True, True, True]
        assert gzip.decompress(bytes(writer.buffer)) == b"\x00" * (3 * 1024)

    @pytest.mark.parametrize("text_mode", [False, True])
    async def test_readlines_holds_wrapper_reservation_for_whole_call(
        self, tmp_path, monkeypatch, text_mode
    ):
        import gzip

        path = tmp_path / "reserved-readlines.gz"
        payload = b"first\nsecond\nthird\n"
        path.write_bytes(gzip.compress(payload, mtime=0))
        observed = []

        if text_mode:
            original = AsyncGzipTextFile._next_fast_line

            async def observe_text(file):
                observed.append(file._read_call_active)
                return await original(file)

            monkeypatch.setattr(
                AsyncGzipTextFile,
                "_next_fast_line",
                observe_text,
            )
            async with AsyncGzipTextFile(path, "rt", newline="\n") as stream:
                assert await stream.readlines() == ["first\n", "second\n", "third\n"]
        else:
            original = AsyncGzipBinaryFile._readline_reserved

            async def observe_binary(file, limit):
                observed.append(file._read_call_active)
                return await original(file, limit)

            monkeypatch.setattr(
                AsyncGzipBinaryFile,
                "_readline_reserved",
                observe_binary,
            )
            async with AsyncGzipBinaryFile(path, "rb") as stream:
                assert await stream.readlines() == [
                    b"first\n",
                    b"second\n",
                    b"third\n",
                ]

        assert observed
        assert all(observed)

    async def test_aborted_rewind_seek_never_publishes_success(self):
        import gzip
        import io

        class SeekBlockingReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.seek_started = asyncio.Event()
                self.release_seek = asyncio.Event()

            async def read(self, size=-1):
                return self.buffer.read(size)

            async def seek(self, offset, whence=0):
                self.seek_started.set()
                await self.release_seek.wait()
                return self.buffer.seek(offset, whence)

            async def seekable(self):
                return True

            async def close(self):
                pass

        reader = SeekBlockingReader(gzip.compress(b"rewind payload", mtime=0))
        stream = AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=True,
            chunk_size=1024,
        )
        seek_task = None
        with pytest.raises(ValueError, match="body failure"):
            async with stream:
                assert await stream.read(4) == b"rewi"
                seek_task = asyncio.create_task(stream.seek(0))
                await reader.seek_started.wait()
                raise ValueError("body failure")

        assert seek_task is not None
        reader.release_seek.set()
        with pytest.raises(OSError, match="read aborted"):
            await seek_task

    async def test_clean_binary_context_exit_waits_for_active_write_and_closes(self):
        import gzip
        import os

        class BlockingWriter:
            def __init__(self):
                self.calls = 0
                self.buffer = bytearray()
                self.write_started = asyncio.Event()
                self.release_write = asyncio.Event()
                self.closed = False

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.write_started.set()
                    await self.release_write.wait()
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                self.closed = True

        payload = os.urandom(512 * 1024)
        writer = BlockingWriter()
        stream = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=True, mtime=0)
        write_task = None
        async with stream:
            write_task = asyncio.create_task(stream.write(payload))
            await writer.write_started.wait()
            asyncio.get_running_loop().call_soon(writer.release_write.set)

        assert write_task is not None
        assert await write_task == len(payload)
        assert stream.closed is True
        assert writer.closed is True
        assert gzip.decompress(bytes(writer.buffer)) == payload

    @pytest.mark.parametrize("text_mode", [False, True])
    async def test_clean_context_exit_outwaits_a_looping_producer(
        self, monkeypatch, text_mode
    ):
        import gzip

        import aiogzip._binary as binary_module

        class BufferWriter:
            def __init__(self):
                self.buffer = bytearray()
                self.closed = False

            async def write(self, data):
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                self.closed = True

        call_started = asyncio.Queue()
        release_call = asyncio.Queue()

        async def controlled_drive(operation, **kwargs):
            for piece in operation:
                yield piece
            call_started.put_nowait(None)
            await release_call.get()

        monkeypatch.setattr(binary_module, "_drive_operation", controlled_drive)
        writer = BufferWriter()
        if text_mode:
            stream = AsyncGzipTextFile(
                None,
                "wt",
                encoding="latin-1",
                fileobj=writer,
                closefd=True,
                mtime=0,
            )
            payload = "x" * (256 * 1024)
            expected = payload.encode("latin-1") * 3
        else:
            stream = AsyncGzipBinaryFile(
                None,
                "wb",
                fileobj=writer,
                closefd=True,
                mtime=0,
            )
            payload = b"x" * (256 * 1024)
            expected = payload * 3

        async def produce():
            for _ in range(3):
                assert await stream.write(payload) == len(payload)

        async def release_all_calls():
            release_call.put_nowait(None)
            for _ in range(2):
                await call_started.get()
                release_call.put_nowait(None)

        producer = None
        releaser = None
        async with stream:
            producer = asyncio.create_task(produce())
            await call_started.get()
            releaser = asyncio.create_task(release_all_calls())

        assert producer is not None
        assert releaser is not None
        await asyncio.gather(producer, releaser)
        assert stream.closed is True
        assert writer.closed is True
        assert gzip.decompress(bytes(writer.buffer)) == expected

    async def test_abort_cleanup_cancellation_propagates_and_remains_retryable(self):
        import gzip
        import io

        class CancellableCloseReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.read_started = asyncio.Event()
                self.release_read = asyncio.Event()
                self.close_started = asyncio.Event()
                self.close_calls = 0
                self.closed = False

            async def read(self, size=-1):
                self.read_started.set()
                await self.release_read.wait()
                return self.buffer.read(size)

            async def close(self):
                self.close_calls += 1
                if self.close_calls == 1:
                    self.close_started.set()
                    await asyncio.Event().wait()
                self.closed = True

        reader = CancellableCloseReader(gzip.compress(b"payload", mtime=0))
        stream = AsyncGzipBinaryFile(
            None,
            "rb",
            fileobj=reader,
            closefd=True,
            chunk_size=1024,
        )
        read_task = None

        async def use_stream():
            nonlocal read_task
            async with stream:
                read_task = asyncio.create_task(stream.read())
                await reader.read_started.wait()
                raise ValueError("body failure")

        context_task = asyncio.create_task(use_stream())
        await reader.close_started.wait()
        context_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await context_task

        assert stream.closed is False
        assert reader.closed is False
        assert read_task is not None
        reader.release_read.set()
        with pytest.raises(OSError, match="read aborted"):
            await read_task

        await stream.close()
        assert stream.closed is True
        assert reader.closed is True
        assert reader.close_calls == 2

    async def test_failed_abort_close_preserves_body_error_and_open_state(self):
        import gzip
        import io

        class RetryableCloseReader:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)
                self.read_started = asyncio.Event()
                self.release_read = asyncio.Event()
                self.close_calls = 0
                self.closed = False

            async def read(self, size=-1):
                self.read_started.set()
                await self.release_read.wait()
                return self.buffer.read(size)

            async def close(self):
                self.close_calls += 1
                if self.close_calls == 1:
                    raise OSError("close failed")
                self.closed = True

        reader = RetryableCloseReader(gzip.compress(b"payload", mtime=0))
        stream = AsyncGzipTextFile(
            None,
            "rt",
            fileobj=reader,
            closefd=True,
            chunk_size=1024,
        )
        read_task = None
        with pytest.raises(ValueError, match="body failure"):
            async with stream:
                read_task = asyncio.create_task(stream.read())
                await reader.read_started.wait()
                raise ValueError("body failure")

        assert stream.closed is False
        assert stream.buffer.closed is False
        assert reader.closed is False
        assert read_task is not None
        reader.release_read.set()
        with pytest.raises(OSError, match="read aborted"):
            await read_task

        await stream.close()
        assert stream.closed is True
        assert stream.buffer.closed is True
        assert reader.closed is True
        assert reader.close_calls == 2

    async def test_text_close_is_retryable_during_active_binary_write(self):
        import gzip
        import os

        class BlockingWriter:
            def __init__(self):
                self.calls = 0
                self.buffer = bytearray()
                self.write_started = asyncio.Event()
                self.release_write = asyncio.Event()

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.write_started.set()
                    await self.release_write.wait()
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        raw = os.urandom(512 * 1024)
        text = raw.decode("latin-1")
        writer = BlockingWriter()
        stream = AsyncGzipTextFile(
            None,
            "wt",
            encoding="latin-1",
            fileobj=writer,
            closefd=False,
            mtime=0,
        )
        await stream.open()

        write_task = asyncio.create_task(stream.write(text))
        await writer.write_started.wait()
        with pytest.raises(ConcurrentOperationError, match="active write or flush"):
            await stream.close()
        assert stream.closed is False
        assert stream.buffer.closed is False

        writer.release_write.set()
        assert await write_task == len(text)
        await stream.close()
        assert stream.closed is True
        assert gzip.decompress(bytes(writer.buffer)) == raw

    async def test_clean_text_context_exit_waits_for_active_write_and_closes(self):
        import gzip
        import os

        class BlockingWriter:
            def __init__(self):
                self.calls = 0
                self.buffer = bytearray()
                self.write_started = asyncio.Event()
                self.release_write = asyncio.Event()
                self.closed = False

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.write_started.set()
                    await self.release_write.wait()
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                self.closed = True

        raw = os.urandom(512 * 1024)
        text = raw.decode("latin-1")
        writer = BlockingWriter()
        stream = AsyncGzipTextFile(
            None,
            "wt",
            encoding="latin-1",
            fileobj=writer,
            closefd=True,
            mtime=0,
        )
        write_task = None
        async with stream:
            write_task = asyncio.create_task(stream.write(text))
            await writer.write_started.wait()
            asyncio.get_running_loop().call_soon(writer.release_write.set)

        assert write_task is not None
        assert await write_task == len(text)
        assert stream.closed is True
        assert writer.closed is True
        assert gzip.decompress(bytes(writer.buffer)) == raw

    async def test_concurrent_text_close_is_serialized_through_trailer_write(self):
        import gzip

        class BlockingTrailerWriter:
            def __init__(self):
                self.calls = 0
                self.buffer = bytearray()
                self.trailer_started = asyncio.Event()
                self.release_trailer = asyncio.Event()

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.trailer_started.set()
                    await self.release_trailer.wait()
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = BlockingTrailerWriter()
        stream = AsyncGzipTextFile(
            None,
            "wt",
            fileobj=writer,
            closefd=False,
            mtime=0,
        )
        await stream.open()
        await stream.write("payload")

        first_close = asyncio.create_task(stream.close())
        await writer.trailer_started.wait()
        second_close = asyncio.create_task(stream.close())
        await asyncio.sleep(0)
        assert second_close.done() is False

        writer.release_trailer.set()
        await asyncio.gather(first_close, second_close)
        assert stream.closed is True
        assert gzip.decompress(bytes(writer.buffer)) == b"payload"

    async def test_concurrent_binary_close_waits_through_trailer_write(self):
        import gzip

        class BlockingTrailerWriter:
            def __init__(self):
                self.calls = 0
                self.buffer = bytearray()
                self.trailer_started = asyncio.Event()
                self.release_trailer = asyncio.Event()

            async def write(self, data):
                self.calls += 1
                if self.calls > 1:
                    self.trailer_started.set()
                    await self.release_trailer.wait()
                self.buffer.extend(data)
                return len(data)

            async def close(self):
                pass

        writer = BlockingTrailerWriter()
        stream = AsyncGzipBinaryFile(
            None,
            "wb",
            fileobj=writer,
            closefd=False,
            mtime=0,
        )
        await stream.open()
        await stream.write(b"payload")

        first_close = asyncio.create_task(stream.close())
        await writer.trailer_started.wait()
        second_close = asyncio.create_task(stream.close())
        await asyncio.sleep(0)
        assert second_close.done() is False

        writer.release_trailer.set()
        await asyncio.gather(first_close, second_close)
        assert stream.closed is True
        assert gzip.decompress(bytes(writer.buffer)) == b"payload"

    async def test_operations_after_close_raise_errors(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test data")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write(b"more data")

    async def test_close_with_exception_during_flush(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        await f.__aenter__()
        await f.write(b"test data")

        if f._file is not None:
            await f._file.close()

        with pytest.raises(ValueError):
            await f.close()

        assert f._is_closed is True
        await f.close()
        await f.close()

    async def test_binary_close_failure_still_closes_fileobj(self):
        class FailingCloseTrackingWriter:
            def __init__(self):
                self.write_calls = 0
                self.close_called = False

            async def write(self, data):
                self.write_calls += 1
                if self.write_calls == 2:
                    raise OSError("close write failed")
                return len(data)

            async def close(self):
                self.close_called = True

        writer = FailingCloseTrackingWriter()
        f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=True)
        await f.__aenter__()

        with pytest.raises(OSError, match="close write failed"):
            await f.close()

        assert writer.close_called is True

    async def test_binary_write_error_wins_over_close_error(self):
        """When both final write and close fail, the write error propagates."""

        class DoublyFailingWriter:
            def __init__(self):
                self.write_calls = 0

            async def write(self, data):
                self.write_calls += 1
                if self.write_calls == 2:
                    raise OSError("final write failed")
                return len(data)

            async def close(self):
                raise RuntimeError("close failed too")

        writer = DoublyFailingWriter()
        f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=True)
        await f.__aenter__()

        with pytest.raises(OSError, match="final write failed"):
            await f.close()

    async def test_text_close_does_not_raise_on_partial_multibyte(self, tmp_path):
        """Regression: close() used to call decoder.decode(b'', final=True),
        which raised UnicodeDecodeError if the decoder held partial multibyte
        state from a read that stopped mid-character."""
        p = tmp_path / "partial_close.gz"
        async with AsyncGzipTextFile(p, "wt", encoding="utf-8") as f:
            await f.write("a🚀b🚀c")

        f = AsyncGzipTextFile(p, "rt", encoding="utf-8", chunk_size=1)
        async with f:
            assert await f.read(1) == "a"
        assert f.closed is True
        assert f.buffer.closed is True


class TestOpenCloseLifecycle:
    """Explicit open()/close() lifecycle (the imperative try/finally pattern)."""

    @staticmethod
    def _write(path, text=b"hello\nworld\n"):
        import gzip

        with gzip.open(path, "wb") as f:
            f.write(text)

    @pytest.mark.asyncio
    async def test_binary_open_read_close(self, tmp_path):
        p = tmp_path / "binary.gz"
        self._write(p)
        f = AsyncGzipBinaryFile(p, "rb")
        assert f.closed is False
        ret = await f.open()
        assert ret is f  # open() returns self
        try:
            assert await f.read() == b"hello\nworld\n"
        finally:
            await f.close()
        assert f.closed is True

    @pytest.mark.asyncio
    async def test_text_open_read_close(self, tmp_path):
        p = tmp_path / "text.gz"
        self._write(p)
        f = AsyncGzipTextFile(p, "rt")
        ret = await f.open()
        assert ret is f
        try:
            assert await f.read() == "hello\nworld\n"
        finally:
            await f.close()
        assert f.closed is True

    @pytest.mark.asyncio
    async def test_binary_open_write_round_trip(self, tmp_path):
        p = tmp_path / "write.gz"
        f = AsyncGzipBinaryFile(p, "wb")
        await f.open()
        try:
            await f.write(b"payload data")
        finally:
            await f.close()

        async with AsyncGzipBinaryFile(p, "rb") as r:
            assert await r.read() == b"payload data"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [AsyncGzipBinaryFile, AsyncGzipTextFile])
    async def test_open_twice_raises(self, tmp_path, cls):
        p = tmp_path / "twice.gz"
        self._write(p)
        mode = "rb" if cls is AsyncGzipBinaryFile else "rt"
        f = cls(p, mode)
        await f.open()
        try:
            with pytest.raises(ValueError, match="already open"):
                await f.open()
        finally:
            await f.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [AsyncGzipBinaryFile, AsyncGzipTextFile])
    async def test_reopen_after_close_raises(self, tmp_path, cls):
        p = tmp_path / "reopen.gz"
        self._write(p)
        mode = "rb" if cls is AsyncGzipBinaryFile else "rt"
        f = cls(p, mode)
        await f.open()
        await f.close()
        with pytest.raises(ValueError, match="closed"):
            await f.open()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [AsyncGzipBinaryFile, AsyncGzipTextFile])
    async def test_operations_before_open_raise(self, tmp_path, cls):
        p = tmp_path / "before.gz"
        self._write(p)
        mode = "rb" if cls is AsyncGzipBinaryFile else "rt"
        f = cls(p, mode)
        with pytest.raises(ValueError, match="File not opened"):
            await f.read()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [AsyncGzipBinaryFile, AsyncGzipTextFile])
    async def test_aenter_matches_open(self, tmp_path, cls):
        """__aenter__ is just open(): same result and same returned object."""
        p = tmp_path / "aenter.gz"
        self._write(p)
        mode = "rb" if cls is AsyncGzipBinaryFile else "rt"
        expected = b"hello\nworld\n" if cls is AsyncGzipBinaryFile else "hello\nworld\n"

        async with cls(p, mode) as f:
            assert f.closed is False
            assert await f.read() == expected
        assert f.closed is True


class TestRepr:
    """__repr__ shows name, mode, and closed state for both open and closed."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cls,mode,classname",
        [
            (AsyncGzipBinaryFile, "rb", "AsyncGzipBinaryFile"),
            (AsyncGzipTextFile, "rt", "AsyncGzipTextFile"),
        ],
    )
    async def test_repr_open_and_closed(self, tmp_path, cls, mode, classname):
        import gzip

        p = tmp_path / "repr.gz"
        with gzip.open(p, "wb") as fh:
            fh.write(b"data")

        name = str(p)
        f = cls(name, mode)
        await f.open()
        assert repr(f) == (
            f"<aiogzip.{classname} name={name!r} mode={mode!r} closed=False>"
        )
        await f.close()
        assert repr(f) == (
            f"<aiogzip.{classname} name={name!r} mode={mode!r} closed=True>"
        )

    @pytest.mark.asyncio
    async def test_repr_fileobj_name_fallback(self, tmp_path):
        """With filename=None, repr falls back to the fileobj's .name."""
        import gzip
        import io

        raw = gzip.compress(b"xyz")

        class NamedReader:
            name = "in-memory.gz"

            def __init__(self):
                self._buf = io.BytesIO(raw)

            async def read(self, size=-1):
                return self._buf.read(size)

            async def close(self):
                pass

        f = AsyncGzipBinaryFile(None, "rb", fileobj=NamedReader(), closefd=False)
        await f.open()
        try:
            assert "name='in-memory.gz'" in repr(f)
        finally:
            await f.close()


class TestFailedOpenRecovery:
    """A failed open() must leave the instance retryable, not half-open.

    Regression: with an external fileobj, _cleanup_failed_enter left _file
    set after a failed open, so a retry raised "File is already open" and
    write() would emit compressed data for a stream whose gzip header was
    never written.
    """

    class _FlakyWriter:
        """Fails the first write (the gzip header), then delegates."""

        def __init__(self, target):
            self._target = target
            self.fail_next = True
            self.closed = False

        async def write(self, data):
            if self.fail_next:
                self.fail_next = False
                raise OSError("transient write failure")
            return await self._target.write(data)

        async def close(self):
            self.closed = True

    @pytest.mark.asyncio
    async def test_failed_open_with_external_fileobj_can_retry(self, tmp_path):
        import gzip

        import aiofiles

        p = tmp_path / "flaky.gz"
        inner = await aiofiles.open(p, "wb")
        try:
            writer = self._FlakyWriter(inner)
            f = AsyncGzipBinaryFile(None, "wb", fileobj=writer)

            with pytest.raises(OSError, match="transient write failure"):
                await f.open()

            # The failed open leaves no half-open state behind: the handle is
            # cleared, the caller's fileobj is untouched, and a retry works.
            assert f._file is None
            assert writer.closed is False

            async with f:
                await f.write(b"recovered payload")
        finally:
            await inner.close()

        with gzip.open(p, "rb") as check:
            assert check.read() == b"recovered payload"

    @pytest.mark.asyncio
    async def test_failed_open_then_write_raises_not_opened(self, tmp_path):
        """After a failed open, write() reports the file as not opened rather
        than silently compressing into a headerless stream."""
        import aiofiles

        inner = await aiofiles.open(tmp_path / "wedge.gz", "wb")
        try:
            writer = self._FlakyWriter(inner)
            f = AsyncGzipBinaryFile(None, "wb", fileobj=writer)
            with pytest.raises(OSError, match="transient write failure"):
                await f.open()
            with pytest.raises(ValueError, match="File not opened"):
                await f.write(b"hello")
        finally:
            await inner.close()


class TestReprOnPartialObjects:
    """repr() must not raise on partially-constructed instances.

    The classes use __slots__ and __init__ validates mid-assignment, so a
    constructor failure leaves an object missing some attributes; debuggers
    and locals-capturing traceback formatters still call repr() on it.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [AsyncGzipBinaryFile, AsyncGzipTextFile])
    async def test_repr_after_failed_init(self, tmp_path, cls):
        obj = cls.__new__(cls)
        try:
            # compresslevel=99 raises after _filename/_mode are assigned but
            # before _is_closed, leaving the object half-built.
            mode = "wb" if cls is AsyncGzipBinaryFile else "wt"
            obj.__init__(tmp_path / "x.gz", mode, compresslevel=99)
        except ValueError:
            pass
        r = repr(obj)  # must not raise
        assert cls.__name__ in r


class TestCancelledOpenRecovery:
    """A cancelled open() must leave the instance retryable, like a failed one.

    Regression: the open() cleanup caught only Exception, so CancelledError
    (a BaseException) escaped it: _file stayed set, the handle leaked, and
    every retry raised "File is already open".
    """

    class _ParkedWriter:
        """Parks the first write (the gzip header) until released."""

        def __init__(self):
            self.release = asyncio.Event()
            self.writes = 0

        async def write(self, data):
            self.writes += 1
            if self.writes == 1:
                await self.release.wait()
            return len(data)

        async def close(self):
            pass

    async def test_binary_cancelled_open_leaves_instance_retryable(self):
        writer = self._ParkedWriter()
        f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False)

        task = asyncio.ensure_future(f.open())
        await asyncio.sleep(0)  # let open() reach the parked header write
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert f._file is None
        async with f:  # retry succeeds
            await f.write(b"recovered")

    async def test_text_cancelled_open_leaves_instance_retryable(self):
        writer = self._ParkedWriter()
        f = AsyncGzipTextFile(None, "wt", fileobj=writer, closefd=False)

        task = asyncio.ensure_future(f.open())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert f._binary_file is None
        async with f:
            await f.write("recovered")


class TestFailedTextOpenRecovery:
    """Text-mode open() failure recovery, mirroring the binary-only tests."""

    async def test_failed_text_open_with_external_fileobj_can_retry(self, tmp_path):
        import gzip

        import aiofiles

        p = tmp_path / "flaky_text.gz"
        inner = await aiofiles.open(p, "wb")
        try:
            writer = TestFailedOpenRecovery._FlakyWriter(inner)
            f = AsyncGzipTextFile(None, "wt", fileobj=writer)

            with pytest.raises(OSError, match="transient write failure"):
                await f.open()

            assert f._binary_file is None
            assert writer.closed is False

            async with f:
                await f.write("recovered text")
        finally:
            await inner.close()

        with gzip.open(p, "rt") as check:
            assert check.read() == "recovered text"
