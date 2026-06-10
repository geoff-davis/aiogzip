"""Forward plain-offset seek fast path in AsyncGzipTextFile.

_seek_to_plain_position replays only the forward delta when the stream is
already at a plain position at/behind the target, instead of restarting the
decode from byte 0. These tests assert that the fast path lands at the same
position and yields the same subsequent read() output and ``newlines`` property
as a genuine replay-from-zero (the reset fallback), including a CRLF that
straddles the seek target and multi-byte UTF-8 around the target.
"""

import gzip
from unittest.mock import patch

import pytest

from aiogzip import AsyncGzipTextFile


def _write_raw(path, raw):
    """Write exact decompressed bytes so byte offsets are under our control."""
    with gzip.open(path, "wb") as f:
        f.write(raw)


async def _stepped_forward(path, p1, p2, **kwargs):
    """Reach a plain position at p1, then forward-seek to p2 (fast path)."""
    async with AsyncGzipTextFile(path, "rt", **kwargs) as f:
        await f.seek(p1)
        # tell() == p1 confirms p1 is a plain position, so the subsequent
        # forward seek exercises the fast path rather than falling back.
        staged_plain = (await f.tell()) == p1
        ret = await f.seek(p2)
        newlines = f.newlines
        rest = await f.read()
        return ret, newlines, rest, staged_plain


async def _replay_from_zero(path, p2, **kwargs):
    """Reference: force the reset path by seeking after draining to EOF."""
    async with AsyncGzipTextFile(path, "rt", **kwargs) as f:
        await f.read()  # drain to EOF so _eof is set -> fast path is bypassed
        ret = await f.seek(p2)
        newlines = f.newlines
        rest = await f.read()
        return ret, newlines, rest


async def _assert_matches(path, p1, p2, **kwargs):
    fast_ret, fast_nl, fast_rest, staged_plain = await _stepped_forward(
        path, p1, p2, **kwargs
    )
    ref_ret, ref_nl, ref_rest = await _replay_from_zero(path, p2, **kwargs)

    assert staged_plain, "p1 was not a plain position; fast path not exercised"
    assert fast_ret == ref_ret == p2
    assert fast_rest == ref_rest
    assert fast_nl == ref_nl
    return fast_rest, fast_nl


def _line_offsets(lines):
    """Return cumulative byte offsets at the start of each line."""
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets


@pytest.mark.asyncio
async def test_forward_plain_seek_lf(temp_file):
    """Forward seek between LF line boundaries matches replay-from-zero."""
    lines = [b"row%d\n" % i for i in range(200)]
    raw = b"".join(lines)
    _write_raw(temp_file, raw)
    offsets = _line_offsets(lines)

    p1, p2 = offsets[50], offsets[120]
    rest, nl = await _assert_matches(temp_file, p1, p2)
    # Sanity: the tail decodes from p2 onward.
    assert rest == raw[p2:].decode("utf-8")
    assert nl == "\n"


@pytest.mark.asyncio
async def test_forward_plain_seek_to_clean_crlf_boundary(temp_file):
    """Forward seek landing exactly on a CRLF boundary stays plain."""
    lines = [b"item%d\r\n" % i for i in range(100)]
    raw = b"".join(lines)
    _write_raw(temp_file, raw)
    offsets = _line_offsets(lines)

    p1, p2 = offsets[10], offsets[40]
    rest, nl = await _assert_matches(temp_file, p1, p2)
    assert rest == raw[p2:].decode("utf-8").replace("\r\n", "\n")
    assert nl == "\r\n"


@pytest.mark.asyncio
async def test_forward_plain_seek_straddling_crlf(temp_file):
    """Forward seek whose target falls between \\r and \\n matches reference."""
    lines = [b"item%d\r\n" % i for i in range(100)]
    raw = b"".join(lines)
    _write_raw(temp_file, raw)
    offsets = _line_offsets(lines)

    p1 = offsets[10]
    # The \n of line 39's CRLF: [.., p2) ends with the bare \r.
    p2 = offsets[40] - 1
    assert raw[p2 - 1 : p2 + 1] == b"\r\n"

    rest, nl = await _assert_matches(temp_file, p1, p2)
    # Reading resumes at the pending-\r boundary; the \n completes the CRLF.
    assert rest == raw[p2 + 1 :].decode("utf-8").replace("\r\n", "\n")


