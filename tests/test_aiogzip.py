# pyrefly: ignore
# pyrefly: disable=all
import gzip
import io
import os

import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
)


class TestEdgeCases:
    """Test edge cases and error conditions."""

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

    def test_invalid_compression_level(self):
        """Test invalid compression level inputs."""
        AsyncGzipBinaryFile("test.gz", mode="wb", compresslevel=-1)
        AsyncGzipTextFile("test.gz", mode="wt", compresslevel=-1)

        with pytest.raises(
            ValueError, match="Compression level must be between -1 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", mode="wb", compresslevel=-2)

        with pytest.raises(
            ValueError, match="Compression level must be between -1 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", mode="wb", compresslevel=10)

        with pytest.raises(
            ValueError, match="Compression level must be between -1 and 9"
        ):
            AsyncGzipTextFile("test.gz", mode="wt", compresslevel=-2)

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
        f = AsyncGzipTextFile("test.gz", errors=None)
        assert f._errors == "strict"

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
            with pytest.raises(gzip.BadGzipFile, match="Error decompressing gzip data"):
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
                assert memory_increase < 200 * 1024 * 1024, (
                    f"Memory usage too high: {memory_increase / 1024 / 1024:.1f}MB"
                )

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
            async for _line in f:
                lines_read += 1

                # Check memory usage periodically
                if lines_read % 10000 == 0:
                    current_memory = process.memory_info().rss
                    memory_increase = current_memory - initial_memory

                    # Memory increase should be reasonable
                    assert memory_increase < 100 * 1024 * 1024, (
                        f"Memory usage too high: {memory_increase / 1024 / 1024:.1f}MB"
                    )

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


class TestErrorHandlingConsistency:
    """Test consistent error handling across the module."""

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
            part3 = await f.read()  # Rest

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
    async def test_trailing_zero_padding_is_ignored(self, temp_file):
        """Trailing zero padding after valid gzip data should be ignored."""
        with gzip.open(temp_file, "wb") as f:
            f.write(b"payload")

        with open(temp_file, "ab") as raw:
            raw.write(b"\x00" * 32)

        # Parity check: stdlib gzip accepts trailing zero padding.
        with gzip.open(temp_file, "rb") as f:
            assert f.read() == b"payload"

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.read() == b"payload"

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
    async def test_binary_mtime_matches_header_after_read(self, temp_file):
        """mtime should be None before reads and set from the gzip header after reads."""
        with gzip.GzipFile(temp_file, "wb", mtime=123456789) as f:
            f.write(b"payload")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert f.mtime is None
            assert await f.read(1) == b"p"
            assert f.mtime == 123456789

    @pytest.mark.asyncio
    async def test_binary_readline_readlines_and_writelines(self, temp_file):
        """Binary files should support line-oriented methods like gzip.GzipFile."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.writelines([b"line1\n", b"line2\n", b"line3"])

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.readline() == b"line1\n"
            assert await f.readline(limit=3) == b"lin"
            assert await f.readline() == b"e2\n"
            assert await f.readlines() == [b"line3"]
            assert await f.readline() == b""

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
        assert text.newlines == ""

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
