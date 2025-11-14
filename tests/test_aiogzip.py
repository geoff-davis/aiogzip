# pyrefly: ignore
# pyrefly: disable=all
import gzip
import os
import tempfile
from typing import Union

import aiocsv
import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipFile,
    AsyncGzipTextFile,
    WithAsyncRead,
    WithAsyncReadWrite,
    WithAsyncWrite,
)


class TestAsyncGzipFile:
    """Test the AsyncGzipFile factory function."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.fixture
    def sample_data(self):
        """Sample data for testing."""
        return b"Hello, World! This is a test string for gzip compression."

    @pytest.fixture
    def large_data(self):
        """Large data for testing chunked operations."""
        return b"Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 1000

    def test_init_valid_modes(self):
        """Test initialization with valid modes."""
        # Test binary modes
        gz_file = AsyncGzipFile("test.gz", "rb")
        assert gz_file._filename == "test.gz"
        assert gz_file._mode == "rb"
        assert gz_file._file_mode == "rb"  # pyrefly: ignore
        assert gz_file._chunk_size == AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE

        gz_file = AsyncGzipFile("test.gz", "wb")
        assert gz_file._mode == "wb"
        assert gz_file._file_mode == "wb"  # pyrefly: ignore

        # Test text modes
        gz_file = AsyncGzipFile("test.gz", "rt")
        assert gz_file._mode == "rt"
        assert gz_file._binary_mode == "rb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "wt")
        assert gz_file._mode == "wt"
        assert gz_file._binary_mode == "wb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "xb")
        assert gz_file._mode == "xb"
        assert gz_file._file_mode == "xb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "xt")
        assert gz_file._mode == "xt"
        assert gz_file._binary_mode == "xb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "wb", chunk_size=1024)
        assert gz_file._chunk_size == 1024

    def test_init_invalid_mode(self):
        """Test initialization with invalid mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid mode"):
            AsyncGzipFile("test.gz", "invalid")

    def test_initial_state_binary(self):
        """Test initial state of AsyncGzipFile in binary mode."""
        gz_file = AsyncGzipFile("test.gz", "rb")
        # Check that we get the correct type
        assert isinstance(gz_file, AsyncGzipBinaryFile)
        assert gz_file._file is None  # pyrefly: ignore
        assert gz_file._engine is None  # pyrefly: ignore
        assert gz_file._buffer == b""  # pyrefly: ignore
        assert gz_file._is_closed is False
        assert gz_file._eof is False  # pyrefly: ignore

    def test_initial_state_text(self):
        """Test initial state of AsyncGzipFile in text mode."""
        gz_file = AsyncGzipFile("test.gz", "rt")
        # Check that we get the correct type
        assert isinstance(gz_file, AsyncGzipTextFile)
        assert gz_file._binary_file is None  # pyrefly: ignore
        assert gz_file._text_buffer == ""  # pyrefly: ignore
        assert gz_file._is_closed is False
        assert gz_file._pending_bytes == b""  # pyrefly: ignore
        assert gz_file._text_data == ""  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_context_manager_write_read_binary(self, temp_file, sample_data):
        """Test writing and reading data using context manager in binary mode."""
        # Write data
        async with AsyncGzipFile(temp_file, "wb") as gz_file:
            bytes_written = await gz_file.write(sample_data)
            assert bytes_written == len(sample_data)

        # Read data
        async with AsyncGzipFile(temp_file, "rb") as gz_file:
            read_data = await gz_file.read()
            assert read_data == sample_data

    @pytest.mark.asyncio
    async def test_context_manager_write_read_text(self, temp_file):
        """Test writing and reading data using context manager in text mode."""
        test_text = "Hello, World! This is a test string."

        # Write data
        async with AsyncGzipFile(temp_file, "wt") as gz_file:
            bytes_written = await gz_file.write(test_text)  # pyrefly: ignore
            assert bytes_written == len(test_text)

        # Read data
        async with AsyncGzipFile(temp_file, "rt") as gz_file:
            read_data = await gz_file.read()
            assert read_data == test_text

    @pytest.mark.asyncio
    async def test_partial_read_binary(self, temp_file, sample_data):
        """Test partial reading in binary mode."""
        async with AsyncGzipFile(temp_file, "wb") as gz_file:
            await gz_file.write(sample_data)

        async with AsyncGzipFile(temp_file, "rb") as gz_file:
            # Read first 10 bytes
            partial_data = await gz_file.read(10)
            assert partial_data == sample_data[:10]

            # Read remaining data
            remaining_data = await gz_file.read()
            assert remaining_data == sample_data[10:]

    @pytest.mark.asyncio
    async def test_partial_read_text(self, temp_file):
        """Test partial reading in text mode."""
        test_text = "Hello, World! This is a test string."

        async with AsyncGzipFile(temp_file, "wt") as gz_file:
            await gz_file.write(test_text)  # pyrefly: ignore

        async with AsyncGzipFile(temp_file, "rt") as gz_file:
            # Read first 10 characters
            partial_data = await gz_file.read(10)
            assert partial_data == test_text[:10]

            # Read remaining data
            remaining_data = await gz_file.read()
            assert remaining_data == test_text[10:]

    @pytest.mark.asyncio
    async def test_large_data_binary(self, temp_file, large_data):
        """Test with large data in binary mode."""
        async with AsyncGzipFile(temp_file, "wb") as gz_file:
            await gz_file.write(large_data)

        async with AsyncGzipFile(temp_file, "rb") as gz_file:
            read_data = await gz_file.read()
            assert read_data == large_data

    @pytest.mark.asyncio
    async def test_large_data_text(self, temp_file):
        """Test with large data in text mode."""
        large_text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 1000

        async with AsyncGzipFile(temp_file, "wt") as gz_file:
            await gz_file.write(large_text)  # pyrefly: ignore

        async with AsyncGzipFile(temp_file, "rt") as gz_file:
            read_data = await gz_file.read()
            assert read_data == large_text

    @pytest.mark.asyncio
    async def test_write_type_error_binary(self, temp_file):
        """Test write with wrong type in binary mode."""
        async with AsyncGzipFile(temp_file, "wb") as gz_file:
            with pytest.raises(
                TypeError, match="write\\(\\) argument must be a bytes-like object"
            ):
                await gz_file.write("string data")  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_write_type_error_text(self, temp_file):
        """Test write with wrong type in text mode."""
        async with AsyncGzipFile(temp_file, "wt") as gz_file:
            with pytest.raises(TypeError, match="write\\(\\) argument must be str"):
                await gz_file.write(b"bytes data")  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_read_type_error_binary(self, temp_file):
        """Test read with wrong mode in binary mode."""
        async with AsyncGzipFile(temp_file, "wb") as gz_file:
            with pytest.raises(IOError, match="File not open for reading"):
                await gz_file.read()

    @pytest.mark.asyncio
    async def test_read_type_error_text(self, temp_file):
        """Test read with wrong mode in text mode."""
        async with AsyncGzipFile(temp_file, "wt") as gz_file:
            with pytest.raises(IOError, match="File not open for reading"):
                await gz_file.read()

    @pytest.mark.asyncio
    async def test_line_iteration_binary_mode_error(self, temp_file):
        """Test that binary mode raises error for line iteration."""
        async with AsyncGzipFile(temp_file, "wb") as f:
            await f.write(b"test data")  # pyrefly: ignore

        async with AsyncGzipFile(temp_file, "rb") as f:
            with pytest.raises(TypeError, match="can only be iterated in text mode"):
                async for line in f:
                    pass

    @pytest.mark.asyncio
    async def test_line_iteration_text_mode(self, temp_file):
        """Test line iteration in text mode."""
        test_lines = ["Line 1\n", "Line 2\n", "Line 3\n"]
        test_text = "".join(test_lines)

        async with AsyncGzipFile(temp_file, "wt") as f:
            await f.write(test_text)  # pyrefly: ignore

        async with AsyncGzipFile(temp_file, "rt") as f:
            lines = []
            async for line in f:
                lines.append(line)
            assert lines == test_lines

    @pytest.mark.asyncio
    async def test_mode_mapping(self):
        """Test that modes are correctly mapped to underlying file modes."""
        # Binary modes
        gz_file = AsyncGzipFile("test.gz", "r")
        assert gz_file._file_mode == "rb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "w")
        assert gz_file._file_mode == "wb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "a")
        assert gz_file._file_mode == "ab"  # pyrefly: ignore

        # Text modes
        gz_file = AsyncGzipFile("test.gz", "rt")
        assert gz_file._binary_mode == "rb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "wt")
        assert gz_file._binary_mode == "wb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "at")
        assert gz_file._binary_mode == "ab"  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_default_chunk_size(self):
        """Test default chunk size."""
        assert AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE == 64 * 1024

    @pytest.mark.asyncio
    async def test_interoperability_with_gzip_binary(self, temp_file, sample_data):
        """Test interoperability with gzip.open for binary data."""
        # Write with AsyncGzipFile
        async with AsyncGzipFile(temp_file, "wb") as f:
            await f.write(sample_data)

        # Read with gzip.open
        with gzip.open(temp_file, "rb") as f:
            read_data = f.read()
            assert read_data == sample_data

        # Write with gzip.open
        with gzip.open(temp_file, "wb") as f:
            f.write(sample_data)

        # Read with AsyncGzipFile
        async with AsyncGzipFile(temp_file, "rb") as f:
            read_data = await f.read()
            assert read_data == sample_data

    @pytest.mark.asyncio
    async def test_interoperability_with_gzip_text(self, temp_file):
        """Test interoperability with gzip.open for text data."""
        test_text = "Hello, World! This is a test string."

        # Write with AsyncGzipFile
        async with AsyncGzipFile(temp_file, "wt") as f:
            await f.write(test_text)  # pyrefly: ignore

        # Read with gzip.open
        with gzip.open(temp_file, "rt") as f:
            read_data = f.read()
            assert read_data == test_text

        # Write with gzip.open
        with gzip.open(temp_file, "wt") as f:
            f.write(test_text)

        # Read with AsyncGzipFile
        async with AsyncGzipFile(temp_file, "rt") as f:
            read_data = await f.read()
            assert read_data == test_text


