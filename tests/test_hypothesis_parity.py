"""Property-based parity tests: aiogzip vs. the stdlib gzip module.

These tests generate randomized multi-member gzip files (with NUL padding,
varied compression levels, and compressible/incompressible payloads) and assert
that ``aiogzip`` reproduces the stdlib's decompressed output byte-for-byte under
a variety of access patterns, that ``tell()`` agrees with the number of bytes
consumed, and that single-byte corruption is detected the same way by both.

The tests are plain (sync) functions that drive the async API via
``asyncio.run`` so they compose with Hypothesis. ``os.urandom`` is used for the
incompressible payloads; the exact bytes are not reproducible across Hypothesis
replays, but any random payload exercises the same code paths.
"""

import asyncio
import gzip
import io
import os
import struct
import tempfile
import zlib

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aiogzip import (
    AsyncGzipBinaryFile,
    GzipDecoder,
    decompress_chunks,
    inspect,
    verify,
)

# Modest example budgets keep CI fast while still exploring a wide space.
MAX_EXAMPLES = 200

CHUNK_SIZES = [1, 2, 3, 7, 64, 1024, 256 * 1024]

_SUPPRESSED = [
    HealthCheck.too_slow,
    HealthCheck.data_too_large,
    HealthCheck.large_base_example,
]


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #

# Highly compressible: a short token repeated to the desired length.
_compressible = st.builds(
    lambda token, n: (token * (n // len(token) + 1))[:n],
    st.binary(min_size=1, max_size=8),
    st.integers(min_value=0, max_value=10_000),
)

# Incompressible: cryptographic random bytes (forces stored/expanded blocks).
_incompressible = st.integers(min_value=0, max_value=10_000).map(os.urandom)

_payload = st.one_of(_compressible, _incompressible)

# A member is (payload, compresslevel, trailing NUL padding). The trailing pad
# lands between members (and after the final member, i.e. at EOF).
_member = st.tuples(
    _payload,
    st.integers(min_value=0, max_value=9),
    st.integers(min_value=0, max_value=64),
)

_members = st.lists(_member, min_size=1, max_size=4)

_chunk_size = st.sampled_from(CHUNK_SIZES)

_latin1_field = st.lists(
    st.integers(min_value=1, max_value=255),
    min_size=0,
    max_size=16,
).map(bytes)

_rich_member = st.tuples(
    st.binary(min_size=0, max_size=4096),
    st.integers(min_value=0, max_value=9),
    st.integers(min_value=0, max_value=16),
    st.integers(min_value=0, max_value=2**32 - 1),
    st.one_of(st.none(), st.binary(min_size=0, max_size=16)),
    st.one_of(st.none(), _latin1_field),
    st.one_of(st.none(), _latin1_field),
    st.booleans(),
)

_rich_members = st.lists(_rich_member, min_size=0, max_size=5)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _build_raw(members):
    """Encode the member spec into concatenated gzip members with NUL padding.

    Returns ``(raw, flg_offsets)``: the stream bytes plus the offset of each
    member's FLG header byte (byte 3 of the member), so the corruption test
    can scope its only allowed strictness exemption to reserved-FLG-bit flips.
    """
    out = bytearray()
    flg_offsets = []
    for payload, level, pad in members:
        buf = io.BytesIO()
        # mtime=0 keeps the header deterministic.
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=level, mtime=0) as g:
            g.write(payload)
        flg_offsets.append(len(out) + 3)
        out += buf.getvalue()
        out += b"\x00" * pad
    return bytes(out), flg_offsets


def _build_rich_raw(members):
    """Build members with every optional header field and return their layout."""
    out = bytearray()
    layouts = []
    for payload, level, pad, mtime, extra, filename, comment, header_crc in members:
        flags = 0
        if extra is not None:
            flags |= 0x04
        if filename is not None:
            flags |= 0x08
        if comment is not None:
            flags |= 0x10
        if header_crc:
            flags |= 0x02

        start = len(out)
        header = bytearray(b"\x1f\x8b\x08")
        header.append(flags)
        header.extend(struct.pack("<I", mtime))
        header.extend(b"\x00\xff")
        extra_offset = None
        if extra is not None:
            header.extend(struct.pack("<H", len(extra)))
            extra_offset = start + len(header)
            header.extend(extra)
        if filename is not None:
            header.extend(filename + b"\x00")
        if comment is not None:
            header.extend(comment + b"\x00")
        if header_crc:
            header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))

        compressor = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS)
        body = compressor.compress(payload) + compressor.flush()
        body_offset = start + len(header)
        trailer_offset = body_offset + len(body)
        trailer = struct.pack(
            "<II",
            zlib.crc32(payload) & 0xFFFFFFFF,
            len(payload) & 0xFFFFFFFF,
        )
        out.extend(header)
        out.extend(body)
        out.extend(trailer)
        member_end = len(out)
        padding_offset = member_end
        out.extend(b"\x00" * pad)
        layouts.append(
            {
                "start": start,
                "size": member_end - start,
                "body": body_offset,
                "trailer": trailer_offset,
                "extra": extra_offset,
                "padding": padding_offset,
                "flags": flags,
            }
        )
    return bytes(out), layouts


