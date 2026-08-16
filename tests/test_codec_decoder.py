"""Direct tests for the public synchronous gzip decoder."""

import gzip
import inspect
import os
import struct
import zlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

import aiogzip.codec as codec_module
from aiogzip import AsyncGzipBinaryFile, GzipDecoder, GzipEncoder, _engine


def _decode(parts, **options):
    decoder = GzipDecoder(**options)
    output = bytearray()
    for part in parts:
        for chunk in decoder.feed(part):
            output.extend(chunk)
    for chunk in decoder.finish():
        output.extend(chunk)
    return bytes(output), decoder


def _metadata_member(payload):
    flags = 0x04 | 0x08 | 0x10 | 0x02
    header = bytearray(b"\x1f\x8b\x08")
    header.append(flags)
    header.extend(struct.pack("<I", 123))
    header.extend(b"\x00\xff")
    extra = b"\x01\x02extra"
    header.extend(struct.pack("<H", len(extra)))
    header.extend(extra)
    header.extend("café.bin".encode("latin-1") + b"\x00")
    header.extend(b"codec test\x00")
    header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))
    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = compressor.compress(payload) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload))
    return bytes(header) + body + trailer


def _corrupt_header_variant(damage):
    if damage == "fhcrc":
        wire = bytearray(_metadata_member(b"payload"))
        wire[4] ^= 1
        return bytes(wire)
    wire = bytearray(gzip.compress(b"payload", mtime=123))
    if damage == "magic":
        wire[0] ^= 1
    elif damage == "method":
        wire[2] ^= 1
    elif damage == "reserved-flags":
        wire[3] |= 0x20
    else:
        raise AssertionError(f"unknown damage: {damage}")
    return bytes(wire)


def test_header_notification_starts_empty_and_commits_at_fixed_header_boundary():
    wire = gzip.compress(b"payload", mtime=0xFFFFFFFF)
    decoder = GzipDecoder()

    assert decoder._header_generation == 0
    assert decoder._last_header_mtime is None
    with pytest.raises(AttributeError):
        decoder._header_generation = 1
    with pytest.raises(AttributeError):
        decoder._last_header_mtime = 1
    operation = decoder.feed(wire[:9])
    assert decoder._header_generation == 0
    assert list(operation) == []
    assert decoder._header_generation == 0

    assert list(decoder.feed(wire[9:10])) == []
    assert decoder._header_generation == 1
    assert decoder._last_header_mtime == 0xFFFFFFFF
    output = b"".join(decoder.feed(wire[10:])) + b"".join(decoder.finish())
    assert output == b"payload"


@pytest.mark.parametrize("split", range(11))
def test_header_notification_fixed_header_split_at_every_boundary(split):
    wire = gzip.compress(b"split payload", mtime=0)
    decoder = GzipDecoder()

    assert list(decoder.feed(wire[:split])) == []
    assert decoder._header_generation == (1 if split == 10 else 0)
    assert list(decoder.feed(wire[split:10])) == []
    assert decoder._header_generation == 1
    assert decoder._last_header_mtime == 0

    output = b"".join(decoder.feed(wire[10:])) + b"".join(decoder.finish())
    assert output == b"split payload"


def test_header_notification_increments_for_every_member_in_one_feed():
    wire = b"".join(
        (
            gzip.compress(b"first", mtime=100),
            gzip.compress(b"second", mtime=100),
            gzip.compress(b"third", mtime=200),
        )
    )
    decoder = GzipDecoder()

    output = b"".join(decoder.feed(wire)) + b"".join(decoder.finish())

    assert output == b"firstsecondthird"
    assert decoder._header_generation == 3
    assert decoder._last_header_mtime == 200


@pytest.mark.parametrize("collect_member_info", [False, True])
def test_header_notification_supports_all_optional_fields_without_collection_dependency(
    collect_member_info,
):
    wire = _metadata_member(b"metadata payload")
    decoder = GzipDecoder(collect_member_info=collect_member_info)

    output = b"".join(decoder.feed(wire)) + b"".join(decoder.finish())

    assert output == b"metadata payload"
    assert decoder._header_generation == 1
    assert decoder._last_header_mtime == 123


