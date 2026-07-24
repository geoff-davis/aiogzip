"""Conformance tests for engine-neutral incremental inflate accounting."""

import zlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aiogzip import _engine


def _raw_deflate(payload: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(payload) + compressor.flush()


@pytest.fixture(
    params=[
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                _engine._zng is None, reason="zlib-ng not installed"
            ),
        ),
    ],
    ids=["stdlib", "zlib-ng"],
)
def selected_engine(request, monkeypatch):
    monkeypatch.setattr(_engine, "_HAVE_ZNG", request.param)
    return request.param


def test_eof_retains_trailer_from_same_span(selected_engine):
    payload = b"adapter boundary" * 100
    raw = _raw_deflate(payload)
    trailer = b"12345678"
    engine = _engine.decompressobj(-_engine.MAX_WBITS)

    step = _engine.inflate_step(engine, raw + trailer)

    assert step.output == payload
    assert step.consumed == len(raw)
    assert step.eof
    assert (raw + trailer)[step.consumed :] == trailer


def test_eof_retains_an_immediately_following_member(selected_engine):
    first_payload = b"first member"
    first = _raw_deflate(first_payload)
    second = _raw_deflate(b"second member")
    engine = _engine.decompressobj(-_engine.MAX_WBITS)

    step = _engine.inflate_step(engine, first + second)

    assert step == _engine._InflateStep(
        output=first_payload,
        consumed=len(first),
        eof=True,
    )
    assert (first + second)[step.consumed :] == second


def test_bounded_output_repeats_over_one_input_span(selected_engine):
    payload = b"highly compressible" * 1000
    pending = _raw_deflate(payload) + b"trailer"
    engine = _engine.decompressobj(-_engine.MAX_WBITS)
    output = bytearray()

    for _ in range(len(payload) + 10):
        step = _engine.inflate_step(engine, pending, max_length=17)
        output.extend(step.output)
        pending = pending[step.consumed :]
        if step.eof:
            break
    else:  # pragma: no cover - protects the test itself from hanging
        pytest.fail("inflate adapter did not reach EOF")

    assert bytes(output) == payload
    assert pending == b"trailer"


@pytest.mark.parametrize(
    ("unused", "tail"),
    [
        (b"TRAILER", b""),
        (b"", b"TRAILER"),
        (b"TRAI", b"LER"),
        (b"TRAILER", b"TRAILER"),
    ],
    ids=["unused-only", "tail-only", "split", "duplicated"],
)
def test_fake_engine_leftover_representations(unused, tail):
    class FakeEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def decompress(self, data, max_length=0):
            self.eof = True
            self.unused_data = unused
            self.unconsumed_tail = tail
            return b"decoded"

    step = _engine.inflate_step(FakeEngine(), b"payloadTRAILER")

    assert step == _engine._InflateStep(output=b"decoded", consumed=7, eof=True)


def test_fake_engine_ignores_leftovers_accumulated_before_current_span():
    class FakeEngine:
        eof = True
        unused_data = b"old padding"
        unconsumed_tail = b""

        def decompress(self, data, max_length=0):
            self.unused_data += data
            return b""

    step = _engine.inflate_step(FakeEngine(), b"new member")

    assert step == _engine._InflateStep(output=b"", consumed=0, eof=True)


def test_non_eof_unconsumed_suffix_is_counted():
    class FakeEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b"tail"

        def decompress(self, data, max_length=0):
            return b"output"

    assert _engine.inflate_step(FakeEngine(), b"consumedtail") == _engine._InflateStep(
        output=b"output",
        consumed=8,
        eof=False,
    )


def test_no_progress_is_rejected():
    class FakeEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b"pending"

        def decompress(self, data, max_length=0):
            return b""

    with pytest.raises(OSError, match="made no progress"):
        _engine.inflate_step(FakeEngine(), b"pending")


def test_malformed_payload_preserves_engine_error(selected_engine):
    engine = _engine.decompressobj(-_engine.MAX_WBITS)

    with pytest.raises(_engine.ZLIB_ERRORS):
        _engine.inflate_step(engine, b"\xff" * 32)


@given(
    payload=st.binary(max_size=4096),
    trailing=st.binary(max_size=32),
    input_chunk_size=st.integers(min_value=1, max_value=64),
)
def test_consumed_boundary_property(payload, trailing, input_chunk_size):
    raw = _raw_deflate(payload)
    engine = zlib.decompressobj(-zlib.MAX_WBITS)
    wire = raw + trailing
    output = bytearray()
    retained = b""

    for offset in range(0, len(wire), input_chunk_size):
        chunk = wire[offset : offset + input_chunk_size]
        step = _engine.inflate_step(engine, chunk)
        output.extend(step.output)
        if step.eof:
            retained = chunk[step.consumed :] + wire[offset + len(chunk) :]
            break
    else:  # pragma: no cover - raw deflate always reaches EOF
        pytest.fail("inflate adapter did not reach EOF")

    assert bytes(output) == payload
    assert retained == trailing
