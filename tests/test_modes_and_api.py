# pyrefly: ignore
# pyrefly: disable=all
import os

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestModeParsingErrors:
    """Tests for invalid mode string parsing in _parse_mode_tokens."""

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
        with pytest.raises(expected_error, match=match_regex):
            AsyncGzipBinaryFile("dummy.gz", mode=invalid_mode)  # type: ignore[arg-type]


class TestNewAPIMethods:
    """Test new API methods: flush() and readline()."""

    @pytest.mark.asyncio
    async def test_binary_flush_method(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"Hello")
            await f.flush()
            await f.write(b" World")
            await f.flush()

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()
            assert data == b"Hello World"

    @pytest.mark.asyncio
    async def test_text_flush_method(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello")
            await f.flush()
            await f.write(" World")
            await f.flush()

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read()
            assert data == "Hello World"

    @pytest.mark.asyncio
    async def test_flush_on_closed_file_raises(self, temp_file):
        f = AsyncGzipBinaryFile(temp_file, "wb")
        async with f:
            await f.write(b"test")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.flush()

    @pytest.mark.asyncio
    async def test_flush_in_read_mode_is_noop(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"test data")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            await f.flush()
            data = await f.read()
            assert data == b"test data"

    @pytest.mark.asyncio
    async def test_readline_basic(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line 1\nLine 2\nLine 3")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line1 = await f.readline()
            assert line1 == "Line 1\n"

            line2 = await f.readline()
            assert line2 == "Line 2\n"

            line3 = await f.readline()
            assert line3 == "Line 3"

            eof = await f.readline()
            assert eof == ""

    @pytest.mark.asyncio
    async def test_readline_empty_file(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            pass

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line = await f.readline()
            assert line == ""

    @pytest.mark.asyncio
    async def test_readline_single_line(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Single line\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line = await f.readline()
            assert line == "Single line\n"
            eof = await f.readline()
            assert eof == ""

    @pytest.mark.asyncio
    async def test_readline_vs_iteration(self, temp_file):
        test_data = "Line 1\nLine 2\nLine 3\n"

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write(test_data)

        lines_readline = []
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            while True:
                line = await f.readline()
                if not line:
                    break
                lines_readline.append(line)

        lines_iter = []
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            async for line in f:
                lines_iter.append(line)

        assert lines_readline == lines_iter

    @pytest.mark.asyncio
    async def test_readline_in_write_mode_raises(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            with pytest.raises(IOError, match="File not open for reading"):
                await f.readline()

    @pytest.mark.asyncio
    async def test_readline_on_closed_file_raises(self, temp_file):
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.readline()

    @pytest.mark.asyncio
    async def test_readline_large_lines(self, temp_file):
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
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello World\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            part1 = await f.readline(5)
            assert part1 == "Hello"
            part2 = await f.readline()
            assert part2 == " World\n"
            eof = await f.readline()
            assert eof == ""

    @pytest.mark.asyncio
    async def test_readline_limit_at_newline(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("abc\ndef\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line1 = await f.readline(4)
            assert line1 == "abc\n"
            line2 = await f.readline()
            assert line2 == "def\n"

    @pytest.mark.asyncio
    async def test_readline_limit_before_newline(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("abcdef\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            part1 = await f.readline(3)
            assert part1 == "abc"
            part2 = await f.readline(3)
            assert part2 == "def"
            part3 = await f.readline()
            assert part3 == "\n"

    @pytest.mark.asyncio
    async def test_readline_limit_larger_than_line(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("short\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            line = await f.readline(100)
            assert line == "short\n"

    @pytest.mark.asyncio
    async def test_readline_limit_zero(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            result = await f.readline(0)
            assert result == ""
            line = await f.readline()
            assert line == "Hello\n"

    @pytest.mark.asyncio
    async def test_readline_limit_on_file_without_newline(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Hello World")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            part1 = await f.readline(5)
            assert part1 == "Hello"
            part2 = await f.readline()
            assert part2 == " World"
            eof = await f.readline()
            assert eof == ""

    @pytest.mark.asyncio
    async def test_readline_limit_multiple_lines(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line1\nLine2\nLine3\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            assert await f.readline(3) == "Lin"
            assert await f.readline(3) == "e1\n"
            assert await f.readline(10) == "Line2\n"
            assert await f.readline() == "Line3\n"

    @pytest.mark.asyncio
    async def test_readlines_basic(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line 1\nLine 2\nLine 3\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines()
            assert lines == ["Line 1\n", "Line 2\n", "Line 3\n"]

    @pytest.mark.asyncio
    async def test_readlines_no_trailing_newline(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("Line 1\nLine 2\nLine 3")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines()
            assert lines == ["Line 1\n", "Line 2\n", "Line 3"]

    @pytest.mark.asyncio
    async def test_readlines_empty_file(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            pass

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines()
            assert lines == []

    @pytest.mark.asyncio
    async def test_readlines_with_hint(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            for i in range(100):
                await f.write(f"Line {i}\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            lines = await f.readlines(50)
            assert len(lines) > 0
            assert len(lines) < 100
            total_chars = sum(len(line) for line in lines)
            assert total_chars >= 50

    @pytest.mark.asyncio
    async def test_readlines_in_write_mode_raises(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            with pytest.raises(OSError, match="File not open for reading"):
                await f.readlines()

    @pytest.mark.asyncio
    async def test_readlines_on_closed_file_raises(self, temp_file):
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.readlines()

    @pytest.mark.asyncio
    async def test_writelines_basic(self, temp_file):
        lines = ["Line 1\n", "Line 2\n", "Line 3\n"]

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines(lines)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            result = await f.readlines()
            assert result == lines

    @pytest.mark.asyncio
    async def test_writelines_generator(self, temp_file):
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
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines([])

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            content = await f.read()
            assert content == ""

    @pytest.mark.asyncio
    async def test_writelines_no_newlines(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines(["a", "b", "c"])

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            content = await f.read()
            assert content == "abc"

    @pytest.mark.asyncio
    async def test_writelines_in_read_mode_raises(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("test")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            with pytest.raises(OSError, match="File not open for writing"):
                await f.writelines(["line"])

    @pytest.mark.asyncio
    async def test_writelines_on_closed_file_raises(self, temp_file):
        f = AsyncGzipTextFile(temp_file, "wt")
        async with f:
            await f.write("test")

        with pytest.raises(ValueError, match="I/O operation on closed file"):
            await f.writelines(["line"])

    @pytest.mark.asyncio
    async def test_readlines_writelines_roundtrip(self, temp_file):
        original_lines = ["First line\n", "Second line\n", "Third line without newline"]

        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.writelines(original_lines)

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            read_lines = await f.readlines()

        temp_file2 = temp_file + ".copy"
        try:
            async with AsyncGzipTextFile(temp_file2, "wt") as f:
                await f.writelines(read_lines)

            async with AsyncGzipTextFile(temp_file2, "rt") as f:
                final_lines = await f.readlines()

            assert final_lines == original_lines
        finally:
            if os.path.exists(temp_file2):
                os.unlink(temp_file2)
