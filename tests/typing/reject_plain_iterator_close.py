"""Negative type-check fixture: an ordinary iterator has no close contract."""

from collections.abc import Iterator


def close_plain_iterator(iterator: Iterator[bytes]) -> None:
    iterator.close()
