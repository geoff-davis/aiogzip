"""Pins the ``raw-1in-1out/v1`` body-corruption reference schedule.

The corruption sits more than 64 KiB of output past the start of the body.
On every engine available here, a one-shot ``decompress`` raises and so
returns nothing, while the schedule captures every byte the engine can
inflate first. The library's output on its own engine, through the codec
and the file API, across chunk sizes, is always a prefix of that reference.
"""

import gzip
import io
import random
import zlib

import pytest
from oracle import SCHEDULE, engine_modules, raw_reference

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


# The first corruption, scanning body offsets from two thirds in and flips
# 0xFF, 0x55, 0x0F, that every engine detects more than LATE bytes of output
# in. Pinned rather than searched at import: the search costs ~18 s.
OFFSET, FLIP = 81_433, 0x55


def _late_corruption():
    wire = gzip.compress(_payload(), mtime=0)
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
    assert _payload().startswith(reference["output"][: reference["error_offset"]])


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
