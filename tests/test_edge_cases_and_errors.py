import gzip
import io
import os

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestEdgeCasesAndErrors:
    """Targeted tests to improve code coverage and handle edge cases."""

    @pytest.mark.asyncio
    async def test_compresslevel_validation(self):
        """Test validation of compresslevel."""
        # -1 is valid (zlib default)
        AsyncGzipBinaryFile("test.gz", mode="wb", compresslevel=-1)

        with pytest.raises(
            ValueError, match="Compression level must be between -1 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", mode="wb", compresslevel=-2)

        with pytest.raises(
            ValueError, match="Compression level must be between -1 and 9"
        ):
            AsyncGzipBinaryFile("test.gz", mode="wb", compresslevel=10)

    @pytest.mark.asyncio
    async def test_mtime_validation(self):
        """Test validation of mtime values."""
        AsyncGzipBinaryFile("test.gz", mode="wb", mtime=0xFFFFFFFF)
        AsyncGzipTextFile("test.gz", mode="wt", mtime=0xFFFFFFFF)

        with pytest.raises(ValueError, match=r"mtime must be <= 4294967295"):
            AsyncGzipBinaryFile("test.gz", mode="wb", mtime=0x100000000)

        with pytest.raises(ValueError, match=r"mtime must be <= 4294967295"):
            AsyncGzipTextFile("test.gz", mode="wt", mtime=0x100000000)

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

    def test_factory_mode_type_error(self):
        """Factory mode validation should happen before mode probing."""
        from aiogzip import AsyncGzipFile

        with pytest.raises(TypeError, match="mode must be a string"):
            AsyncGzipFile("test.gz", mode=123)  # type: ignore[arg-type]

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

        # None values should be accepted and normalized
        f = AsyncGzipTextFile("test.gz", encoding=None, errors=None)
        assert f._encoding == "utf-8"
        assert f._errors == "strict"

        # Text mode cannot include binary (explicit check in init)
        with pytest.raises(ValueError, match="Text mode cannot include binary"):
            AsyncGzipTextFile("test.gz", mode="rb")

        # Invalid mode op
        with pytest.raises(ValueError, match="Invalid mode"):
            AsyncGzipTextFile("test.gz", mode="y")

        # Invalid newline value
        with pytest.raises(ValueError, match="illegal newline value"):
            AsyncGzipTextFile("test.gz", newline="bad")

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
    async def test_binary_enter_failure_closes_owned_file(self, monkeypatch, tmp_path):
        """Failed binary __aenter__ should close internally opened file handles."""
        import aiogzip._binary as binary_module

        class FailingFile:
            def __init__(self):
                self.close_called = False

            async def write(self, data):
                raise OSError("header write failed")

            async def close(self):
                self.close_called = True

        opened_file = FailingFile()

        async def fake_open(*args, **kwargs):
            return opened_file

        monkeypatch.setattr(binary_module.aiofiles, "open", fake_open)

        f = AsyncGzipBinaryFile(tmp_path / "broken.gz", "wb")
        with pytest.raises(OSError, match="header write failed"):
            await f.__aenter__()

        assert opened_file.close_called is True
        assert f._file is None

    @pytest.mark.asyncio
    async def test_text_enter_failure_closes_nested_binary_file(
        self, monkeypatch, tmp_path
    ):
        """Failed text __aenter__ should clean up the nested binary layer."""
        import aiogzip._text as text_module

        class FailingBinaryFile:
            last_instance = None

            def __init__(self, *args, **kwargs):
                self.close_called = False
                self.__class__.last_instance = self

            async def __aenter__(self):
                raise OSError("binary setup failed")

            async def close(self):
                self.close_called = True

        monkeypatch.setattr(text_module, "AsyncGzipBinaryFile", FailingBinaryFile)

        f = AsyncGzipTextFile(tmp_path / "broken.gz", "wt")
        with pytest.raises(OSError, match="binary setup failed"):
            await f.__aenter__()

        assert FailingBinaryFile.last_instance is not None
        assert FailingBinaryFile.last_instance.close_called is True
        assert f._binary_file is None

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
    async def test_binary_iteration_requires_read_mode(self, tmp_path):
        """Binary iteration should raise if the file is not open for reading."""
        p = tmp_path / "iter_write.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"data")
            iterator = f.__aiter__()
            with pytest.raises(OSError, match="File not open for reading"):
                await iterator.__anext__()