def _split_by_sizes(raw, sizes):
    parts = []
    offset = 0
    index = 0
    while offset < len(raw):
        size = sizes[index % len(sizes)]
        parts.append(raw[offset : offset + size])
        offset += size
        index += 1
    return parts


def _expected_len(members):
    """Decompressed length == sum of member payload lengths (padding is skipped)."""
    return sum(len(payload) for payload, _, _ in members)


def _write_tmp(raw):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
        f.write(raw)
        return f.name


def _run(coro):
    return asyncio.run(coro)


async def _aio_read_all(path, chunk_size):
    async with AsyncGzipBinaryFile(path, "rb", chunk_size=chunk_size) as g:
        return await g.read()


async def _async_parts(raw, split):
    for offset in range(0, len(raw), split):
        yield raw[offset : offset + split]


async def _check_unified_surfaces(path, raw, expected, member_count, split):
    streamed = b"".join(
        [
            piece
            async for piece in decompress_chunks(
                _async_parts(raw, split), output_chunk_size=split
            )
        ]
    )
    async with AsyncGzipBinaryFile(path, "rb", chunk_size=split) as stream:
        file_output = await stream.read()
    info = await inspect(path, chunk_size=split)
    verification = await verify(path, chunk_size=split)

    assert streamed == file_output == expected
    assert info.member_count == verification.member_count == member_count
    assert info.uncompressed_size == verification.uncompressed_size == len(expected)


async def _check_rich_surfaces(
    path,
    raw,
    parts,
    expected,
    decoder,
    layouts,
    members,
    output_chunk_size,
):
    async def source():
        for part in parts:
            yield part

    streamed = b"".join(
        [
            piece
            async for piece in decompress_chunks(
                source(),
                output_chunk_size=output_chunk_size,
            )
        ]
    )
    async with AsyncGzipBinaryFile(path, "rb", chunk_size=31) as stream:
        file_output = await stream.read()
    info = await inspect(path, chunk_size=23)
    verification = await verify(path, chunk_size=29)

    assert streamed == file_output == expected
    assert info.members == decoder.members
    assert info.member_count == verification.member_count == len(members)
    assert info.compressed_size == verification.compressed_size == len(raw)
    assert info.uncompressed_size == verification.uncompressed_size == len(expected)

    for actual, layout, member in zip(
        info.members,
        layouts,
        members,
        strict=True,
    ):
        payload, _, _, mtime, extra, filename, comment, _ = member
        assert actual.compressed_offset == layout["start"]
        assert actual.compressed_size == layout["size"]
        assert actual.uncompressed_size == len(payload)
        assert actual.mtime == mtime
        assert actual.original_filename == (
            filename.decode("latin-1") if filename is not None else None
        )
        assert actual.comment == (
            comment.decode("latin-1") if comment is not None else None
        )
        assert actual.extra == extra
        assert actual.flags == layout["flags"]


async def _assert_corrupt_async_surfaces(path, parts):
    async def source():
        for part in parts:
            yield part

    with pytest.raises(gzip.BadGzipFile) as streamed_error:
        async for _ in decompress_chunks(source(), output_chunk_size=13):
            pass
    with pytest.raises(gzip.BadGzipFile) as file_error:
        async with AsyncGzipBinaryFile(path, "rb", chunk_size=19) as stream:
            await stream.read()
    with pytest.raises(gzip.BadGzipFile) as inspection_error:
        await inspect(path, chunk_size=17)
    with pytest.raises(gzip.BadGzipFile) as verification_error:
        await verify(path, chunk_size=11)
    assert all(
        str(error.value)
        for error in (
            streamed_error,
            file_error,
            inspection_error,
            verification_error,
        )
    )