class TestAsyncGzipBinaryFile:
    """Test the AsyncGzipBinaryFile class."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.fixture
    def sample_data(self):
        """Sample data for testing."""
        return b"Hello, World! This is a test string for gzip compression."

    @pytest.fixture
    def large_data(self):
        """Large data for testing chunked operations."""
        return b"Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 1000

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
            # Read first 10 bytes
            partial_data = await f.read(10)
            assert partial_data == sample_data[:10]

            # Read remaining data
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
        # Write with AsyncGzipBinaryFile
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(sample_data)

        # Read with gzip.open
        with gzip.open(temp_file, "rb") as f:
            read_data = f.read()
            assert read_data == sample_data

        # Write with gzip.open
        with gzip.open(temp_file, "wb") as f:
            f.write(sample_data)

        # Read with AsyncGzipBinaryFile
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            read_data = await f.read()
            assert read_data == sample_data


class TestAsyncGzipTextFile:
    """Test the AsyncGzipTextFile class."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.fixture
    def sample_text(self):
        """Sample text for testing."""
        return "Hello, World! This is a test string for gzip compression."

    @pytest.fixture
    def large_text(self):
        """Large text for testing chunked operations."""
        return "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 1000

    @pytest.mark.asyncio
    async def test_text_write_read_roundtrip(self, temp_file, sample_text):
        """Test basic write/read roundtrip in text mode."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(sample_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            read_data = await f.read()
            assert read_data == sample_text

    @pytest.mark.asyncio
    async def test_text_partial_read(self, temp_file, sample_text):
        """Test partial reading in text mode."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(sample_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Read first 10 characters
            partial_data = await f.read(10)
            assert partial_data == sample_text[:10]

            # Read remaining data
            remaining_data = await f.read()
            assert remaining_data == sample_text[10:]

    @pytest.mark.asyncio
    async def test_text_read_negative_size_returns_all(self, temp_file, sample_text):
        """Negative size should behave the same as read(-1)."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(sample_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read(-42)
            assert data == sample_text

    @pytest.mark.asyncio
    async def test_text_write_returns_character_count(self, temp_file):
        """write() should report the number of characters, not bytes."""
        text = "snowman ☃ and rocket 🚀"
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            written = await f.write(text)
            assert written == len(text)

    @pytest.mark.asyncio
    async def test_text_write_character_count_with_newline_translation(self, temp_file):
        """Character count should ignore newline expansion during encoding."""
        text = "line1\nline2\n"
        async with AsyncGzipTextFile(temp_file, "wt", newline="\r\n") as f:
            written = await f.write(text)
            assert written == len(text)

        # Ensure newline translation actually occurred in the stored bytes.
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
        assert data.count(b"\r\n") == text.count("\n")

    @pytest.mark.asyncio
    async def test_text_read_all_after_partial_with_buffering(self, temp_file):
        """Test read(-1) returns all remaining data including buffered text.

        This test catches a bug where read(-1) would only return buffered
        text data without reading the rest of the file.
        """
        # Create test data that's large enough to ensure internal buffering
        test_text = "x" * 10000 + "END"

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Read a small amount first - this creates internal buffering
            # because the binary read will fetch more data than needed
            first_chars = await f.read(5)
            assert first_chars == "xxxxx"

            # Now read all remaining data with read(-1)
            # This should return ALL remaining data, not just buffered data
            remaining = await f.read(-1)

            # Verify we got everything
            assert first_chars + remaining == test_text
            assert len(remaining) == len(test_text) - 5
            assert remaining.endswith("END")

    @pytest.mark.asyncio
    async def test_text_large_data(self, temp_file, large_text):
        """Test with large data in text mode."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(large_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            read_data = await f.read()
            assert read_data == large_text

    @pytest.mark.asyncio
    async def test_text_bytes_path(self, temp_file, sample_text):
        """Ensure text mode accepts bytes filenames."""
        path_bytes = os.fsencode(temp_file)

        async with AsyncGzipTextFile(path_bytes, "wt") as f:
            await f.write(sample_text)

        async with AsyncGzipTextFile(path_bytes, "rt") as f:
            assert await f.read() == sample_text

    @pytest.mark.asyncio
    async def test_text_mode_xt(self, temp_file, sample_text):
        """Exclusive create mode should be supported for text files."""
        exclusive_path = temp_file + ".xt"
        if os.path.exists(exclusive_path):
            os.unlink(exclusive_path)

        async with AsyncGzipTextFile(exclusive_path, "xt") as f:
            await f.write(sample_text)

        async with AsyncGzipTextFile(exclusive_path, "rt") as f:
            assert await f.read() == sample_text

        os.unlink(exclusive_path)

    @pytest.mark.asyncio
    async def test_text_mode_rt_plus(self, temp_file, sample_text):
        """rt+ should open for reading while still forbidding writes."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(sample_text)

        async with AsyncGzipTextFile(temp_file, "rt+") as f:
            assert await f.read() == sample_text
            with pytest.raises(IOError, match="File not open for writing"):
                await f.write("more")  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_text_newline_empty_handles_split_crlf(self, temp_file):
        """newline='' should treat split CRLF sequences as a single newline."""
        data = "line1\r\nline2\r\n"
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(data)

        async with AsyncGzipTextFile(temp_file, "rt", newline="") as f:
            f._binary_file._chunk_size = 1
            first = await f.readline()
            second = await f.readline()
            assert first == "line1\r\n"
            assert second == "line2\r\n"

    @pytest.mark.asyncio
    async def test_text_newline_empty_trailing_cr(self, temp_file):
        """A trailing CR without LF should still terminate the final line."""
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write("solo\r")

        async with AsyncGzipTextFile(temp_file, "rt", newline="") as f:
            f._binary_file._chunk_size = 1
            line = await f.readline()
            assert line == "solo\r"
            assert await f.readline() == ""

    @pytest.mark.asyncio
    async def test_text_custom_error_handler(self, temp_file):
        """Arbitrary codecs error handlers (e.g., surrogatepass) should be accepted."""
        text = "snowman ☃"
        async with AsyncGzipTextFile(temp_file, "wt", errors="surrogatepass") as f:
            await f.write(text)

        async with AsyncGzipTextFile(temp_file, "rt", errors="surrogatepass") as f:
            assert await f.read() == text

    @pytest.mark.asyncio
    async def test_text_readline_limit(self, temp_file):
        """readline(limit) should stop after limit characters."""
        text = "abcdef\nXYZ\n"

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            part = await f.readline(5)
            assert part == "abcde"
            rest = await f.readline()
            assert rest == "f\n"
            final = await f.readline()
            assert final == "XYZ\n"

    @pytest.mark.asyncio
    async def test_text_line_iteration(self, temp_file):
        """Test line-by-line iteration in text mode."""
        test_lines = ["Line 1\n", "Line 2\n", "Line 3\n"]
        test_text = "".join(test_lines)

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)  # pyrefly: ignore

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = []
            async for line in f:
                lines.append(line)
            assert lines == test_lines

    @pytest.mark.asyncio
    async def test_text_unicode_handling(self, temp_file):
        """Test Unicode character handling in text mode."""
        test_text = "Hello, 世界! 🌍 This is a test with unicode characters."

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)  # pyrefly: ignore

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            read_data = await f.read()
            assert read_data == test_text

    @pytest.mark.asyncio
    async def test_text_multi_byte_character_handling(self, temp_file):
        """Test multi-byte character handling in text mode."""
        test_text = "a" * 100 + "世界" + "b" * 100 + "🚀" + "c" * 100

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)  # pyrefly: ignore

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            read_data = await f.read()
            assert read_data == test_text

    @pytest.mark.asyncio
    async def test_text_multi_byte_character_handling_small_chunks(self, temp_file):
        """Test multi-byte character handling with small read chunks."""
        test_text = "a" * 100 + "世界" + "b" * 100 + "🚀" + "c" * 100

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)  # pyrefly: ignore

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            result = ""
            while True:
                chunk = await f.read(10)
                if not chunk:
                    break
                result += chunk
            assert result == test_text

    @pytest.mark.asyncio
    async def test_text_type_error(self, temp_file):
        """Test type error when writing bytes to text file."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            with pytest.raises(TypeError, match="write\\(\\) argument must be str"):
                await f.write(b"bytes data")  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_text_interoperability_with_gzip(self, temp_file, sample_text):
        """Test interoperability with gzip.open for text data."""
        # Write with AsyncGzipTextFile
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(sample_text)

        # Read with gzip.open
        with gzip.open(temp_file, "rt") as f:
            read_data = f.read()
            assert read_data == sample_text