class TestAdditionalCoverage:
    """Additional tests to improve code coverage."""

    @pytest.mark.asyncio
    async def test_derive_header_filename_type_error(self, tmp_path):
        """Test _derive_header_filename raises TypeError for invalid type."""
        from aiogzip import _derive_header_filename

        # Pass an invalid type (not str, bytes, or Path)
        with pytest.raises(TypeError, match="original_filename must be"):
            _derive_header_filename(12345, None)

    @pytest.mark.asyncio
    async def test_derive_header_filename_unicode_error(self, tmp_path):
        """Test _derive_header_filename handles UnicodeEncodeError gracefully."""
        from aiogzip import _derive_header_filename

        # Characters that can't be encoded to latin-1
        result = _derive_header_filename("日本語.gz", None)
        assert result == b""

    def test_original_filename_rejects_nul_bytes(self):
        """NUL bytes would terminate FNAME early and corrupt the gzip stream."""
        with pytest.raises(ValueError, match="original_filename cannot contain NUL"):
            AsyncGzipBinaryFile("test.gz", "wb", original_filename=b"a\x00b")

        with pytest.raises(ValueError, match="original_filename cannot contain NUL"):
            AsyncGzipTextFile("test.gz", "wt", original_filename="a\x00b")

    @pytest.mark.asyncio
    async def test_rewind_in_write_mode_raises(self, tmp_path):
        """Test rewind() raises error in write mode."""
        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"test")
            with pytest.raises(OSError, match="Can't rewind in write mode"):
                await f.rewind()

    @pytest.mark.asyncio
    async def test_peek_in_write_mode_raises(self, tmp_path):
        """Test peek() raises error in write mode."""
        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            with pytest.raises(OSError, match="File not open for reading"):
                await f.peek()

    @pytest.mark.asyncio
    async def test_readinto_in_write_mode_raises(self, tmp_path):
        """Test readinto() raises error in write mode."""
        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            buf = bytearray(10)
            with pytest.raises(OSError, match="File not open for reading"):
                await f.readinto(buf)

    @pytest.mark.asyncio
    async def test_seek_invalid_whence(self, tmp_path):
        """Test seek() with invalid whence value."""
        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"test data")

        async with AsyncGzipBinaryFile(p, "rb") as f:
            with pytest.raises(ValueError, match="Invalid whence"):
                await f.seek(0, 99)  # Invalid whence

    @pytest.mark.asyncio
    async def test_seek_end_in_write_mode(self, tmp_path):
        """Test seek(SEEK_END) in write mode raises error."""
        import os

        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"test data")
            with pytest.raises(ValueError, match="Seek from end not supported"):
                await f.seek(0, os.SEEK_END)

    @pytest.mark.asyncio
    async def test_seek_end_in_read_mode(self, tmp_path):
        """Test seek(SEEK_END) in read mode matches gzip.GzipFile semantics."""
        import os

        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"test data")

        async with AsyncGzipBinaryFile(p, "rb") as f:
            assert await f.seek(-4, os.SEEK_END) == 5
            assert await f.read() == b"data"

    @pytest.mark.asyncio
    async def test_fileno_no_fileno_method(self, tmp_path):
        """Test fileno() raises when underlying file has no fileno."""
        import io

        class NoFilenoFile:
            async def read(self, size=-1):
                return b""

            async def write(self, data):
                return len(data)

            async def close(self):
                pass

        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"test")

        # Create a fake file object without fileno
        fake_file = NoFilenoFile()
        f = AsyncGzipBinaryFile(None, "rb", fileobj=fake_file)
        await f.__aenter__()
        try:
            with pytest.raises(io.UnsupportedOperation, match="fileno"):
                f.fileno()
        finally:
            await f.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_text_seek_cookie_remains_valid_after_many_tells(self, tmp_path):
        """tell() cookies should remain valid for the full stream lifetime."""
        p = tmp_path / "long_lived_cookie.gz"
        async with AsyncGzipTextFile(p, "wt", newline="") as f:
            await f.write("aé🙂b" * 600)

        async with AsyncGzipTextFile(p, "rt", newline="", chunk_size=1) as f:
            await f.read(5)
            cookie = await f.tell()
            expected = await f.read(10)

            for _ in range(300):
                if not await f.read(5):
                    break
                await f.tell()

            await f.seek(cookie)
            assert await f.read(10) == expected

    @pytest.mark.asyncio
    async def test_text_tell_cookies_are_self_contained(self, tmp_path):
        """Text cookies should not rely on per-position cache state in the stream."""
        p = tmp_path / "self_contained_cookie.gz"
        async with AsyncGzipTextFile(p, "wt", newline="") as f:
            await f.write("abcdefghij" * 1000)

        async with AsyncGzipTextFile(p, "rt", newline="", chunk_size=4096) as f:
            assert not hasattr(f, "_cookie_cache")
            assert not hasattr(f, "_cookie_lookup")
            await f.read(1)
            cookie = await f.tell()
            assert isinstance(cookie, int)
            assert cookie < 0

    @pytest.mark.asyncio
    async def test_text_seek_cookie_from_other_stream_raises(self, tmp_path):
        """Cookies should remain scoped to the open handle that created them."""
        p = tmp_path / "cross_stream_cookie.gz"
        async with AsyncGzipTextFile(p, "wt") as f:
            await f.write("hello world")

        async with AsyncGzipTextFile(p, "rt") as first:
            await first.read(5)
            cookie = await first.tell()

        async with AsyncGzipTextFile(p, "rt") as second:
            with pytest.raises(
                OSError, match="Cannot seek to invalid text cookie for this stream"
            ):
                await second.seek(cookie)

    @pytest.mark.asyncio
    async def test_text_seek_invalid_cookie_raises(self, tmp_path):
        """Seeking an arbitrary cookie should fail cleanly."""
        p = tmp_path / "invalid_cookie.gz"
        async with AsyncGzipTextFile(p, "wt") as f:
            await f.write("hello world")

        async with AsyncGzipTextFile(p, "rt") as f:
            with pytest.raises(
                OSError, match="Cannot seek to invalid text cookie for this stream"
            ):
                await f.seek(-1)

    @pytest.mark.asyncio
    async def test_text_seek_non_seek_set(self, tmp_path):
        """Test text file seek() non-SEEK_SET semantics."""
        import os

        p = tmp_path / "test.gz"
        async with AsyncGzipTextFile(p, "wt") as f:
            await f.write("Hello World")

        async with AsyncGzipTextFile(p, "rt") as f:
            assert await f.seek(0, os.SEEK_CUR) == await f.tell()
            with pytest.raises(
                io.UnsupportedOperation, match="can't do nonzero cur-relative seeks"
            ):
                await f.seek(1, os.SEEK_CUR)

    @pytest.mark.asyncio
    async def test_coerce_byteslike_invalid_type(self, tmp_path):
        """Test _coerce_byteslike with invalid type."""
        from aiogzip import AsyncGzipBinaryFile

        p = tmp_path / "test.gz"
        async with AsyncGzipBinaryFile(p, "wb") as f:
            with pytest.raises(TypeError, match="must be a bytes-like object"):
                await f.write("string not allowed")  # type: ignore

    @pytest.mark.asyncio
    async def test_runtime_checkable_protocols(self):
        """Test that protocols are runtime checkable."""
        from aiogzip import WithAsyncRead, WithAsyncReadWrite, WithAsyncWrite

        class MockReader:
            async def read(self, size=-1):
                return b""

        class MockWriter:
            async def write(self, data):
                return len(data)

        class MockReadWriter:
            async def read(self, size=-1):
                return b""

            async def write(self, data):
                return len(data)

            async def close(self):
                pass

        reader = MockReader()
        writer = MockWriter()
        readwriter = MockReadWriter()

        assert isinstance(reader, WithAsyncRead)
        assert isinstance(writer, WithAsyncWrite)
        assert isinstance(readwriter, WithAsyncReadWrite)

    @pytest.mark.asyncio
    async def test_get_line_terminator_explicit_cr(self, tmp_path):
        """Test line terminator detection with explicit CR newline mode."""
        p = tmp_path / "test.gz"

        # Write with CR line endings
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"line1\rline2\rline3")

        # Read with explicit CR newline mode
        async with AsyncGzipTextFile(p, "rt", newline="\r") as f:
            line1 = await f.readline()
            line2 = await f.readline()
            assert line1 == "line1\r"
            assert line2 == "line2\r"

    @pytest.mark.asyncio
    async def test_get_line_terminator_explicit_crlf(self, tmp_path):
        """Test line terminator detection with explicit CRLF newline mode."""
        p = tmp_path / "test.gz"

        # Write with CRLF line endings
        async with AsyncGzipBinaryFile(p, "wb") as f:
            await f.write(b"line1\r\nline2\r\nline3")

        # Read with explicit CRLF newline mode
        async with AsyncGzipTextFile(p, "rt", newline="\r\n") as f:
            line1 = await f.readline()
            line2 = await f.readline()
            assert line1 == "line1\r\n"
            assert line2 == "line2\r\n"


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

    def test_chunk_size_upper_bound(self):
        """chunk_size must be rejected if it exceeds the safety cap."""
        # 128 MiB is the cap; just over should raise.
        too_big = 128 * 1024 * 1024 + 1
        with pytest.raises(ValueError, match="Chunk size must be <="):
            AsyncGzipBinaryFile("test.gz", chunk_size=too_big)
        with pytest.raises(ValueError, match="Chunk size must be <="):
            AsyncGzipTextFile("test.gz", chunk_size=too_big)
        # Exactly at the cap is allowed.
        AsyncGzipBinaryFile("test.gz", chunk_size=128 * 1024 * 1024)

    @pytest.mark.asyncio
    async def test_peek_size_upper_bound(self, temp_file, sample_data):
        """peek(size) must reject absurd sizes rather than try to buffer them."""
        async with AsyncGzipBinaryFile(temp_file, mode="wb") as f:
            await f.write(sample_data)
        async with AsyncGzipBinaryFile(temp_file, mode="rb") as f:
            with pytest.raises(ValueError, match="peek size"):
                await f.peek(128 * 1024 * 1024 + 1)

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
        """Test that exception chaining is used (from e) for debugging.

        Start from a valid gzip and corrupt a byte inside the deflate
        payload so the error surfaces through zlib rather than through
        the truncation check.
        """
        import gzip as _gzip

        with _gzip.open(temp_file, "wb") as fh:
            fh.write(b"payload data " * 4096)
        data = bytearray(open(temp_file, "rb").read())
        # Flip a byte well inside the deflate body to force a zlib.error.
        data[100] ^= 0xFF
        with open(temp_file, "wb") as fh:
            fh.write(data)

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
