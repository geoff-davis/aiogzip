"""Deterministic regression tests for bounded decoder body processing."""

from __future__ import annotations

import gc
import gzip
import hashlib
import struct
import tracemalloc
import weakref
import zlib
from typing import Any

import pytest

import aiogzip.codec as codec_module
from aiogzip import GzipDecoder, _engine


def _payload(size: int) -> bytes:
    return hashlib.shake_256(b"aiogzip-a2-body-regression").digest(size)


def _decode(wire: bytes, input_size: int, output_size: int = 64 * 1024) -> bytes:
    decoder = GzipDecoder(output_chunk_size=output_size)
    output = bytearray()
    for offset in range(0, len(wire), input_size):
        output.extend(b"".join(decoder.feed(wire[offset : offset + input_size])))
    output.extend(b"".join(decoder.finish()))
    return bytes(output)


def _fake_wire(body: bytes, output: bytes) -> bytes:
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
    trailer = struct.pack("<II", zlib.crc32(output) & 0xFFFFFFFF, len(output))
    return header + body + trailer


class _RecordingEngine:
    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped
        self.input_lengths: list[int] = []
        self.output_lengths: list[int] = []
        self.max_lengths: list[int] = []

    def decompress(self, data: bytes, max_length: int = 0) -> bytes:
        self.input_lengths.append(len(data))
        self.max_lengths.append(max_length)
        output = self.wrapped.decompress(data, max_length=max_length)
        self.output_lengths.append(len(output))
        return output

    def __getattr__(self, name: str) -> Any:
        return getattr(self.wrapped, name)


def _record_engines(monkeypatch) -> list[_RecordingEngine]:
    original = _engine.decompressobj
    engines: list[_RecordingEngine] = []

    def create(wbits: int) -> _RecordingEngine:
        engine = _RecordingEngine(original(wbits))
        engines.append(engine)
        return engine

    monkeypatch.setattr(_engine, "decompressobj", create)
    return engines


@pytest.mark.parametrize("input_size", [1, 1024, 64 * 1024, 256 * 1024])
def test_one_large_feed_matches_transport_boundaries(input_size):
    payload = _payload(128 * 1024)
    wire = gzip.compress(payload, mtime=0)

    assert _decode(wire, input_size) == _decode(wire, len(wire) + 1) == payload


@pytest.mark.parametrize("output_size", [1, 1024, 64 * 1024, 256 * 1024])
def test_every_public_output_bound_is_strict(output_size):
    payload = b"bounded output" * 20_000
    wire = gzip.compress(payload, mtime=0)
    decoder = GzipDecoder(output_chunk_size=output_size)

    chunks = list(decoder.feed(wire))
    chunks.extend(decoder.finish())

    assert b"".join(chunks) == payload
    assert chunks
    assert max(map(len, chunks)) <= output_size


def test_tiny_public_chunks_do_not_multiply_inflate_calls(monkeypatch):
    payload = _payload(128 * 1024)
    wire = gzip.compress(payload, mtime=0)
    engines = _record_engines(monkeypatch)

    assert _decode(wire, len(wire) + 1, output_size=1) == payload
    tiny_calls = len(engines[-1].input_lengths)
    assert _decode(wire, len(wire) + 1, output_size=256 * 1024) == payload
    large_calls = len(engines[-1].input_lengths)

    assert tiny_calls == large_calls
    assert tiny_calls <= 3


def test_retained_non_eof_input_is_replayed_once_in_order(monkeypatch):
    payload = b"AB"
    wire = _fake_wire(b"BODY", payload)

    class RetainingEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def __init__(self) -> None:
            self.inputs: list[bytes] = []

        def decompress(self, data: bytes, max_length: int = 0) -> bytes:
            self.inputs.append(data)
            if len(self.inputs) == 1:
                self.unconsumed_tail = data[2:]
                return b"A"
            self.eof = True
            self.unused_data = data[2:]
            self.unconsumed_tail = data[2:]
            return b"B"

    engine = RetainingEngine()
    monkeypatch.setattr(_engine, "decompressobj", lambda wbits: engine)

    assert _decode(wire, len(wire) + 1, output_size=1) == payload
    assert engine.inputs == [b"BODY" + wire[-8:], b"DY" + wire[-8:]]


def test_eof_retained_trailer_precedes_later_queued_spans(monkeypatch):
    first_payload = b"A"
    first = _fake_wire(b"X", first_payload)
    second_payload = b"second"
    second = gzip.compress(second_payload, mtime=0)
    original = _engine.decompressobj
    created = 0

    class FirstEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def decompress(self, data: bytes, max_length: int = 0) -> bytes:
            self.eof = True
            self.unused_data = data[1:]
            self.unconsumed_tail = data[1:]
            return first_payload

    def create(wbits: int):
        nonlocal created
        created += 1
        return FirstEngine() if created == 1 else original(wbits)

    monkeypatch.setattr(_engine, "decompressobj", create)
    decoder = GzipDecoder()

    output = bytearray(b"".join(decoder.feed(first[:-4])))
    output.extend(b"".join(decoder.feed(first[-4:] + second)))
    output.extend(b"".join(decoder.finish()))

    assert bytes(output) == first_payload + second_payload
    assert decoder.member_count == 2


