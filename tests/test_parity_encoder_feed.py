"""Parity matrix D2: public ``feed()`` and private ``_feed_snapshot()``.

The file writer snapshots its input and calls ``_feed_snapshot`` directly,
repeating ``feed()``'s preconditions inline to avoid three helper frames per
small write. The private adapter mirrors that caller: snapshot first, then
``_feed_snapshot``.

Precedence is characterized before anything else. ``feed()`` checks, in
order: active operation, unusable, finished, unstarted, input type, strict
size. A refactor that delegated ``feed()`` as snapshot-then-private-feed
would move the type check ahead of the state checks; the pairwise test fails
if that happens.
"""

import gzip
import itertools
import zlib

import pytest

from aiogzip import GzipEncoder
from aiogzip.codec import _snapshot_bytes_input

ISIZE_MAX = 0xFFFFFFFF


def _public(encoder, data):
    return encoder.feed(data)


def _private(encoder, data):
    return encoder._feed_snapshot(_snapshot_bytes_input(data))


ADAPTERS = {"public": _public, "private": _private}


def _started(**options):
    encoder = GzipEncoder(mtime=0, **options)
    b"".join(encoder.start())
    return encoder


# Precedence


ACTIVE = (RuntimeError, "active operation")
UNUSABLE = (OSError, "unusable")
FINISHED = (ValueError, "already finalized")
UNSTARTED = (ValueError, "must be started")
BAD_TYPE = (TypeError, "must be bytes")
OVERSIZE = (OSError, "4 GiB limit")
ORDER = [ACTIVE, UNUSABLE, FINISHED, UNSTARTED, BAD_TYPE, OVERSIZE]


def _encoder_violating(violations):
    encoder = GzipEncoder(mtime=0, strict_size=True)
    encoder._started = UNSTARTED not in violations
    if FINISHED in violations:
        encoder._finished = True
    if UNUSABLE in violations:
        encoder._unusable = True
    if ACTIVE in violations:
        encoder._active_token = object()
    if OVERSIZE in violations:
        encoder._input_size = ISIZE_MAX
    data = bytearray(b"x") if BAD_TYPE in violations else b"x"
    return encoder, data


@pytest.mark.parametrize(
    "violations",
    list(itertools.combinations(ORDER, 2)),
    ids=lambda pair: "+".join(v[1].split()[0] for v in pair),
)
def test_public_feed_reports_the_first_violation_in_order(violations):
    encoder, data = _encoder_violating(violations)
    expected = violations[0]  # combinations preserve ORDER
    with pytest.raises(expected[0], match=expected[1]):
        encoder.feed(data)
    assert encoder._active_token is None or ACTIVE in violations


STATE_ORDER = [v for v in ORDER if v is not BAD_TYPE]


@pytest.mark.parametrize(
    "violations",
    list(itertools.combinations(STATE_ORDER, 2)),
    ids=lambda pair: "+".join(v[1].split()[0] for v in pair),
)
def test_private_feed_keeps_the_public_state_order(violations):
    # The private path receives an exact snapshot, so input type is the
    # caller's concern; every state check keeps the public order.
    encoder, data = _encoder_violating(violations)
    expected = violations[0]
    with pytest.raises(expected[0], match=expected[1]):
        encoder._feed_snapshot(data)


def test_private_adapter_checks_type_before_state():
    # Recorded difference: the writer snapshots before reserving, so for the
    # private adapter an invalid type wins over an active operation. The
    # public method must not inherit this order (see the pairwise test).
    encoder, data = _encoder_violating([ACTIVE, BAD_TYPE])
    with pytest.raises(TypeError):
        _private(encoder, data)


# Preconditions and boundaries, compared across adapters


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("violation", [ACTIVE, UNUSABLE, FINISHED, UNSTARTED])
def test_single_precondition_failures_match(adapter, violation):
    encoder, data = _encoder_violating([violation])
    before = dict(vars(encoder))
    with pytest.raises(violation[0], match=violation[1]):
        ADAPTERS[adapter](encoder, data)
    assert vars(encoder) == before


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_strict_size_boundary(adapter):
    encoder = _started(strict_size=True)
    encoder._input_size = ISIZE_MAX - 3
    with pytest.raises(OSError, match="4 GiB limit"):
        ADAPTERS[adapter](encoder, b"abcd")
    assert encoder._active_token is None
    assert encoder._unusable is False
    operation = ADAPTERS[adapter](encoder, b"abc")
    b"".join(operation)
    assert encoder.input_size == ISIZE_MAX


def _capture_feed(encoder):
    captured = []
    original = encoder._feed

    def feed(data):
        captured.append(data)
        return original(data)

    encoder._feed = feed
    return captured


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_exact_bytes_pass_through_without_copy(adapter):
    encoder = _started()
    captured = _capture_feed(encoder)
    data = b"exact payload" * 10
    b"".join(ADAPTERS[adapter](encoder, data))
    assert captured[0] is data


class _Hostile(bytes):
    def __bytes__(self):
        raise AssertionError("__bytes__ called")

    def __len__(self):
        raise AssertionError("__len__ called")

    def __iter__(self):
        raise AssertionError("__iter__ called")

    def __getitem__(self, index):
        raise AssertionError("__getitem__ called")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_hostile_subclass_is_snapshotted_without_overrides(adapter):
    encoder = _started()
    captured = _capture_feed(encoder)
    wire = b"".join(ADAPTERS[adapter](encoder, _Hostile(b"hostile")))
    assert type(captured[0]) is bytes
    assert captured[0] == b"hostile"
    wire += b"".join(encoder.finish())
    header = b"".join(GzipEncoder(mtime=0).start())
    assert gzip.decompress(header + wire) == b"hostile"


@pytest.mark.parametrize("data", [bytearray(b"x"), memoryview(b"x"), "x", None])
def test_public_feed_rejects_mutable_and_non_bytes_input(data):
    encoder = _started()
    with pytest.raises(TypeError, match="must be bytes"):
        encoder.feed(data)
    assert encoder._active_token is None
    assert encoder._unusable is False


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_snapshot_failure_reserves_nothing(adapter):
    encoder = _started()
    with pytest.raises(TypeError):
        ADAPTERS[adapter](encoder, bytearray(b"x"))
    assert encoder._active_token is None
    b"".join(encoder.feed(b"still usable"))


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_reservation_and_counter_timing(adapter):
    encoder = _started()
    operation = ADAPTERS[adapter](encoder, b"counted")
    # Reserved at call time; counters move only when the operation advances.
    assert encoder._active_token is operation
    assert (encoder.input_size, encoder.crc32) == (0, 0)
    with pytest.raises(RuntimeError, match="active operation"):
        encoder.flush()
    b"".join(operation)
    assert encoder._active_token is None
    assert encoder.input_size == len(b"counted")
    assert encoder.crc32 == zlib.crc32(b"counted")


def test_adapters_produce_identical_members():
    members = []
    for adapter in ADAPTERS.values():
        encoder = GzipEncoder(mtime=0, output_chunk_size=3)
        wire = b"".join(encoder.start())
        for piece in (b"alpha ", _Hostile(b"beta "), b"", b"gamma" * 100):
            wire += b"".join(adapter(encoder, piece))
        wire += b"".join(encoder.finish())
        members.append(wire)
    assert members[0] == members[1]
    assert gzip.decompress(members[0]) == b"alpha beta " + b"gamma" * 100
