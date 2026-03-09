# pyrefly: ignore
# pyrefly: disable=all
from typing import Union

import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipFile,
    AsyncGzipTextFile,
    WithAsyncRead,
    WithAsyncReadWrite,
    WithAsyncWrite,
)


class TestProtocols:
    """Test the protocol classes."""

    def test_with_async_read_protocol(self):
        class MockReader:
            async def read(self, size: int = -1) -> str:
                return "test data"

        reader: WithAsyncRead = MockReader()
        assert reader is not None

    def test_with_async_write_protocol(self):
        class MockWriter:
            async def write(self, data: Union[str, bytes]) -> int:
                return len(data)

        writer: WithAsyncWrite = MockWriter()
        assert writer is not None

    def test_with_async_read_write_protocol(self):
        class MockReadWriter:
            async def read(self, size: int = -1) -> Union[str, bytes]:
                return "test data"

            async def write(self, data: Union[str, bytes]) -> int:
                return len(data)

        read_writer: WithAsyncReadWrite = MockReadWriter()
        assert read_writer is not None


class TestPathlibSupport:
    """Test support for pathlib.Path objects."""

    @pytest.mark.asyncio
    async def test_binary_file_with_path_object(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        test_data = b"Hello, Path!"

        async with AsyncGzipBinaryFile(path_obj, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipBinaryFile(path_obj, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data

    @pytest.mark.asyncio
    async def test_text_file_with_path_object(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        test_text = "Hello, Path!"

        async with AsyncGzipTextFile(path_obj, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(path_obj, "rt") as f:
            read_text = await f.read()

        assert read_text == test_text

    @pytest.mark.asyncio
    async def test_factory_with_path_object(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        test_data = b"Hello, Factory!"

        async with AsyncGzipFile(path_obj, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipFile(path_obj, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data

    @pytest.mark.asyncio
    async def test_path_with_bytes(self, temp_file):
        path_bytes = temp_file.encode("utf-8")
        test_data = b"Hello, bytes path!"

        async with AsyncGzipBinaryFile(path_bytes, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipBinaryFile(path_bytes, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data


class TestNameProperty:
    """Test the name property for file API compatibility."""

    @pytest.mark.asyncio
    async def test_binary_file_name_with_string(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            assert f.name == temp_file
            await f.write(b"test")

    @pytest.mark.asyncio
    async def test_binary_file_name_with_path(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        async with AsyncGzipBinaryFile(path_obj, "wb") as f:
            assert f.name == path_obj
            await f.write(b"test")

    @pytest.mark.asyncio
    async def test_binary_file_name_with_bytes(self, temp_file):
        path_bytes = temp_file.encode("utf-8")
        async with AsyncGzipBinaryFile(path_bytes, "wb") as f:
            assert f.name == path_bytes
            await f.write(b"test")

    @pytest.mark.asyncio
    async def test_binary_file_name_with_fileobj(self, temp_file):
        import aiofiles

        file_handle = await aiofiles.open(temp_file, "wb")
        try:
            async with AsyncGzipBinaryFile(
                None, "wb", fileobj=file_handle, closefd=False
            ) as f:
                assert f.name == file_handle.name
                await f.write(b"test")
        finally:
            await file_handle.close()

    @pytest.mark.asyncio
    async def test_text_file_name_with_string(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            assert f.name == temp_file
            await f.write("test")

    @pytest.mark.asyncio
    async def test_text_file_name_with_path(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        async with AsyncGzipTextFile(path_obj, "wt") as f:
            assert f.name == path_obj
            await f.write("test")

    @pytest.mark.asyncio
    async def test_text_file_name_with_fileobj(self, temp_file):
        import aiofiles

        file_handle = await aiofiles.open(temp_file, "wb")
        try:
            async with AsyncGzipTextFile(
                None, "wt", fileobj=file_handle, closefd=False
            ) as f:
                assert f.name == file_handle.name
                await f.write("test")
        finally:
            await file_handle.close()

    @pytest.mark.asyncio
    async def test_name_available_before_enter(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        assert f.name == temp_file

    @pytest.mark.asyncio
    async def test_name_available_after_close(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")
        assert f.name == temp_file
