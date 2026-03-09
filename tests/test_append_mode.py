# pyrefly: ignore
# pyrefly: disable=all
import gzip

import pytest

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile


class TestAppendMode:
    """Test append mode operations and limitations."""

    @pytest.mark.asyncio
    async def test_append_mode_binary(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"first write")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"second write")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"first writesecond write"

    @pytest.mark.asyncio
    async def test_append_mode_text(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("first line\n")

        async with AsyncGzipTextFile(temp_file, "at") as f:
            await f.write("second line\n")

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            data = await f.read()

        assert data == "first line\nsecond line\n"

    @pytest.mark.asyncio
    async def test_append_mode_multiple_appends(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"part1")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"part2")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"part3")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"part1part2part3"

    @pytest.mark.asyncio
    async def test_append_to_empty_file(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"appended data")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"appended data"

    @pytest.mark.asyncio
    async def test_append_mode_interoperability_with_gzip(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"async write")

        with gzip.open(temp_file, "ab") as f:
            f.write(b" gzip append")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"async write gzip append"

    @pytest.mark.asyncio
    async def test_cannot_read_in_append_mode(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            with pytest.raises(IOError, match="File not open for reading"):
                await f.read()

    @pytest.mark.asyncio
    async def test_append_mode_with_line_iteration(self, temp_file):
        async with AsyncGzipTextFile(temp_file, "wt") as f:
            await f.write("line1\nline2\n")

        async with AsyncGzipTextFile(temp_file, "at") as f:
            await f.write("line3\nline4\n")

        lines = []
        async with AsyncGzipTextFile(temp_file, "rt") as f:
            async for line in f:
                lines.append(line)

        assert lines == ["line1\n", "line2\n", "line3\n", "line4\n"]
