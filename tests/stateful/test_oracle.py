"""Pins the ``raw-1in-1out/v1`` body-corruption reference schedule.

The corruption sits more than 64 KiB of output past the start of the body.
On every engine available here, a one-shot ``decompress`` raises and so
returns nothing, while the schedule captures every byte the engine can
inflate first. The library's output on its own engine, through the codec
and the file API, across chunk sizes, is always a prefix of that reference.
"""

import base64
import gzip
import hashlib
import io
import random
import zlib
from pathlib import Path

import pytest
from oracle import (
    SCHEDULE,
    WIRE_SCHEDULE,
    engine_modules,
    raw_reference,
    wire_reference,
)

import aiogzip
from aiogzip import AsyncGzipBinaryFile, GzipDecoder

HEADER = 10  # gzip.compress(mtime=0) writes no optional header fields
TRAILER = 8
LATE = 64 * 1024


def _payload() -> bytes:
    rng = random.Random(20261006)
    words = [
        "".join(rng.choices("abcdefghijklmnop", k=rng.randint(2, 9)))
        for _ in range(400)
    ]
    return " ".join(rng.choices(words, k=60_000)).encode()


# gzip.compress(_payload(), mtime=0) under zlib 1.3.1, committed because the
# compressed bytes depend on the platform's zlib: a zlib-ng-backed stdlib (for
# example CPython 3.14 on Windows) emits a different stream in which the
# pinned corruption below goes undetected.
WIRE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "data" / "oracle_late_corruption.gz"
)
WIRE_SHA256 = "34594219ed4c602b531df98c0ef7291e033e79a19e417d54584876167be60af3"


def _clean_wire() -> bytes:
    wire = WIRE_FIXTURE.read_bytes()
    assert hashlib.sha256(wire).hexdigest() == WIRE_SHA256
    assert gzip.decompress(wire) == _payload()
    return wire


# The first corruption, scanning body offsets from two thirds in and flips
# 0xFF, 0x55, 0x0F, that every engine detects more than LATE bytes of output
# in. Pinned rather than searched at import: the search costs ~18 s.
OFFSET, FLIP = 81_433, 0x55


def _late_corruption():
    wire = _clean_wire()
    corrupt = bytearray(wire[HEADER:-TRAILER])
    corrupt[OFFSET] ^= FLIP
    references = {
        name: raw_reference(module, bytes(corrupt))
        for name, module in engine_modules().items()
    }
    for name, reference in references.items():
        assert reference["error"] is not None, f"{name} no longer detects it"
        assert len(reference["output"]) > LATE, name
    return bytes(corrupt), wire[:HEADER] + bytes(corrupt) + wire[-TRAILER:], references


BODY, WIRE, REFERENCES = _late_corruption()
ENGINE = aiogzip.engine_info().decompression


@pytest.mark.parametrize("engine", sorted(REFERENCES))
def test_one_shot_decompress_raises_where_the_schedule_captures_output(engine):
    module = engine_modules()[engine]
    with pytest.raises(module.error):
        module.decompressobj(-15).decompress(BODY)
    reference = REFERENCES[engine]
    assert reference["schedule"] == SCHEDULE
    assert len(reference["output"]) > LATE
    # Everything inflatable from the body before the flipped byte is the
    # payload, and the reference reproduces all of it. What the engine
    # inflates from the corrupt region before detecting it is unconstrained.
    clean_body = _clean_wire()[HEADER:-TRAILER]
    before = module.decompressobj(-15).decompress(clean_body[:OFFSET])
    assert len(before) > LATE
    assert _payload().startswith(before)
    assert reference["output"].startswith(before)


def test_schedule_is_deterministic_and_reports_no_error_for_a_clean_body():
    module = engine_modules()[ENGINE]
    assert raw_reference(module, BODY) == REFERENCES[ENGINE]
    clean = gzip.compress(b"clean body" * 100, mtime=0)[HEADER:-TRAILER]
    result = raw_reference(module, clean)
    assert result["error"] is None
    assert result["output"] == b"clean body" * 100