class TestTextErrorsBehavior:
    """Tests for errors= behavior matching gzip semantics."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_read_errors_strict_raises_on_invalid_bytes(self, temp_file):
        """Reading invalid UTF-8 with errors=strict should raise UnicodeDecodeError."""
        invalid = b"hello " + b"\xff" + b" world"
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(invalid)

        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="utf-8", errors="strict"
        ) as f:
            with pytest.raises(UnicodeDecodeError):
                await f.read()

    @pytest.mark.asyncio
    async def test_read_errors_replace_inserts_replacement_char(self, temp_file):
        """errors=replace should insert U+FFFD for undecodable bytes."""
        invalid = b"good " + b"\xff" + b" text"
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(invalid)

        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="utf-8", errors="replace"
        ) as f:
            data = await f.read()
            assert data == "good \ufffd text"

    @pytest.mark.asyncio
    async def test_read_errors_ignore_drops_undecodable_bytes(self, temp_file):
        """errors=ignore should drop undecodable bytes."""
        invalid = b"good " + b"\xff" + b" text"
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(invalid)

        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="utf-8", errors="ignore"
        ) as f:
            data = await f.read()
            assert data == "good  text"

    @pytest.mark.asyncio
    async def test_write_errors_strict_raises_on_unencodable(self, temp_file):
        """Writing with unencodable chars using strict should raise UnicodeEncodeError."""
        text = "ascii and emoji 🚀"
        async with AsyncGzipTextFile(
            temp_file, "wt", encoding="ascii", errors="strict"
        ) as f:
            with pytest.raises(UnicodeEncodeError):
                await f.write(text)  # pyrefly: ignore

    @pytest.mark.asyncio
    async def test_write_errors_ignore_allows_unencodable(self, temp_file):
        """errors=ignore should drop unencodable characters on write."""
        text = "ascii and emoji 🚀"
        async with AsyncGzipTextFile(
            temp_file, "wt", encoding="ascii", errors="ignore"
        ) as f:
            await f.write(text)  # pyrefly: ignore

        # Read back; content should have emoji removed
        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="ascii", errors="strict"
        ) as f:
            data = await f.read()
            assert data == "ascii and emoji "


class TestTextNewlineBehavior:
    """Tests for newline handling similar to TextIOWrapper semantics."""

    @pytest.fixture
    def temp_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_read_universal_newlines_default(self, temp_file):
        # Prepare data containing CRLF and CR line endings
        raw_text = "line1\r\nline2\rline3\nline4"
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            # newline='' disables translation on write so we store exact bytes
            await f.write(raw_text)  # pyrefly: ignore

        # Default newline=None should translate to \n on read
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read()
            assert data == "line1\nline2\nline3\nline4"

    @pytest.mark.asyncio
    async def test_write_translate_default(self, temp_file):
        # Default newline=None should translate \n -> os.linesep when writing
        text = "a\nb\n"
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(text)  # pyrefly: ignore

        # Read back raw bytes with binary API and check platform linesep occurrence
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
        decoded = data.decode("utf-8")
        assert decoded == ("a" + os.linesep + "b" + os.linesep)

    @pytest.mark.asyncio
    async def test_write_newline_explicit(self, temp_file):
        text = "a\nb\n"
        async with AsyncGzipTextFile(temp_file, "wt", newline="\r\n") as f:
            await f.write(text)  # pyrefly: ignore

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
        decoded = data.decode("utf-8")
        assert decoded == "a\r\nb\r\n"

    @pytest.mark.asyncio
    async def test_no_translation_newline_empty(self, temp_file):
        text = "a\nb\n"
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(text)  # pyrefly: ignore

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
        assert data.decode("utf-8") == text


class TestFileobjSupport:
    """Tests for wrapping an existing async file-like object via fileobj."""

    @pytest.mark.asyncio
    async def test_fileobj_roundtrip(self, tmp_path):
        # Create a real file to obtain an aiofiles handle
        p = tmp_path / "via_fileobj.gz"

        # Use aiofiles directly to open and pass as fileobj
        import aiofiles

        async with aiofiles.open(p, "wb") as raw:
            async with AsyncGzipBinaryFile(None, "wb", fileobj=raw, closefd=False) as f:
                await f.write(b"hello fileobj")

        # Now read using fileobj as well
        async with aiofiles.open(p, "rb") as raw_r:
            async with AsyncGzipBinaryFile(
                None, "rb", fileobj=raw_r, closefd=False
            ) as f:
                data = await f.read()
                assert data == b"hello fileobj"


class TestAiocsvIntegration:
    """Test integration with aiocsv."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_csv_read_write_roundtrip(self, temp_file):
        """Test CSV read/write roundtrip with aiocsv."""
        test_data = [
            {"name": "Alice", "age": "30", "city": "New York"},
            {"name": "Bob", "age": "25", "city": "London"},
            {"name": "Charlie", "age": "35", "city": "Paris"},
        ]

        # Write CSV data
        async with AsyncGzipFile(temp_file, "wt") as f:
            writer = aiocsv.AsyncDictWriter(
                f, fieldnames=["name", "age", "city"]
            )  # pyrefly: ignore
            for row in test_data:
                await writer.writerow(row)

        # Read CSV data
        async with AsyncGzipFile(temp_file, "rt") as f:
            reader = aiocsv.AsyncDictReader(
                f, fieldnames=["name", "age", "city"]
            )  # pyrefly: ignore
            rows = []
            async for row in reader:
                rows.append(row)
            assert rows == test_data

    @pytest.mark.asyncio
    async def test_csv_large_data(self, temp_file):
        """Test CSV with large data."""
        # Generate large CSV data
        test_data = []
        for i in range(1000):
            test_data.append(
                {
                    "id": str(i),
                    "name": f"Person {i}",
                    "email": f"person{i}@example.com",
                    "age": str(20 + (i % 50)),
                }
            )

        # Write CSV data
        async with AsyncGzipFile(temp_file, "wt") as f:
            writer = aiocsv.AsyncDictWriter(
                f, fieldnames=["id", "name", "email", "age"]  # pyrefly: ignore
            )
            for row in test_data:
                await writer.writerow(row)

        # Read CSV data
        async with AsyncGzipFile(temp_file, "rt") as f:
            reader = aiocsv.AsyncDictReader(
                f, fieldnames=["id", "name", "email", "age"]  # pyrefly: ignore
            )
            rows = []
            async for row in reader:
                rows.append(row)
            assert len(rows) == 1000
            assert rows[0] == test_data[0]
            assert rows[-1] == test_data[-1]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_tricky_unicode_split(self, temp_file):
        """
        Tests that multi-byte characters are decoded correctly even when
        split across internal read-chunk boundaries.
        """
        # 1. SETUP: Define a chunk size and create a string that will
        # force a multi-byte character to be split by a read operation.
        chunk_size = 1024

        # The character "世界" is 6 bytes in UTF-8: b'\xe4\xb8\x96\xe7\x95\x8c'.
        # We construct the string so the first binary read of `chunk_size`
        # bytes will end mid-character, capturing only the first few bytes.
        # This creates the adversarial condition we want to test.
        test_text = "a" * (chunk_size - 2) + "世界"

        # 2. ACTION: Write the test string to a compressed file.
        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-8") as f_write:
            await f_write.write(test_text)

        # 3. VERIFICATION: Read the file back using a controlled chunk size
        #    to ensure our multi-byte character is split.
        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-8") as f_read:
            # This is a testing-specific modification to force the desired
            # read behavior by manipulating an internal attribute.
            f_read._binary_file._chunk_size = chunk_size

            # Read the entire file. The library's internal logic will have
            # to handle the broken character across reads.
            read_content = await f_read.read()

        # 4. ASSERT: The final decoded content must exactly match the original.
        assert read_content == test_text

    def test_invalid_filename(self):
        """Test invalid filename inputs."""
        with pytest.raises(ValueError, match="Filename cannot be empty"):
            AsyncGzipBinaryFile("")

        with pytest.raises(ValueError, match="Filename cannot be empty"):
            AsyncGzipTextFile("")

        with pytest.raises(
            ValueError, match="Either filename or fileobj must be provided"
        ):
            AsyncGzipBinaryFile(None)

        with pytest.raises(
            ValueError, match="Either filename or fileobj must be provided"
        ):
            AsyncGzipTextFile(None)

        with pytest.raises(TypeError, match="Filename must be a string"):
            AsyncGzipBinaryFile(123)  # pyrefly: ignore

        with pytest.raises(TypeError, match="Filename must be a string"):
            AsyncGzipTextFile(123)  # pyrefly: ignore

    def test_invalid_chunk_size(self):
        """Test invalid chunk size inputs."""
        with pytest.raises(ValueError, match="Chunk size must be positive"):
            AsyncGzipBinaryFile("test.gz", chunk_size=0)

        with pytest.raises(ValueError, match="Chunk size must be positive"):
            AsyncGzipBinaryFile("test.gz", chunk_size=-1)

        with pytest.raises(ValueError, match="Chunk size too large"):
            AsyncGzipBinaryFile("test.gz", chunk_size=11 * 1024 * 1024)

    def test_invalid_compression_level(self):
        """Test invalid compression level inputs."""
        with pytest.raises(
            ValueError, match="Compression level must be between 0 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", compresslevel=-1)

        with pytest.raises(
            ValueError, match="Compression level must be between 0 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", compresslevel=10)

        with pytest.raises(
            ValueError, match="Compression level must be between 0 and 9"
        ):
            AsyncGzipTextFile("test.gz", compresslevel=-1)

    def test_invalid_mode(self):
        """Test invalid mode inputs."""
        with pytest.raises(ValueError, match="Invalid mode"):
            AsyncGzipBinaryFile("test.gz", mode="invalid")

        with pytest.raises(ValueError, match="Invalid mode"):
            AsyncGzipTextFile("test.gz", mode="invalid")

        # Test that binary file rejects text modes
        with pytest.raises(ValueError, match="text \\('t'\\)"):
            AsyncGzipBinaryFile("test.gz", mode="rt")

        with pytest.raises(ValueError, match="text \\('t'\\)"):
            AsyncGzipBinaryFile("test.gz", mode="wt")

        with pytest.raises(ValueError, match="text \\('t'\\)"):
            AsyncGzipBinaryFile("test.gz", mode="at")

        # Test that text file rejects binary modes
        with pytest.raises(ValueError, match="binary \\('b'\\)"):
            AsyncGzipTextFile("test.gz", mode="rb")

        with pytest.raises(ValueError, match="binary \\('b'\\)"):
            AsyncGzipTextFile("test.gz", mode="wb")

        with pytest.raises(ValueError, match="binary \\('b'\\)"):
            AsyncGzipTextFile("test.gz", mode="ab")

    def test_invalid_encoding(self):
        """Test invalid encoding inputs."""
        with pytest.raises(ValueError, match="Encoding cannot be empty"):
            AsyncGzipTextFile("test.gz", encoding="")

    def test_invalid_errors(self):
        """Test invalid errors inputs."""
        # Arbitrary error handlers should now be accepted
        AsyncGzipTextFile("test.gz", errors="invalid")
        with pytest.raises(ValueError, match="Errors cannot be None"):
            AsyncGzipTextFile("test.gz", errors=None)

    def test_valid_errors_values(self):
        """Test that all valid errors values are accepted."""
        valid_errors = [
            "strict",
            "ignore",
            "replace",
            "backslashreplace",
            "surrogateescape",
            "xmlcharrefreplace",
            "namereplace",
        ]
        for error_val in valid_errors:
            # Should not raise an exception
            f = AsyncGzipTextFile("test.gz", errors=error_val)
            assert f._errors == error_val

    @pytest.mark.asyncio
    async def test_empty_file_operations(self, temp_file):
        """Test operations on empty files."""
        # Write empty file
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            pass  # Write nothing

        # Read empty file
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
            assert data == b""

        # Test partial read on empty file
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read(100)
            assert data == b""

    @pytest.mark.asyncio
    async def test_empty_text_file_operations(self, temp_file):
        """Test operations on empty text files."""
        # Write empty text file
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            pass  # Write nothing

        # Read empty text file
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read()
            assert data == ""

        # Test line iteration on empty file
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = []
            async for line in f:
                lines.append(line)
            assert lines == []

    @pytest.mark.asyncio
    async def test_corrupted_file_handling(self, temp_file):
        """Test handling of corrupted gzip files."""
        # Create a file with invalid gzip data
        with open(temp_file, "wb") as f:
            f.write(b"This is not gzip data")

        # Try to read it
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            with pytest.raises(OSError, match="Error decompressing gzip data"):
                await f.read()

    @pytest.mark.asyncio
    async def test_operations_on_closed_file(self, temp_file):
        """Test operations on closed files."""
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")

        # File is now closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write(b"more data")

    @pytest.mark.asyncio
    async def test_operations_without_context_manager(self, temp_file):
        """Test operations without using context manager."""
        f = AsyncGzipBinaryFile(temp_file, "wb")

        with pytest.raises(ValueError, match="File not opened"):
            await f.write(b"test")

    @pytest.mark.asyncio
    async def test_compression_levels(self, temp_file):
        """Test different compression levels."""
        test_data = b"Hello, World! " * 1000  # Repeating data compresses well

        sizes = {}
        for level in [0, 1, 6, 9]:  # Test min, low, default, max compression
            temp_file_level = f"{temp_file}_{level}"
            async with AsyncGzipBinaryFile(
                temp_file_level, "wb", compresslevel=level
            ) as f:
                await f.write(test_data)

            # Check file size
            sizes[level] = os.path.getsize(temp_file_level)

            # Verify we can read it back
            async with AsyncGzipBinaryFile(temp_file_level, "rb") as f:
                read_data = await f.read()
                assert read_data == test_data

            # Clean up
            os.unlink(temp_file_level)

        # Level 0 (no compression) should be largest
        # Level 9 (max compression) should be smallest for this data
        assert sizes[0] > sizes[9]

    @pytest.mark.asyncio
    async def test_unicode_edge_cases(self, temp_file):
        """Test Unicode edge cases in text mode."""
        # Test various Unicode characters
        test_strings = [
            "Hello, 世界!",  # Mixed ASCII and Chinese
            "🚀🌟💫",  # Emojis
            "Ñoño niño",  # Spanish characters
            "Здравствуй мир",  # Cyrillic
            "مرحبا بالعالم",  # Arabic
            "\n\r\t",  # Control characters
            "",  # Empty string
        ]

        for test_str in test_strings:
            async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
                await f.write(test_str)

            async with AsyncGzipTextFile(temp_file, "rt", newline="") as f:
                read_str = await f.read()
                assert read_str == test_str

    @pytest.mark.asyncio
    async def test_multiple_writes_and_reads(self, temp_file):
        """Test multiple write operations followed by reads."""
        chunks = [b"chunk1", b"chunk2", b"chunk3", b"chunk4"]

        # Write multiple chunks
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            for chunk in chunks:
                await f.write(chunk)

        # Read back all at once
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            all_data = await f.read()
            assert all_data == b"".join(chunks)

        # Read back in parts
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            read_chunks = []
            for expected_chunk in chunks:
                chunk = await f.read(len(expected_chunk))
                read_chunks.append(chunk)
            assert read_chunks == chunks


