# pyrefly: ignore
# pyrefly: disable=all
import gzip

import pytest

from aiogzip import AsyncGzipBinaryFile


class TestInterop:
    """Stdlib gzip interoperability and compatibility tests."""

    @pytest.mark.asyncio
    async def test_multi_member_empty_member(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"first part")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            pass

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"third part")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"first partthird part"

    @pytest.mark.asyncio
    async def test_multi_member_many_members(self, temp_file):
        for i in range(10):
            async with AsyncGzipBinaryFile(temp_file, "ab" if i > 0 else "wb") as f:
                await f.write(f"part{i}".encode())

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        expected = b"".join(f"part{i}".encode() for i in range(10))
        assert data == expected

    @pytest.mark.asyncio
    async def test_multi_member_partial_read(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.write(b"AAAA")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"BBBB")

        async with AsyncGzipBinaryFile(temp_file, "ab") as f:
            await f.write(b"CCCC")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            part1 = await f.read(6)
            part2 = await f.read(6)
            part3 = await f.read()

        assert part1 + part2 + part3 == b"AAAABBBBCCCC"

    @pytest.mark.asyncio
    async def test_multi_member_unused_data_handling(self, temp_file):
        with gzip.open(temp_file, "wb") as f:
            f.write(b"member1")

        with gzip.open(temp_file, "ab") as f:
            f.write(b"member2")

        with gzip.open(temp_file, "ab") as f:
            f.write(b"member3")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            data = await f.read()

        assert data == b"member1member2member3"

    @pytest.mark.asyncio
    async def test_trailing_zero_padding_is_ignored(self, temp_file):
        with gzip.open(temp_file, "wb") as f:
            f.write(b"payload")

        with open(temp_file, "ab") as raw:
            raw.write(b"\x00" * 32)

        with gzip.open(temp_file, "rb") as f:
            assert f.read() == b"payload"

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.read() == b"payload"

    @pytest.mark.asyncio
    async def test_binary_mtime_matches_header_after_read(self, temp_file):
        with gzip.GzipFile(temp_file, "wb", mtime=123456789) as f:
            f.write(b"payload")

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert f.mtime is None
            assert await f.read(1) == b"p"
            assert f.mtime == 123456789

    @pytest.mark.asyncio
    async def test_binary_readline_readlines_and_writelines(self, temp_file):
        async with AsyncGzipBinaryFile(temp_file, "wb") as f:
            await f.writelines([b"line1\n", b"line2\n", b"line3"])

        async with AsyncGzipBinaryFile(temp_file, "rb") as f:
            assert await f.readline() == b"line1\n"
            assert await f.readline(limit=3) == b"lin"
            assert await f.readline() == b"e2\n"
            assert await f.readlines() == [b"line3"]
            assert await f.readline() == b""
