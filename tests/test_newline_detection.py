"""Newline-type tracking (the ``newlines`` property) is chunk-size independent.

Regression tests for a bug where ``_apply_newline_decoding`` mis-counted the
``\\r`` and ``\\n`` of a ``\\r\\n`` pair as a bare CR and a bare LF once the CRLF
type had already been recorded — so a pure-CRLF file read across multiple chunks
wrongly reported ``('\\r', '\\n', '\\r\\n')`` instead of ``'\\r\\n'``. The result
must match the stdlib ``io.TextIOWrapper`` for every chunk size.
"""

import gzip
import io

import pytest

from aiogzip import AsyncGzipTextFile

CHUNK_SIZES = [1, 2, 3, 7, 16, 64, 1 << 20]


# Raw decompressed payloads exercising every newline combination, with the
# patterns repeated enough to span many chunk boundaries at small chunk sizes.
def _payloads():
    return {
        "crlf_only": b"".join(b"item%d\r\n" % i for i in range(60)),
        "lf_only": b"".join(b"row%d\n" % i for i in range(60)),
        "cr_only": b"".join(b"row%d\r" % i for i in range(60)),
        "lf_and_crlf": b"".join(b"a%d\nb%d\r\n" % (i, i) for i in range(60)),
        "cr_and_crlf": b"".join(b"a%d\rb%d\r\n" % (i, i) for i in range(60)),
        "all_three": b"".join(b"a%d\nb%d\rc%d\r\n" % (i, i, i) for i in range(60)),
        # Adjacent terminators stress split handling across boundaries.
        "adjacent": b"\r\n\n\r\r\n\n\r\n\r" * 30,
    }


def _stdlib_newlines(raw):
    wrapper = io.TextIOWrapper(io.BytesIO(raw))
    wrapper.read()
    return wrapper.newlines


def _normalize(newlines):
    if newlines is None:
        return frozenset()
    if isinstance(newlines, str):
        return frozenset([newlines])
    return frozenset(newlines)


def _write(path, raw):
    with gzip.open(path, "wb") as f:
        f.write(raw)


class CountingText(str):
    """Track count scans and membership probes in the newline hot path."""

    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.counted = []
        instance.probed = []
        return instance

    def count(self, sub, *args):
        self.counted.append(sub)
        return super().count(sub, *args)

    def __contains__(self, sub):
        self.probed.append(sub)
        return super().__contains__(sub)


@pytest.mark.parametrize("newline", [None, ""])
def test_lf_only_chunk_probes_without_counting_and_tracks_newline(newline):
    stream = AsyncGzipTextFile("unused.gz", "rt", newline=newline)
    text = CountingText("first\nsecond\n")

    assert stream._apply_newline_decoding(text) is text
    # LF-only text takes the early-exit membership probes and never pays a
    # full counting scan.
    assert text.counted == []
    assert text.probed == ["\r", "\n"]
    assert stream.newlines == "\n"


def test_lf_only_chunks_stay_count_free_after_lf_is_known():
    stream = AsyncGzipTextFile("unused.gz", "rt", newline=None)
    first = CountingText("first\n")
    second = CountingText("second\n")

    assert stream._apply_newline_decoding(first) is first
    assert stream._apply_newline_decoding(second) is second
    assert first.counted == []
    assert first.probed == ["\r", "\n"]
    # Once LF is recorded, later LF-only chunks pay only the single CR probe.
    assert second.counted == []
    assert second.probed == ["\r"]
    assert stream.newlines == "\n"


def test_mixed_chunk_probes_then_counts():
    stream = AsyncGzipTextFile("unused.gz", "rt", newline=None)
    text = CountingText("first\r\nsecond\rthird\n")

    assert stream._apply_newline_decoding(text) == "first\nsecond\nthird\n"
    # The CR probe exits at the first hit, then the three counting scans
    # classify the mix; translation re-probes CR before rewriting.
    assert text.counted == ["\r\n", "\n", "\r"]
    assert text.probed == ["\r", "\r"]
    assert stream.newlines == ("\r", "\n", "\r\n")


@pytest.mark.parametrize("name", list(_payloads()))
@pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
@pytest.mark.asyncio
async def test_newlines_match_stdlib_via_read(temp_file, name, chunk_size):
    raw = _payloads()[name]
    _write(temp_file, raw)
    expected = _normalize(_stdlib_newlines(raw))

    async with AsyncGzipTextFile(temp_file, "rt", chunk_size=chunk_size) as f:
        await f.read()
        assert _normalize(f.newlines) == expected


@pytest.mark.parametrize("name", list(_payloads()))
@pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
@pytest.mark.asyncio
async def test_newlines_match_stdlib_via_iteration(temp_file, name, chunk_size):
    raw = _payloads()[name]
    _write(temp_file, raw)
    expected = _normalize(_stdlib_newlines(raw))

    async with AsyncGzipTextFile(temp_file, "rt", chunk_size=chunk_size) as f:
        async for _ in f:
            pass
        assert _normalize(f.newlines) == expected


@pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
@pytest.mark.asyncio
async def test_pure_crlf_never_reports_bare_terminators(temp_file, chunk_size):
    """The original bug: a pure-CRLF file must report only '\\r\\n'."""
    raw = b"".join(b"line%d\r\n" % i for i in range(100))
    _write(temp_file, raw)

    async with AsyncGzipTextFile(temp_file, "rt", chunk_size=chunk_size) as f:
        await f.read()
        assert f.newlines == "\r\n"