class TestPerformanceAndMemory:
    """Test performance and memory efficiency."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_memory_efficiency_large_file(self, temp_file):
        """Test that large files don't consume excessive memory."""
        try:
            import psutil
        except ImportError:
            pytest.skip("psutil not available for memory testing")
        import gc

        # Get initial memory usage
        process = psutil.Process()
        initial_memory = process.memory_info().rss

        # Create a large file (10MB of data)
        large_data = b"x" * (10 * 1024 * 1024)

        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(large_data)

        # Force garbage collection
        gc.collect()

        # Read the file in chunks without loading it all into memory
        total_read = 0
        chunk_size = 8192

        async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                total_read += len(chunk)

                # Check memory usage periodically
                current_memory = process.memory_info().rss
                memory_increase = current_memory - initial_memory

                # Memory increase should be reasonable (less than 200MB for 10MB file)
                # Note: gzip decompression can produce large buffers due to compression ratios
                # and the current implementation accumulates decompressed data in memory
                # This is a known limitation of the current streaming implementation
                assert (
                    memory_increase < 200 * 1024 * 1024
                ), f"Memory usage too high: {memory_increase / 1024 / 1024:.1f}MB"

        assert total_read == len(large_data)

    @pytest.mark.asyncio
    async def test_streaming_performance(self, temp_file):
        """Test streaming performance with different chunk sizes."""
        import time

        # Create test data
        test_data = b"Hello, World! " * 100000  # ~1.3MB

        # Write the data
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(test_data)

        # Test different chunk sizes
        chunk_sizes = [1024, 8192, 64 * 1024, 256 * 1024]
        times = {}

        for chunk_size in chunk_sizes:
            start_time = time.time()

            total_read = 0
            async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=chunk_size) as f:
                while True:
                    chunk = await f.read(8192)  # Read in 8KB chunks
                    if not chunk:
                        break
                    total_read += len(chunk)

            end_time = time.time()
            times[chunk_size] = end_time - start_time

            assert total_read == len(test_data)

        # Larger chunk sizes should generally be faster (or at least not much slower)
        # This is a rough heuristic - actual performance depends on many factors
        print(f"Chunk size performance: {times}")

    @pytest.mark.asyncio
    async def test_concurrent_access_different_files(self, temp_file):
        """Test concurrent access to different files."""
        import asyncio

        # Create multiple temp files
        temp_files = [f"{temp_file}_{i}" for i in range(5)]

        async def write_and_read_file(filename, data):
            # Write data
            async with AsyncGzipBinaryFile(filename, "wb") as f:
                await f.write(data)

            # Read it back
            async with AsyncGzipBinaryFile(filename, "rb") as f:
                return await f.read()

        # Create different data for each file
        test_data = [f"File {i} data: " * 1000 for i in range(5)]
        test_data_bytes = [data.encode() for data in test_data]

        # Run concurrent operations
        tasks = [
            write_and_read_file(temp_files[i], test_data_bytes[i]) for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # Verify all results
        for i, result in enumerate(results):
            assert result == test_data_bytes[i]

        # Clean up
        for temp_file_path in temp_files:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    @pytest.mark.asyncio
    async def test_text_mode_memory_efficiency(self, temp_file):
        """Test memory efficiency in text mode with large files."""
        try:
            import psutil
        except ImportError:
            pytest.skip("psutil not available for memory testing")
        import gc

        # Get initial memory usage
        process = psutil.Process()
        initial_memory = process.memory_info().rss

        # Create a large text file
        large_text = "Hello, World! This is a test line.\n" * 100000  # ~3.5MB

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(large_text)

        # Force garbage collection
        gc.collect()

        # Read the file line by line without loading it all into memory
        lines_read = 0

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            async for line in f:
                lines_read += 1

                # Check memory usage periodically
                if lines_read % 10000 == 0:
                    current_memory = process.memory_info().rss
                    memory_increase = current_memory - initial_memory

                    # Memory increase should be reasonable
                    assert (
                        memory_increase < 100 * 1024 * 1024
                    ), f"Memory usage too high: {memory_increase / 1024 / 1024:.1f}MB"

        assert lines_read == 100000

    @pytest.mark.asyncio
    async def test_compression_efficiency(self, temp_file):
        """Test compression efficiency at different levels."""
        # Create highly compressible data
        test_data = b"AAAAAAAAAA" * 100000  # 1MB of repeated data

        compression_ratios = {}

        for level in [0, 1, 6, 9]:
            temp_file_level = f"{temp_file}_{level}"

            async with AsyncGzipBinaryFile(
                temp_file_level, "wb", compresslevel=level
            ) as f:
                await f.write(test_data)

            # Calculate compression ratio
            compressed_size = os.path.getsize(temp_file_level)
            compression_ratios[level] = len(test_data) / compressed_size

            # Verify we can read it back correctly
            async with AsyncGzipBinaryFile(temp_file_level, "rb") as f:
                read_data = await f.read()
                assert read_data == test_data

            # Clean up
            os.unlink(temp_file_level)

        # Level 0 should have minimal compression
        # Level 9 should have maximum compression for this data
        assert compression_ratios[0] < compression_ratios[9]
        print(f"Compression ratios: {compression_ratios}")


class TestProtocols:
    """Test the protocol classes."""

    def test_with_async_read_protocol(self):
        """Test WithAsyncRead protocol."""

        class MockReader:
            async def read(self, size: int = -1) -> str:
                return "test data"

        reader: WithAsyncRead = MockReader()
        assert reader is not None

    def test_with_async_write_protocol(self):
        """Test WithAsyncWrite protocol."""

        class MockWriter:
            async def write(self, data: Union[str, bytes]) -> int:
                return len(data)

        writer: WithAsyncWrite = MockWriter()
        assert writer is not None

    def test_with_async_read_write_protocol(self):
        """Test WithAsyncReadWrite protocol."""

        class MockReadWriter:
            async def read(self, size: int = -1) -> Union[str, bytes]:
                return "test data"

            async def write(self, data: Union[str, bytes]) -> int:
                return len(data)

        read_writer: WithAsyncReadWrite = MockReadWriter()
        assert read_writer is not None


class TestPathlibSupport:
    """Test support for pathlib.Path objects."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_binary_file_with_path_object(self, temp_file):
        """Test AsyncGzipBinaryFile with pathlib.Path object."""
        from pathlib import Path

        path_obj = Path(temp_file)
        test_data = b"Hello, Path!"

        # Write with Path object
        async with AsyncGzipBinaryFile(path_obj, "wb") as f:
            await f.write(test_data)

        # Read with Path object
        async with AsyncGzipBinaryFile(path_obj, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data

    @pytest.mark.asyncio
    async def test_text_file_with_path_object(self, temp_file):
        """Test AsyncGzipTextFile with pathlib.Path object."""
        from pathlib import Path

        path_obj = Path(temp_file)
        test_text = "Hello, Path!"

        # Write with Path object
        async with AsyncGzipTextFile(path_obj, "wt") as f:
            await f.write(test_text)

        # Read with Path object
        async with AsyncGzipTextFile(path_obj, "rt") as f:
            read_text = await f.read()

        assert read_text == test_text

    @pytest.mark.asyncio
    async def test_factory_with_path_object(self, temp_file):
        """Test AsyncGzipFile factory with pathlib.Path object."""
        from pathlib import Path

        path_obj = Path(temp_file)
        test_data = b"Hello, Factory!"

        # Write with Path object
        async with AsyncGzipFile(path_obj, "wb") as f:
            await f.write(test_data)

        # Read with Path object
        async with AsyncGzipFile(path_obj, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data

    @pytest.mark.asyncio
    async def test_path_with_bytes(self, temp_file):
        """Test with bytes path (os.PathLike)."""
        path_bytes = temp_file.encode("utf-8")
        test_data = b"Hello, bytes path!"

        # Write with bytes path
        async with AsyncGzipBinaryFile(path_bytes, "wb") as f:
            await f.write(test_data)

        # Read with bytes path
        async with AsyncGzipBinaryFile(path_bytes, "rb") as f:
            read_data = await f.read()

        assert read_data == test_data


class TestClosefdParameter:
    """Test closefd parameter behavior."""

    @pytest.mark.asyncio
    async def test_closefd_true_closes_file(self, tmp_path):
        """Test that closefd=True closes the underlying file object."""
        import aiofiles

        p = tmp_path / "test_closefd_true.gz"

        # Open file and pass to AsyncGzipBinaryFile with closefd=True
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipBinaryFile(
            None, "wb", fileobj=file_handle, closefd=True
        ) as f:
            await f.write(b"test data")

        # File should be closed after context manager exit
        # Attempting to write should fail
        with pytest.raises((ValueError, AttributeError)):
            await file_handle.write(b"more data")

    @pytest.mark.asyncio
    async def test_closefd_false_keeps_file_open(self, tmp_path):
        """Test that closefd=False keeps the underlying file object open."""
        import aiofiles

        p = tmp_path / "test_closefd_false.gz"

        # Open file and pass to AsyncGzipBinaryFile with closefd=False
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipBinaryFile(
            None, "wb", fileobj=file_handle, closefd=False
        ) as f:
            await f.write(b"test data")

        # File should still be open after context manager exit
        # We should be able to write more data
        await file_handle.write(b"more data")
        await file_handle.close()

        # Verify both writes succeeded
        async with aiofiles.open(p, "rb") as f:
            content = await f.read()

        # The file should contain gzipped data followed by "more data"
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_closefd_default_closes_owned_file(self, tmp_path):
        """Test that default closefd behavior closes file when we own it."""
        p = tmp_path / "test_closefd_default.gz"

        # When filename is provided (not fileobj), we own the file
        f = AsyncGzipBinaryFile(p, "wb")
        async with f:
            await f.write(b"test data")

        # Internal file should be closed
        assert f._is_closed is True

    @pytest.mark.asyncio
    async def test_closefd_with_text_file(self, tmp_path):
        """Test closefd parameter with AsyncGzipTextFile."""
        import aiofiles

        p = tmp_path / "test_text_closefd.gz"

        # Open file and pass to AsyncGzipTextFile with closefd=False
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipTextFile(
            None, "wt", fileobj=file_handle, closefd=False
        ) as f:
            await f.write("test text")

        # File should still be accessible
        # Close it manually
        await file_handle.close()


class TestAppendMode:
    """Test append mode operations and limitations."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_append_mode_binary(self, temp_file):
        """Test append mode with binary data.

        Note: Appending to gzip files creates a multi-member gzip archive.
        Standard gzip tools can read these, but they're not commonly used.
        """
        # Write initial data
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"first write")

        # Append more data
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"second write")

        # Read back - should get concatenated decompressed data
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        # Standard gzip readers handle multi-member archives by concatenating
        assert data == b"first writesecond write"

    @pytest.mark.asyncio
    async def test_append_mode_text(self, temp_file):
        """Test append mode with text data."""
        # Write initial data
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("first line\n")

        # Append more data
        async with AsyncGzipTextFile(temp_file, "at") as f:
            await f.write("second line\n")

        # Read back
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read()

        assert data == "first line\nsecond line\n"

    @pytest.mark.asyncio
    async def test_append_mode_multiple_appends(self, temp_file):
        """Test multiple append operations."""
        # Initial write
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"part1")

        # First append
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"part2")

        # Second append
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"part3")

        # Read back all data
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"part1part2part3"

    @pytest.mark.asyncio
    async def test_append_to_empty_file(self, temp_file):
        """Test appending to an empty/new file (should work like write)."""
        # Append to a new file
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"appended data")

        # Read back
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"appended data"

    @pytest.mark.asyncio
    async def test_append_mode_interoperability_with_gzip(self, temp_file):
        """Test that append mode works with standard gzip library."""
        # Write with AsyncGzipBinaryFile
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"async write")

        # Append with standard gzip
        with gzip.open(temp_file, "ab") as f:
            f.write(b" gzip append")

        # Read with AsyncGzipBinaryFile
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"async write gzip append"

    @pytest.mark.asyncio
    async def test_cannot_read_in_append_mode(self, temp_file):
        """Test that reading is not allowed in append mode."""
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            with pytest.raises(IOError, match="File not open for reading"):
                await f.read()

    @pytest.mark.asyncio
    async def test_append_mode_with_line_iteration(self, temp_file):
        """Test line iteration after appending text data."""
        # Write initial lines
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("line1\nline2\n")

        # Append more lines
        async with AsyncGzipTextFile(temp_file, "at") as f:
            await f.write("line3\nline4\n")

        # Read lines
        lines = []
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            async for line in f:
                lines.append(line)

        assert lines == ["line1\n", "line2\n", "line3\n", "line4\n"]