def _codec_output(step: int, output_chunk_size: int) -> tuple[bytes, Exception | None]:
    decoder = GzipDecoder(output_chunk_size=output_chunk_size)
    output = bytearray()
    try:
        for start in range(0, len(WIRE), step):
            for chunk in decoder.feed(WIRE[start : start + step]):
                output += chunk
        for chunk in decoder.finish():
            output += chunk
    except (OSError, zlib.error) as error:
        return bytes(output), error
    return bytes(output), None


@pytest.mark.parametrize("step", [1, 977, 65_536, len(WIRE)])
@pytest.mark.parametrize("output_chunk_size", [1, 4096, 256 * 1024])
def test_codec_output_is_a_prefix_of_the_reference(step, output_chunk_size):
    if step == 1 and output_chunk_size == 1:
        pytest.skip("byte-at-a-time in and out is covered by the schedule itself")
    output, error = _codec_output(step, output_chunk_size)
    assert error is not None
    assert REFERENCES[ENGINE]["output"].startswith(output)


class _Source:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self.buffer.read(size)


@pytest.mark.parametrize("chunk_size", [1024, 64 * 1024, 256 * 1024])
@pytest.mark.parametrize("read_size", [1, 5000, -1])
async def test_file_output_including_salvage_is_a_prefix_of_the_reference(
    chunk_size, read_size
):
    stream = AsyncGzipBinaryFile(
        None, "rb", fileobj=_Source(WIRE), closefd=False, chunk_size=chunk_size
    )
    output = bytearray()
    async with stream:
        failures = 0
        while failures < 2:
            try:
                data = await stream.read(read_size)
            except OSError as error:
                failures += 1
                # The salvage drain ends in the broken-stream refusal.
                if failures == 2:
                    assert "broken" in str(error)
                continue
            assert data, "a failed body-corrupt stream never reports clean EOF"
            output += data
    assert REFERENCES[ENGINE]["output"].startswith(bytes(output))


# ``wire-1in-1out/v1``: the member-loop oracle for spliced or replayed wires.


def _header(flags=0, extra=None, name=None, comment=None, hcrc=None, method=8):
    header = bytes([0x1F, 0x8B, method, flags]) + bytes(6)
    if extra is not None:
        header += len(extra).to_bytes(2, "little") + extra
    for field in (name, comment):
        if field is not None:
            header += field + b"\0"
    if hcrc is not None:
        header += (
            hcrc
            if isinstance(hcrc, bytes)
            else (zlib.crc32(header) & 0xFFFF).to_bytes(2, "little")
        )
    return header


def _member(payload: bytes, header: bytes | None = None, crc=None, isize=None):
    body = gzip.compress(payload, mtime=0)[HEADER:-TRAILER]
    crc = zlib.crc32(payload) if crc is None else crc
    isize = len(payload) if isize is None else isize
    trailer = crc.to_bytes(4, "little") + (isize & 0xFFFFFFFF).to_bytes(4, "little")
    return (_header() if header is None else header) + body + trailer


ONE, TWO = b"first member\n" * 9, b"second member\n" * 7
FLAGS = 0x02 | 0x04 | 0x08 | 0x10
WIRE_CASES = {
    # case: (wire, failure, output, validated)
    "empty": (b"", None, b"", 0),
    "one member": (_member(ONE), None, ONE, len(ONE)),
    "padding between and after members": (
        _member(ONE) + bytes(5) + _member(TWO) + bytes(3),
        None,
        ONE + TWO,
        len(ONE + TWO),
    ),
    "optional header fields": (
        _member(ONE, _header(FLAGS, b"xy", b"name", b"note", hcrc=True)),
        None,
        ONE,
        len(ONE),
    ),
    "leading padding": (bytes(1) + _member(ONE), "header invalid", b"", 0),
    "bad magic after a member": (
        _member(ONE) + b"\x1f\x8c" + bytes(8),
        "header invalid",
        ONE,
        len(ONE),
    ),
    "unknown method": (_member(ONE, _header(method=7)), "header invalid", b"", 0),
    "reserved flag": (_member(ONE, _header(0x20)), "header invalid", b"", 0),
    "header crc mismatch": (
        _member(ONE, _header(0x02, hcrc=b"\0\0")),
        "header invalid",
        b"",
        0,
    ),
    "header ends in a name": (
        _member(ONE) + _header(0x08)[:12],
        "header truncated",
        ONE,
        len(ONE),
    ),
    "header ends in the fixed fields": (
        _member(ONE) + b"\x1f",
        "header truncated",
        ONE,
        len(ONE),
    ),
    "body ends early": (_member(ONE)[:-20], "body truncated", None, 0),
    "trailer ends early": (_member(ONE)[:-3], "trailer truncated", ONE, 0),
    "crc mismatch": (_member(ONE, crc=1), "trailer crc", ONE, len(ONE)),
    "isize mismatch": (
        _member(TWO) + _member(ONE, isize=1),
        "trailer isize",
        TWO + ONE,
        len(TWO + ONE),
    ),
    "crc mismatch in a later member": (
        _member(TWO) + _member(ONE, crc=1),
        "trailer crc",
        TWO + ONE,
        len(TWO + ONE),
    ),
}


