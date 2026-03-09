# pyrefly: ignore
# pyrefly: disable=all
import gzip
import io
import os
import tarfile
import time

import pytest
from conftest import parse_gzip_header_bytes

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestAsyncGzipBinaryFile:
    """Test the AsyncGzipBinaryFile class."""

    @pytest.mark.asyncio
    async def test_binary_write_read_roundtrip(self, temp_file, sample_data):
        """Test basic write/read roundtrip in binary mode."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            read_data = await f.read()
            assert read_data == sample_data

    @pytest.mark.asyncio
    async def test_binary_partial_read(self, temp_file, sample_data):
        """Test partial reading in binary mode."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            partial_data = await f.read(10)
            assert partial_data == sample_data[:10]

            remaining_data = await f.read()
            assert remaining_data == sample_data[10:]

    @pytest.mark.asyncio
    async def test_binary_read_negative_size_returns_all(self, temp_file, sample_data):
        """Negative size arguments should read the entire remaining stream."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read(-5)
            assert data == sample_data

    @pytest.mark.asyncio
    async def test_binary_large_data(self, temp_file, large_data):
        """Test with large data in binary mode."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(large_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            read_data = await f.read()
            assert read_data == large_data

    @pytest.mark.asyncio
    async def test_binary_type_error(self, temp_file):
        """Test type error when writing string to binary file."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            with pytest.raises(
                TypeError, match="write\\(\\) argument must be a bytes-like object"
            ):
                await f.write("string data")  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_binary_mode_xb(self, temp_file, sample_data):
        """Exclusive create mode should work for binary files."""
        exclusive_path = temp_file + ".xb"
        if os.path.exists(exclusive_path):
            os.unlink(exclusive_path)

        async with AsyncGzipBinaryFile(exclusive_path, "xb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(exclusive_path, "rb") as f:
            assert await f.read() == sample_data

        os.unlink(exclusive_path)

    @pytest.mark.asyncio
    async def test_binary_mode_rb_plus_allows_read_only(self, temp_file, sample_data):
        """rb+ should open successfully but still disallow writes, matching gzip."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb+") as f:
            assert await f.read() == sample_data
            with pytest.raises(IOError, match="File not open for writing"):
                await f.write(sample_data)

    @pytest.mark.asyncio
    async def test_binary_bytes_path(self, temp_file, sample_data):
        """Ensure binary mode accepts bytes paths."""
        path_bytes = os.fsencode(temp_file)

        async with AsyncGzipBinaryFile(path_bytes, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(path_bytes, "rb") as f:
            assert await f.read() == sample_data

    @pytest.mark.asyncio
    async def test_binary_accepts_bytearray_and_memoryview(self, temp_file):
        """Binary writes should support general buffer-protocol inputs."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(bytearray(b"abc"))
            await f.write(memoryview(b"def"))

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.read() == b"abcdef"

    @pytest.mark.asyncio
    async def test_binary_interoperability_with_gzip(self, temp_file, sample_data):
        """Test interoperability with gzip.open for binary data."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        with gzip.open(temp_file, "rb") as f:
            read_data = f.read()
            assert read_data == sample_data

        with gzip.open(temp_file, "wb") as f:
            f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            read_data = await f.read()
            assert read_data == sample_data

    @pytest.mark.asyncio
    async def test_binary_custom_header_metadata(self, tmp_path):
        """Binary writer should honor provided mtime and original filename."""
        target = tmp_path / "custom_meta.gz"
        async with AsyncGzipBinaryFile(
            target, "wb", mtime=0, original_filename="report.csv"
        ) as f:
            await f.write(b"payload")

        header = parse_gzip_header_bytes(target)
        assert header["mtime"] == 0
        assert header["filename"] == b"report.csv"
        assert header["flags"] & 0x08

        with gzip.open(target, "rb") as fh:
            assert fh.read() == b"payload"

    @pytest.mark.asyncio
    async def test_binary_header_defaults_to_basename(self, tmp_path):
        """When no original filename provided, derive from the gzip path."""
        target = tmp_path / "dataset.gz"
        async with AsyncGzipBinaryFile(target, "wb") as f:
            await f.write(b"x")

        header = parse_gzip_header_bytes(target)
        assert header["filename"] == b"dataset"
        assert abs(header["mtime"] - int(time.time())) < 10

    @pytest.mark.asyncio
    async def test_text_custom_header_metadata(self, tmp_path):
        """Text writer should forward metadata options to the binary layer."""
        target = tmp_path / "text_meta.gz"
        async with AsyncGzipTextFile(
            target, "wt", mtime=12345, original_filename=b"notes.txt"
        ) as f:
            await f.write("hello")

        header = parse_gzip_header_bytes(target)
        assert header["mtime"] == 12345
        assert header["filename"] == b"notes.txt"

        with gzip.open(target, "rt") as fh:
            assert fh.read() == "hello"

    @pytest.mark.asyncio
    async def test_binary_seek_tell_peek(self, temp_file, sample_data):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            first = await f.read(5)
            assert first == sample_data[:5]
            assert await f.tell() == 5

            peeked = await f.peek(4)
            assert peeked.startswith(sample_data[5:9])

            await f.seek(2)
            assert await f.tell() == 2
            chunk = await f.read(4)
            assert chunk == sample_data[2:6]

            await f.seek(1, os.SEEK_CUR)
            assert await f.tell() == 7

    @pytest.mark.asyncio
    async def test_binary_seek_from_end_clamps_to_stream_bounds(self, temp_file):
        payload = b"abcdef"
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(payload)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.seek(0, os.SEEK_END) == len(payload)
            assert await f.read() == b""

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.seek(-1, os.SEEK_END) == len(payload) - 1
            assert await f.read() == payload[-1:]

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.seek(-100, os.SEEK_END) == 0
            assert await f.read() == payload

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.seek(100, os.SEEK_END) == len(payload)
            assert await f.read() == b""

    @pytest.mark.asyncio
    async def test_binary_readinto(self, temp_file, sample_data):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            buf = bytearray(10)
            read = await f.readinto(buf)
            assert read == 10
            assert bytes(buf) == sample_data[:10]

    @pytest.mark.asyncio
    async def test_binary_peek_zero_returns_data_without_advancing(self, temp_file):
        """peek(0) should still return available bytes like gzip.GzipFile.peek()."""
        payload = b"abcdef"
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(payload)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            before = await f.tell()
            peeked = await f.peek(0)
            after = await f.tell()

            assert peeked != b""
            assert before == after
            assert await f.read() == payload

    @pytest.mark.asyncio
    async def test_binary_peek_from_start_returns_data(self, temp_file):
        """peek() from a fresh reader should not return empty for valid gzip data."""
        payload = b"abcdefghijklmnopqrstuvwxyz"
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(payload)

        async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=9) as f:
            assert await f.tell() == 0
            peeked = await f.peek(5)
            assert peeked != b""
            assert await f.tell() == 0
            assert await f.read(len(payload)) == payload

    @pytest.mark.asyncio
    async def test_binary_fileno_and_raw(self, temp_file, sample_data):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            fd = f.fileno()
            assert isinstance(fd, int)
            assert f.raw() is not None

    @pytest.mark.asyncio
    async def test_binary_fileno_missing(self, temp_file, sample_data):
        class NoFileno:
            async def write(self, data):
                return len(data)

            async def read(self, size=-1):
                return b""

        f = AsyncGzipBinaryFile(temp_file, "rb")
        f._file = NoFileno()
        with pytest.raises(io.UnsupportedOperation, match="fileno\\(\\)"):
            f.fileno()

    @pytest.mark.asyncio
    async def test_binary_read1_and_readinto1(self, temp_file, sample_data):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read1(10)
            assert len(data) == 10
            buf = bytearray(5)
            read = await f.readinto1(buf)
            assert read == 5

    @pytest.mark.asyncio
    async def test_binary_read1_negative_size_leaves_remaining_data(self, temp_file):
        payload = os.urandom(200000)
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(payload)

        async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=128) as f:
            first = await f.read1(-1)
            rest = await f.read()

        assert first != b""
        assert rest != b""
        assert first + rest == payload

    def test_binary_seekable_and_writable_flags(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        assert f.seekable()
        assert f.writable()
        assert not f.readable()

    def test_text_seekable_and_writable_flags(self, temp_file):
        reader = AsyncGzipTextFile(temp_file, "rt")
        assert reader.seekable()
        assert reader.readable()
        assert not reader.writable()

        writer = AsyncGzipTextFile(temp_file, "wt")
        assert writer.seekable()
        assert writer.writable()
        assert not writer.readable()

    @pytest.mark.asyncio
    async def test_binary_seek_write_extends_with_zeros(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"hi")
            await f.seek(5)
            await f.write(b"X")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
            assert data == b"hi" + b"\x00" * 3 + b"X"

    @pytest.mark.asyncio
    async def test_tarfile_like_iteration(self, tmp_path):
        """Simulate tarfile's seek/tell pattern over a gzip tarball."""
        tar_path = tmp_path / "archive.tar.gz"
        file1 = tmp_path / "inner1.txt"
        file2 = tmp_path / "inner2.txt"
        contents = {
            "inner1.txt": "alpha\nbeta",
            "inner2.txt": "gamma",
        }
        file1.write_text(contents["inner1.txt"], encoding="utf-8")
        file2.write_text(contents["inner2.txt"], encoding="utf-8")
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(file1, arcname="inner1.txt")
            tar.add(file2, arcname="inner2.txt")

        seen = []
        async with AsyncGzipBinaryFile(tar_path, "rb") as f:
            while True:
                header = await f.read(512)
                if not header or header == b"\x00" * 512:
                    break
                info = tarfile.TarInfo.frombuf(
                    header, encoding="utf-8", errors="surrogateescape"
                )
                seen.append(info.name)
                file_start = await f.tell()
                data = await f.read(info.size)
                if info.name in contents:
                    assert data.decode("utf-8") == contents[info.name]
                await f.seek(file_start)
                if data:
                    assert await f.read(1) == data[:1]
                await f.seek(file_start + info.size)
                pad = (-info.size) % 512
                if pad:
                    await f.seek(await f.tell() + pad)

        actual = [name for name in seen if name in contents]
        assert sorted(actual) == sorted(contents.keys())
