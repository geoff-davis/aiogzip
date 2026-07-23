"""Direct tests for the public synchronous gzip encoder."""

import gzip
import inspect
import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aiogzip import AsyncGzipBinaryFile, GzipEncoder, _common, _engine
from aiogzip.codec import _snapshot_bytes_input


def _encode(parts, **options):
    encoder = GzipEncoder(**options)
    output = bytearray()
    for chunk in encoder.start():
        output.extend(chunk)
    for part in parts:
        for chunk in encoder.feed(part):
            output.extend(chunk)
    for chunk in encoder.finish():
        output.extend(chunk)
    return bytes(output), encoder


def test_default_constructor_and_empty_member():
    wire, encoder = _encode([])

    assert gzip.decompress(wire) == b""
    assert encoder.started
    assert encoder.finished
    assert encoder.input_size == 0
    assert encoder.crc32 == 0


@pytest.mark.parametrize("value", [True, 1.5, 0, -1, 128 * 1024 * 1024 + 1])
def test_output_chunk_size_validation_matches_file_api(value):
    expected = TypeError if value in (True, 1.5) else ValueError

    with pytest.raises(expected):
        GzipEncoder(output_chunk_size=value)
    with pytest.raises(expected):
        AsyncGzipBinaryFile("unused.gz", "wb", chunk_size=value)


def test_output_chunk_size_accepts_128_mib_boundary():
    encoder = GzipEncoder(output_chunk_size=128 * 1024 * 1024)

    encoder.discard()


@pytest.mark.parametrize("value", [True, 1.5, -2, 10])
def test_compresslevel_validation_matches_file_api(value):
    expected = TypeError if value in (True, 1.5) else ValueError

    with pytest.raises(expected):
        GzipEncoder(compresslevel=value)
    with pytest.raises(expected):
        AsyncGzipBinaryFile("unused.gz", "wb", compresslevel=value)


@pytest.mark.parametrize(
    ("mtime", "expected"),
    [(None, None), (0, 0), (0xFFFFFFFF, 0xFFFFFFFF), (12.9, 12)],
)
def test_mtime_validation_and_header_value(mtime, expected):
    encoder = GzipEncoder(mtime=mtime)
    header = b"".join(encoder.start())

    if expected is not None:
        assert struct.unpack("<I", header[4:8])[0] == expected
    encoder.discard()


def test_mtime_none_is_sampled_when_start_advances(monkeypatch):
    encoder = GzipEncoder(mtime=None)
    monkeypatch.setattr(_common.time, "time", lambda: 987)

    header = b"".join(encoder.start())

    assert struct.unpack("<I", header[4:8])[0] == 987
    encoder.discard()


@pytest.mark.parametrize("mtime", [-0.1, -1, 0x100000000, 0x100000000 + 0.9])
def test_mtime_rejects_negative_and_uint32_overflow(mtime):
    with pytest.raises(ValueError):
        GzipEncoder(mtime=mtime)
    with pytest.raises(ValueError):
        AsyncGzipBinaryFile("unused.gz", "wb", mtime=mtime)


def test_deterministic_header_fields_and_filename():
    wire, _ = _encode(
        [b"payload"],
        mtime=123,
        original_filename="directory/events.jsonl.gz",
        compresslevel=9,
    )

    assert wire[:4] == b"\x1f\x8b\x08\x08"
    assert struct.unpack("<I", wire[4:8])[0] == 123
    assert wire[8:10] == b"\x02\xff"
    assert wire[10:].startswith(b"events.jsonl\x00")
    assert gzip.decompress(wire) == b"payload"


@pytest.mark.parametrize("filename", ["bad\x00name", b"bad\x00name"])
def test_filename_nul_is_rejected(filename):
    with pytest.raises(ValueError, match="NUL"):
        GzipEncoder(original_filename=filename)


@given(
    payload=st.binary(max_size=20_000),
    split=st.integers(min_value=1, max_value=1000),
    output_chunk_size=st.integers(min_value=1, max_value=257),
)
def test_roundtrip_arbitrary_feed_boundaries(payload, split, output_chunk_size):
    parts = [
        payload[offset : offset + split] for offset in range(0, len(payload), split)
    ]
    wire, encoder = _encode(parts, mtime=0, output_chunk_size=output_chunk_size)

    assert gzip.decompress(wire) == payload
    assert encoder.input_size == len(payload)