def test_header_notification_waits_for_bytewise_optional_header_completion():
    wire = _metadata_member(b"bytewise metadata")
    extra = b"\x01\x02extra"
    filename = "café.bin".encode("latin-1")
    comment = b"codec test"
    header_size = 10 + 2 + len(extra) + len(filename) + 1 + len(comment) + 1 + 2
    decoder = GzipDecoder()
    output = bytearray()

    for index, byte in enumerate(wire):
        output.extend(b"".join(decoder.feed(bytes((byte,)))))
        expected_generation = 1 if index + 1 >= header_size else 0
        assert decoder._header_generation == expected_generation
    output.extend(decoder.finish())

    assert output == b"bytewise metadata"
    assert decoder._last_header_mtime == 123


@pytest.mark.parametrize("damage", ["magic", "method", "reserved-flags", "fhcrc"])
def test_invalid_header_does_not_commit_notification(damage):
    decoder = GzipDecoder()

    with pytest.raises(gzip.BadGzipFile):
        list(decoder.feed(_corrupt_header_variant(damage)))

    assert decoder._header_generation == 0
    assert decoder._last_header_mtime is None


def test_truncated_header_does_not_commit_notification():
    decoder = GzipDecoder()

    assert list(decoder.feed(b"\x1f\x8b\x08")) == []
    with pytest.raises(gzip.BadGzipFile, match="truncated gzip member header"):
        list(decoder.finish())

    assert decoder._header_generation == 0
    assert decoder._last_header_mtime is None


@pytest.mark.parametrize("damage", ["body", "crc", "isize"])
def test_valid_header_notification_survives_later_member_failure(damage):
    wire = bytearray(gzip.compress(b"payload", mtime=321))
    if damage == "body":
        wire[10] ^= 0xFF
    elif damage == "crc":
        wire[-8] ^= 1
    else:
        wire[-4] ^= 1
    decoder = GzipDecoder()

    with pytest.raises(gzip.BadGzipFile):
        list(decoder.feed(bytes(wire)))

    assert decoder._header_generation == 1
    assert decoder._last_header_mtime == 321


def test_malformed_later_header_retains_previous_notification():
    decoder = GzipDecoder()
    wire = gzip.compress(b"first", mtime=456) + b"not a gzip header"

    with pytest.raises(gzip.BadGzipFile):
        list(decoder.feed(wire))

    assert decoder._header_generation == 1
    assert decoder._last_header_mtime == 456


def test_discard_retains_completed_header_notification_scalars():
    wire = gzip.compress(b"payload", mtime=789)
    decoder = GzipDecoder()

    assert list(decoder.feed(wire[:10])) == []
    decoder.discard()

    assert decoder._header_generation == 1
    assert decoder._last_header_mtime == 789


@pytest.mark.parametrize("parts", [[], [b""], [b"", b""]])
def test_empty_input_is_a_valid_zero_member_stream(parts):
    output, decoder = _decode(parts, collect_member_info=True)

    assert output == b""
    assert decoder.finished
    assert decoder.member_count == 0
    assert decoder.members == ()


def test_empty_feed_is_legal_before_finish():
    decoder = GzipDecoder()

    assert list(decoder.feed(b"")) == []
    assert list(decoder.finish()) == []


def test_stdlib_and_encoder_generated_input():
    payload = b"codec payload" * 1000
    stdlib_wire = gzip.compress(payload, mtime=0)
    encoder = GzipEncoder(mtime=0)
    codec_wire = b"".join(encoder.start()) + b"".join(encoder.feed(payload))
    codec_wire += b"".join(encoder.finish())

    assert _decode([stdlib_wire])[0] == payload
    assert _decode([codec_wire])[0] == payload


def test_every_byte_input_boundaries():
    payload = b"bytewise codec input" * 100
    wire = gzip.compress(payload, mtime=0)

    assert (
        _decode([wire[index : index + 1] for index in range(len(wire))])[0] == payload
    )


@given(
    payload=st.binary(max_size=20_000),
    split=st.integers(min_value=1, max_value=257),
    output_chunk_size=st.integers(min_value=1, max_value=257),
)
def test_random_payload_and_input_splits(payload, split, output_chunk_size):
    wire = gzip.compress(payload, mtime=0)
    parts = [wire[offset : offset + split] for offset in range(0, len(wire), split)]
    output, _ = _decode(parts, output_chunk_size=output_chunk_size)

    assert output == payload