@pytest.mark.parametrize("case", sorted(WIRE_CASES))
def test_wire_reference_classifies_each_member_loop_stage(case):
    wire, failure, output, validated = WIRE_CASES[case]
    reference = wire_reference(engine_modules()[ENGINE], wire)
    assert reference["schedule"] == WIRE_SCHEDULE
    assert reference["failure"] == failure
    if output is not None:
        assert reference["output"] == output
    else:
        assert ONE.startswith(reference["output"])
    assert reference["validated"] == validated


def _decoder_output(wire: bytes, step: int) -> tuple[bytes, Exception | None]:
    decoder = GzipDecoder(output_chunk_size=4096)
    output = bytearray()
    try:
        for start in range(0, len(wire), step):
            for chunk in decoder.feed(wire[start : start + step]):
                output += chunk
        for chunk in decoder.finish():
            output += chunk
    except (OSError, zlib.error) as error:
        return bytes(output), error
    return bytes(output), None


def _spliced_wires() -> list[bytes]:
    rng = random.Random(20261006)
    payloads = [bytes(rng.choices(b"abc\n", k=rng.randint(50, 3000))) for _ in range(3)]
    wire = b"".join(gzip.compress(p, mtime=0) for p in payloads[:2])
    wire += bytes(2) + gzip.compress(payloads[2], mtime=0)
    wires = list(case[0] for case in WIRE_CASES.values())
    for _ in range(60):
        a = rng.randrange(len(wire))
        b = rng.randrange(a, len(wire) + 1)
        wires.append(wire[:a] + wire[b:])  # a lost range
        wires.append(wire[:a] + wire)  # a replayed prefix
    return wires


SPLICED = _spliced_wires()


@pytest.mark.parametrize("step", [1, 13, 1 << 20])
def test_codec_agrees_with_the_wire_reference(step):
    """The library's own decoder, on its engine, at several feed sizes: a
    clean wire decodes exactly, and a failing one raises after delivering
    at least the validated bytes and never more than the reference."""
    module = engine_modules()[ENGINE]
    failures = set()
    for wire in SPLICED:
        reference = wire_reference(module, wire)
        output, error = _decoder_output(wire, step)
        if reference["failure"] is None:
            assert error is None, (wire, error)
            assert output == reference["output"]
            continue
        failures.add(reference["failure"])
        assert error is not None, (wire, reference["failure"])
        assert reference["output"].startswith(output)
        assert len(output) >= reference["validated"]
    assert failures >= {"header invalid", "body invalid", "trailer crc"}


def test_wire_reference_agrees_with_the_structural_model():
    """Over generated read scenarios, the oracle reproduces the payload
    model's expectation exactly; for a truncation, whose structural upper
    bound is the whole truncated member, it is the exact inflatable prefix."""
    from generator import generate
    from model import expectation

    module = engine_modules()[ENGINE]
    kinds = set()
    for seed in range(400):
        scenario = generate(seed)
        if scenario["mode"] not in ("rb", "rt"):
            continue
        kind = scenario["corruption"]["kind"]
        if kind == "limit":
            continue
        expect = expectation(scenario, ENGINE)
        reference = wire_reference(module, base64.b64decode(scenario["wire"]))
        if kind == "truncate":
            assert expect.upper.startswith(reference["output"]), seed
        else:
            assert reference["output"] == expect.upper, seed
        assert reference["validated"] == expect.lower, seed
        assert (reference["failure"] is None) == expect.clean, seed
        kinds.add(kind)
    assert kinds == {"none", "crc", "isize", "truncate", "body"}
