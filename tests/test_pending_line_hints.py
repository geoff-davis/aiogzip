"""Public hint boundaries while draining and refilling pending text lines."""

import gzip

import pytest

from aiogzip import AsyncGzipTextFile


@pytest.mark.parametrize("hint", [-1, 0, 1, 2, 3, 17, 4096])
@pytest.mark.parametrize("newline", [None, "", "\n", "\r", "\r\n"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
async def test_pending_hints_match_whole_line_boundaries(
    tmp_path, hint, newline, encoding
):
    terminator = newline or "\n"
    expected = [terminator, "α" * 19 + terminator, "β" + terminator] * 80
    expected.append("unterminated α")
    path = tmp_path / "hints.gz"
    text = "".join(expected)
    if newline is None:
        parts = text.split("\n")
        text = (
            "".join(
                part + ("\r", "\r\n", "\n")[i % 3] for i, part in enumerate(parts[:-1])
            )
            + parts[-1]
        )
    path.write_bytes(gzip.compress(text.encode(encoding), mtime=0))
    async with AsyncGzipTextFile(
        path, "rt", newline=newline, encoding=encoding, chunk_size=128
    ) as reader:
        offset = 0
        while offset < len(expected):
            end = offset
            size = 0
            while end < len(expected):
                size += len(expected[end])
                end += 1
                if hint > 0 and size >= hint:
                    break
            assert await reader.readlines(hint) == expected[offset:end]
            offset = end
        assert await reader.readlines(hint) == []


@pytest.mark.parametrize("hint", [1, 256, 8192, 65536, 1 << 20, -1])
async def test_pending_work_is_linear_even_with_long_lines(tmp_path, hint):
    # Charge every line-length inspection, indexed visit, sliced element, and
    # returned element. At most six units per input line plus two per call;
    # repeated whole-suffix scans fail this bound even if no slices are made.
    work = 0

    class Line(str):
        def __len__(self):
            nonlocal work
            work += 1
            return super().__len__()

    class Batch(list):
        def __getitem__(self, key):
            nonlocal work
            result = super().__getitem__(key)
            work += len(result) if isinstance(key, slice) else 1
            return result

    expected = ["x" * 1023 + "\n", "\n"] * 1024
    path = tmp_path / "work.gz"
    path.write_bytes(gzip.compress(b"", mtime=0))
    async with AsyncGzipTextFile(path, "rt", newline="\n") as reader:
        # Supply a coherent pre-split batch; input construction is uncharged.
        reader._set_buffer("".join(expected))
        reader._pending_lines = Batch(map(Line, expected))
        calls = 0
        actual = []
        while len(actual) < len(expected):
            result = await reader.readlines(hint)
            assert result
            work += len(result)
            actual.extend(result)
            calls += 1
        assert actual == expected
        assert work <= 6 * len(expected) + 2 * calls


@pytest.mark.parametrize("newline", [None, "\n", "\r"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
async def test_pending_hints_interleave_with_cookie_replay(tmp_path, newline, encoding):
    term = newline or "\n"
    lines = [f"αβ {i:04d}" + term for i in range(1000)]
    path = tmp_path / "interleave.gz"
    path.write_bytes(gzip.compress("".join(lines).encode(encoding), mtime=0))
    async with AsyncGzipTextFile(
        path, "rt", newline=newline, encoding=encoding, chunk_size=128
    ) as reader:
        assert await reader.readlines(1) == lines[:1]
        assert await reader.readline() == lines[1]
        cookie = await reader.tell()
        assert await reader.read(2) == lines[2][:2]
        assert await reader.readline() == lines[2][2:]
        assert await anext(reader) == lines[3]
        assert await reader.readlines(1 << 20) == lines[4:]
        await reader.seek(cookie)
        assert await reader.readlines(1) == lines[2:3]
        assert await reader.readlines() == lines[3:]
