"""Deliberately invalid uses; both release type checkers must reject them."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aiogzip

path = Path("payload.gz")


async def text_source() -> AsyncIterator[str]:
    yield "payload"


async def invalid_calls() -> None:
    await aiogzip.write(path, "payload")  # EXPECT_ERROR
    await aiogzip.read(path, chunk_size="64")  # EXPECT_ERROR
    aiogzip.compress_chunks(text_source())  # EXPECT_ERROR


binary = aiogzip.open(path, "rb")
text: aiogzip.AsyncGzipTextFile = binary  # EXPECT_ERROR

plain: Iterator[bytes] = iter([b"payload"])
operation: aiogzip.CodecOperation = plain  # EXPECT_ERROR

reader: aiogzip.WithAsyncRead = object()  # EXPECT_ERROR


def mutate_member(member: aiogzip.GzipMemberInfo) -> None:
    member.index = 1  # EXPECT_ERROR
