# pyrefly: ignore
# pyrefly: disable=all
import gzip
import io
import os
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


class TestAiocsvIntegration:
    """Test integration with aiocsv."""

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
                f,
                fieldnames=["id", "name", "email", "age"],  # pyrefly: ignore
            )
            for row in test_data:
                await writer.writerow(row)

        # Read CSV data
        async with AsyncGzipFile(temp_file, "rt") as f:
            reader = aiocsv.AsyncDictReader(
                f,
                fieldnames=["id", "name", "email", "age"],  # pyrefly: ignore
            )
            rows = []
            async for row in reader:
                rows.append(row)
            assert len(rows) == 1000
            assert rows[0] == test_data[0]
            assert rows[-1] == test_data[-1]


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


class TestNameProperty:
    """Test the name property for file API compatibility."""

    @pytest.mark.asyncio
    async def test_binary_file_name_with_string(self, temp_file):
        """Test name property with string filename."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            assert f.name == temp_file
            await f.write(b"test")

    @pytest.mark.asyncio
    async def test_binary_file_name_with_path(self, temp_file):
        """Test name property with Path object."""
        from pathlib import Path

        path_obj = Path(temp_file)
        async with AsyncGzipBinaryFile(path_obj, "wb") as f:
            assert f.name == path_obj
            await f.write(b"test")

    @pytest.mark.asyncio
    async def test_binary_file_name_with_bytes(self, temp_file):
        """Test name property with bytes filename."""
        path_bytes = temp_file.encode("utf-8")
        async with AsyncGzipBinaryFile(path_bytes, "wb") as f:
            assert f.name == path_bytes
            await f.write(b"test")

    @pytest.mark.asyncio
    async def test_binary_file_name_with_fileobj(self, temp_file):
        """Test name property when opened with fileobj."""
        import aiofiles

        file_handle = await aiofiles.open(temp_file, "wb")
        try:
            async with AsyncGzipBinaryFile(
                None, "wb", fileobj=file_handle, closefd=False
            ) as f:
                assert f.name is None
                await f.write(b"test")
        finally:
            await file_handle.close()

    @pytest.mark.asyncio
    async def test_text_file_name_with_string(self, temp_file):
        """Test name property on text file with string filename."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            assert f.name == temp_file
            await f.write("test")

    @pytest.mark.asyncio
    async def test_text_file_name_with_path(self, temp_file):
        """Test name property on text file with Path object."""
        from pathlib import Path

        path_obj = Path(temp_file)
        async with AsyncGzipTextFile(path_obj, "wt") as f:
            assert f.name == path_obj
            await f.write("test")

    @pytest.mark.asyncio
    async def test_text_file_name_with_fileobj(self, temp_file):
        """Test name property on text file when opened with fileobj."""
        import aiofiles

        file_handle = await aiofiles.open(temp_file, "wb")
        try:
            async with AsyncGzipTextFile(
                None, "wt", fileobj=file_handle, closefd=False
            ) as f:
                assert f.name is None
                await f.write("test")
        finally:
            await file_handle.close()

    @pytest.mark.asyncio
    async def test_name_available_before_enter(self, temp_file):
        """Test that name is available even before entering context manager."""
        f = AsyncGzipBinaryFile(temp_file, "wb")
        assert f.name == temp_file
        # Don't enter context manager - just check the name is accessible

    @pytest.mark.asyncio
    async def test_name_available_after_close(self, temp_file):
        """Test that name is still available after closing."""
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")
        # After close, name should still be available
        assert f.name == temp_file


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
    async def test_closefd_default_with_fileobj_keeps_file_open(self, tmp_path):
        """Default closefd should keep caller-owned fileobj open."""
        import aiofiles

        p = tmp_path / "test_closefd_default_fileobj.gz"

        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipBinaryFile(None, "wb", fileobj=file_handle) as f:
            await f.write(b"test data")

        # Should still be writable because fileobj ownership stays with caller
        await file_handle.write(b"more data")
        await file_handle.close()

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

    @pytest.mark.asyncio
    async def test_closefd_default_with_text_fileobj_keeps_file_open(self, tmp_path):
        """Default closefd should keep caller-owned text-mode fileobj open."""
        import aiofiles

        p = tmp_path / "test_text_closefd_default.gz"
        file_handle = await aiofiles.open(p, "wb")

        async with AsyncGzipTextFile(None, "wt", fileobj=file_handle) as f:
            await f.write("test text")

        await file_handle.write(b"more data")
        await file_handle.close()