class TestResourceCleanup:
    """Test proper resource cleanup and concurrent close handling."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_double_close_binary(self, temp_file):
        """Test that calling close() twice doesn't cause errors."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        # File is already closed by context manager
        # Calling close again should be safe
        await f.close()
        await f.close()  # Third close should also be safe

    @pytest.mark.asyncio
    async def test_double_close_text(self, temp_file):
        """Test that calling close() twice on text file doesn't cause errors."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test data")

        # File is already closed by context manager
        # Calling close again should be safe
        await f.close()
        await f.close()  # Third close should also be safe

    @pytest.mark.asyncio
    async def test_concurrent_close_binary(self, temp_file):
        """Test concurrent close calls don't cause race conditions."""
        import asyncio

        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test data")

        # Attempt to close concurrently
        # Both should complete without errors
        await asyncio.gather(
            f.close(),
            f.close(),
            f.close(),
        )

    @pytest.mark.asyncio
    async def test_concurrent_close_text(self, temp_file):
        """Test concurrent close calls on text file don't cause race conditions."""
        import asyncio

        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test data")

        # Attempt to close concurrently
        # Both should complete without errors
        await asyncio.gather(
            f.close(),
            f.close(),
            f.close(),
        )

    @pytest.mark.asyncio
    async def test_operations_after_close_raise_errors(self, temp_file):
        """Test that operations after close raise appropriate errors."""
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test data")

        # After close, operations should fail
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write(b"more data")

    @pytest.mark.asyncio
    async def test_close_with_exception_during_flush(self, temp_file):
        """Test that close handles exceptions during flush properly."""
        # Open file but don't use context manager so we can control closure
        f = AsyncGzipBinaryFile(temp_file, "wb")
        await f.__aenter__()
        await f.write(b"test data")

        # Close the underlying file first to cause an error during flush
        if f._file is not None:
            await f._file.close()

        # Close should mark file as closed even if flush fails
        # But it should propagate the exception
        with pytest.raises(Exception):
            await f.close()

        # File should still be marked as closed
        assert f._is_closed is True

        # Subsequent closes should be safe (idempotent)
        await f.close()
        await f.close()


