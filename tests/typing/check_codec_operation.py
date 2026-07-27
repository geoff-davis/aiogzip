"""Positive static-typing assertions for public codec operations."""

from collections.abc import Iterator

import aiogzip


def decode(data: bytes) -> bytes:
    decoder = aiogzip.GzipDecoder()
    operation: aiogzip.CodecOperation = decoder.feed(data)
    iterator: Iterator[bytes] = operation
    try:
        output = b"".join(iterator)
    finally:
        operation.close()

    final_operation: aiogzip.CodecOperation = decoder.finish()
    try:
        return output + b"".join(final_operation)
    finally:
        final_operation.close()
