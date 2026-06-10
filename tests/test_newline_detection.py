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
