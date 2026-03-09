# pyrefly: ignore
# pyrefly: disable=all
import io

import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
)


class TestHighPriorityEdgeCases:
    """Test high priority edge cases for improved coverage."""

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
        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="utf-8", chunk_size=chunk_size
        ) as f:
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
        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="utf-8", errors="ignore"
        ) as f:
            data = await f.read()
            # Should only get "test", incomplete sequence ignored
            assert data == "test"

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

            async with AsyncGzipTextFile(
                temp_file, "rt", encoding="utf-8", chunk_size=chunk_size
            ) as f:
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
        for _i in range(5):
            text_parts.append("x" * (chunk_size - 2))
            text_parts.append("🚀")

        test_text = "".join(text_parts)

        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-8") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="utf-8", chunk_size=chunk_size
        ) as f:
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

    @pytest.mark.asyncio
    async def test_closed_property_binary_and_text(self, temp_file):
        """closed should reflect context manager lifecycle like file objects."""
        binary = AsyncGzipBinaryFile(temp_file, "wb")
        assert binary.closed is False
        async with binary:
            assert binary.closed is False
            await binary.write(b"data")
        assert binary.closed is True

        text = AsyncGzipTextFile(temp_file, "rt")
        assert text.closed is False
        async with text:
            assert text.closed is False
            await text.read()
        assert text.closed is True

    @pytest.mark.asyncio
    async def test_binary_readline_long_line_small_chunk(self, temp_file):
        """Binary readline should handle long lines split across many chunks."""
        long_line = (b"x" * 50000) + b"\n"
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(long_line + b"tail")

        async with AsyncGzipBinaryFile(temp_file, "rb", chunk_size=17) as f:
            assert await f.readline() == long_line
            assert await f.readline() == b"tail"
            assert await f.readline() == b""

    def test_text_stream_properties(self, temp_file):
        """Text stream metadata properties should be exposed for compatibility."""
        text = AsyncGzipTextFile(
            temp_file, "rt", encoding="latin-1", errors="ignore", newline=""
        )
        assert text.encoding == "latin-1"
        assert text.errors == "ignore"
        assert text.newlines is None

        default_text = AsyncGzipTextFile(temp_file, "rt")
        assert default_text.encoding == "utf-8"
        assert default_text.errors == "strict"
        assert default_text.newlines is None

    @pytest.mark.asyncio
    async def test_text_buffer_property(self, temp_file):
        """Text mode should expose the underlying binary buffer."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            assert f.buffer is f._binary_file

    @pytest.mark.asyncio
    async def test_binary_isatty_detach_and_truncate_compatibility(self, temp_file):
        """Binary stream should expose stdlib-compatible capability methods."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            assert f.isatty() is False
            with pytest.raises(io.UnsupportedOperation, match="detach"):
                f.detach()
            with pytest.raises(io.UnsupportedOperation, match="truncate"):
                f.truncate()

    @pytest.mark.asyncio
    async def test_binary_async_iteration_reads_lines(self, temp_file):
        """Binary readers should support async iteration over lines."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"a\nbb\nccc")

        lines = []
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            async for line in f:
                lines.append(line)

        assert lines == [b"a\n", b"bb\n", b"ccc"]


class TestMediumPriorityEdgeCases:
    """Test medium priority edge cases for improved coverage."""

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
                if hasattr(self.real_file, "flush"):
                    flush_method = self.real_file.flush
                    if callable(flush_method):
                        result = flush_method()
                        if hasattr(result, "__await__"):
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


class TestLowPriorityEdgeCases:
    """Test low priority edge cases for improved coverage."""

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
