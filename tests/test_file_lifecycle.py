# pyrefly: ignore
# pyrefly: disable=all
import asyncio

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


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
        assert f._is_closed is True


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
