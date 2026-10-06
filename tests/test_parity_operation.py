"""Parity matrix D1: public ``next()`` and private ``_advance_raw()`` drivers.

``_Operation.__next__`` keeps its ownership block inline instead of calling
``_advance_raw()`` (a helper frame per advancement). Every scenario runs under
both drivers and compares the projected public byte stream, the raised
exception and the codec's final state. Advancement counts are not compared:
public ``next()`` deliberately hides the private progress events, which are
checked separately for the raw driver.
"""

import gzip
import zlib

import pytest

from aiogzip import GzipDecoder, GzipEncoder
from aiogzip.codec import _CodecProgress

PAYLOAD = b"parity payload " * 64
MEMBER = gzip.compress(PAYLOAD, mtime=0)


def _corrupt_crc(data=MEMBER):
    corrupt = bytearray(data)
    corrupt[-8] ^= 1
    return bytes(corrupt)


def _drive(operation, driver):
    """Drive to completion; return (public bytes, progress events, error)."""
    output, progress = [], 0
    try:
        while True:
            if driver == "public":
                output.append(next(operation))
                continue
            item = operation._advance_raw()
            if isinstance(item, _CodecProgress):
                progress += 1
            else:
                output.append(item)
    except StopIteration:
        return b"".join(output), progress, None
    except BaseException as error:
        return b"".join(output), progress, error


def _state(codec):
    state = {
        "active": codec._active_token is not None,
        "unusable": codec._unusable,
        "discarded": codec._discarded,
        "finished": codec.finished,
    }
    if isinstance(codec, GzipEncoder):
        state.update(input_size=codec.input_size, crc32=codec.crc32)
    else:
        state.update(
            compressed_size=codec.compressed_size,
            uncompressed_size=codec.uncompressed_size,
            members=codec.member_count,
        )
    return state


class _FailingEngine:
    """Compression engine whose every call fails."""

    def compress(self, data):
        raise zlib.error("injected compression failure")

    def flush(self, mode=zlib.Z_FINISH):
        raise zlib.error("injected flush failure")


def _started_encoder(**options):
    encoder = GzipEncoder(mtime=0, **options)
    b"".join(encoder.start())
    return encoder


# Each scenario returns (codec, operation) ready to drive.


def _encoder_header():
    encoder = GzipEncoder(mtime=0, output_chunk_size=7)
    return encoder, encoder.start()


def _encoder_empty_feed():
    encoder = _started_encoder()
    return encoder, encoder.feed(b"")


def _encoder_finish():
    encoder = _started_encoder(output_chunk_size=5)
    b"".join(encoder.feed(PAYLOAD))
    return encoder, encoder.finish()


def _encoder_failure_before_output():
    encoder = _started_encoder()
    encoder._engine = _FailingEngine()
    return encoder, encoder.feed(PAYLOAD)


def _decoder_member():
    decoder = GzipDecoder(output_chunk_size=64)
    return decoder, decoder.feed(MEMBER)


def _decoder_progress_only():
    decoder = GzipDecoder()
    return decoder, decoder.feed(gzip.compress(b"", mtime=0))


def _decoder_finish():
    decoder = GzipDecoder()
    b"".join(decoder.feed(MEMBER))
    return decoder, decoder.finish()


def _decoder_failure_after_output():
    decoder = GzipDecoder(output_chunk_size=64)
    return decoder, decoder.feed(_corrupt_crc())


SCENARIOS = {
    "encoder-output": _encoder_header,
    "encoder-no-output-work": _encoder_empty_feed,
    "encoder-completion": _encoder_finish,
    "encoder-failure-before-output": _encoder_failure_before_output,
    "decoder-output": _decoder_member,
    "decoder-private-progress": _decoder_progress_only,
    "decoder-completion": _decoder_finish,
    "decoder-failure-after-output": _decoder_failure_after_output,
}


def _outcome(scenario, driver):
    codec, operation = SCENARIOS[scenario]()
    output, progress, error = _drive(operation, driver)
    error_view = None if error is None else (type(error), str(error))
    # A drained operation is single-use under either driver.
    with pytest.raises(StopIteration):
        next(operation)
    with pytest.raises(StopIteration):
        operation._advance_raw()
    return output, error_view, _state(codec), progress


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_drivers_project_the_same_bytes_error_and_state(scenario):
    public = _outcome(scenario, "public")
    raw = _outcome(scenario, "raw")
    assert public[:3] == raw[:3]
    assert public[3] == 0  # public next() never exposes progress


def test_failure_scenarios_release_ownership_and_poison():
    for scenario in ("encoder-failure-before-output", "decoder-failure-after-output"):
        for driver in ("public", "raw"):
            output, error, state, _ = _outcome(scenario, driver)
            assert error is not None
            assert state["active"] is False
            assert state["unusable"] is True
    _, error, _, _ = _outcome("decoder-failure-after-output", "public")
    assert error[0] is gzip.BadGzipFile


def test_raw_driver_exposes_progress_without_bytes():
    output, error, state, progress = _outcome("decoder-private-progress", "raw")
    assert output == b"" and error is None
    assert progress >= 1
    assert state["members"] == 1


