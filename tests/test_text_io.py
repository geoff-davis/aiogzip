# pyrefly: ignore
# pyrefly: disable=all
import gzip
import io
import os

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestAsyncGzipTextFile:
    """Test the AsyncGzipTextFile class."""

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
            partial_data = await f.read(10)
            assert partial_data == sample_text[:10]

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

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
        assert data.count(b"\r\n") == text.count("\n")

    @pytest.mark.asyncio
    async def test_text_read_all_after_partial_with_buffering(self, temp_file):
        """Test read(-1) returns all remaining data including buffered text."""
        test_text = "x" * 10000 + "END"

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            first_chars = await f.read(5)
            assert first_chars == "xxxxx"

            remaining = await f.read(-1)

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
        """Arbitrary codecs error handlers should be accepted."""
        text = "snowman ☃"
        async with AsyncGzipTextFile(temp_file, "wt", errors="surrogatepass") as f:
            await f.write(text)

    @pytest.mark.asyncio
    async def test_text_seek_and_tell(self, temp_file, sample_text):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(sample_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            head = await f.read(4)
            assert head == sample_text[:4]
            pos = await f.tell()
            assert isinstance(pos, int)
            await f.seek(0)
            entire = await f.read()
            assert entire == sample_text

        async with AsyncGzipTextFile(temp_file, "wt") as wf:
            await wf.write("ééé")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            await f.read(1)
            await f.tell()
            await f.seek(0)
            assert await f.read() == "ééé"

    @pytest.mark.asyncio
    async def test_text_seek_cookie_restores_buffer(self, temp_file):
        text = "abcdefghijklmnopqrstuvwxyz"
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            first = await f.read(5)
            assert first == text[:5]
            cookie = await f.tell()
            remaining = await f.read()
            assert remaining == text[5:]
            await f.seek(cookie)
            replay = await f.read()
            assert replay == remaining

    @pytest.mark.asyncio
    async def test_text_seek_cookie_handles_multibyte(self, temp_file):
        text = "éå漢字"
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            await f.read(1)
            cookie = await f.tell()
            rest = await f.read()
            await f.seek(cookie)
            replay = await f.read()
            assert replay == rest

    @pytest.mark.asyncio
    async def test_text_tell_cookies_are_unique_for_nearby_positions(self, temp_file):
        text = "abcdefghij" * 1000
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(text)

        async with AsyncGzipTextFile(temp_file, "rt", newline="", chunk_size=1024) as f:
            assert await f.read(1) == "a"
            cookie1 = await f.tell()
            assert await f.read(1) == "b"
            cookie2 = await f.tell()

            assert cookie1 != cookie2

            await f.seek(cookie1)
            assert await f.read(2) == "bc"

    @pytest.mark.asyncio
    async def test_text_seek_cur_and_end_zero(self, temp_file):
        """Text seek should support zero-offset SEEK_CUR and SEEK_END."""
        text = "abc\ndef"
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            assert await f.tell() == 0
            assert await f.seek(0, os.SEEK_CUR) == 0
            await f.read(2)
            cur = await f.seek(0, os.SEEK_CUR)
            assert cur == await f.tell()

            end = await f.seek(0, os.SEEK_END)
            assert end == len(text)
            assert await f.tell() == len(text)
            assert await f.read() == ""

    @pytest.mark.asyncio
    async def test_text_seek_nonzero_cur_end_raises(self, temp_file):
        """Text seek should reject nonzero relative seeks."""
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("abc")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            with pytest.raises(
                io.UnsupportedOperation, match="can't do nonzero cur-relative seeks"
            ):
                await f.seek(1, os.SEEK_CUR)
            with pytest.raises(
                io.UnsupportedOperation, match="can't do nonzero end-relative seeks"
            ):
                await f.seek(1, os.SEEK_END)

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
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(sample_text)

        with gzip.open(temp_file, "rt") as f:
            read_data = f.read()
            assert read_data == sample_text


class TestTextErrorsBehavior:
    """Tests for errors= behavior matching gzip semantics."""

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

        async with AsyncGzipTextFile(
            temp_file, "rt", encoding="ascii", errors="strict"
        ) as f:
            data = await f.read()
            assert data == "ascii and emoji "


class TestTextNewlineBehavior:
    """Tests for newline handling similar to TextIOWrapper semantics."""

    @pytest.mark.asyncio
    async def test_read_universal_newlines_default(self, temp_file):
        raw_text = "line1\r\nline2\rline3\nline4"
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(raw_text)  # pyrefly: ignore

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read()
            assert data == "line1\nline2\nline3\nline4"

    @pytest.mark.asyncio
    async def test_write_translate_default(self, temp_file):
        text = "a\nb\n"
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(text)  # pyrefly: ignore

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

    @pytest.mark.asyncio
    async def test_newlines_reports_observed_universal_newlines(self, temp_file):
        raw_text = "line1\r\nline2\nline3\r"
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(raw_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            assert f.newlines is None
            assert await f.read() == "line1\nline2\nline3\n"
            assert f.newlines == ("\r", "\n", "\r\n")

    @pytest.mark.asyncio
    async def test_newlines_reports_observed_types_without_translation(self, temp_file):
        raw_text = "line1\r\nline2\n"
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(raw_text)

        async with AsyncGzipTextFile(temp_file, "rt", newline="") as f:
            assert f.newlines is None
            assert await f.readline() == "line1\r\n"
            assert f.newlines == ("\n", "\r\n")


class TestNewlineHandlingBugs:
    """Tests for newline handling bugs identified in code review."""

    @pytest.mark.asyncio
    async def test_crlf_split_across_chunk_boundary(self, temp_file):
        """Test that CRLF split across chunk boundaries is handled correctly."""
        chunk_size = 1024
        text = "x" * (chunk_size - 10) + "\r\n" + "y" * 100

        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write(text)

        async with AsyncGzipTextFile(temp_file, "rt", chunk_size=chunk_size) as f:
            f._binary_file._chunk_size = 100
            result = await f.read()

        expected = "x" * (chunk_size - 10) + "\n" + "y" * 100
        newline_count = result.count("\n")
        assert result == expected, (
            f"Got {newline_count} newlines instead of 1, CRLF was split incorrectly"
        )

    @pytest.mark.asyncio
    async def test_line_iteration_with_cr_only_newline(self, temp_file):
        """Test that line iteration respects newline='\\r' mode."""
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write("line1\rline2\rline3")

        lines = []
        async with AsyncGzipTextFile(temp_file, "rt", newline="\r") as f:
            async for line in f:
                lines.append(line)

        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {lines}"

    @pytest.mark.asyncio
    async def test_readline_with_cr_only_newline(self, temp_file):
        """Test that readline respects newline='\\r' mode."""
        async with AsyncGzipTextFile(temp_file, "wt", newline="") as f:
            await f.write("line1\rline2\rline3")

        async with AsyncGzipTextFile(temp_file, "rt", newline="\r") as f:
            line1 = await f.readline()
            line2 = await f.readline()
            line3 = await f.readline()

        assert line1 == "line1\r", f"Expected 'line1\\r', got {repr(line1)}"
        assert line2 == "line2\r", f"Expected 'line2\\r', got {repr(line2)}"
        assert line3 == "line3", f"Expected 'line3', got {repr(line3)}"

    @pytest.mark.asyncio
    async def test_read_zero_returns_empty_string(self, temp_file):
        """Test that read(0) returns empty string, not buffered text."""
        test_text = "Hello, World! This is a test."

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_text)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            first_part = await f.read(5)
            assert first_part == "Hello"

            empty = await f.read(0)
            assert empty == "", f"read(0) should return '', got {repr(empty)}"

            rest = await f.read()
            assert rest == ", World! This is a test.", (
                f"Buffer was drained! Got {repr(rest)}"
            )

    @pytest.mark.asyncio
    async def test_read_zero_binary_returns_empty_bytes(self, temp_file):
        """Test that binary read(0) returns empty bytes."""
        test_data = b"Hello, World! This is a test."

        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(test_data)

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            first_part = await f.read(5)
            assert first_part == b"Hello"

            empty = await f.read(0)
            assert empty == b"", f"read(0) should return b'', got {repr(empty)}"

            rest = await f.read()
            assert rest == b", World! This is a test."