def test_one_input_window_can_contain_two_complete_members():
    payloads = (b"first" * 100, b"second" * 100)
    wire = b"".join(gzip.compress(payload, mtime=0) for payload in payloads)

    assert _decode(wire, len(wire) + 1) == b"".join(payloads)


def test_eof_output_block_drains_before_trailer_validation():
    payload = b"output before CRC" * 1000
    wire = bytearray(gzip.compress(payload, mtime=0))
    wire[-8] ^= 1
    decoder = GzipDecoder(output_chunk_size=7)
    operation = decoder.feed(bytes(wire))
    output = bytearray()

    with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
        while True:
            output.extend(next(operation))

    assert bytes(output) == payload
    assert decoder.uncompressed_size == len(payload)


@pytest.mark.parametrize("cleanup", ["close", "discard"])
def test_cleanup_releases_pending_output_and_input(cleanup):
    payload = b"pending output" * 100_000
    decoder = GzipDecoder(output_chunk_size=1)
    operation = decoder.feed(gzip.compress(payload, mtime=0))

    assert next(operation) == payload[:1]
    assert len(decoder._output) > 0
    if cleanup == "close":
        operation.close()
        with pytest.raises(OSError, match="unusable"):
            decoder.finish()
    else:
        decoder.discard()
        with pytest.raises(RuntimeError, match="invalidated"):
            next(operation)

    assert len(decoder._pending) == 0
    assert decoder._inflate_input is None
    assert len(decoder._output) == 0


def test_exact_limit_is_emitted_before_later_overflow_error():
    payload = b"limit payload" * 50_000
    limit = 100_003
    decoder = GzipDecoder(
        output_chunk_size=64 * 1024,
        max_decompressed_size=limit,
    )
    operation = decoder.feed(gzip.compress(payload, mtime=0))
    output = bytearray()

    while len(output) < limit:
        output.extend(next(operation))
    assert len(output) == limit
    assert bytes(output) == payload[:limit]
    assert decoder.uncompressed_size == limit
    assert decoder._member_size == limit
    assert decoder._member_crc == zlib.crc32(payload[:limit])

    with pytest.raises(OSError, match="max_decompressed_size"):
        next(operation)
    assert decoder.uncompressed_size == limit
    assert decoder._member_size == limit
    assert decoder._member_crc == zlib.crc32(payload[:limit])


def test_fake_engine_output_with_zero_consumption_makes_progress(monkeypatch):
    payload = b"AB"
    wire = _fake_wire(b"X", payload)

    class ZeroConsumptionEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""
        calls = 0

        def decompress(self, data: bytes, max_length: int = 0) -> bytes:
            self.calls += 1
            if self.calls == 1:
                self.unconsumed_tail = data
                return b"A"
            self.eof = True
            self.unused_data = data[1:]
            self.unconsumed_tail = data[1:]
            return b"B"

    engine = ZeroConsumptionEngine()
    monkeypatch.setattr(_engine, "decompressobj", lambda wbits: engine)

    assert _decode(wire, len(wire) + 1, output_size=1) == payload
    assert engine.calls == 2


def test_fake_engine_without_output_or_consumption_fails(monkeypatch):
    wire = _fake_wire(b"X", b"")

    class StalledEngine:
        eof = False
        unused_data = b""
        unconsumed_tail = b""

        def decompress(self, data: bytes, max_length: int = 0) -> bytes:
            self.unconsumed_tail = data
            return b""

    monkeypatch.setattr(_engine, "decompressobj", lambda wbits: StalledEngine())

    with pytest.raises(OSError, match="made no progress"):
        _decode(wire, len(wire) + 1)


def test_engine_input_never_exceeds_private_window(monkeypatch):
    window = 31
    monkeypatch.setattr(codec_module, "_INFLATE_INPUT_WINDOW", window)
    engines = _record_engines(monkeypatch)
    payload = _payload(4096)

    assert _decode(gzip.compress(payload, mtime=0), 4096) == payload
    assert engines
    assert max(engines[0].input_lengths) <= window


def test_internal_output_never_exceeds_private_batch(monkeypatch):
    batch = 31
    monkeypatch.setattr(codec_module, "_INFLATE_OUTPUT_BATCH", batch)
    engines = _record_engines(monkeypatch)
    payload = b"A" * 4096

    assert _decode(gzip.compress(payload, mtime=0), 4096, output_size=1) == payload
    assert engines
    assert max(engines[0].output_lengths) <= batch
    assert all(0 < length <= batch for length in engines[0].max_lengths)


def test_completed_decoder_stress_retains_no_instances_spans_or_output_blocks():
    payload = _payload(32 * 1024)
    wire = gzip.compress(payload, mtime=0)
    decoder_refs = []
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()

    try:
        for _ in range(250):
            decoder = GzipDecoder(output_chunk_size=31)
            feed_operation = decoder.feed(wire)
            output = b"".join(feed_operation)
            finish_operation = decoder.finish()
            output += b"".join(finish_operation)

            assert output == payload
            assert len(decoder._pending) == 0
            assert decoder._inflate_input is None
            assert len(decoder._output) == 0
            assert decoder._engine is None
            decoder_refs.append(weakref.ref(decoder))
            del feed_operation, finish_operation, decoder

        gc.collect()
        retained, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert all(reference() is None for reference in decoder_refs)
    assert retained - baseline < 512 * 1024
