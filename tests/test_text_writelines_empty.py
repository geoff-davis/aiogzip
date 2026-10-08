"""R08: text ``writelines()`` stays bounded however many empty strings arrive.

Empty strings used to be stored in the pending batch, whose flush threshold
counts characters only, so a long run of them grew the batch list with the
input count. They are now recorded by a flag instead. The batches written,
and therefore the encoder calls (an empty write still emits a UTF-16/32 BOM),
must be exactly those the stored-empty-string algorithm produced.
"""

from __future__ import annotations

import gzip
import sys
from contextlib import contextmanager

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aiogzip import AsyncGzipTextFile

CHUNK = 8


def _reference_batches(lines, chunk_size):
    """The batches the b2 algorithm (empty strings stored) wrote, in order."""
    batches = []
    pending = []
    pending_chars = 0
    for line in lines:
        length = len(line)
        if length >= chunk_size:
            if pending:
                batches.append("".join(pending))
                pending = []
                pending_chars = 0
            batches.append(line)
        else:
            if pending and pending_chars + length > chunk_size:
                batches.append("".join(pending))
                pending = []
                pending_chars = 0
            pending.append(line)
            pending_chars += length
    if pending:
        batches.append("".join(pending))
    return batches


@contextmanager
def _recorded_batches():
    """Record every batch text ``writelines()`` hands to the encoder path."""
    batches = []
    original = AsyncGzipTextFile._write_batch_reserved

    async def recording(self, data):
        batches.append(data)
        return await original(self, data)

    AsyncGzipTextFile._write_batch_reserved = recording  # type: ignore[method-assign]
    try:
        yield batches
    finally:
        AsyncGzipTextFile._write_batch_reserved = original  # type: ignore[method-assign]


def _pending_sizes(lines, sizes):
    """Yield ``lines`` and record writelines' pending-list size before each."""
    for line in lines:
        caller = sys._getframe(1)
        assert caller.f_code.co_name == "writelines"
        sizes.append(len(caller.f_locals["pending"]))
        yield line
    sizes.append(len(sys._getframe(1).f_locals["pending"]))


MIXED = [
    [],
    [""],
    ["", "", ""],
    ["a", "", "b", "", ""],
    ["", "x" * CHUNK, ""],
    ["", "", "x" * (CHUNK + 3)],
    ["abc", "", "defgh", "", "ij", ""],
    ["abcdefg", "", "h", "", "i"],
    ["", "a\n", "", "b\n"],
    ["x" * CHUNK, "", "", "x" * CHUNK],
]


class TestWritelinesEmptyInputs:
    @pytest.mark.parametrize("lines", MIXED)
    async def test_batches_match_the_stored_empty_algorithm(self, tmp_path, lines):
        path = tmp_path / "out.gz"
        with _recorded_batches() as batches:
            async with AsyncGzipTextFile(path, "wt", chunk_size=CHUNK, newline="") as f:
                await f.writelines(lines)
        assert batches == _reference_batches(lines, CHUNK)
        assert gzip.decompress(path.read_bytes()).decode() == "".join(lines)

    @settings(max_examples=200, deadline=None)
    @given(
        st.lists(
            st.one_of(st.just(""), st.text(alphabet="ab\n", max_size=2 * CHUNK)),
            max_size=30,
        )
    )
    async def test_batches_match_for_generated_inputs(self, tmp_path_factory, lines):
        path = tmp_path_factory.mktemp("wl") / "out.gz"
        with _recorded_batches() as batches:
            async with AsyncGzipTextFile(path, "wt", chunk_size=CHUNK, newline="") as f:
                await f.writelines(lines)
        assert batches == _reference_batches(lines, CHUNK)
        assert gzip.decompress(path.read_bytes()).decode() == "".join(lines)

    async def test_a_long_empty_run_stores_nothing(self, tmp_path):
        path = tmp_path / "out.gz"
        sizes: list[int] = []
        with _recorded_batches() as batches:
            async with AsyncGzipTextFile(path, "wt", chunk_size=CHUNK) as f:
                await f.writelines(_pending_sizes([""] * 200_000, sizes))
        assert max(sizes) == 0
        assert batches == [""]
        assert gzip.decompress(path.read_bytes()) == b""

    async def test_pending_items_are_bounded_by_the_chunk_size(self, tmp_path):
        # Each stored string is non-empty, so a batch holds at most chunk_size
        # strings, whatever the empty strings between them.
        lines = ["", "a", "", ""] * 5_000
        path = tmp_path / "out.gz"
        sizes: list[int] = []
        with _recorded_batches() as batches:
            async with AsyncGzipTextFile(path, "wt", chunk_size=CHUNK, newline="") as f:
                await f.writelines(_pending_sizes(lines, sizes))
        assert max(sizes) <= CHUNK
        assert batches == _reference_batches(lines, CHUNK)
        assert gzip.decompress(path.read_bytes()) == b"a" * 5_000

    @pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "utf-8-sig"])
    @pytest.mark.parametrize("count", [1, 3, 10_000])
    async def test_an_empty_only_run_writes_the_bom_once(
        self, tmp_path, encoding, count
    ):
        path = tmp_path / "out.gz"
        async with AsyncGzipTextFile(path, "wt", encoding=encoding) as f:
            await f.writelines([""] * count)
        assert gzip.decompress(path.read_bytes()) == "".encode(encoding)
        assert gzip.decompress(path.read_bytes()) != b""

    @pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
    async def test_empty_then_text_round_trips(self, tmp_path, encoding):
        lines = ["", "", "héllo\n", "", "wörld\n", ""]
        path = tmp_path / "out.gz"
        async with AsyncGzipTextFile(
            path, "wt", encoding=encoding, chunk_size=CHUNK, newline=""
        ) as f:
            await f.writelines(lines)
        assert gzip.decompress(path.read_bytes()) == "".join(lines).encode(encoding)

    @pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
    async def test_iterator_failure_after_empties_writes_the_batch(
        self, tmp_path, encoding
    ):
        def failing():
            yield ""
            yield ""
            raise RuntimeError("source failed")

        path = tmp_path / "out.gz"
        with _recorded_batches() as batches:
            async with AsyncGzipTextFile(path, "wt", encoding=encoding) as f:
                with pytest.raises(RuntimeError, match="source failed"):
                    await f.writelines(failing())
        assert batches == [""]
        assert gzip.decompress(path.read_bytes()) == "".encode(encoding)

    async def test_iterator_failure_after_mixed_input_keeps_the_text(self, tmp_path):
        def failing():
            yield "ab"
            yield ""
            yield "cd"
            raise RuntimeError("source failed")

        path = tmp_path / "out.gz"
        with _recorded_batches() as batches:
            async with AsyncGzipTextFile(path, "wt", chunk_size=CHUNK, newline="") as f:
                with pytest.raises(RuntimeError, match="source failed"):
                    await f.writelines(failing())
        assert batches == ["abcd"]
        assert gzip.decompress(path.read_bytes()) == b"abcd"

    async def test_a_non_string_after_empties_flushes_then_refuses(self, tmp_path):
        path = tmp_path / "out.gz"
        with _recorded_batches() as batches:
            async with AsyncGzipTextFile(path, "wt", encoding="utf-16") as f:
                with pytest.raises(TypeError, match="must be str"):
                    await f.writelines(["", "", b"bytes"])  # type: ignore[list-item]
        assert batches == ["", b"bytes"]
        assert gzip.decompress(path.read_bytes()) == "".encode("utf-16")
