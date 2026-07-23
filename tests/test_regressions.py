# pyrefly: ignore
# pyrefly: disable=all
import io
import os

import pytest

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipTextFile,
)


class TestHighPriorityEdgeCases:
    """Test high priority edge cases for improved coverage."""

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

        # Replace the encoder's raw engine with our mock.
        f._encoder._engine = MockEngine()

        with pytest.raises(OSError, match="Unexpected error during compression"):
            await f.write(b"test data")

        await f.__aexit__(None, None, None)

    async def test_unexpected_decompression_error(self, temp_file):
        """Test that unexpected errors during decompression are wrapped in OSError."""

        # First write valid data
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        # Now read with a mocked codec inflate step.
        f = AsyncGzipBinaryFile(temp_file, "rb")
        await f.__aenter__()

        def fail_inflate(data):
            raise RuntimeError("Unexpected decompress error")

        f._decoder._inflate = fail_inflate

        with pytest.raises(OSError, match="Unexpected error during decompression"):
            await f.read()

        await f.__aexit__(None, None, None)

    async def test_decompression_finalization_error(self, temp_file):
        """Test error handling when finalizing gzip decompression at EOF."""
        import zlib

        # Write valid data
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        f = AsyncGzipBinaryFile(temp_file, "rb")
        await f.__aenter__()

        def fail_finish():
            def operation():
                raise zlib.error("Finalization error")
                yield b""  # pragma: no cover

            return operation()

        f._decoder.finish = fail_finish

        with pytest.raises(OSError, match="Error finalizing gzip decompression"):
            await f.read()

        await f.__aexit__(None, None, None)

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
        f._encoder._engine = mock_engine

        with pytest.raises(OSError, match="Unexpected error during flush"):
            await f.flush()

        # Now manually close, allowing the second flush to succeed
        await f.__aexit__(None, None, None)

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

    async def test_utf16_encoding_incomplete_handling(self, temp_file):
        """Test UTF-16 encoding with potential incomplete sequences."""
        test_text = "Hello 世界 🚀"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-16") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-16") as f:
            read_text = await f.read()

        assert read_text == test_text

    async def test_utf32_encoding_incomplete_handling(self, temp_file):
        """Test UTF-32 encoding with potential incomplete sequences."""
        test_text = "Hello 世界 🚀"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="utf-32") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="utf-32") as f:
            read_text = await f.read()

        assert read_text == test_text

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

    async def test_text_buffer_property(self, temp_file):
        """Text mode should expose the underlying binary buffer."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            assert f.buffer is f._binary_file

    async def test_binary_isatty_detach_and_truncate_compatibility(self, temp_file):
        """Binary stream should expose stdlib-compatible capability methods."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            assert f.isatty() is False
            with pytest.raises(io.UnsupportedOperation, match="detach"):
                f.detach()
            with pytest.raises(io.UnsupportedOperation, match="truncate"):
                f.truncate()

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

    async def test_read_with_none_size_binary(self, temp_file):
        """Test that read(None) works correctly in binary mode (converts to -1)."""
        test_data = b"Hello, World! This is test data."

        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            # read(None) should read all data
            data = await f.read(None)
            assert data == test_data

    async def test_read_with_none_size_text(self, temp_file):
        """Test that read(None) works correctly in text mode (converts to -1)."""
        test_text = "Hello, World! This is test text."

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            # read(None) should read all data
            data = await f.read(None)
            assert data == test_text

    async def test_unusual_encoding_shift_jis(self, temp_file):
        """Test with shift_jis encoding (Japanese)."""
        test_text = "こんにちは世界"  # "Hello World" in Japanese

        async with AsyncGzipTextFile(temp_file, "wt", encoding="shift_jis") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="shift_jis") as f:
            data = await f.read()
            assert data == test_text

    async def test_unusual_encoding_iso_8859_1(self, temp_file):
        """Test with iso-8859-1 encoding (Latin-1)."""
        test_text = "Café résumé naïve"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="iso-8859-1") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="iso-8859-1") as f:
            data = await f.read()
            assert data == test_text

    async def test_unusual_encoding_cp1252(self, temp_file):
        """Test with cp1252 encoding (Windows-1252)."""
        test_text = "Euro sign: € and other symbols"

        async with AsyncGzipTextFile(temp_file, "wt", encoding="cp1252") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt", encoding="cp1252") as f:
            data = await f.read()
            assert data == test_text

    @pytest.mark.parametrize(
        ("encoding", "parts"),
        [
            ("utf-16", ["Hello ", "世界", " 🚀"]),
            ("iso2022_jp", ["日本", "語の", "文章"]),
        ],
    )
    async def test_stateful_encoding_is_preserved_across_writes(
        self, temp_file, encoding, parts
    ):
        """Separate text writes must share one incremental encoder state."""
        import gzip as _gzip

        async with AsyncGzipTextFile(temp_file, "wt", encoding=encoding) as f:
            for part in parts:
                await f.write(part)

        with open(temp_file, "rb") as raw_file:
            raw = _gzip.decompress(raw_file.read())
        assert raw == "".join(parts).encode(encoding)

    async def test_write_failure_does_not_advance_accounting(self):
        """If the underlying file.write fails, CRC/size/position must not
        reflect bytes that never reached the file, and subsequent writes
        must not silently produce a corrupted stream."""

        class FailOnNthWrite:
            """Fileobj that records writes and fails on a chosen one."""

            def __init__(self, fail_on_call: int):
                self.calls = 0
                self.fail_on_call = fail_on_call
                self.buf = bytearray()

            async def write(self, data):
                self.calls += 1
                if self.calls == self.fail_on_call:
                    raise OSError("simulated disk full")
                self.buf.extend(data)
                return len(data)

            async def close(self):
                pass

        # Call 1 is the gzip header emitted by __aenter__; fail call 2,
        # which is the first data write. Use incompressible random bytes
        # so the compressor has to flush output.
        import os as _os

        payload = _os.urandom(256 * 1024)
        mock = FailOnNthWrite(fail_on_call=2)
        f = AsyncGzipBinaryFile(None, "wb", fileobj=mock, closefd=False)
        await f.__aenter__()

        with pytest.raises(OSError, match="simulated disk full"):
            await f.write(payload)

        # The codec advances before yielding compressed output, but the file
        # wrapper must not expose that input as committed to the failed sink.
        assert f._encoder.input_size == len(payload)
        assert await f.tell() == 0

        # The stream should be marked broken so a follow-up write does
        # not silently emit bytes on top of a torn compressor state.
        with pytest.raises(OSError, match="broken|unusable|failed"):
            await f.write(b"more")

        # Closing a broken writer should not raise and should not append
        # a trailer that claims data never written.
        await f.__aexit__(None, None, None)

    async def test_flush_write_failure_marks_stream_broken(self):
        """A failed sync-flush write advances zlib and must poison the stream."""

        class FlushFailingWriter:
            def __init__(self):
                self.calls = 0

            async def write(self, data):
                self.calls += 1
                if self.calls == 2:
                    raise OSError("simulated flush failure")
                return len(data)

            async def close(self):
                pass

        writer = FlushFailingWriter()
        f = AsyncGzipBinaryFile(None, "wb", fileobj=writer, closefd=False)
        await f.open()
        await f.write(b"pending data")

        with pytest.raises(OSError, match="simulated flush failure"):
            await f.flush()

        assert f._write_broken is True
        with pytest.raises(OSError, match="broken"):
            await f.write(b"more")

        # A broken stream must not append a final block or trailer on close.
        await f.close()
        assert writer.calls == 2

    async def test_max_decompressed_size_trips_on_bomb(self, temp_file):
        """A highly compressible gzip should not expand past the caller's
        max_decompressed_size cap."""
        import gzip as _gzip

        # 10 MiB of zeros — compresses to a few KB. Untrusted input could
        # easily hide a payload like this.
        bomb_uncompressed = b"\x00" * (10 * 1024 * 1024)
        with _gzip.open(temp_file, "wb") as fh:
            fh.write(bomb_uncompressed)

        # Cap the decompressed output at 1 MiB and expect a clear failure.
        with pytest.raises(OSError, match="max_decompressed_size"):
            async with AsyncGzipBinaryFile(
                temp_file, "rb", max_decompressed_size=1 * 1024 * 1024
            ) as f:
                await f.read()

    async def test_max_decompressed_size_bounds_each_inflate_call(
        self, temp_file, monkeypatch
    ):
        """The guard must limit zlib output, not inspect it after allocation."""
        import gzip as _gzip
        import zlib

        from aiogzip import _binary

        cap = 1 * 1024 * 1024
        with open(temp_file, "wb") as raw_file:
            raw_file.write(_gzip.compress(b"x" * (20 * 1024 * 1024)))

        class TrackingDecompressor:
            def __init__(self, wbits):
                self.inner = zlib.decompressobj(wbits)
                self.limits = []
                self.output_sizes = []

            def decompress(self, data, max_length=0):
                self.limits.append(max_length)
                output = self.inner.decompress(data, max_length)
                self.output_sizes.append(len(output))
                return output

            def flush(self):
                return self.inner.flush()

            @property
            def eof(self):
                return self.inner.eof

            @property
            def unconsumed_tail(self):
                return self.inner.unconsumed_tail

            @property
            def unused_data(self):
                return self.inner.unused_data

        engines = []

        def tracking_factory(wbits):
            engine = TrackingDecompressor(wbits)
            engines.append(engine)
            return engine

        monkeypatch.setattr(_binary._engine, "decompressobj", tracking_factory)

        with pytest.raises(OSError, match="max_decompressed_size"):
            async with AsyncGzipBinaryFile(
                temp_file, "rb", max_decompressed_size=cap
            ) as f:
                await f.read()

        assert engines
        assert engines[0].limits
        assert all(limit > 0 for limit in engines[0].limits)
        assert max(engines[0].output_sizes) <= cap + 1

    async def test_max_decompressed_size_allows_under_cap(self, temp_file):
        """Reads comfortably under the cap should succeed."""
        import gzip as _gzip

        payload = b"ok " * 100
        with _gzip.open(temp_file, "wb") as fh:
            fh.write(payload)

        async with AsyncGzipBinaryFile(
            temp_file, "rb", max_decompressed_size=10 * 1024
        ) as f:
            assert await f.read() == payload

    async def test_max_decompressed_size_resets_after_rewind(self, temp_file):
        """Re-reading an under-cap archive after seek(0) should remain under cap."""
        import gzip as _gzip

        payload = b"abc" * 100
        with _gzip.open(temp_file, "wb") as fh:
            fh.write(payload)

        async with AsyncGzipBinaryFile(
            temp_file, "rb", max_decompressed_size=len(payload)
        ) as f:
            assert await f.read() == payload
            assert await f.seek(0) == 0
            assert await f.read() == payload

    async def test_max_decompressed_size_validated(self):
        """Zero and negative caps should be rejected at construction time."""
        with pytest.raises(ValueError, match="max_decompressed_size"):
            AsyncGzipBinaryFile("test.gz", "rb", max_decompressed_size=0)
        with pytest.raises(ValueError, match="max_decompressed_size"):
            AsyncGzipBinaryFile("test.gz", "rb", max_decompressed_size=-1)
        with pytest.raises(ValueError, match="max_decompressed_size"):
            AsyncGzipTextFile("test.gz", "rt", max_decompressed_size=0)

    async def test_max_decompressed_size_text_mode_trips(self, temp_file):
        """The cap should also apply when reading through AsyncGzipTextFile."""
        import gzip as _gzip

        with _gzip.open(temp_file, "wt") as fh:
            fh.write("a" * (2 * 1024 * 1024))

        with pytest.raises(OSError, match="max_decompressed_size"):
            async with AsyncGzipTextFile(
                temp_file, "rt", max_decompressed_size=256 * 1024
            ) as f:
                await f.read()

    async def test_large_compress_offloaded_to_executor(self, temp_file):
        """compress() of a payload above the offload threshold must run in
        an executor so the event loop is not blocked during the CPU work."""
        import os as _os
        from unittest.mock import patch

        from aiogzip import _binary

        calls = []
        original = _binary._engine.run_zlib_in_thread

        async def tracking(method, data):
            calls.append(len(data))
            return await original(method, data)

        with patch.object(_binary._engine, "run_zlib_in_thread", tracking):
            payload = _os.urandom(2 * 1024 * 1024)  # Above threshold.
            async with AsyncGzipBinaryFile(temp_file, "wb") as f:
                await f.write(payload)
            assert calls, "large write should have been offloaded"
            assert max(calls) >= _binary._ZLIB_OFFLOAD_THRESHOLD

    async def test_small_compress_stays_inline(self, temp_file):
        """Tiny writes should not pay the executor round-trip cost."""
        from unittest.mock import patch

        from aiogzip import _binary

        calls = []

        async def tracking(method, data):
            calls.append(len(data))
            return method(data)

        with patch.object(_binary._engine, "run_zlib_in_thread", tracking):
            async with AsyncGzipBinaryFile(temp_file, "wb") as f:
                await f.write(b"small payload")
        # Small payloads must stay inline to avoid executor overhead.
        assert calls == []

    async def test_large_decompress_offloaded_to_executor(self, temp_file):
        """decompress() of a large member should also run in the executor."""
        import gzip as _gzip
        import os as _os
        from unittest.mock import patch

        from aiogzip import _binary

        payload = _os.urandom(2 * 1024 * 1024)  # Incompressible → large chunks.
        with _gzip.open(temp_file, "wb") as fh:
            fh.write(payload)

        calls = []
        original = _binary._engine.run_zlib_in_thread

        async def tracking(method, data):
            calls.append(len(data))
            return await original(method, data)

        with patch.object(_binary._engine, "run_zlib_in_thread", tracking):
            async with AsyncGzipBinaryFile(
                temp_file, "rb", chunk_size=_binary._ZLIB_OFFLOAD_THRESHOLD * 2
            ) as f:
                got = await f.read()
        assert got == payload
        assert calls, "large decompress should have been offloaded"

    async def test_large_subsequent_member_offloaded_to_executor(self, temp_file):
        """A large second member, surfaced as unused_data after the first
        member ends, must also be offloaded to the executor rather than
        decompressed inline on the event loop."""
        import gzip as _gzip
        import os as _os
        from unittest.mock import patch

        from aiogzip import _binary

        small = b"first member"
        large = _os.urandom(2 * 1024 * 1024)  # incompressible second member
        # Two concatenated gzip members.
        with open(temp_file, "wb") as fh:
            fh.write(_gzip.compress(small))
            fh.write(_gzip.compress(large))

        calls = []
        original = _binary._engine.run_zlib_in_thread

        async def tracking(method, data):
            calls.append(len(data))
            return await original(method, data)

        # A chunk_size large enough to read both members in one read, so the
        # second member arrives as unused_data on the first decompressor.
        with patch.object(_binary._engine, "run_zlib_in_thread", tracking):
            async with AsyncGzipBinaryFile(
                temp_file, "rb", chunk_size=8 * 1024 * 1024
            ) as f:
                got = await f.read()
        assert got == small + large
        assert any(n >= _binary._ZLIB_OFFLOAD_THRESHOLD for n in calls), (
            "large subsequent member should have been offloaded"
        )

    async def test_strict_size_rejects_write_past_4gib(self, temp_file):
        """With strict_size=True, a write that would push input_size past
        the gzip ISIZE field's 4 GiB cap must raise rather than silently
        emit a truncated-looking trailer."""
        async with AsyncGzipBinaryFile(temp_file, "wb", strict_size=True) as f:
            # Pre-seed the accumulator just below the ISIZE limit. A real
            # caller would have reached this via actual writes; simulating
            # it keeps the test cheap.
            f._encoder._input_size = 0xFFFFFFFF - 2
            with pytest.raises(OSError, match="4 GiB"):
                await f.write(b"abcdef")

    async def test_strict_size_at_limit_ok(self, temp_file):
        """A write that lands exactly on the 4 GiB boundary is allowed."""
        async with AsyncGzipBinaryFile(temp_file, "wb", strict_size=True) as f:
            f._encoder._input_size = 0xFFFFFFFF - 3
            # Exactly three bytes leaves input_size == 0xFFFFFFFF, which
            # still fits the ISIZE field.
            await f.write(b"abc")
            assert f._encoder.input_size == 0xFFFFFFFF

    async def test_text_cookie_rejected_by_different_instance(self, temp_file):
        """A tell() cookie from one AsyncGzipTextFile must not be accepted
        by a different instance, even if both point at the same file.
        The per-instance cookie nonce is what guarantees this."""
        import gzip as _gzip

        with _gzip.open(temp_file, "wt") as fh:
            fh.write("alpha\nbeta\ngamma\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f1:
            await f1.readline()
            cookie = await f1.tell()

        async with AsyncGzipTextFile(temp_file, "rt") as f2:
            with pytest.raises(OSError, match="invalid text cookie"):
                await f2.seek(cookie)

    async def test_failed_enter_with_raising_close_leaves_null_file(self, tmp_path):
        """If __aenter__ fails on an internally-opened file and the
        subsequent close() also raises, _cleanup_failed_enter must still
        null _file so the half-closed handle is not reachable."""
        from unittest.mock import AsyncMock, patch

        from aiogzip import _binary

        class BadFile:
            def __init__(self):
                self.closed_called = False

            async def write(self, data):
                raise OSError("write boom")

            async def close(self):
                self.closed_called = True
                raise OSError("close boom")

        bad = BadFile()

        # Make aiofiles.open return our BadFile so the file is treated as
        # internally owned; __aenter__ then writes the gzip header via
        # BadFile.write which raises, triggering cleanup — whose close()
        # also raises.
        async def fake_open(*args, **kwargs):
            return bad

        target = tmp_path / "out.gz"
        f = AsyncGzipBinaryFile(str(target), "wb")
        with patch.object(_binary.aiofiles, "open", AsyncMock(side_effect=fake_open)):
            with pytest.raises(OSError):
                await f.__aenter__()
        assert bad.closed_called, "cleanup must still attempt close()"
        assert f._file is None, "cleanup must null _file even if close raises"
        assert f._owns_file is False

    async def test_strict_size_defaults_off(self, temp_file):
        """Default behaviour (strict_size=False) still silently wraps to
        match gzip.open() so we do not break existing callers."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            f._encoder._input_size = 0xFFFFFFFE
            # Should not raise.
            await f.write(b"abcdef")

    async def test_truncated_gzip_seek_end_raises(self, temp_file):
        """SEEK_END on a mid-stream truncated gzip must not silently report
        a partial position; the reader should detect the missing trailer."""
        import gzip as _gzip

        # Create a valid gzip then drop the last 200 bytes so the deflate
        # stream is cut mid-block (no trailing CRC/ISIZE).
        with _gzip.open(temp_file, "wb") as fh:
            fh.write(b"x" * (256 * 1024))
        size = os.path.getsize(temp_file)
        with open(temp_file, "r+b") as fh:
            fh.truncate(size - 200)

        with pytest.raises(_gzip.BadGzipFile):
            async with AsyncGzipBinaryFile(temp_file, "rb") as gz:
                await gz.seek(0, 2)  # SEEK_END

    async def test_truncated_gzip_read_raises(self, temp_file):
        """Reading to EOF on a truncated gzip must also raise."""
        import gzip as _gzip

        with _gzip.open(temp_file, "wb") as fh:
            fh.write(b"y" * (128 * 1024))
        size = os.path.getsize(temp_file)
        with open(temp_file, "r+b") as fh:
            fh.truncate(size - 50)

        with pytest.raises(_gzip.BadGzipFile):
            async with AsyncGzipBinaryFile(temp_file, "rb") as gz:
                await gz.read()

    async def test_crc_is_masked_to_32_bits(self, temp_file):
        """The accumulated CRC must stay within the 32-bit range so that
        the trailer bytes match what zlib would have produced."""
        import zlib

        payload = b"x" * 1024
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(payload)
            # Pre-close: the codec CRC must be the same uint32 value
            # that zlib.crc32 returns for the same bytes.
            expected = zlib.crc32(payload) & 0xFFFFFFFF
            assert f._encoder.crc32 == expected
            assert 0 <= f._encoder.crc32 <= 0xFFFFFFFF


class TestLowPriorityEdgeCases:
    """Test low priority edge cases for improved coverage."""

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

    async def test_text_read_on_closed_file(self, temp_file):
        """Test that reading on closed text file raises ValueError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            await f.read()

        # Now file is closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.read()

    async def test_binary_read_without_context_manager(self, temp_file):
        """Test that reading without entering context manager raises ValueError."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test")

        f = AsyncGzipBinaryFile(temp_file, "rb")
        # Don't enter context manager
        with pytest.raises(ValueError, match="File not opened"):
            await f.read()

    async def test_text_read_without_context_manager(self, temp_file):
        """Test that reading without entering context manager raises ValueError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        f = AsyncGzipTextFile(temp_file, "rt")
        # Don't enter context manager
        with pytest.raises(ValueError, match="File not opened"):
            await f.read()

    async def test_binary_write_on_closed_file(self, temp_file):
        """Test that writing on closed binary file raises ValueError."""
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")

        # Now file is closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write(b"more")

    async def test_text_write_on_closed_file(self, temp_file):
        """Test that writing on closed text file raises ValueError."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        # Now file is closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.write("more")

    async def test_text_write_in_read_mode(self, temp_file):
        """Test that write in read mode raises IOError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            with pytest.raises(IOError, match="File not open for writing"):
                await f.write("should fail")

    async def test_text_read_in_write_mode(self, temp_file):
        """Test that read in write mode raises IOError."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            with pytest.raises(IOError, match="File not open for reading"):
                await f.read()

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

    async def test_text_flush_on_closed_file(self, temp_file):
        """Test that flush on closed text file raises ValueError."""
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        # Now closed
        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.flush()

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

    async def test_binary_write_in_read_mode(self, temp_file):
        """Test that write in read mode raises IOError for binary files."""
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            with pytest.raises(IOError, match="File not open for writing"):
                await f.write(b"should fail")

    async def test_text_write_without_context_manager(self, temp_file):
        """Test that write without context manager raises ValueError."""
        f = AsyncGzipTextFile(temp_file, "wt")
        # Don't enter context manager
        with pytest.raises(ValueError, match="File not opened"):
            await f.write("should fail")

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
        f._encoder._engine = MockEngine()

        with pytest.raises(OSError, match="Error compressing data"):
            await f.write(b"test")

        await f.__aexit__(None, None, None)

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
        f._encoder._engine = MockEngine()

        with pytest.raises(OSError, match="Error flushing compressed data"):
            await f.flush()

        await f.__aexit__(None, None, None)


class TestNegativeReadlineLimit:
    """A negative readline limit must mean "no limit" (io.IOBase semantics).

    Regression: limits below -1 previously reached the offset arithmetic and
    moved the buffer offset backwards, re-serving already-consumed bytes
    (binary) or driving the text buffer offset negative so every subsequent
    readline returned "".
    """

    async def test_binary_negative_limit_returns_full_line(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"hello world\nsecond line\n")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.readline(-2) == b"hello world\n"
            assert await f.readline(-100) == b"second line\n"

    async def test_binary_negative_limit_does_not_rewind_position(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"hello world\nsecond line\n")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            await f.read(3)  # populate the buffer, consume "hel"
            assert await f.readline(-2) == b"lo world\n"
            assert await f.tell() == 12
            assert await f.read(6) == b"second"

    async def test_text_negative_limit_returns_full_line(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("hello world\nsecond line\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            assert await f.readline(-2) == "hello world\n"
            assert await f.readline(-100) == "second line\n"
            assert await f.readline(-1) == ""

    async def test_text_negative_limit_does_not_corrupt_buffer(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("hello world\nsecond line\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            await f.read(3)  # populate the buffer, consume "hel"
            assert await f.readline(-5) == "lo world\n"
            assert await f.readline() == "second line\n"


class TestZeroByteFile:
    """A zero-byte file must read as empty, matching gzip.open().

    Regression: the truncation guard fired for files that never yielded any
    compressed bytes, raising BadGzipFile where stdlib returns empty output.
    Files that end mid-member must still raise.
    """

    async def test_binary_read_returns_empty(self, temp_file):
        open(temp_file, "wb").close()
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.read() == b""
            assert await f.readline() == b""

    async def test_text_read_returns_empty(self, temp_file):
        open(temp_file, "wb").close()
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            assert await f.read() == ""

    async def test_binary_iteration_yields_nothing(self, temp_file):
        open(temp_file, "wb").close()
        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            lines = [line async for line in f]
        assert lines == []

    async def test_truncated_file_still_raises(self, temp_file):
        import gzip

        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"payload that will be truncated mid-member")
        with open(temp_file, "rb") as raw:
            data = raw.read()
        with open(temp_file, "wb") as raw:
            raw.write(data[: len(data) // 2])

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            with pytest.raises(gzip.BadGzipFile, match="truncated"):
                await f.read()


class TestWriteCancellationDuringOffload:
    """Cancelling a write during the executor compress hop must break the stream.

    Regression: the executor thread keeps running after the await is
    cancelled, so the shared compressor can consume bytes that were never
    accounted for; a subsequent write would silently produce a torn member.
    """

    async def test_cancelled_offloaded_write_marks_stream_broken(
        self, temp_file, monkeypatch
    ):
        import asyncio

        from aiogzip import _binary

        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking_offload(method, data):
            started.set()
            await release.wait()
            return method(data)

        monkeypatch.setattr(_binary._engine, "run_zlib_in_thread", blocking_offload)

        payload = os.urandom(512 * 1024)  # above the offload threshold
        f = AsyncGzipBinaryFile(temp_file, "wb")
        await f.__aenter__()
        try:
            task = asyncio.ensure_future(f.write(payload))
            await started.wait()
            task.cancel()
            # Cancellation waits for the executor-backed codec step to stop
            # mutating shared state before the encoder is discarded.
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

            with pytest.raises(OSError, match="broken"):
                await f.write(b"more")
        finally:
            await f.__aexit__(None, None, None)


class TestReadCancellationDuringOffload:
    """Cancelling executor decompression must make later reads fail safely."""

    @pytest.mark.parametrize("use_cap", [False, True])
    async def test_cancelled_offloaded_read_marks_stream_broken(
        self, temp_file, monkeypatch, use_cap
    ):
        import asyncio
        import gzip

        from aiogzip import _binary

        payload = os.urandom(512 * 1024)
        with gzip.open(temp_file, "wb") as raw:
            raw.write(payload)

        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking_offload(method, data):
            started.set()
            await release.wait()
            return method(data)

        monkeypatch.setattr(_binary._engine, "run_zlib_in_thread", blocking_offload)
        cap = len(payload) * 2 if use_cap else None
        f = AsyncGzipBinaryFile(
            temp_file,
            "rb",
            chunk_size=1024 * 1024,
            max_decompressed_size=cap,
        )
        await f.open()
        try:
            task = asyncio.ensure_future(f.read())
            await started.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert f._read_broken is True
            with pytest.raises(OSError, match="broken.*close and reopen"):
                await f.read()
            with pytest.raises(OSError, match="broken.*close and reopen"):
                await f.peek(1)
            with pytest.raises(OSError, match="broken.*close and reopen"):
                await f.seek(0)
        finally:
            await f.close()
