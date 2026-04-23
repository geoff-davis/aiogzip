# pyrefly: ignore
# pyrefly: disable=all
import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestClosefdParameter:
    """Test closefd parameter behavior."""

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_closefd_default_with_fileobj_keeps_file_open(self, tmp_path):
        import aiofiles

        p = tmp_path / "test_closefd_default_fileobj.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipBinaryFile(None, "wb", fileobj=file_handle) as f:
            await f.write(b"test data")

        await file_handle.write(b"more data")
        await file_handle.close()

    @pytest.mark.asyncio
    async def test_closefd_default_closes_owned_file(self, tmp_path):
        p = tmp_path / "test_closefd_default.gz"

        f = AsyncGzipBinaryFile(p, "wb")
        async with f:
            await f.write(b"test data")

        assert f._is_closed is True

    @pytest.mark.asyncio
    async def test_closefd_with_text_file(self, tmp_path):
        import aiofiles

        p = tmp_path / "test_text_closefd.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipTextFile(
            None, "wt", fileobj=file_handle, closefd=False
        ) as f:
            await f.write("test text")

        await file_handle.close()

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_double_close_binary(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        await f.close()
        await f.close()

    @pytest.mark.asyncio
    async def test_double_close_text(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test data")

        await f.close()
        await f.close()

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_operations_after_close_raise_errors(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test data")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write(b"more data")

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