class TestErrorHandlingConsistency:
    """Test consistent error handling across the module."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_zlib_errors_wrapped_as_oserror(self, temp_file):
        """Test that zlib errors are consistently wrapped in OSError."""
        # Create corrupted gzip file
        with open(temp_file, "wb") as f:
            f.write(b"Not a valid gzip file")

        # Reading should raise OSError (not zlib.error)
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            with pytest.raises(OSError, match="Error decompressing gzip data"):
                await f.read()

    @pytest.mark.asyncio
    async def test_all_operation_errors_are_oserror(self, temp_file):
        """Test that all operation failures raise OSError consistently."""
        # Write valid data first
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        # Try to write when file is read-only
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            with pytest.raises(IOError, match="File not open for writing"):
                await f.write(b"more data")

        # Try to read when file is write-only
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            with pytest.raises(IOError, match="File not open for reading"):
                await f.read()

    @pytest.mark.asyncio
    async def test_exception_chaining_preserved(self, temp_file):
        """Test that exception chaining is used (from e) for debugging."""
        # Create corrupted file
        with open(temp_file, "wb") as f:
            f.write(b"\x1f\x8b\x08\x00corrupted")

        try:
            async with AsyncGzipBinaryFile(temp_file, "rb") as f:
                await f.read()
        except OSError as e:
            # Should have a __cause__ from the original zlib.error
            assert e.__cause__ is not None
            assert (
                "zlib" in str(type(e.__cause__)).lower()
                or "error" in str(type(e.__cause__)).lower()
            )

    @pytest.mark.asyncio
    async def test_clear_error_messages(self, temp_file):
        """Test that error messages clearly indicate which operation failed."""
        # Test compression error message
        with open(temp_file, "wb") as f:
            f.write(b"\x1f\x8b\x08\x00corrupted")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            try:
                await f.read()
            except OSError as e:
                # Error message should indicate it's a decompression error
                assert "decompress" in str(e).lower()

    @pytest.mark.asyncio
    async def test_io_errors_not_wrapped(self, tmp_path):
        """Test that I/O errors are re-raised as-is, not wrapped."""
        # Create a file that we'll delete while reading
        test_file = tmp_path / "test.gz"

        async with AsyncGzipBinaryFile(test_file, "wb") as f:
            await f.write(b"test data")

        # Open file for reading but don't read yet
        f = AsyncGzipBinaryFile(test_file, "rb")
        await f.__aenter__()

        # Close the underlying file to simulate I/O error
        if f._file is not None:
            await f._file.close()

        # Try to read - should get an I/O error (not wrapped in our custom OSError)
        with pytest.raises(
            (OSError, ValueError)
        ):  # aiofiles may raise ValueError for closed file
            await f.read()

        # Clean up
        await f.__aexit__(None, None, None)


class TestNewAPIMethods:
    """Test new API methods: flush() and readline()."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_binary_flush_method(self, temp_file):
        """Test flush() method on binary file."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"Hello")
            await f.flush()  # Should not raise
            await f.write(b" World")
            await f.flush()  # Should not raise

        # Verify data was written correctly
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
            assert data == b"Hello World"

    @pytest.mark.asyncio
    async def test_text_flush_method(self, temp_file):
        """Test flush() method on text file."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello")
            await f.flush()  # Should not raise
            await f.write(" World")
            await f.flush()  # Should not raise

        # Verify data was written correctly
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read()
            assert data == "Hello World"

    @pytest.mark.asyncio
    async def test_flush_on_closed_file_raises(self, temp_file):
        """Test that flush() raises on closed file."""
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")

        # After close, flush should raise
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.flush()

    @pytest.mark.asyncio
    async def test_flush_in_read_mode_is_noop(self, temp_file):
        """Test that flush() is a no-op in read mode."""
        # Write some data first
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        # Flush in read mode should not raise
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            await f.flush()  # Should be no-op
            data = await f.read()
            assert data == b"test data"

    @pytest.mark.asyncio
    async def test_readline_basic(self, temp_file):
        """Test basic readline() functionality."""
        # Write test data with multiple lines
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line 1\nLine 2\nLine 3")

        # Read line by line
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line1 = await f.readline()
            assert line1 == "Line 1\n"

            line2 = await f.readline()
            assert line2 == "Line 2\n"

            line3 = await f.readline()
            assert line3 == "Line 3"  # No newline at end

            eof = await f.readline()
            assert eof == ""  # EOF returns empty string

    @pytest.mark.asyncio
    async def test_readline_empty_file(self, temp_file):
        """Test readline() on empty file."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            pass  # Write nothing

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line = await f.readline()
            assert line == ""

    @pytest.mark.asyncio
    async def test_readline_single_line(self, temp_file):
        """Test readline() with single line."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Single line\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line = await f.readline()
            assert line == "Single line\n"
            eof = await f.readline()
            assert eof == ""

    @pytest.mark.asyncio
    async def test_readline_vs_iteration(self, temp_file):
        """Test that readline() and iteration produce same results."""
        test_data = "Line 1\nLine 2\nLine 3\n"

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_data)

        # Read with readline
        lines_readline = []
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            while True:
                line = await f.readline()
                if not line:
                    break
                lines_readline.append(line)

        # Read with iteration
        lines_iter = []
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            async for line in f:
                lines_iter.append(line)

        assert lines_readline == lines_iter

    @pytest.mark.asyncio
    async def test_readline_in_write_mode_raises(self, temp_file):
        """Test that readline() raises in write mode."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            with pytest.raises(IOError, match="File not open for reading"):
                await f.readline()

    @pytest.mark.asyncio
    async def test_readline_on_closed_file_raises(self, temp_file):
        """Test that readline() raises on closed file."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.readline()

    @pytest.mark.asyncio
    async def test_readline_large_lines(self, temp_file):
        """Test readline() with large lines."""
        # Create a large line that exceeds buffer size
        large_line = "x" * 100000 + "\n"

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(large_line)
            await f.write("small line\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line1 = await f.readline()
            assert line1 == large_line
            line2 = await f.readline()
            assert line2 == "small line\n"


class TestHighPriorityEdgeCases:
    """Test high priority edge cases for improved coverage."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_unexpected_compression_error(self, temp_file):
        """Test that unexpected errors during compression are wrapped in OSError."""

        class MockEngine:
            """Mock compression engine that raises unexpected error."""
            def compress(self, data):
                raise RuntimeError("Unexpected error")
            def flush(self, mode=None):
                return b""

        f = AsyncGzipBinaryFile(temp_file, "wb")
        await f.__aenter__()

        # Replace engine with our mock
        f._engine = MockEngine()

        with pytest.raises(OSError, match="Unexpected error during compression"):
            await f.write(b"test data")

        await f.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_unexpected_decompression_error(self, temp_file):
        """Test that unexpected errors during decompression are wrapped in OSError."""

        # First write valid data
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        class MockEngine:
            """Mock decompression engine that raises unexpected error."""
            def decompress(self, data):
                raise RuntimeError("Unexpected decompress error")
            @property
            def unused_data(self):
                return b""

        # Now read with mocked decompressor
        f = AsyncGzipBinaryFile(temp_file, "rb")
        await f.__aenter__()

        # Replace engine with our mock
        f._engine = MockEngine()

        with pytest.raises(OSError, match="Unexpected error during decompression"):
            await f.read()

        await f.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_decompression_finalization_error(self, temp_file):
        """Test error handling when finalizing gzip decompression at EOF."""
        import zlib

        # Write valid data
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        class MockEngine:
            """Mock decompression engine that raises error on flush."""
            def __init__(self):
                self._called_decompress = False

            def decompress(self, data):
                self._called_decompress = True
                # First call works, subsequent calls fail
                return b""

            def flush(self):
                raise zlib.error("Finalization error")

            @property
            def unused_data(self):
                return b""

        f = AsyncGzipBinaryFile(temp_file, "rb")
        await f.__aenter__()

        # Replace engine after opening
        f._engine = MockEngine()

        with pytest.raises(OSError, match="Error finalizing gzip decompression"):
            await f.read()

        await f.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_unexpected_flush_error(self, temp_file):
        """Test that unexpected errors during flush are wrapped in OSError."""
        import zlib

        class MockEngine:
            """Mock compression engine that raises unexpected error on flush."""
            def __init__(self):
                self.flush_count = 0

            def compress(self, data):
                return b"compressed"

            def flush(self, mode=zlib.Z_SYNC_FLUSH):
                self.flush_count += 1
                # Only raise on the first explicit flush call, not on close
                if self.flush_count == 1:
                    raise RuntimeError("Unexpected flush error")
                return b""

        f = AsyncGzipBinaryFile(temp_file, "wb")
        await f.__aenter__()
        await f.write(b"test data")

        # Replace engine with our mock
        mock_engine = MockEngine()
        f._engine = mock_engine

        with pytest.raises(OSError, match="Unexpected error during flush"):
            await f.flush()

        # Now manually close, allowing the second flush to succeed
        await f.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_multibyte_split_at_start(self, temp_file):
        """Test multibyte character incomplete at the very start of a chunk."""
        # Create a string where a 4-byte emoji is split right at chunk boundary
        # UTF-8 emoji "🚀" = b'\xf0\x9f\x9a\x80' (4 bytes)
        chunk_size = 1024

        # Put emoji at positions that will split across chunk boundaries
        test_text = "a" * (chunk_size - 1) + "🚀" + "b" * 100

        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-8") as f:
            await f.write(test_text)

        # Read with small chunks to force splits
        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-8", chunk_size=chunk_size) as f:
            # Force small binary reads
            f._binary_file._chunk_size = chunk_size
            read_content = await f.read()

        assert read_content == test_text

    @pytest.mark.asyncio
    async def test_multibyte_incomplete_with_errors_ignore(self, temp_file):
        """Test incomplete multibyte sequence handling with errors='ignore'."""
        # Write data with an incomplete UTF-8 sequence at the end
        # We'll write raw bytes with binary mode
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            # Valid UTF-8 "test" followed by incomplete 4-byte sequence (only 2 bytes)
            await f.write(b"test\xf0\x9f")

        # Read with errors='ignore' should skip incomplete bytes
        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-8", errors="ignore") as f:
            data = await f.read()
            # Should only get "test", incomplete sequence ignored
            assert data == "test"

    @pytest.mark.asyncio
    async def test_multibyte_incomplete_with_errors_replace(self, temp_file):
        """Test incomplete multibyte sequence handling with errors='replace'."""
        # Write data with an incomplete UTF-8 sequence at the end
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            # Valid UTF-8 "test" followed by incomplete 4-byte sequence (only 2 bytes)
            await f.write(b"test\xf0\x9f")

        # Read with errors='replace' should replace incomplete bytes with U+FFFD
        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-8", errors="replace") as f:
            data = await f.read()
            # Should get "test" followed by replacement characters
            assert data.startswith("test")
            assert "\ufffd" in data

    @pytest.mark.asyncio
    async def test_empty_data_in_safe_decode_with_remainder(self, temp_file):
        """Test that empty data in _safe_decode_with_remainder returns empty string."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Test the internal method directly
            result, remainder = f._safe_decode_with_remainder(b"")
            assert result == ""
            assert remainder == b""

    @pytest.mark.asyncio
    async def test_multibyte_all_split_positions(self, temp_file):
        """Test multibyte character split at different positions (1, 2, 3 bytes)."""
        # UTF-8 emoji "🚀" = b'\xf0\x9f\x9a\x80' (4 bytes)
        # We'll test splits after 1, 2, and 3 bytes

        for split_pos in [1, 2, 3]:
            chunk_size = 1024
            # Position emoji so it splits at different points
            prefix_len = chunk_size - split_pos
            test_text = "a" * prefix_len + "🚀test"

            async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-8") as f:
                await f.write(test_text)

            async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-8", chunk_size=chunk_size) as f:
                f._binary_file._chunk_size = chunk_size
                read_content = await f.read()

            assert read_content == test_text, f"Failed at split position {split_pos}"

    @pytest.mark.asyncio
    async def test_multiple_multibyte_characters_at_boundaries(self, temp_file):
        """Test multiple multibyte characters at chunk boundaries."""
        chunk_size = 1024

        # Create text with multiple emojis positioned at boundaries
        # Each emoji is 4 bytes in UTF-8
        text_parts = []
        for i in range(5):
            text_parts.append("x" * (chunk_size - 2))
            text_parts.append("🚀")

        test_text = "".join(text_parts)

        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-8") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-8", chunk_size=chunk_size) as f:
            f._binary_file._chunk_size = chunk_size
            # Read in small increments to stress test boundary handling
            result = ""
            while True:
                chunk = await f.read(100)
                if not chunk:
                    break
                result += chunk

        assert result == test_text

    @pytest.mark.asyncio
    async def test_utf16_encoding_incomplete_handling(self, temp_file):
        """Test UTF-16 encoding with potential incomplete sequences."""
        test_text = "Hello 世界 🚀"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-16") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-16") as f:
            read_text = await f.read()

        assert read_text == test_text

    @pytest.mark.asyncio
    async def test_utf32_encoding_incomplete_handling(self, temp_file):
        """Test UTF-32 encoding with potential incomplete sequences."""
        test_text = "Hello 世界 🚀"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-32") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-32") as f:
            read_text = await f.read()

        assert read_text == test_text

    @pytest.mark.asyncio
    async def test_multi_member_empty_member(self, temp_file):
        """Test reading multi-member gzip with an empty member."""
        # Create a multi-member gzip file with one empty member
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"first part")

        # Append an empty member
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            pass  # Write nothing

        # Append more data
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"third part")

        # Read should concatenate all members
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"first partthird part"

    @pytest.mark.asyncio
    async def test_multi_member_many_members(self, temp_file):
        """Test reading multi-member gzip with many members."""
        # Create multiple members
        for i in range(10):
            async with AsyncGzipBinaryFile(temp_file, "ab" if i > 0 else "wb") as f:
                await f.write(f"part{i}".encode())

        # Read should concatenate all
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        expected = b"".join(f"part{i}".encode() for i in range(10))
        assert data == expected

    @pytest.mark.asyncio
    async def test_multi_member_partial_read(self, temp_file):
        """Test partial reading of multi-member gzip."""
        # Create multi-member file
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"AAAA")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"BBBB")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"CCCC")

        # Read in small chunks across member boundaries
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            part1 = await f.read(6)  # Should span first two members
            part2 = await f.read(6)  # Should span into third member
            part3 = await f.read()   # Rest

        assert part1 + part2 + part3 == b"AAAABBBBCCCC"

    @pytest.mark.asyncio
    async def test_multi_member_unused_data_handling(self, temp_file):
        """Test that unused_data from multi-member archives is handled correctly."""
        import gzip

        # Create multi-member file using standard gzip
        with gzip.open(temp_file, "wb") as f:
            f.write(b"member1")

        with gzip.open(temp_file, "ab") as f:
            f.write(b"member2")

        with gzip.open(temp_file, "ab") as f:
            f.write(b"member3")

        # Read and verify all members are concatenated
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"member1member2member3"

    @pytest.mark.asyncio
    async def test_reading_after_eof_repeatedly(self, temp_file):
        """Test that reading after EOF works correctly."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            # Read all data
            data1 = await f.read()
            assert data1 == b"test data"

            # Read after EOF should return empty
            data2 = await f.read()
            assert data2 == b""

            # Read after EOF again should still return empty
            data3 = await f.read()
            assert data3 == b""

            # Partial read after EOF
            data4 = await f.read(100)
            assert data4 == b""


class TestMediumPriorityEdgeCases:
    """Test medium priority edge cases for improved coverage."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_async_flush_on_underlying_file(self, temp_file):
        """Test that async flush method on underlying file object is awaited."""

        class AsyncFileWithAsyncFlush:
            """Mock file object with async flush method."""
            def __init__(self, real_file):
                self.real_file = real_file
                self.flush_called = False

            async def write(self, data):
                return await self.real_file.write(data)

            async def flush(self):
                """Async flush method that should be detected and awaited."""
                self.flush_called = True
                # Call real file's flush if it exists
                if hasattr(self.real_file, 'flush'):
                    flush_method = self.real_file.flush
                    if callable(flush_method):
                        result = flush_method()
                        if hasattr(result, '__await__'):
                            await result

            async def close(self):
                await self.real_file.close()

        import aiofiles

        # Create a real aiofiles handle
        real_file = await aiofiles.open(temp_file, "wb")

        # Wrap it with our mock that has async flush
        mock_file = AsyncFileWithAsyncFlush(real_file)

        # Use it as fileobj
        f = AsyncGzipBinaryFile(None, "wb", fileobj=mock_file, closefd=False)
        await f.__aenter__()
        await f.write(b"test data")

        # Call flush - should detect and await the async flush
        await f.flush()

        # Verify our async flush was called
        assert mock_file.flush_called is True

        await f.__aexit__(None, None, None)
        await real_file.close()

    @pytest.mark.asyncio
    async def test_async_close_on_underlying_file(self, temp_file):
        """Test that async close method on underlying file object is awaited."""

        class AsyncFileWithAsyncClose:
            """Mock file object with async close method."""
            def __init__(self, real_file):
                self.real_file = real_file
                self.close_called = False

            async def write(self, data):
                return await self.real_file.write(data)

            async def close(self):
                """Async close method that should be detected and awaited."""
                self.close_called = True
                await self.real_file.close()

        import aiofiles

        # Create a real aiofiles handle
        real_file = await aiofiles.open(temp_file, "wb")

        # Wrap it with our mock that has async close
        mock_file = AsyncFileWithAsyncClose(real_file)

        # Use it as fileobj with closefd=True to trigger close
        f = AsyncGzipBinaryFile(None, "wb", fileobj=mock_file, closefd=True)
        await f.__aenter__()
        await f.write(b"test data")

        # Close should detect and await the async close
        await f.__aexit__(None, None, None)

        # Verify our async close was called
        assert mock_file.close_called is True

    @pytest.mark.asyncio
    async def test_sync_flush_on_underlying_file(self, temp_file):
        """Test that sync flush method on underlying file object is called."""

        class FileWithSyncFlush:
            """Mock file object with sync flush method."""
            def __init__(self, real_file):
                self.real_file = real_file
                self.flush_called = False

            async def write(self, data):
                return await self.real_file.write(data)

            def flush(self):
                """Sync flush method that should be detected and called."""
                self.flush_called = True
                # Don't call real file's flush to keep it simple

            async def close(self):
                await self.real_file.close()

        import aiofiles

        # Create a real aiofiles handle
        real_file = await aiofiles.open(temp_file, "wb")

        # Wrap it with our mock that has sync flush
        mock_file = FileWithSyncFlush(real_file)

        # Use it as fileobj
        f = AsyncGzipBinaryFile(None, "wb", fileobj=mock_file, closefd=False)
        await f.__aenter__()
        await f.write(b"test data")

        # Call flush - should detect and call the sync flush
        await f.flush()

        # Verify our sync flush was called
        assert mock_file.flush_called is True

        await f.__aexit__(None, None, None)
        await real_file.close()

    @pytest.mark.asyncio
    async def test_read_with_none_size_binary(self, temp_file):
        """Test that read(None) works correctly in binary mode (converts to -1)."""
        test_data = b"Hello, World! This is test data."

        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            # read(None) should read all data
            data = await f.read(None)
            assert data == test_data

    @pytest.mark.asyncio
    async def test_read_with_none_size_text(self, temp_file):
        """Test that read(None) works correctly in text mode (converts to -1)."""
        test_text = "Hello, World! This is test text."

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # read(None) should read all data
            data = await f.read(None)
            assert data == test_text

    @pytest.mark.asyncio
    async def test_unusual_encoding_shift_jis(self, temp_file):
        """Test with shift_jis encoding (Japanese)."""
        test_text = "こんにちは世界"  # "Hello World" in Japanese

        async with AsyncGzipTextFile(temp_file, "wt", encoding="shift_jis") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="shift_jis") as f:
            data = await f.read()
            assert data == test_text

    @pytest.mark.asyncio
    async def test_unusual_encoding_iso_8859_1(self, temp_file):
        """Test with iso-8859-1 encoding (Latin-1)."""
        test_text = "Café résumé naïve"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="iso-8859-1") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="iso-8859-1") as f:
            data = await f.read()
            assert data == test_text

    @pytest.mark.asyncio
    async def test_unusual_encoding_cp1252(self, temp_file):
        """Test with cp1252 encoding (Windows-1252)."""
        test_text = "Euro sign: € and other symbols"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="cp1252") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="cp1252") as f:
            data = await f.read()
            assert data == test_text

    @pytest.mark.asyncio
    async def test_max_incomplete_bytes_detection_utf8(self, temp_file):
        """Test that UTF-8 is detected correctly for max incomplete bytes."""
        # This tests the _determine_max_incomplete_bytes method
        f = AsyncGzipTextFile(temp_file, "wt", encoding="utf-8")
        assert f._max_incomplete_bytes == 4

        f = AsyncGzipTextFile(temp_file, "wt", encoding="UTF-8")
        assert f._max_incomplete_bytes == 4

    @pytest.mark.asyncio
    async def test_max_incomplete_bytes_detection_ascii(self, temp_file):
        """Test that ASCII is detected correctly for max incomplete bytes."""
        f = AsyncGzipTextFile(temp_file, "wt", encoding="ascii")
        assert f._max_incomplete_bytes == 1

        f = AsyncGzipTextFile(temp_file, "wt", encoding="latin-1")
        assert f._max_incomplete_bytes == 1

    @pytest.mark.asyncio
    async def test_max_incomplete_bytes_detection_unknown(self, temp_file):
        """Test that unknown encodings get safe fallback for max incomplete bytes."""
        f = AsyncGzipTextFile(temp_file, "wt", encoding="shift_jis")
        # Unknown encoding should default to safe fallback of 8
        assert f._max_incomplete_bytes == 8