def test_highly_compressible_output_is_strictly_bounded():
    payload = b"A" * (2 * 1024 * 1024)
    decoder = GzipDecoder(output_chunk_size=113)
    chunks = list(decoder.feed(gzip.compress(payload, mtime=0)))
    chunks.extend(decoder.finish())

    assert b"".join(chunks) == payload
    assert all(0 < len(chunk) <= 113 for chunk in chunks)


def test_concatenated_empty_members_and_nul_padding():
    payloads = [b"first", b"", os.urandom(4096)]
    wire = b"\x00".join(gzip.compress(part, mtime=0) for part in payloads) + b"\x00" * 5
    output, decoder = _decode([wire], collect_member_info=True)

    assert output == b"".join(payloads)
    assert decoder.member_count == 3
    assert len(decoder.members) == 3
    assert decoder._header_generation == 3
    assert decoder._last_header_mtime == 0


def test_metadata_heavy_header_and_offsets():
    first_payload = b"first"
    second_payload = b"second" * 100
    first = _metadata_member(first_payload)
    second = gzip.compress(second_payload, mtime=456)
    output, decoder = _decode(
        [first + second], output_chunk_size=7, collect_member_info=True
    )

    assert output == first_payload + second_payload
    first_info, second_info = decoder.members
    assert first_info.compressed_offset == 0
    assert first_info.compressed_size == len(first)
    assert first_info.mtime == 123
    assert first_info.original_filename == "café.bin"
    assert first_info.comment == "codec test"
    assert first_info.extra == b"\x01\x02extra"
    assert second_info.compressed_offset == len(first)
    assert second_info.compressed_size == len(second)


def test_metadata_collection_is_opt_in():
    wire = gzip.compress(b"payload", mtime=0)
    _, decoder = _decode([wire])

    assert decoder.member_count == 1
    assert decoder.members == ()


@pytest.mark.parametrize("optional_flag", [0x08, 0x10])
def test_completed_optional_header_over_safety_limit_is_rejected(
    monkeypatch, optional_flag
):
    monkeypatch.setattr(codec_module, "_MAX_CHUNK_SIZE", 16)
    header = (
        b"\x1f\x8b\x08"
        + bytes([optional_flag])
        + b"\x00\x00\x00\x00\x00\xff"
        + b"1234567\x00"
    )
    decoder = GzipDecoder()

    with pytest.raises(gzip.BadGzipFile, match="header exceeds"):
        list(decoder.feed(header))


def test_simple_and_hostile_bytes_subclasses_use_raw_buffer():
    class Simple(bytes):
        pass

    class Hostile(bytes):
        def __bytes__(self):
            raise AssertionError("__bytes__ must not run")

        def __len__(self):
            raise AssertionError("__len__ must not run")

        def __iter__(self):
            raise AssertionError("__iter__ must not run")

        def __getitem__(self, key):
            raise AssertionError("__getitem__ must not run")

    wire = gzip.compress(b"subclass payload", mtime=0)
    for value in (Simple(wire), Hostile(wire)):
        assert _decode([value])[0] == b"subclass payload"


@pytest.mark.parametrize("value", [bytearray(b"x"), memoryview(b"x"), "x", 1])
def test_mutable_and_non_bytes_inputs_are_rejected_without_poisoning(value):
    decoder = GzipDecoder()

    with pytest.raises(TypeError, match="must be bytes"):
        decoder.feed(value)
    wire = gzip.compress(b"ok", mtime=0)
    assert b"".join((*decoder.feed(wire), *decoder.finish())) == b"ok"


@pytest.mark.parametrize("value", [True, 1.5, 0, -1, 128 * 1024 * 1024 + 1])
def test_output_chunk_validation_matches_file_api(value):
    expected = TypeError if value in (True, 1.5) else ValueError

    with pytest.raises(expected):
        GzipDecoder(output_chunk_size=value)
    with pytest.raises(expected):
        AsyncGzipBinaryFile("unused.gz", "rb", chunk_size=value)


def test_output_chunk_size_accepts_128_mib_boundary():
    decoder = GzipDecoder(output_chunk_size=128 * 1024 * 1024)

    decoder.discard()


@pytest.mark.parametrize("value", [True, 1.5, 0, -1])
def test_limit_validation_matches_file_api(value):
    expected = TypeError if value in (True, 1.5) else ValueError

    with pytest.raises(expected):
        GzipDecoder(max_decompressed_size=value)
    with pytest.raises(expected):
        AsyncGzipBinaryFile("unused.gz", "rb", max_decompressed_size=value)


