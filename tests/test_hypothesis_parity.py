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
import tempfile
import zlib

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aiogzip import AsyncGzipBinaryFile

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


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _build_raw(members):
    """Encode the member spec into concatenated gzip members with NUL padding."""
    out = bytearray()
    for payload, level, pad in members:
        buf = io.BytesIO()
        # mtime=0 keeps the header deterministic.
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=level, mtime=0) as g:
            g.write(payload)
        out += buf.getvalue()
        out += b"\x00" * pad
    return bytes(out)


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
    raw = _build_raw(members)
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


# --------------------------------------------------------------------------- #
# Single-byte corruption parity
# --------------------------------------------------------------------------- #


@settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=_SUPPRESSED)
@given(members=_members, data=st.data())
def test_single_byte_corruption_parity(members, data):
    """A flipped byte is detected (or ignored) identically by stdlib and aiogzip.

    Most flips fall in the compressed body or trailer and make both raise
    (``gzip.BadGzipFile``/``OSError`` for aiogzip; stdlib may also surface
    ``EOFError`` or ``zlib.error``). A few flips land in benign header metadata
    (mtime/XFL/OS) and leave the stream readable; in that case both must still
    decode to identical bytes.
    """
    raw = bytearray(_build_raw(members))
    idx = data.draw(st.integers(min_value=0, max_value=len(raw) - 1))
    mask = data.draw(st.integers(min_value=1, max_value=255))
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
        # aiogzip surfaces corruption as gzip.BadGzipFile, a subclass of OSError.
        assert isinstance(aio_exc, (gzip.BadGzipFile, OSError))
    else:
        assert not aio_raised, f"aiogzip raised {aio_exc!r} but stdlib decoded cleanly"
        assert aio_bytes == std_bytes


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
