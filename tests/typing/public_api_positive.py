"""Positive static assertions for the frozen aiogzip 2.0 public API."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Union, assert_type

import aiogzip


class Reader:
    async def read(self, size: int = -1) -> bytes:
        return b"" if size else b""


class Writer:
    async def write(self, data: str | bytes) -> int:
        return len(data)


class ReaderWriter:
    async def read(self, size: int = -1) -> bytes:
        return b"" if size else b""

    async def write(self, data: str | bytes) -> int:
        return len(data)

    async def close(self) -> None:
        return None


path = Path("payload.gz")

# Conventional mode literals and permutations retain mode-sensitive narrowing.
assert_type(aiogzip.open(path), aiogzip.AsyncGzipBinaryFile)
assert_type(aiogzip.open(path, "rb"), aiogzip.AsyncGzipBinaryFile)
assert_type(aiogzip.open(path, "br"), aiogzip.AsyncGzipBinaryFile)
assert_type(aiogzip.open(path, "r+b"), aiogzip.AsyncGzipBinaryFile)
assert_type(aiogzip.open(path, "+wb"), aiogzip.AsyncGzipBinaryFile)
assert_type(aiogzip.open(path, "rt"), aiogzip.AsyncGzipTextFile)
assert_type(aiogzip.open(path, "tr"), aiogzip.AsyncGzipTextFile)
assert_type(aiogzip.open(path, "r+t"), aiogzip.AsyncGzipTextFile)
assert_type(aiogzip.open(path, "+wt"), aiogzip.AsyncGzipTextFile)

assert_type(aiogzip.AsyncGzipFile(path), aiogzip.AsyncGzipBinaryFile)
assert_type(aiogzip.AsyncGzipFile(path, "ab"), aiogzip.AsyncGzipBinaryFile)
assert_type(aiogzip.AsyncGzipFile(path, "at"), aiogzip.AsyncGzipTextFile)


def dynamic_mode(mode: str) -> None:
    assert_type(
        aiogzip.open(path, mode),
        Union[aiogzip.AsyncGzipBinaryFile, aiogzip.AsyncGzipTextFile],
    )
    assert_type(
        aiogzip.AsyncGzipFile(path, mode),
        Union[aiogzip.AsyncGzipBinaryFile, aiogzip.AsyncGzipTextFile],
    )


async def source() -> AsyncIterator[bytes]:
    yield b"payload"


async def whole_file_contract() -> None:
    assert_type(await aiogzip.read(path), bytes)
    assert_type(await aiogzip.write(path, b"payload"), None)
    assert_type(await aiogzip.write(path, bytearray(b"payload")), None)
    assert_type(await aiogzip.write(path, memoryview(b"payload")), None)
    assert_type(await aiogzip.inspect(path), aiogzip.GzipInfo)
    assert_type(await aiogzip.verify(path), aiogzip.VerificationResult)


def streaming_contract() -> None:
    assert_type(aiogzip.decompress_chunks(source()), AsyncIterator[bytes])
    assert_type(aiogzip.compress_chunks(source()), AsyncIterator[bytes])


def codec_contract() -> None:
    encoder = aiogzip.GzipEncoder(mtime=0)
    decoder = aiogzip.GzipDecoder()
    operations = (
        encoder.start(),
        encoder.feed(b"payload"),
        encoder.flush(),
        encoder.finish(),
        decoder.feed(b"compressed"),
        decoder.finish(),
    )
    for operation in operations:
        assert_type(operation, aiogzip.CodecOperation)
        iterator: Iterator[bytes] = operation
        del iterator
        assert_type(operation.close(), None)


def dataclass_contract(
    engine: aiogzip.EngineInfo,
    member: aiogzip.GzipMemberInfo,
    info: aiogzip.GzipInfo,
    verification: aiogzip.VerificationResult,
) -> None:
    assert_type(engine.compression, str)
    assert_type(engine.decompression, str)
    assert_type(engine.crc32, str)
    assert_type(member.index, int)
    assert_type(member.compressed_offset, int)
    assert_type(member.compressed_size, int)
    assert_type(member.uncompressed_size, int)
    assert_type(member.mtime, int)
    assert_type(member.original_filename, str | None)
    assert_type(member.comment, str | None)
    assert_type(member.extra, bytes | None)
    assert_type(member.flags, int)
    assert_type(member.crc32, int)
    assert_type(member.trailer_isize, int)
    assert_type(info.members, tuple[aiogzip.GzipMemberInfo, ...])
    assert_type(info.compressed_size, int)
    assert_type(info.uncompressed_size, int)
    assert_type(info.member_count, int)
    assert_type(verification.member_count, int)
    assert_type(verification.compressed_size, int)
    assert_type(verification.uncompressed_size, int)


def protocol_contract() -> None:
    reader: aiogzip.WithAsyncRead = Reader()
    writer: aiogzip.WithAsyncWrite = Writer()
    reader_writer: aiogzip.WithAsyncReadWrite = ReaderWriter()
    del reader, writer, reader_writer


def diagnostic_contract() -> None:
    version: str = aiogzip.__version__
    del version
    assert_type(aiogzip.engine_info(), aiogzip.EngineInfo)
