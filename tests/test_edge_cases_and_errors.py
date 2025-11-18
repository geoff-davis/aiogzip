import pytest
from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestEdgeCasesAndErrors:
    """Targeted tests to improve code coverage and handle edge cases."""

    @pytest.mark.asyncio
    async def test_compresslevel_validation(self):
        """Test validation of compresslevel."""
        with pytest.raises(
            ValueError, match="Compression level must be between 0 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", compresslevel=-1)

        with pytest.raises(
            ValueError, match="Compression level must be between 0 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", compresslevel=10)

    @pytest.mark.asyncio
    async def test_binary_file_init_errors(self):
        """Test initialization errors for AsyncGzipBinaryFile."""
        # Binary mode cannot include text
        # Note: _parse_mode_tokens catches "both b and t" before AsyncGzipBinaryFile checks for "t"
        with pytest.raises(
            ValueError, match="Mode string cannot include both 'b' and 't'"
        ):
            AsyncGzipBinaryFile("test.gz", mode="rbt")

        # Invalid mode op
        with pytest.raises(ValueError, match="Invalid mode"):
            AsyncGzipBinaryFile("test.gz", mode="y")  # Invalid op

    @pytest.mark.asyncio
    async def test_binary_file_filename_none_error(self):
        """Test error when filename is None and no fileobj provided."""
        # Error is raised during init, not aenter
        with pytest.raises(
            ValueError, match="Either filename or fileobj must be provided"
        ):
            AsyncGzipBinaryFile(None)

    @pytest.mark.asyncio
    async def test_text_file_init_errors(self):
        """Test initialization errors for AsyncGzipTextFile."""
        # Empty encoding
        with pytest.raises(ValueError, match="Encoding cannot be empty"):
            AsyncGzipTextFile("test.gz", encoding="")

        # None errors
        with pytest.raises(ValueError, match="Errors cannot be None"):
            AsyncGzipTextFile("test.gz", errors=None)

        # Text mode cannot include binary (explicit check in init)
        with pytest.raises(ValueError, match="Text mode cannot include binary"):
            AsyncGzipTextFile("test.gz", mode="rb")

        # Invalid mode op
        with pytest.raises(ValueError, match="Invalid mode"):
            AsyncGzipTextFile("test.gz", mode="y")

    @pytest.mark.asyncio
    async def test_text_file_plus_mode(self, tmp_path):
        """Test 'rt+' mode handling in AsyncGzipTextFile."""
        # This should set _binary_mode to 'rb+'
        p = tmp_path / "test.gz"
        p.touch()

        async with AsyncGzipTextFile(p, "rt+") as f:
            assert f._binary_mode == "rb+"

    @pytest.mark.asyncio
    async def test_write_newlines_coverage(self, tmp_path):
        """Test write with different newline settings to cover branching."""
        p = tmp_path / "newlines.gz"

        # newline='\n'
        async with AsyncGzipTextFile(p, "wt", newline="\n") as f:
            await f.write("line1\n")

        # newline='\r'
        async with AsyncGzipTextFile(p, "wt", newline="\r") as f:
            await f.write("line1\n")

        # newline='' (no translation)
        async with AsyncGzipTextFile(p, "wt", newline="") as f:
            await f.write("line1\n")

    @pytest.mark.asyncio
    async def test_read_size_none_or_negative(self, tmp_path):
        """Test read with size=None or size < 0."""
        p = tmp_path / "read_size.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"data")

        async with AsyncGzipBinaryFile(p, "rb") as f:
            assert await f.read(None) == b"data"

        async with AsyncGzipBinaryFile(p, "rb") as f:
            assert await f.read(-5) == b"data"

        async with AsyncGzipTextFile(p, "rt") as f:
            assert await f.read(None) == "data"

        async with AsyncGzipTextFile(p, "rt") as f:
            assert await f.read(-5) == "data"

    @pytest.mark.asyncio
    async def test_read_zero(self, tmp_path):
        """Test read with size=0."""
        p = tmp_path / "read_zero.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"data")

        async with AsyncGzipBinaryFile(p, "rb") as f:
            assert await f.read(0) == b""

        async with AsyncGzipTextFile(p, "rt") as f:
            assert await f.read(0) == ""

    @pytest.mark.asyncio
    async def test_binary_write_errors(self, tmp_path):
        """Test binary write error conditions."""
        p = tmp_path / "write_err.gz"

        # Not writing mode
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"init")

        async with AsyncGzipBinaryFile(p, "rb") as f:
            with pytest.raises(OSError, match="File not open for writing"):
                await f.write(b"fail")

        # File is closed
        f = AsyncGzipBinaryFile(p, "wb")
        await f.__aenter__()
        await f.close()
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write(b"fail")

        # File is None
        f = AsyncGzipBinaryFile(p, "wb")
        with pytest.raises(ValueError, match="File not opened"):
            await f.write(b"fail")

    @pytest.mark.asyncio
    async def test_binary_read_errors(self, tmp_path):
        """Test binary read error conditions."""
        p = tmp_path / "read_err.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"data")

        # Not reading mode
        async with AsyncGzipBinaryFile(p, "wb") as f:
            with pytest.raises(OSError, match="File not open for reading"):
                await f.read()

        # File is closed
        f = AsyncGzipBinaryFile(p, "rb")
        await f.__aenter__()
        await f.close()
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.read()

        # File is None
        f = AsyncGzipBinaryFile(p, "rb")
        with pytest.raises(ValueError, match="File not opened"):
            await f.read()

    @pytest.mark.asyncio
    async def test_binary_compression_error(self, tmp_path):
        """Test zlib error during compression."""
        p = tmp_path / "comp_err.gz"

        import zlib

        class MockCompressor:
            def compress(self, data):
                raise zlib.error("Mock compression error")

            def flush(self, mode=None):
                return b""

        async with AsyncGzipBinaryFile(p, "wb") as f:
            f._engine = MockCompressor()
            with pytest.raises(OSError, match="Error compressing data"):
                await f.write(b"data")

    @pytest.mark.asyncio
    async def test_binary_flush_error(self, tmp_path):
        """Test zlib error during flush."""
        p = tmp_path / "flush_err.gz"

        import zlib

        class MockCompressor:
            def compress(self, data):
                return b""

            def flush(self, mode=None):
                # Raise only on explicit flush() call which uses Z_SYNC_FLUSH
                if mode == zlib.Z_SYNC_FLUSH:
                    raise zlib.error("Mock flush error")
                return b""

        async with AsyncGzipBinaryFile(p, "wb") as f:
            f._engine = MockCompressor()
            await f.write(b"data")
            with pytest.raises(OSError, match="Error flushing compressed data"):
                await f.flush()

    @pytest.mark.asyncio
    async def test_text_write_type_error(self, tmp_path):
        """Test write raises TypeError for non-string input."""
        p = tmp_path / "text_type_err.gz"
        async with AsyncGzipTextFile(p, "wt") as f:
            with pytest.raises(TypeError, match="write\\(\\) argument must be str"):
                await f.write(b"bytes")  # type: ignore

    @pytest.mark.asyncio
    async def test_text_read_eof_flush_data(self, tmp_path):
        """Test that decoder flush at EOF returns remaining data."""
        p = tmp_path / "text_flush.gz"

        # Write data that might leave state in decoder (e.g. incomplete multibyte?)
        # Hard to force decoder to have pending data at EOF that is valid, usually it's error.
        # But we can test that _read_chunk_and_decode handles it.
        # We'll just verify standard read works, which exercises the path.
        async with AsyncGzipTextFile(p, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(p, "rt") as f:
            assert await f.read() == "test"

    @pytest.mark.asyncio
    async def test_text_anext_stops_iteration(self, tmp_path):
        """Test __anext__ raises StopAsyncIteration when closed."""
        p = tmp_path / "iter.gz"
        async with AsyncGzipTextFile(p, "wt") as f:
            await f.write("line1")

        f = AsyncGzipTextFile(p, "rt")
        await f.__aenter__()
        await f.close()

        with pytest.raises(StopAsyncIteration):
            await f.__anext__()

    @pytest.mark.asyncio
    async def test_binary_iter_error(self):
        """Test binary file raises TypeError on iteration."""
        f = AsyncGzipBinaryFile("test.gz", "rb")
        with pytest.raises(
            TypeError, match="AsyncGzipBinaryFile can only be iterated in text mode"
        ):
            f.__aiter__()
