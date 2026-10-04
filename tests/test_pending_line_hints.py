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

    pair = ["x" * 1023 + "\n", "\n"]
    expected = pair * (AsyncGzipTextFile._LINE_BATCH_CHARS // sum(map(len, pair)))
    assert sum(map(len, expected)) <= AsyncGzipTextFile._LINE_BATCH_CHARS
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


@pytest.mark.parametrize("hint", [1, 8192, 1 << 20])
@pytest.mark.parametrize("newline", [None, "\n", "\r"])
async def test_pending_hints_salvage_complete_lines_before_partial_tail(
    tmp_path, hint, newline
):
    term = newline or "\n"
    lines = ["αβ" + term] * 1000
    tail = "unterminated α"
    corrupt = bytearray(gzip.compress(("".join(lines) + tail).encode(), mtime=0))
    corrupt[-8] ^= 1
    path = tmp_path / "corrupt.gz"
    path.write_bytes(corrupt)
    async with AsyncGzipTextFile(path, "rt", newline=newline) as reader:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await reader.read()
        recovered = []
        while len(recovered) < len(lines):
            batch = await reader.readlines(hint)
            assert batch
            recovered.extend(batch)
        assert recovered == lines
        with pytest.raises(OSError, match="broken"):
            await reader.readlines(hint)
        assert await reader.read() == tail


@pytest.mark.parametrize("newline", [None, "\n", "\r"])
async def test_large_chunk_retains_bulk_transfer(tmp_path, newline):
    class Batch(list):
        copied = 0

        def __getitem__(self, key):
            result = super().__getitem__(key)
            if isinstance(key, slice):
                self.copied += len(result)
            return result

    term = newline or "\n"
    line = "αβ" * 16 + term
    path = tmp_path / "large-chunk.gz"
    path.write_bytes(gzip.compress((line * 200000).encode(), mtime=0))
    async with AsyncGzipTextFile(
        path, "rt", newline=newline, chunk_size=4 << 20
    ) as reader:
        assert await reader.readline() == line
        assert await reader.readline() == line
        pending = Batch(reader._pending_lines)
        reader._pending_lines = pending
        assert len(reader._text_buffer) - reader._text_buffer_offset > 1 << 20
        remaining = len(pending) - reader._pending_idx
        assert remaining > 1
        batch = await reader.readlines(1 << 20)
        assert batch == [line] * (((1 << 20) + len(line) - 1) // len(line))
        # The first pending batch must use bulk transfer even though the
        # decoded buffer exceeds the hint. Timing is not part of this test.
        assert pending.copied == remaining


@pytest.mark.parametrize("newline", [None, "\n", "\r"])
@pytest.mark.parametrize("long_first_line", [False, True])
async def test_refill_window_bounds_live_pending_lines(
    tmp_path, monkeypatch, newline, long_first_line
):
    term = newline or "\n"
    line = "αβ" + term
    first = "x" * (AsyncGzipTextFile._LINE_BATCH_CHARS + 1) + term
    text = line + (first if long_first_line else "") + line * 100000
    path = tmp_path / "window.gz"
    path.write_bytes(gzip.compress(text.encode(), mtime=0))
    take = AsyncGzipTextFile._take_first_refilled_line
    checked = 0
    overlong = 0

    def checked_take(reader):
        nonlocal checked, overlong
        result = take(reader)
        if len(result) > reader._LINE_BATCH_CHARS:
            overlong += 1
            assert len(reader._pending_lines) == reader._pending_idx == 1
        pending = "".join(reader._pending_lines[reader._pending_idx :])
        assert len(pending) <= reader._LINE_BATCH_CHARS
        assert reader._text_buffer[reader._text_buffer_offset :].startswith(pending)
        checked += 1
        return result

    monkeypatch.setattr(AsyncGzipTextFile, "_take_first_refilled_line", checked_take)
    async with AsyncGzipTextFile(
        path, "rt", newline=newline, chunk_size=4 << 20
    ) as reader:
        output = []
        async for batch in reader.iter_batches():
            output.extend(batch)
        assert "".join(output) == text
    assert checked > 0
    assert overlong == int(long_first_line)
