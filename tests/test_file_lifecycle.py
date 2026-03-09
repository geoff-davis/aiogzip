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
