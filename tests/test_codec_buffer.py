"""Tests for private bounded codec input and output storage."""

from __future__ import annotations

import sys

import pytest

from aiogzip._codec_buffer import _InputQueue, _OutputCursor, _Span


def test_append_tracks_length_and_retains_exact_span():
    data = b"immutable input"
    queue = _InputQueue()

    queue.append(data)

    assert len(queue) == len(data)
    assert queue._spans[0].data is data
    assert queue.peek_byte() == data[0]


def test_whole_span_take_preserves_identity():
    data = bytes(bytearray(b"whole span"))
    queue = _InputQueue()
    queue.append(data)

    assert queue.pop_window(len(data)) is data
    assert len(queue) == 0
    assert queue.peek_byte() is None


def test_partial_consumption_advances_offset_and_releases_drained_span():
    first = b"abcdef"
    second = b"ghij"
    queue = _InputQueue()
    queue.append(first)
    queue.append(second)

    queue.consume(2)
    assert queue._spans[0] == _Span(first, 2, len(first))
    assert len(queue) == 8

    queue.consume(4)
    assert queue._spans[0].data is second
    assert len(queue) == 4


def test_cross_span_take_is_bounded_and_ordered():
    queue = _InputQueue()
    for part in (b"ab", b"cde", b"fghi"):
        queue.append(part)

    assert queue.take(6) == b"abcdef"
    assert len(queue) == 3
    assert queue.take(100) == b"ghi"
    assert len(queue) == 0


def test_exact_take_failure_does_not_consume_partial_input():
    queue = _InputQueue()
    queue.append(b"abc")
    queue.append(b"de")

    assert queue.take_exact(6) is None
    assert len(queue) == 5
    assert queue.take_exact(5) == b"abcde"
    assert len(queue) == 0


def test_head_inspection_is_bounded_zero_copy_and_does_not_consume():
    first = b"abc"
    queue = _InputQueue()
    queue.append(first)
    queue.append(b"def")

    view = queue.peek_span(2)

    assert bytes(view) == b"ab"
    assert view.obj is first
    assert queue.head_size == 3
    assert queue.find_in_head(ord("b"), 3) == 1
    assert queue.find_in_head(ord("d"), 3) is None
    assert len(queue) == 6
    with pytest.raises(ValueError):
        queue.peek_span(-1)
    with pytest.raises(ValueError):
        queue.find_in_head(ord("a"), -1)


def test_prepend_orders_retained_input_before_later_spans():
    queue = _InputQueue()
    later = b"later"
    retained = b"retained"
    queue.append(later)
    queue.prepend(retained)

    assert queue.take(len(retained)) is retained
    assert queue.take(len(later)) is later


def test_repeated_small_spans_remain_ordered():
    queue = _InputQueue()
    parts = [bytes([index % 251]) for index in range(10_000)]
    for part in parts:
        queue.append(part)

    assert len(queue) == len(parts)
    assert queue.take(len(parts)) == b"".join(parts)
    assert not queue._spans


def test_leading_byte_inspection_and_consumption():
    queue = _InputQueue()
    queue.append(b"\x00\x00")
    queue.append(b"\x00abc")

    assert queue.peek_byte() == 0
    assert queue.consume_leading_zeroes() == 3
    assert queue.peek_byte() == ord("a")
    assert queue.consume_leading(ord("a")) == 1
    assert queue.take(2) == b"bc"


def test_clear_is_idempotent_and_releases_span_reference():
    data = bytes(bytearray(b"referenced input"))
    references = sys.getrefcount(data)
    queue = _InputQueue()
    queue.append(data)
    assert sys.getrefcount(data) == references + 1

    queue.clear()
    queue.clear()

    assert len(queue) == 0
    assert not queue._spans
    assert sys.getrefcount(data) == references


@pytest.mark.parametrize("value", [bytearray(b"x"), memoryview(b"x")])
@pytest.mark.parametrize("method", ["append", "prepend"])
def test_internal_input_boundary_rejects_non_exact_bytes(method, value):
    queue = _InputQueue()

    with pytest.raises(TypeError, match="exact bytes"):
        getattr(queue, method)(value)


def test_invalid_consumption_and_read_bounds_do_not_change_queue():
    queue = _InputQueue()
    queue.append(b"abc")

    for method, value in (
        (queue.consume, -1),
        (queue.consume, 4),
        (queue.take, -1),
        (queue.take_exact, -1),
        (queue.pop_window, 0),
        (queue.pop_window, -1),
    ):
        with pytest.raises(ValueError):
            method(value)
        assert len(queue) == 3


def test_output_cursor_emits_bounded_slices_and_releases_drained_block():
    block = bytes(bytearray(b"abcdefgh"))
    cursor = _OutputCursor()
    cursor.set_block(block)

    assert len(cursor) == 8
    assert cursor.pop(3) == b"abc"
    assert cursor._offset == 3
    assert cursor.pop(3) == b"def"
    assert cursor.pop(3) == b"gh"
    assert len(cursor) == 0
    assert cursor._block is None
    assert cursor.pop(3) is None


def test_output_cursor_reuses_whole_block_and_guards_replacement():
    first = bytes(bytearray(b"first"))
    second = b"second"
    cursor = _OutputCursor()
    cursor.set_block(first)

    with pytest.raises(RuntimeError, match="not drained"):
        cursor.set_block(second)
    assert cursor.pop(100) is first

    cursor.set_block(second)
    cursor.clear()
    cursor.clear()
    assert len(cursor) == 0


def test_output_cursor_rejects_non_exact_bytes_and_invalid_bound():
    cursor = _OutputCursor()
    with pytest.raises(TypeError, match="exact bytes"):
        cursor.set_block(bytearray(b"x"))

    cursor.set_block(b"x")
    with pytest.raises(ValueError):
        cursor.pop(0)
    assert len(cursor) == 1