@pytest.mark.parametrize("limit", [5, 6, 7])
def test_cumulative_limit_boundary_and_no_over_limit_output(limit):
    wire = gzip.compress(b"abc", mtime=0) + gzip.compress(b"def", mtime=0)
    decoder = GzipDecoder(output_chunk_size=2, max_decompressed_size=limit)
    output = bytearray()

    if limit < 6:
        with pytest.raises(OSError, match="max_decompressed_size"):
            for chunk in decoder.feed(wire):
                output.extend(chunk)
        assert len(output) <= limit
    else:
        for chunk in decoder.feed(wire):
            output.extend(chunk)
        for chunk in decoder.finish():
            output.extend(chunk)
        assert output == b"abcdef"


@pytest.mark.parametrize(
    "damage",
    ["crc", "isize", "magic", "method", "flags", "fhcrc"],
)
def test_corrupt_headers_and_trailers(damage):
    if damage == "fhcrc":
        wire = bytearray(_metadata_member(b"payload"))
        wire[4] ^= 1
    else:
        wire = bytearray(gzip.compress(b"payload", mtime=0))
        index = {
            "crc": -8,
            "isize": -4,
            "magic": 0,
            "method": 2,
            "flags": 3,
        }[damage]
        wire[index] ^= 0x20 if damage == "flags" else 1

    with pytest.raises(gzip.BadGzipFile):
        _decode([bytes(wire)])


def test_invalid_deflate_payload_is_normalized_and_poisons_decoder():
    wire = b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"\xff" * 16 + b"\x00" * 8
    decoder = GzipDecoder()

    with pytest.raises(gzip.BadGzipFile, match="Error decompressing") as exc_info:
        list(decoder.feed(wire))
    assert isinstance(exc_info.value.__cause__, _engine.ZLIB_ERRORS)
    with pytest.raises(OSError, match="unusable"):
        decoder.finish()


@pytest.mark.parametrize(
    "wire",
    [
        b"\x1f\x8b\x08\x04" + b"\x00" * 6 + b"\x05",
        b"\x1f\x8b\x08\x04" + b"\x00" * 6 + b"\x05\x00xx",
        b"\x1f\x8b\x08\x08" + b"\x00" * 6 + b"unterminated",
        b"\x1f\x8b\x08\x10" + b"\x00" * 6 + b"unterminated",
        b"\x1f\x8b\x08\x02" + b"\x00" * 6 + b"\x00",
    ],
    ids=["extra-length", "extra-data", "filename", "comment", "fhcrc"],
)
def test_truncated_optional_header_fields(wire):
    decoder = GzipDecoder()

    with pytest.raises(gzip.BadGzipFile, match="truncated gzip member header"):
        list(decoder.feed(wire))
        list(decoder.finish())

    assert decoder._header_generation == 0
    assert decoder._last_header_mtime is None


@pytest.mark.parametrize(
    "wire",
    [
        b"\x1f",
        b"\x1f\x8b\x08",
        gzip.compress(b"payload", mtime=0)[:-9],
        gzip.compress(b"payload", mtime=0)[:-1],
    ],
)
def test_truncated_header_body_and_trailer(wire):
    with pytest.raises(gzip.BadGzipFile):
        _decode([wire])


def test_trailing_non_nul_junk_is_rejected():
    with pytest.raises(gzip.BadGzipFile):
        _decode([gzip.compress(b"payload", mtime=0) + b"junk"])


def test_statistics_and_terminal_state():
    wire = gzip.compress(b"payload", mtime=0)
    output, decoder = _decode([wire], collect_member_info=True)

    assert output == b"payload"
    assert decoder.compressed_size == len(wire)
    assert decoder.uncompressed_size == 7
    assert decoder.finished
    with pytest.raises(ValueError, match="already finalized"):
        decoder.feed(b"")
    with pytest.raises(ValueError, match="already finalized"):
        decoder.finish()


def test_public_methods_are_synchronous():
    for name in ("feed", "finish", "discard"):
        method = getattr(GzipDecoder, name)
        assert not inspect.iscoroutinefunction(method)
        assert not inspect.isasyncgenfunction(method)