async def _check_limit_async_surfaces(path, raw, limit, expected, should_succeed):
    async def source():
        for part in _split_by_sizes(raw, [1, 7, 31]):
            yield part

    streamed = bytearray()
    if should_succeed:
        async for piece in decompress_chunks(
            source(),
            output_chunk_size=13,
            max_decompressed_size=limit,
        ):
            streamed.extend(piece)
        assert bytes(streamed) == expected
        async with AsyncGzipBinaryFile(
            path,
            "rb",
            chunk_size=17,
            max_decompressed_size=limit,
        ) as stream:
            assert await stream.read() == expected
        assert (
            await inspect(path, max_decompressed_size=limit)
        ).uncompressed_size == len(expected)
        assert (
            await verify(path, max_decompressed_size=limit)
        ).uncompressed_size == len(expected)
        return

    with pytest.raises(OSError, match="max_decompressed_size"):
        async for piece in decompress_chunks(
            source(),
            output_chunk_size=13,
            max_decompressed_size=limit,
        ):
            streamed.extend(piece)
    assert bytes(streamed) == expected[:limit]
    with pytest.raises(OSError, match="max_decompressed_size"):
        async with AsyncGzipBinaryFile(
            path,
            "rb",
            chunk_size=17,
            max_decompressed_size=limit,
        ) as stream:
            await stream.read()
    with pytest.raises(OSError, match="max_decompressed_size"):
        await inspect(path, max_decompressed_size=limit)
    with pytest.raises(OSError, match="max_decompressed_size"):
        await verify(path, max_decompressed_size=limit)


# --------------------------------------------------------------------------- #
# Access-pattern parity
# --------------------------------------------------------------------------- #


async def _check_pattern(path, chunk_size, pattern, params):
    """Drive stdlib and aiogzip with the identical access pattern in lockstep."""
    sf = gzip.open(path, "rb")
    try:
        async with AsyncGzipBinaryFile(path, "rb", chunk_size=chunk_size) as af:
            if pattern == "all":
                a = await af.read(-1)
                s = sf.read()
                assert a == s
                assert await af.tell() == len(s) == sf.tell()

            elif pattern == "fixed":
                size = params
                consumed = 0
                while True:
                    a = await af.read(size)
                    s = sf.read(size)
                    assert a == s
                    if not a:
                        break
                    consumed += len(a)
                    assert await af.tell() == consumed == sf.tell()

            elif pattern == "line":
                consumed = 0
                while True:
                    a = await af.readline()
                    s = sf.readline()
                    assert a == s
                    if not a:
                        break
                    consumed += len(a)
                    assert await af.tell() == consumed == sf.tell()

            elif pattern == "interleave":
                for op, value in params:
                    if op == "read":
                        a = await af.read(value)
                        s = sf.read(value)
                        assert a == s
                        assert await af.tell() == sf.tell()
                    else:  # seek to an earlier (absolute) offset
                        ra = await af.seek(value, os.SEEK_SET)
                        rs = sf.seek(value, os.SEEK_SET)
                        assert ra == rs == value
                        assert await af.tell() == sf.tell() == value
            else:  # pragma: no cover - defensive
                raise AssertionError(pattern)
    finally:
        sf.close()


@settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=_SUPPRESSED)
@given(members=_members, chunk_size=_chunk_size, data=st.data())
def test_read_patterns_match_stdlib(members, chunk_size, data):
    """aiogzip output and tell() match stdlib gzip across access patterns."""
    raw, _ = _build_raw(members)
    total = _expected_len(members)
    pattern = data.draw(st.sampled_from(["all", "fixed", "line", "interleave"]))

    if pattern == "fixed":
        params = data.draw(st.integers(min_value=1, max_value=8192))
    elif pattern == "interleave":
        n_ops = data.draw(st.integers(min_value=1, max_value=20))
        ops = []
        for _ in range(n_ops):
            if data.draw(st.booleans()):
                ops.append(
                    ("read", data.draw(st.integers(min_value=1, max_value=8192)))
                )
            else:
                ops.append(
                    ("seek", data.draw(st.integers(min_value=0, max_value=total)))
                )
        params = ops
    else:
        params = None

    path = _write_tmp(raw)
    try:
        _run(_check_pattern(path, chunk_size, pattern, params))
    finally:
        os.unlink(path)