class TestLowPriorityEdgeCases:
    """Test low priority edge cases for improved coverage."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_binary_read_on_closed_file(self, temp_file):
        """Test that reading on closed binary file raises ValueError."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            await f.read()
            # File is now at EOF but still open

        # Now file is closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.read()

    @pytest.mark.asyncio
    async def test_text_read_on_closed_file(self, temp_file):
        """Test that reading on closed text file raises ValueError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            await f.read()

        # Now file is closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.read()

    @pytest.mark.asyncio
    async def test_binary_read_without_context_manager(self, temp_file):
        """Test that reading without entering context manager raises ValueError."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test")

        f = AsyncGzipBinaryFile(temp_file, "rb")
        # Don't enter context manager
        with pytest.raises(ValueError, match="File not opened"):
            await f.read()

    @pytest.mark.asyncio
    async def test_text_read_without_context_manager(self, temp_file):
        """Test that reading without entering context manager raises ValueError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        f = AsyncGzipTextFile(temp_file, "rt")
        # Don't enter context manager
        with pytest.raises(ValueError, match="File not opened"):
            await f.read()

    @pytest.mark.asyncio
    async def test_binary_write_on_closed_file(self, temp_file):
        """Test that writing on closed binary file raises ValueError."""
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")

        # Now file is closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write(b"more")

    @pytest.mark.asyncio
    async def test_text_write_on_closed_file(self, temp_file):
        """Test that writing on closed text file raises ValueError."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        # Now file is closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write("more")

    @pytest.mark.asyncio
    async def test_text_write_in_read_mode(self, temp_file):
        """Test that write in read mode raises IOError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            with pytest.raises(IOError, match="File not open for writing"):
                await f.write("should fail")

    @pytest.mark.asyncio
    async def test_text_read_in_write_mode(self, temp_file):
        """Test that read in write mode raises IOError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            with pytest.raises(IOError, match="File not open for reading"):
                await f.read()

    @pytest.mark.asyncio
    async def test_iteration_on_closed_text_file(self, temp_file):
        """Test that iteration on closed text file raises StopAsyncIteration."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("line1\nline2\n")

        f = AsyncGzipTextFile(temp_file, "rt")
        async with f:
            # Read one line
            line = await f.__anext__()
            assert line == "line1\n"

        # Now closed - should raise StopAsyncIteration
        with pytest.raises(StopAsyncIteration):
            await f.__anext__()

    @pytest.mark.asyncio
    async def test_file_without_final_newline_iteration(self, temp_file):
        """Test iteration handles file without final newline correctly."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("line1\nline2")  # No final newline

        lines = []
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            async for line in f:
                lines.append(line)

        # Should get both lines, second without newline
        assert lines == ["line1\n", "line2"]

    @pytest.mark.asyncio
    async def test_text_flush_on_closed_file(self, temp_file):
        """Test that flush on closed text file raises ValueError."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        # Now closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.flush()

    @pytest.mark.asyncio
    async def test_text_file_close_idempotent(self, temp_file):
        """Test that closing text file multiple times is safe."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        # First close (done by context manager)
        # Second close should be safe
        await f.close()
        # Third close should also be safe
        await f.close()

    @pytest.mark.asyncio
    async def test_binary_write_in_read_mode(self, temp_file):
        """Test that write in read mode raises IOError for binary files."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            with pytest.raises(IOError, match="File not open for writing"):
                await f.write(b"should fail")

    @pytest.mark.asyncio
    async def test_text_write_without_context_manager(self, temp_file):
        """Test that write without context manager raises ValueError."""
        f = AsyncGzipTextFile(temp_file, "wt")
        # Don't enter context manager
        with pytest.raises(ValueError, match="File not opened"):
            await f.write("should fail")

    @pytest.mark.asyncio
    async def test_zlib_compress_error_path(self, temp_file):
        """Test zlib compression error is wrapped in OSError."""
        import zlib

        class MockEngine:
            """Mock compression engine that raises zlib.error."""
            def compress(self, data):
                raise zlib.error("Compression error")
            def flush(self, mode=None):
                return b""

        f = AsyncGzipBinaryFile(temp_file, "wb")
        await f.__aenter__()
        f._engine = MockEngine()

        with pytest.raises(OSError, match="Error compressing data"):
            await f.write(b"test")

        await f.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_zlib_flush_error_path(self, temp_file):
        """Test zlib flush error is wrapped in OSError."""
        import zlib

        class MockEngine:
            """Mock compression engine that raises zlib.error on flush."""
            def __init__(self):
                self.flush_count = 0

            def compress(self, data):
                return b"compressed"

            def flush(self, mode=zlib.Z_SYNC_FLUSH):
                self.flush_count += 1
                # Raise on first flush, succeed on close
                if self.flush_count == 1:
                    raise zlib.error("Flush error")
                return b""

        f = AsyncGzipBinaryFile(temp_file, "wb")
        await f.__aenter__()
        await f.write(b"test")
        f._engine = MockEngine()

        with pytest.raises(OSError, match="Error flushing compressed data"):
            await f.flush()

        await f.__aexit__(None, None, None)


class TestNewlineHandlingBugs:
    """Tests for newline handling bugs identified in code review."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
            temp_path = f.name
        yield temp_path
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_crlf_split_across_chunk_boundary(self, temp_file):
        """Test that CRLF split across chunk boundaries is handled correctly.

        BUG: _apply_newline_decoding is stateless, so when \\r\\n is split across
        chunks, the \\r at end of chunk1 gets converted to \\n, then the \\n at
        start of chunk2 is kept, resulting in \\n\\n (two line breaks).
        """
        # Create text with CRLF positioned to split across chunk boundary
        chunk_size = 1024

        # Position CRLF so \r is at byte 1023 and \n is at byte 1024
        # After UTF-8 encoding, we need to account for compression effects
        # Use a predictable pattern
        text = "x" * (chunk_size - 10) + "\r\n" + "y" * 100

        # Write with newline='' to preserve exact CRLF
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(text)

        # Read back with default newline=None (universal newlines)
        # Should convert all CRLF to LF
        async with AsyncGzipTextFile(temp_file, "rt", chunk_size=chunk_size) as f:
            # Force small chunk size at binary level to trigger split
            f._binary_file._chunk_size = 100  # Very small to force CRLF split
            result = await f.read()

        # Should have exactly one newline, not two
        # Bug causes "\r\n" → "\n\n"
        expected = "x" * (chunk_size - 10) + "\n" + "y" * 100

        # Count newlines in result
        newline_count = result.count("\n")

        # This will FAIL with current implementation if CRLF splits
        assert result == expected, f"Got {newline_count} newlines instead of 1, CRLF was split incorrectly"

    @pytest.mark.asyncio
    async def test_line_iteration_with_cr_only_newline(self, temp_file):
        """Test that line iteration respects newline='\\r' mode.

        FIXED: __anext__/readline now respect newline mode parameter.
        Files with bare \\r line endings split correctly.
        """
        # Write file with CR-only line endings
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write("line1\rline2\rline3")

        # Read with newline='\r' - should split on \r
        lines = []
        async with AsyncGzipTextFile(temp_file, "rt", newline="\r") as f:
            async for line in f:
                lines.append(line)

        # BUG: Current implementation will NOT split on \r, returning entire file
        # Expected behavior: split into 3 lines
        # Actual behavior: 1 line containing "line1\rline2\rline3"

        # This will FAIL with current implementation
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {lines}"
        # Note: Python's TextIOWrapper behavior with newline='\r' is complex
        # but it should at least attempt to handle \r as a terminator

    @pytest.mark.asyncio
    async def test_readline_with_cr_only_newline(self, temp_file):
        """Test that readline respects newline='\\r' mode.

        FIXED: readline now respects newline mode parameter.
        """
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write("line1\rline2\rline3")

        async with AsyncGzipTextFile(temp_file, "rt", newline="\r") as f:
            line1 = await f.readline()
            line2 = await f.readline()
            line3 = await f.readline()

        # BUG: Will likely return entire file as line1
        # This will FAIL with current implementation
        assert line1 == "line1\r", f"Expected 'line1\\r', got {repr(line1)}"
        assert line2 == "line2\r", f"Expected 'line2\\r', got {repr(line2)}"
        assert line3 == "line3", f"Expected 'line3', got {repr(line3)}"

    @pytest.mark.asyncio
    async def test_read_zero_returns_empty_string(self, temp_file):
        """Test that read(0) returns empty string, not buffered text.

        BUG: AsyncGzipTextFile.read(0) returns entire buffered text instead of ''.
        This violates TextIOBase contract and drains the buffer unexpectedly.
        """
        test_text = "Hello, World! This is a test."

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Read some data to fill internal buffer
            first_part = await f.read(5)
            assert first_part == "Hello"

            # Now call read(0) - should return empty string without draining buffer
            empty = await f.read(0)

            # BUG: Current implementation returns buffered text
            # This will FAIL with current implementation
            assert empty == "", f"read(0) should return '', got {repr(empty)}"

            # Verify buffer wasn't drained - we should still be able to read remaining
            rest = await f.read()
            assert rest == ", World! This is a test.", f"Buffer was drained! Got {repr(rest)}"

    @pytest.mark.asyncio
    async def test_read_zero_binary_returns_empty_bytes(self, temp_file):
        """Test that binary read(0) returns empty bytes."""
        test_data = b"Hello, World! This is a test."

        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            # Read some data to fill internal buffer
            first_part = await f.read(5)
            assert first_part == b"Hello"

            # Now call read(0) - should return empty bytes
            empty = await f.read(0)

            # Binary mode might have same bug
            assert empty == b"", f"read(0) should return b'', got {repr(empty)}"

            # Verify buffer wasn't drained
            rest = await f.read()
            assert rest == b", World! This is a test."