@pytest.mark.parametrize("driver", ["public", "raw"])
def test_output_scenarios_produce_the_reference_bytes(driver):
    output, *_ = _outcome("decoder-output", driver)
    assert output == PAYLOAD
    encoder = GzipEncoder(mtime=0, output_chunk_size=5)
    wire = b""
    for operation in (encoder.start, lambda: encoder.feed(PAYLOAD), encoder.finish):
        chunk, _, error = _drive(operation(), driver)
        assert error is None
        wire += chunk
    assert gzip.decompress(wire) == PAYLOAD


# Guards: the ownership block that __next__ duplicates.


def _guard_case(case):
    encoder = GzipEncoder(mtime=0, output_chunk_size=1)
    operation = encoder.start()
    if case == "closed":
        b"".join(operation)
        operation.close()  # close after exhaustion has no effect
        expected = StopIteration
    elif case == "invalidated":
        encoder.discard()
        expected = RuntimeError
    elif case == "close-before-start":
        operation.close()
        expected = StopIteration
    elif case == "non-active":
        encoder._active_token = object()
        expected = RuntimeError
    else:  # closed by close() before exhaustion
        next(operation)
        operation.close()
        expected = StopIteration
    return encoder, operation, expected


@pytest.mark.parametrize(
    "case", ["closed", "invalidated", "non-active", "close-before-start", "early-close"]
)
def test_ownership_guards_match_between_drivers(case):
    results = []
    for driver in ("public", "raw"):
        encoder, operation, expected = _guard_case(case)
        before = _state(encoder)
        with pytest.raises(expected) as raised:
            if driver == "public":
                next(operation)
            else:
                operation._advance_raw()
        results.append((type(raised.value), str(raised.value), before, _state(encoder)))
    assert results[0] == results[1]
    # A guard rejection never changes codec state.
    assert results[0][2] == results[0][3]
    if case == "closed":
        # Closing an exhausted start() operation leaves the encoder usable.
        after = results[0][3]
        assert (after["active"], after["unusable"]) == (False, False)
    if case in ("close-before-start", "early-close"):
        # Closing before exhaustion abandons the codec under either driver.
        after = results[0][3]
        assert (after["active"], after["unusable"], after["finished"]) == (
            False,
            True,
            False,
        )


@pytest.mark.parametrize("driver", ["public", "raw"])
def test_reentrant_advancement_is_rejected_without_state_change(driver):
    encoder = _started_encoder()
    holder, caught = {}, []

    class ReentrantEngine:
        def compress(self, data):
            try:
                if driver == "public":
                    next(holder["operation"])
                else:
                    holder["operation"]._advance_raw()
            except RuntimeError as error:
                caught.append(str(error))
            return b""

    encoder._engine = ReentrantEngine()
    holder["operation"] = operation = encoder.feed(b"x")
    output, _, error = _drive(operation, driver)
    assert (output, error) == (b"", None)
    assert caught == ["gzip codec operation cannot be advanced reentrantly"]
    assert _state(encoder)["active"] is False


@pytest.mark.parametrize("driver", ["public", "raw"])
def test_discard_with_a_retained_iterator(driver):
    decoder, operation = _decoder_member()
    first = next(operation) if driver == "public" else operation._advance_raw()
    assert first
    decoder.discard()
    for advance in (lambda: next(operation), operation._advance_raw):
        with pytest.raises(RuntimeError, match="invalidated"):
            advance()
    operation.close()
    state = _state(decoder)
    assert (state["active"], state["unusable"], state["discarded"]) == (
        False,
        True,
        True,
    )
    assert state["finished"] is False


@pytest.mark.parametrize("driver", ["public", "raw"])
def test_release_ordering_on_success_and_failure(driver):
    # The token is cleared before success or failure is observable, and
    # failure releases codec state as part of the same advancement.
    seen = []
    encoder = _started_encoder()

    class Engine:
        def compress(self, data):
            return b""

    encoder._engine = Engine()
    operation = encoder.feed(b"ok")
    original_succeeded = encoder._operation_succeeded

    def succeeded(token):
        original_succeeded(token)
        seen.append(("success", encoder._active_token is None))

    encoder._operation_succeeded = succeeded
    assert _drive(operation, driver)[2] is None
    assert seen == [("success", True)]

    encoder = _started_encoder()
    encoder._engine = _FailingEngine()
    operation = encoder.feed(b"bad")
    released = []
    original_release = encoder._release_state

    def release():
        released.append(encoder._active_token is None)
        original_release()

    encoder._release_state = release
    error = _drive(operation, driver)[2]
    assert isinstance(error, OSError)
    assert released == [True]
    assert encoder._engine is None


def test_failure_after_output_scenario_really_emits_output_first():
    for driver in ("public", "raw"):
        output, error, _, _ = _outcome("decoder-failure-after-output", driver)
        assert output == PAYLOAD
        assert error is not None
    output, error, _, _ = _outcome("encoder-failure-before-output", "public")
    assert output == b"" and error[0] is OSError
