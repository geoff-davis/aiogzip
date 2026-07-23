"""Deterministic ownership and abandonment tests for codec operations."""

import gc
import gzip

import pytest

from aiogzip import GzipDecoder, GzipEncoder


def test_encoder_requires_start_and_transitions_once():
    encoder = GzipEncoder(mtime=0)

    with pytest.raises(ValueError, match="must be started"):
        encoder.feed(b"payload")
    with pytest.raises(ValueError, match="must be started"):
        encoder.flush()
    with pytest.raises(ValueError, match="must be started"):
        encoder.finish()

    list(encoder.start())
    with pytest.raises(ValueError, match="already started"):
        encoder.start()
    list(encoder.feed(b"payload"))
    list(encoder.flush())
    list(encoder.flush())
    list(encoder.finish())
    with pytest.raises(ValueError, match="already finalized"):
        encoder.finish()


@pytest.mark.parametrize("kind", ["encoder", "decoder"])
def test_concurrent_operation_is_rejected(kind):
    if kind == "encoder":
        codec = GzipEncoder(mtime=0)
        operation = codec.start()
        competing = codec.start
    else:
        codec = GzipDecoder()
        operation = codec.feed(gzip.compress(b"payload", mtime=0))
        competing = codec.finish

    with pytest.raises(RuntimeError, match="active operation"):
        competing()
    list(operation)
    codec.discard()


@pytest.mark.parametrize("partially_advanced", [False, True])
def test_dropped_encoder_operation_stays_reserved_across_gc(partially_advanced):
    encoder = GzipEncoder(mtime=0, output_chunk_size=1)
    operation = encoder.start()
    if partially_advanced:
        assert next(operation)

    enabled = gc.isenabled()
    gc.disable()
    try:
        del operation
        with pytest.raises(RuntimeError, match="active operation"):
            encoder.start()
        gc.collect()
        with pytest.raises(RuntimeError, match="active operation"):
            encoder.start()
    finally:
        if enabled:
            gc.enable()
        encoder.discard()


@pytest.mark.parametrize("partially_advanced", [False, True])
def test_dropped_decoder_operation_stays_reserved_across_gc(partially_advanced):
    decoder = GzipDecoder(output_chunk_size=1)
    operation = decoder.feed(gzip.compress(b"payload", mtime=0))
    if partially_advanced:
        assert next(operation)

    enabled = gc.isenabled()
    gc.disable()
    try:
        del operation
        with pytest.raises(RuntimeError, match="active operation"):
            decoder.finish()
        gc.collect()
        with pytest.raises(RuntimeError, match="active operation"):
            decoder.finish()
    finally:
        if enabled:
            gc.enable()
        decoder.discard()


@pytest.mark.parametrize("partially_advanced", [False, True])
@pytest.mark.parametrize("kind", ["encoder", "decoder"])
def test_discard_invalidates_retained_operations(kind, partially_advanced):
    if kind == "encoder":
        codec = GzipEncoder(mtime=0, output_chunk_size=1)
        operation = codec.start()
    else:
        codec = GzipDecoder(output_chunk_size=1)
        operation = codec.feed(gzip.compress(b"payload", mtime=0))
    if partially_advanced:
        assert next(operation)

    codec.discard()
    state = vars(codec).copy()

    with pytest.raises(RuntimeError, match="invalidated"):
        next(operation)
    assert vars(codec) == state
    operation.close()
    operation.close()
    assert vars(codec) == state


@pytest.mark.parametrize("partially_advanced", [False, True])
@pytest.mark.parametrize("kind", ["encoder", "decoder"])
def test_early_close_poisons_codec(kind, partially_advanced):
    if kind == "encoder":
        codec = GzipEncoder(mtime=0, output_chunk_size=1)
        operation = codec.start()
        next_call = codec.start
    else:
        codec = GzipDecoder(output_chunk_size=1)
        operation = codec.feed(gzip.compress(b"payload", mtime=0))
        next_call = codec.finish

    if partially_advanced:
        next(operation)
    operation.close()

    with pytest.raises(OSError, match="unusable"):
        next_call()


def test_reentrant_advancement_raises_runtime_error_at_inner_call():
    encoder = GzipEncoder(mtime=0)
    list(encoder.start())
    operation_holder = {}
    caught = []

    class ReentrantEngine:
        def compress(self, data):
            try:
                next(operation_holder["operation"])
            except RuntimeError as error:
                caught.append(str(error))
            return b""

    encoder._engine = ReentrantEngine()
    operation = encoder.feed(b"payload")
    operation_holder["operation"] = operation

    assert list(operation) == []
    assert caught == ["gzip codec operation cannot be advanced reentrantly"]
    encoder.discard()


def test_exhausted_operation_is_single_use():
    encoder = GzipEncoder(mtime=0)
    operation = encoder.start()

    assert list(operation)
    with pytest.raises(StopIteration):
        next(operation)
    encoder.discard()


@pytest.mark.parametrize("kind", ["encoder", "decoder"])
def test_discard_is_idempotent(kind):
    codec = GzipEncoder() if kind == "encoder" else GzipDecoder()

    codec.discard()
    codec.discard()

    with pytest.raises(OSError, match="unusable"):
        codec.start() if kind == "encoder" else codec.finish()
