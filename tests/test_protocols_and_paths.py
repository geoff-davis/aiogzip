# pyrefly: ignore
# pyrefly: disable=all
import gzip
import os
from typing import Union

import pytest

import aiogzip
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

    async def test_binary_file_with_path_object(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        test_data = b"Hello, Path!"

        async with AsyncGzipBinaryFile(path_obj, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipBinaryFile(path_obj, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data

    async def test_text_file_with_path_object(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        test_text = "Hello, Path!"

        async with AsyncGzipTextFile(path_obj, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(path_obj, "rt") as f:
            read_text = await f.read()

        assert read_text == test_text

    async def test_factory_with_path_object(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        test_data = b"Hello, Factory!"

        async with AsyncGzipFile(path_obj, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipFile(path_obj, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data

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

    async def test_binary_file_name_with_string(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            assert f.name == temp_file
            await f.write(b"test")

    async def test_binary_file_name_with_path(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        async with AsyncGzipBinaryFile(path_obj, "wb") as f:
            assert f.name == path_obj
            await f.write(b"test")

    async def test_binary_file_name_with_bytes(self, temp_file):
        path_bytes = temp_file.encode("utf-8")
        async with AsyncGzipBinaryFile(path_bytes, "wb") as f:
            assert f.name == path_bytes
            await f.write(b"test")

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

    async def test_text_file_name_with_string(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            assert f.name == temp_file
            await f.write("test")

    async def test_text_file_name_with_path(self, temp_file):
        from pathlib import Path

        path_obj = Path(temp_file)
        async with AsyncGzipTextFile(path_obj, "wt") as f:
            assert f.name == path_obj
            await f.write("test")

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

    async def test_name_available_before_enter(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        assert f.name == temp_file

    async def test_name_available_after_close(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")
        assert f.name == temp_file


class _FsPath:
    """A minimal os.PathLike that is not a pathlib class."""

    def __init__(self, path):
        self._path = path

    def __fspath__(self):
        return self._path


class TestPathLikeSupport:
    """Every public filename accepts os.PathLike[str] and os.PathLike[bytes],
    which is what the annotations promise."""

    @pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
    async def test_path_like_round_trip(self, temp_file, as_bytes):
        raw = os.fsencode(temp_file) if as_bytes else temp_file
        path = _FsPath(raw)

        await aiogzip.write(path, b"one\n")
        async with aiogzip.open(path, "ab") as binary:
            assert binary.name is path
            await binary.write(b"two\n")
        async with AsyncGzipTextFile(path, "at", newline="") as text:
            assert text.name is path
            await text.write("three\n")

        assert await aiogzip.read(path) == b"one\ntwo\nthree\n"
        async with AsyncGzipFile(path, "rt") as text:
            assert await text.read() == "one\ntwo\nthree\n"
        async with AsyncGzipBinaryFile(path, "rb") as binary:
            assert await binary.read() == b"one\ntwo\nthree\n"
        assert (await aiogzip.verify(path)).member_count == 3
        info = await aiogzip.inspect(path)
        assert info.members[0].original_filename == os.path.basename(
            temp_file
        ).removesuffix(".gz")

    async def test_pure_path(self, temp_file):
        from pathlib import PurePath

        path = PurePath(temp_file)
        await aiogzip.write(path, b"payload")
        assert await aiogzip.read(path) == b"payload"
        assert (await aiogzip.verify(path)).member_count == 1


class TestBinarySink:
    """A fileobj sink's write() receives only exact bytes, in binary and text
    mode, so ``WithAsyncWrite.write`` takes ``bytes``."""

    class Sink:
        def __init__(self):
            self.calls = []

        async def write(self, b: bytes, /) -> int:
            self.calls.append(b)
            return len(b)

    async def test_binary_writes_pass_bytes(self):
        sink = self.Sink()
        await aiogzip.write(None, bytearray(b"payload"), fileobj=sink)
        async with aiogzip.open(None, "wb", fileobj=sink) as f:
            await f.write(memoryview(b"more"))
            await f.flush()
        assert sink.calls
        assert all(type(call) is bytes for call in sink.calls)
        assert gzip.decompress(b"".join(sink.calls)) == b"payloadmore"

    async def test_text_writes_pass_bytes(self):
        sink = self.Sink()
        async with aiogzip.open(None, "wt", fileobj=sink, encoding="utf-16") as f:
            await f.write("héllo\n")
            await f.flush()
            await f.writelines(["a\n", "b\n"])
        assert sink.calls
        assert all(type(call) is bytes for call in sink.calls)
        text = gzip.decompress(b"".join(sink.calls)).decode("utf-16")
        assert text.replace(os.linesep, "\n") == "héllo\na\nb\n"