@pytest.mark.asyncio
async def test_forward_plain_seek_around_multibyte_utf8(temp_file):
    """Forward seek near/inside multi-byte UTF-8 sequences matches reference."""
    unit = "héllo wörld 日本語\n"
    raw = (unit * 50).encode("utf-8")
    _write_raw(temp_file, raw)
    unit_len = len(unit.encode("utf-8"))

    # Byte offset of "日" within a unit (a 3-byte sequence).
    ni_byte = len(unit[: unit.index("日")].encode("utf-8"))

    p1 = unit_len * 5  # clean unit boundary
    # Target inside the 3-byte "日": one byte past its start.
    p2 = unit_len * 20 + ni_byte + 1
    await _assert_matches(temp_file, p1, p2, encoding="utf-8")

    # Also target exactly after a multi-byte char (clean boundary).
    p2_clean = unit_len * 20 + ni_byte + 3
    await _assert_matches(temp_file, p1, p2_clean, encoding="utf-8")


@pytest.mark.asyncio
async def test_forward_plain_seek_no_translation_newline_mode(temp_file):
    r"""With newline='' the fast path preserves seen-newline tracking."""
    lines = [b"a%d\r\nb%d\rc%d\n" % (i, i, i) for i in range(50)]
    raw = b"".join(lines)
    _write_raw(temp_file, raw)
    offsets = _line_offsets(lines)

    p1, p2 = offsets[5], offsets[30]
    fast = await _stepped_forward(temp_file, p1, p2, newline="")
    ref = await _replay_from_zero(temp_file, p2, newline="")
    assert fast[3], "p1 not plain"
    assert fast[0] == ref[0] == p2
    assert fast[2] == ref[2]  # rest, untranslated
    assert fast[1] == ref[1]  # newlines property
    assert set(fast[1]) == {"\r", "\n", "\r\n"}


@pytest.mark.asyncio
async def test_forward_plain_seek_skips_reset_backward_does_not(temp_file):
    """The forward fast path avoids _reset_to_start; a backward seek uses it."""
    lines = [b"row%d\n" % i for i in range(200)]
    raw = b"".join(lines)
    _write_raw(temp_file, raw)
    offsets = _line_offsets(lines)
    p1, p2 = offsets[50], offsets[120]

    orig_reset = AsyncGzipTextFile._reset_to_start
    with patch.object(
        AsyncGzipTextFile, "_reset_to_start", autospec=True
    ) as mock_reset:

        async def _call_through(self):
            return await orig_reset(self)

        mock_reset.side_effect = _call_through

        async with AsyncGzipTextFile(temp_file, "rt") as f:
            await f.seek(p1)
            assert (await f.tell()) == p1
            calls_before = mock_reset.call_count

            await f.seek(p2)  # forward from a plain position -> no reset
            assert mock_reset.call_count == calls_before

            await f.seek(p1)  # backward -> must reset and replay from zero
            assert mock_reset.call_count == calls_before + 1
            assert (await f.tell()) == p1


@pytest.mark.asyncio
async def test_forward_seek_after_direct_buffer_read_replays_from_zero(temp_file):
    """Bytes consumed via the public binary `buffer` accessor bypass the text
    decoder, so the live decoder state no longer matches the binary position.

    Regression: the fast path spliced the decoder onto the advanced binary
    position and resumed decoding mid-character (UnicodeDecodeError for
    strict encodings, silent corruption for tolerant ones). It must fall
    back to replay-from-zero instead.
    """
    raw = ("☃" * 100).encode("utf-8")  # 3 bytes per snowman
    _write_raw(temp_file, raw)

    async with AsyncGzipTextFile(temp_file, "rt", chunk_size=64) as f:
        # Consume one byte behind the decoder's back, stopping mid-character.
        assert await f.buffer.read(1) == raw[:1]
        # Seek to a character boundary: must decode cleanly from there.
        assert await f.seek(3) == 3
        assert await f.read() == "☃" * 99


@pytest.mark.asyncio
async def test_fast_path_still_used_after_pure_text_seeks(temp_file):
    """Sanity: the decoder-frontier gate does not disable the fast path for
    the supported pattern (plain seeks/tells with no direct buffer reads)."""
    raw = b"".join(b"row%d\n" % i for i in range(200))
    _write_raw(temp_file, raw)

    async with AsyncGzipTextFile(temp_file, "rt") as f:
        await f.seek(6)
        with patch.object(
            AsyncGzipTextFile, "_reset_to_start", side_effect=AssertionError
        ):
            await f.seek(12)
        # Offset 12 is two bytes into "row2\n".
        assert await f.read(6) == "w2\nrow"