@settings(max_examples=100, deadline=None, suppress_health_check=_SUPPRESSED)
@given(members=_members, split=st.integers(min_value=1, max_value=1024))
def test_all_decoder_surfaces_share_member_and_output_semantics(members, split):
    """Every public decoder surface agrees on randomized member groupings."""
    raw, _ = _build_raw(members)
    expected = gzip.decompress(raw)

    decoder = GzipDecoder(output_chunk_size=split)
    codec_output = bytearray()
    for offset in range(0, len(raw), split):
        codec_output.extend(b"".join(decoder.feed(raw[offset : offset + split])))
    codec_output.extend(b"".join(decoder.finish()))
    assert bytes(codec_output) == expected

    path = _write_tmp(raw)
    try:
        _run(_check_unified_surfaces(path, raw, expected, len(members), split))
    finally:
        os.unlink(path)


@settings(max_examples=75, deadline=None, suppress_health_check=_SUPPRESSED)
@given(
    members=_rich_members,
    source_sizes=st.lists(
        st.integers(min_value=1, max_value=1024),
        min_size=1,
        max_size=8,
    ),
    output_chunk_size=st.sampled_from(CHUNK_SIZES),
)
def test_rich_archives_agree_across_every_decoder_surface(
    members,
    source_sizes,
    output_chunk_size,
):
    """Random optional fields, padding, boundaries, and bounds stay unified."""
    raw, layouts = _build_rich_raw(members)
    expected = b"".join(member[0] for member in members)
    assert gzip.decompress(raw) == expected
    parts = _split_by_sizes(raw, source_sizes)

    decoder = GzipDecoder(
        output_chunk_size=output_chunk_size,
        collect_member_info=True,
    )
    codec_chunks = []
    for part in parts:
        codec_chunks.extend(decoder.feed(part))
    codec_chunks.extend(decoder.finish())

    assert b"".join(codec_chunks) == expected
    assert all(0 < len(chunk) <= output_chunk_size for chunk in codec_chunks)
    path = _write_tmp(raw)
    try:
        _run(
            _check_rich_surfaces(
                path,
                raw,
                parts,
                expected,
                decoder,
                layouts,
                members,
                output_chunk_size,
            )
        )
    finally:
        os.unlink(path)


@settings(max_examples=40, deadline=None, suppress_health_check=_SUPPRESSED)
@given(
    payload=st.binary(min_size=2, max_size=8192),
    source_sizes=st.lists(
        st.integers(min_value=1, max_value=257),
        min_size=1,
        max_size=6,
    ),
    output_chunk_size=st.sampled_from(CHUNK_SIZES),
)
def test_exact_and_one_over_limits_agree_across_decoder_surfaces(
    payload,
    source_sizes,
    output_chunk_size,
):
    raw = gzip.compress(payload, mtime=0)
    path = _write_tmp(raw)
    try:
        for limit, should_succeed in (
            (len(payload), True),
            (len(payload) - 1, False),
        ):
            decoder = GzipDecoder(
                output_chunk_size=output_chunk_size,
                max_decompressed_size=limit,
            )
            codec_output = bytearray()
            if should_succeed:
                for part in _split_by_sizes(raw, source_sizes):
                    codec_output.extend(b"".join(decoder.feed(part)))
                codec_output.extend(b"".join(decoder.finish()))
                assert bytes(codec_output) == payload
            else:
                with pytest.raises(OSError, match="max_decompressed_size"):
                    for part in _split_by_sizes(raw, source_sizes):
                        for piece in decoder.feed(part):
                            codec_output.extend(piece)
                assert bytes(codec_output) == payload[:limit]

            _run(
                _check_limit_async_surfaces(
                    path,
                    raw,
                    limit,
                    payload,
                    should_succeed,
                )
            )
    finally:
        os.unlink(path)


# --------------------------------------------------------------------------- #
# Single-byte corruption parity
# --------------------------------------------------------------------------- #


@settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=_SUPPRESSED)
@given(
    members=_members,
    # Drawn from fixed ranges, NOT via data.draw(..., max_value=len(raw)-1):
    # the compressed length depends on os.urandom payloads and so varies
    # between Hypothesis replays, which would make a len(raw)-bounded draw
    # change structure and raise Flaky. ``pos`` is mapped onto a byte index at
    # runtime instead.
    pos=st.integers(min_value=0, max_value=2**31 - 1),
    mask=st.integers(min_value=1, max_value=255),
)
def test_single_byte_corruption_parity(members, pos, mask):
    """A flipped byte never lets aiogzip silently accept what stdlib rejects.

    Most flips fall in the compressed body or trailer and make both raise
    (``gzip.BadGzipFile``/``OSError`` for aiogzip; stdlib may also surface
    ``EOFError`` or ``zlib.error``). The invariants asserted here:

    - If stdlib detects corruption, aiogzip must too (it never decodes a stream
      stdlib rejects).
    - When both decode the stream, their output is byte-identical.
    - If aiogzip raises where stdlib decoded cleanly, the flip must have set a
      reserved bit of a member's FLG header byte — the one place aiogzip is
      legitimately *stricter*: it decompresses via zlib, which rejects reserved
      flag bits that stdlib's hand-rolled header parser silently ignores. Any
      other spurious rejection of a stream stdlib accepts is a failure.
    """
    built, flg_offsets = _build_raw(members)
    raw = bytearray(built)
    idx = pos % len(raw)  # raw is always a full gzip member, so len(raw) > 0
    raw[idx] ^= mask
    corrupt = bytes(raw)

    # stdlib
    try:
        std_bytes = gzip.open(io.BytesIO(corrupt), "rb").read()
        std_raised = False
    except (OSError, EOFError, zlib.error):
        std_bytes = None
        std_raised = True

    # aiogzip
    path = _write_tmp(corrupt)
    aio_exc = None
    aio_bytes = None
    try:
        aio_bytes = _run(_aio_read_all(path, chunk_size=64))
        aio_raised = False
    except (OSError, EOFError, zlib.error) as exc:
        aio_raised = True
        aio_exc = exc
    finally:
        os.unlink(path)

    if std_raised:
        assert aio_raised, (
            f"stdlib detected corruption but aiogzip returned {aio_bytes!r}"
        )
    if aio_raised:
        # aiogzip surfaces corruption as gzip.BadGzipFile, a subclass of OSError.
        assert isinstance(aio_exc, (gzip.BadGzipFile, OSError))
        if not std_raised:
            # Stricter-than-stdlib is allowed only for reserved FLG bits
            # (0xE0); anything else is a spurious rejection of a valid stream.
            assert idx in flg_offsets and mask & 0xE0, (
                f"aiogzip raised {aio_exc!r} on a stream stdlib decoded "
                f"cleanly (flip at byte {idx} with mask {mask:#04x} is not a "
                f"reserved FLG-bit flip)"
            )
    else:
        # aiogzip decoded; it must agree with stdlib whenever stdlib also decoded.
        assert std_raised or aio_bytes == std_bytes


_corruption_member = st.tuples(
    st.binary(min_size=0, max_size=2048),
    st.integers(min_value=0, max_value=9),
    st.just(1),
    st.integers(min_value=0, max_value=2**32 - 1),
    st.binary(min_size=1, max_size=16),
    st.one_of(st.none(), _latin1_field),
    st.one_of(st.none(), _latin1_field),
    st.just(True),
)


@settings(max_examples=60, deadline=None, suppress_health_check=_SUPPRESSED)
@given(
    first=_corruption_member,
    second=_rich_member,
    region=st.sampled_from(["fixed", "optional", "body", "trailer", "boundary"]),
    source_sizes=st.lists(
        st.integers(min_value=1, max_value=127),
        min_size=1,
        max_size=5,
    ),
)
def test_structural_corruption_fails_across_every_decoder_surface(
    first,
    second,
    region,
    source_sizes,
):
    built, layouts = _build_rich_raw([first, second])
    corrupt = bytearray(built)
    first_layout = layouts[0]

    if region == "fixed":
        corrupt[first_layout["start"]] = 0
    elif region == "optional":
        extra_offset = first_layout["extra"]
        assert extra_offset is not None
        corrupt[extra_offset - 2 : extra_offset] = b"\xff\xff"
    elif region == "body":
        body_offset = first_layout["body"]
        corrupt[body_offset] = (corrupt[body_offset] & 0xF8) | 0x07
    elif region == "trailer":
        corrupt[first_layout["trailer"]] ^= 1
    else:
        corrupt[first_layout["padding"]] = 1

    damaged = bytes(corrupt)
    with pytest.raises((OSError, EOFError, zlib.error)):
        gzip.decompress(damaged)

    decoder = GzipDecoder(output_chunk_size=13)
    with pytest.raises(gzip.BadGzipFile) as caught:
        for part in _split_by_sizes(damaged, source_sizes):
            list(decoder.feed(part))
        list(decoder.finish())
    assert str(caught.value)

    path = _write_tmp(damaged)
    try:
        _run(
            _assert_corrupt_async_surfaces(
                path,
                _split_by_sizes(damaged, source_sizes),
            )
        )
    finally:
        os.unlink(path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
