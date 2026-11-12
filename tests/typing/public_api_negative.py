"""Deliberately invalid uses; both release type checkers must reject them.

Each expected-error marker names the exact error code per checker
(tests/_typing_contract.py); no other diagnostic may be reported.
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aiogzip

# Markers must stay on the line that reports the error.
# fmt: off
path = Path("payload.gz")


async def text_source() -> AsyncIterator[str]:
    yield "payload"


class NoCountSink:
    async def write(self, data: bytes) -> None:
        return None


class TextSink:
    async def write(self, data: str) -> int:
        return len(data)


async def invalid_calls() -> None:
    await aiogzip.write(None, b"payload", fileobj=NoCountSink())  # EXPECT_ERROR[mypy=arg-type, ty=invalid-argument-type]
    await aiogzip.write(None, b"payload", fileobj=TextSink())  # EXPECT_ERROR[mypy=arg-type, ty=invalid-argument-type]
    await aiogzip.read(3)  # EXPECT_ERROR[mypy=arg-type, ty=invalid-argument-type]
    await aiogzip.write(path, "payload")  # EXPECT_ERROR[mypy=arg-type, ty=invalid-argument-type]
    await aiogzip.read(path, chunk_size="64")  # EXPECT_ERROR[mypy=arg-type, ty=invalid-argument-type]
    aiogzip.compress_chunks(text_source())  # EXPECT_ERROR[mypy=arg-type, ty=invalid-argument-type]


binary = aiogzip.open(path, "rb")
text: aiogzip.AsyncGzipTextFile = binary  # EXPECT_ERROR[mypy=assignment, ty=invalid-assignment]

plain: Iterator[bytes] = iter([b"payload"])
operation: aiogzip.CodecOperation = plain  # EXPECT_ERROR[mypy=assignment, ty=invalid-assignment]

no_count: aiogzip.WithAsyncWrite = NoCountSink()  # EXPECT_ERROR[mypy=assignment, ty=invalid-assignment]

reader: aiogzip.WithAsyncRead = object()  # EXPECT_ERROR[mypy=assignment, ty=invalid-assignment]


def mutate_member(member: aiogzip.GzipMemberInfo) -> None:
    member.index = 1  # EXPECT_ERROR[mypy=misc, ty=invalid-assignment]