class TestAppendMode:
    """Test append mode operations and limitations."""

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
        with pytest.raises(ValueError):
            await f.close()

        # File should still be marked as closed
        assert f._is_closed is True

        # Subsequent closes should be safe (idempotent)
        await f.close()
        await f.close()


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


class TestModeParsingErrors:
    """Tests for invalid mode string parsing in _parse_mode_tokens."""

    # We need to import the internal function for direct testing
    # or test via the AsyncGzipFile / AsyncGzipBinaryFile / AsyncGzipTextFile constructors.
    # Testing constructors is generally better as it reflects real usage.

    @pytest.mark.parametrize(
        "invalid_mode, expected_error, match_regex",
        [
            (123, TypeError, "mode must be a string"),
            ("", ValueError, "Mode string cannot be empty"),
            ("rwb", ValueError, "Mode string can only specify one of r, w, a, or x"),
            ("rbb", ValueError, "Mode string cannot specify 'b' more than once"),
            ("rtt", ValueError, "Mode string cannot specify 't' more than once"),
            ("r++", ValueError, "Mode string cannot include '\\+' more than once"),
            ("r_b", ValueError, "Invalid mode character '_'"),
            ("b", ValueError, "Mode string must include one of 'r', 'w', 'a', or 'x'"),
            ("rbt", ValueError, "Mode string cannot include both 'b' and 't'"),
        ],
    )
    def test_parse_mode_tokens_errors(self, invalid_mode, expected_error, match_regex):
        """Test that _parse_mode_tokens raises correct errors for invalid modes."""
        with pytest.raises(expected_error, match=match_regex):
            # We directly call AsyncGzipBinaryFile for simplicity as mode parsing happens there.
            AsyncGzipBinaryFile("dummy.gz", mode=invalid_mode)  # type: ignore[arg-type]