def test_exact_bytes_snapshot_is_zero_copy():
    data = b"exact bytes"

    assert _snapshot_bytes_input(data) is data


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

    for value in (Simple(b"simple"), Hostile(b"hostile")):
        wire, encoder = _encode([value], mtime=0)
        assert gzip.decompress(wire) == memoryview(value).tobytes()
        assert encoder.input_size == memoryview(value).nbytes


@pytest.mark.parametrize("value", [bytearray(b"x"), memoryview(b"x"), "x", 1])
def test_mutable_and_non_bytes_inputs_are_rejected_without_poisoning(value):
    encoder = GzipEncoder(mtime=0)
    header = b"".join(encoder.start())

    with pytest.raises(TypeError, match="must be bytes"):
        encoder.feed(value)
    wire = header + b"".join(encoder.feed(b"ok")) + b"".join(encoder.finish())
    assert gzip.decompress(wire) == b"ok"


def test_all_output_chunks_obey_strict_bound_across_flush_and_finish():
    encoder = GzipEncoder(mtime=0, output_chunk_size=3)
    chunks = list(encoder.start())
    chunks.extend(encoder.feed(b"payload" * 100))
    chunks.extend(encoder.flush())
    chunks.extend(encoder.feed(b"after flush"))
    chunks.extend(encoder.flush())
    chunks.extend(encoder.finish())

    assert chunks
    assert all(0 < len(chunk) <= 3 for chunk in chunks)
    assert gzip.decompress(b"".join(chunks)) == b"payload" * 100 + b"after flush"


def test_strict_size_fails_before_engine_advances():
    encoder = GzipEncoder(mtime=0, strict_size=True)
    list(encoder.start())
    encoder._input_size = 0xFFFFFFFF
    calls = []

    class SpyEngine:
        def compress(self, data):
            calls.append(data)

    encoder._engine = SpyEngine()

    with pytest.raises(OSError, match="4 GiB limit"):
        encoder.feed(b"x")

    assert calls == []
    encoder.discard()


def test_strict_size_accepts_exact_isize_boundary_without_large_allocation():
    encoder = GzipEncoder(mtime=0, strict_size=True)
    list(encoder.start())
    encoder._input_size = 0xFFFFFFFE

    list(encoder.feed(b"x"))

    assert encoder.input_size == 0xFFFFFFFF
    encoder.discard()


def test_fast_compression_selection_reaches_engine(monkeypatch):
    calls = []
    real = _engine.compressobj
    monkeypatch.setattr(_engine, "have_fast_engine", lambda: True)

    def recording(level, wbits, fast=False):
        calls.append(fast)
        return real(level, wbits, fast=False)

    monkeypatch.setattr(_engine, "compressobj", recording)
    encoder = GzipEncoder(fast_compress=True)

    assert calls == [True]
    encoder.discard()


def test_fast_compression_warns_when_engine_is_unavailable(monkeypatch):
    monkeypatch.setattr(_engine, "_HAVE_ZNG", False)

    with pytest.warns(UserWarning, match="zlib-ng is not available"):
        encoder = GzipEncoder(fast_compress=True)

    encoder.discard()


def test_engine_error_is_wrapped(monkeypatch):
    class BrokenEngine:
        def compress(self, data):
            raise RuntimeError("engine failed")

    encoder = GzipEncoder(mtime=0)
    list(encoder.start())
    encoder._engine = BrokenEngine()

    with pytest.raises(OSError, match="Unexpected error during compression"):
        list(encoder.feed(b"payload"))
    with pytest.raises(OSError, match="unusable"):
        encoder.finish()


def test_public_methods_are_synchronous():
    for name in ("start", "feed", "flush", "finish", "discard"):
        method = getattr(GzipEncoder, name)
        assert not inspect.iscoroutinefunction(method)
        assert not inspect.isasyncgenfunction(method)
