# pyrefly: ignore
# pyrefly: disable=all
import gzip

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipFile, AsyncGzipTextFile


class TestAsyncGzipFile:
    """Test the AsyncGzipFile factory function."""

    def test_init_valid_modes(self):
        """Test initialization with valid modes."""
        gz_file = AsyncGzipFile("test.gz", "rb")
        assert gz_file._filename == "test.gz"
        assert gz_file._mode == "rb"
        assert gz_file._file_mode == "rb"  # pyrefly: ignore
        assert gz_file._chunk_size == AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE

        gz_file = AsyncGzipFile("test.gz", "wb")
        assert gz_file._mode == "wb"
        assert gz_file._file_mode == "wb"  # pyrefly: ignore

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

    def test_init_non_string_mode(self):
        """Factory should validate mode type consistently."""
        with pytest.raises(TypeError, match="mode must be a string"):
            AsyncGzipFile("test.gz", b"rb")  # type: ignore[arg-type]

    def test_read_mode_ignores_compresslevel_validation(self):
        """Read modes should accept any compresslevel like gzip.open()."""
        binary = AsyncGzipFile("test.gz", "rb", compresslevel=-1)
        text = AsyncGzipFile("test.gz", "rt", compresslevel=999)
        assert isinstance(binary, AsyncGzipBinaryFile)
        assert isinstance(text, AsyncGzipTextFile)

    @pytest.mark.parametrize(
        "kwarg_name, kwarg_value",
        [
            ("encoding", "utf-8"),
            ("errors", "ignore"),
            ("newline", "\n"),
        ],
    )
    def test_binary_mode_rejects_text_kwargs(self, kwarg_name, kwarg_value):
        """Binary factory mode should reject text-specific kwargs like gzip.open()."""
        with pytest.raises(
            ValueError, match=f"Argument '{kwarg_name}' not supported in binary mode"
        ):
            AsyncGzipFile("test.gz", "rb", **{kwarg_name: kwarg_value})

    @pytest.mark.parametrize("kwarg_name", ["encoding", "errors", "newline"])
    def test_binary_mode_accepts_none_text_kwargs(self, kwarg_name):
        """Binary factory mode should ignore text kwargs when explicitly set to None."""
        gz_file = AsyncGzipFile("test.gz", "rb", **{kwarg_name: None})
        assert isinstance(gz_file, AsyncGzipBinaryFile)

    def test_init_invalid_newline_text_mode(self):
        """Text mode should reject unsupported newline values."""
        with pytest.raises(ValueError, match="illegal newline value"):
            AsyncGzipFile("test.gz", "rt", newline="bad")

    def test_text_mode_accepts_none_encoding_and_errors(self):
        """Text mode should accept None for encoding/errors like gzip.open()."""
        gz_file = AsyncGzipFile("test.gz", "rt", encoding=None, errors=None)
        assert isinstance(gz_file, AsyncGzipTextFile)

    def test_initial_state_binary(self):
        """Test initial state of AsyncGzipFile in binary mode."""
        gz_file = AsyncGzipFile("test.gz", "rb")
        assert isinstance(gz_file, AsyncGzipBinaryFile)
        assert gz_file._file is None  # pyrefly: ignore
        assert gz_file._engine is None  # pyrefly: ignore
        assert gz_file._buffer == b""  # pyrefly: ignore
        assert gz_file._is_closed is False
        assert gz_file._eof is False  # pyrefly: ignore

    def test_initial_state_text(self):
        """Test initial state of AsyncGzipFile in text mode."""
        gz_file = AsyncGzipFile("test.gz", "rt")
        assert isinstance(gz_file, AsyncGzipTextFile)
        assert gz_file._binary_file is None  # pyrefly: ignore
        assert gz_file._text_buffer == ""  # pyrefly: ignore
        assert gz_file._is_closed is False

    @pytest.mark.asyncio
    async def test_context_manager_write_read_binary(self, temp_file, sample_data):
        """Test writing and reading data using context manager in binary mode."""
        async with AsyncGzipFile(temp_file, "wb") as gz_file:
            bytes_written = await gz_file.write(sample_data)
            assert bytes_written == len(sample_data)

        async with AsyncGzipFile(temp_file, "rb") as gz_file:
            read_data = await gz_file.read()
            assert read_data == sample_data

    @pytest.mark.asyncio
    async def test_context_manager_write_read_text(self, temp_file):
        """Test writing and reading data using context manager in text mode."""
        test_text = "Hello, World! This is a test string."

        async with AsyncGzipFile(temp_file, "wt") as gz_file:
            bytes_written = await gz_file.write(test_text)  # pyrefly: ignore
            assert bytes_written == len(test_text)

        async with AsyncGzipFile(temp_file, "rt") as gz_file:
            read_data = await gz_file.read()
            assert read_data == test_text

    @pytest.mark.asyncio
    async def test_partial_read_binary(self, temp_file, sample_data):
        """Test partial reading in binary mode."""
        async with AsyncGzipFile(temp_file, "wb") as gz_file:
            await gz_file.write(sample_data)

        async with AsyncGzipFile(temp_file, "rb") as gz_file:
            partial_data = await gz_file.read(10)
            assert partial_data == sample_data[:10]

            remaining_data = await gz_file.read()
            assert remaining_data == sample_data[10:]

    @pytest.mark.asyncio
    async def test_partial_read_text(self, temp_file):
        """Test partial reading in text mode."""
        test_text = "Hello, World! This is a test string."

        async with AsyncGzipFile(temp_file, "wt") as gz_file:
            await gz_file.write(test_text)  # pyrefly: ignore

        async with AsyncGzipFile(temp_file, "rt") as gz_file:
            partial_data = await gz_file.read(10)
            assert partial_data == test_text[:10]

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
    async def test_line_iteration_binary_mode(self, temp_file):
        """Test line iteration in binary mode."""
        async with AsyncGzipFile(temp_file, "wb") as f:
            await f.write(b"line1\nline2")  # pyrefly: ignore

        async with AsyncGzipFile(temp_file, "rb") as f:
            lines = []
            async for line in f:  # pyrefly: ignore
                lines.append(line)
            assert lines == [b"line1\n", b"line2"]

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
        gz_file = AsyncGzipFile("test.gz", "r")
        assert gz_file._file_mode == "rb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "w")
        assert gz_file._file_mode == "wb"  # pyrefly: ignore

        gz_file = AsyncGzipFile("test.gz", "a")
        assert gz_file._file_mode == "ab"  # pyrefly: ignore

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
        async with AsyncGzipFile(temp_file, "wb") as f:
            await f.write(sample_data)

        with gzip.open(temp_file, "rb") as f:
            read_data = f.read()
            assert read_data == sample_data

        with gzip.open(temp_file, "wb") as f:
            f.write(sample_data)

        async with AsyncGzipFile(temp_file, "rb") as f:
            read_data = await f.read()
            assert read_data == sample_data

    @pytest.mark.asyncio
    async def test_interoperability_with_gzip_text(self, temp_file):
        """Test interoperability with gzip.open for text data."""
        test_text = "Hello, World! This is a test string."

        async with AsyncGzipFile(temp_file, "wt") as f:
            await f.write(test_text)  # pyrefly: ignore

        with gzip.open(temp_file, "rt") as f:
            read_data = f.read()
            assert read_data == test_text

        with gzip.open(temp_file, "wt") as f:
            f.write(test_text)

        async with AsyncGzipFile(temp_file, "rt") as f:
            read_data = await f.read()
            assert read_data == test_text