class TestNewAPIMethods:
    """Test new API methods: flush() and readline()."""

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

    @pytest.mark.asyncio
    async def test_readline_with_limit(self, temp_file):
        """Test readline() with limit parameter."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello World\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Read only 5 characters
            part1 = await f.readline(5)
            assert part1 == "Hello"
            # Read remaining (including newline)
            part2 = await f.readline()
            assert part2 == " World\n"
            # EOF
            eof = await f.readline()
            assert eof == ""

    @pytest.mark.asyncio
    async def test_readline_limit_at_newline(self, temp_file):
        """Test readline() with limit exactly at newline position."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("abc\ndef\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Limit of 4 should get "abc\n"
            line1 = await f.readline(4)
            assert line1 == "abc\n"
            # Next readline should get "def\n"
            line2 = await f.readline()
            assert line2 == "def\n"

    @pytest.mark.asyncio
    async def test_readline_limit_before_newline(self, temp_file):
        """Test readline() with limit before newline."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("abcdef\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Limit of 3 should get "abc"
            part1 = await f.readline(3)
            assert part1 == "abc"
            # Limit of 3 should get "def"
            part2 = await f.readline(3)
            assert part2 == "def"
            # Next should get just newline
            part3 = await f.readline()
            assert part3 == "\n"

    @pytest.mark.asyncio
    async def test_readline_limit_larger_than_line(self, temp_file):
        """Test readline() with limit larger than the line."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("short\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Limit of 100 should return the whole line
            line = await f.readline(100)
            assert line == "short\n"

    @pytest.mark.asyncio
    async def test_readline_limit_zero(self, temp_file):
        """Test readline() with limit=0."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Limit of 0 should return empty string
            result = await f.readline(0)
            assert result == ""
            # File position should not change
            line = await f.readline()
            assert line == "Hello\n"

    @pytest.mark.asyncio
    async def test_readline_limit_on_file_without_newline(self, temp_file):
        """Test readline() with limit on file that has no trailing newline."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello World")  # No newline

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Read with limit
            part1 = await f.readline(5)
            assert part1 == "Hello"
            # Read rest
            part2 = await f.readline()
            assert part2 == " World"
            # EOF
            eof = await f.readline()
            assert eof == ""

    @pytest.mark.asyncio
    async def test_readline_limit_multiple_lines(self, temp_file):
        """Test readline() with limit across multiple calls."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line1\nLine2\nLine3\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Read with various limits
            assert await f.readline(3) == "Lin"
            assert await f.readline(3) == "e1\n"
            assert await f.readline(10) == "Line2\n"
            assert await f.readline() == "Line3\n"

    @pytest.mark.asyncio
    async def test_readlines_basic(self, temp_file):
        """Test basic readlines() functionality."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line 1\nLine 2\nLine 3\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines()
            assert lines == ["Line 1\n", "Line 2\n", "Line 3\n"]

    @pytest.mark.asyncio
    async def test_readlines_no_trailing_newline(self, temp_file):
        """Test readlines() when last line has no newline."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line 1\nLine 2\nLine 3")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines()
            assert lines == ["Line 1\n", "Line 2\n", "Line 3"]

    @pytest.mark.asyncio
    async def test_readlines_empty_file(self, temp_file):
        """Test readlines() on empty file."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            pass  # Write nothing

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines()
            assert lines == []

    @pytest.mark.asyncio
    async def test_readlines_with_hint(self, temp_file):
        """Test readlines() with size hint."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            # Write many lines
            for i in range(100):
                await f.write(f"Line {i}\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # Request ~50 characters worth of lines
            lines = await f.readlines(50)
            # Should get some lines but not all
            assert len(lines) > 0
            assert len(lines) < 100
            # Total characters should be approximately >= hint
            total_chars = sum(len(line) for line in lines)
            assert total_chars >= 50

    @pytest.mark.asyncio
    async def test_readlines_in_write_mode_raises(self, temp_file):
        """Test that readlines() raises in write mode."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            with pytest.raises(OSError, match="File not open for reading"):
                await f.readlines()

    @pytest.mark.asyncio
    async def test_readlines_on_closed_file_raises(self, temp_file):
        """Test that readlines() raises on closed file."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.readlines()

    @pytest.mark.asyncio
    async def test_writelines_basic(self, temp_file):
        """Test basic writelines() functionality."""
        lines = ["Line 1\n", "Line 2\n", "Line 3\n"]

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines(lines)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            result = await f.readlines()
            assert result == lines

    @pytest.mark.asyncio
    async def test_writelines_generator(self, temp_file):
        """Test writelines() with a generator."""

        def line_generator():
            for i in range(5):
                yield f"Line {i}\n"

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines(line_generator())

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines()
            assert lines == ["Line 0\n", "Line 1\n", "Line 2\n", "Line 3\n", "Line 4\n"]

    @pytest.mark.asyncio
    async def test_writelines_empty_list(self, temp_file):
        """Test writelines() with empty list."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines([])

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            content = await f.read()
            assert content == ""

    @pytest.mark.asyncio
    async def test_writelines_no_newlines(self, temp_file):
        """Test that writelines() does not add newlines automatically."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines(["a", "b", "c"])

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            content = await f.read()
            assert content == "abc"

    @pytest.mark.asyncio
    async def test_writelines_in_read_mode_raises(self, temp_file):
        """Test that writelines() raises in read mode."""
        # Create file first
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            with pytest.raises(OSError, match="File not open for writing"):
                await f.writelines(["line"])

    @pytest.mark.asyncio
    async def test_writelines_on_closed_file_raises(self, temp_file):
        """Test that writelines() raises on closed file."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.writelines(["line"])

    @pytest.mark.asyncio
    async def test_readlines_writelines_roundtrip(self, temp_file):
        """Test that writelines(readlines()) preserves data."""
        original_lines = ["First line\n", "Second line\n", "Third line without newline"]

        # Write original
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines(original_lines)

        # Read back
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            read_lines = await f.readlines()

        # Write to new file
        temp_file2 = temp_file + ".copy"
        try:
            async with AsyncGzipTextFile(temp_file2, "wt") as f:
                await f.writelines(read_lines)

            # Read from copy
            async with AsyncGzipTextFile(temp_file2, "rt") as f:
                final_lines = await f.readlines()

            assert final_lines == original_lines
        finally:
            if os.path.exists(temp_file2):
                os.unlink(temp_file2)


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

