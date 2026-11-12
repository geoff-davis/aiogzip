"""Positive static assertions for the frozen aiogzip 2.0 public API."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path, PurePosixPath
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


class BytesSink:
    """A binary sink: it accepts only bytes, under its own parameter name."""

    async def write(self, b: bytes) -> int:
        return len(b)


class PositionalBytesSink:
    async def write(self, data: bytes, /) -> int:
        return len(data)


class StrPath:
    def __fspath__(self) -> str:
        return "payload.gz"


class BytesPath:
    def __fspath__(self) -> bytes:
        return b"payload.gz"


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


async def path_contract(
    str_path_like: os.PathLike[str], bytes_path_like: os.PathLike[bytes]
) -> None:
    # Every public filename accepts what the runtime does: any os.PathLike.
    pure = PurePosixPath("payload.gz")
    assert_type(aiogzip.open(pure, "rb"), aiogzip.AsyncGzipBinaryFile)
    assert_type(aiogzip.open(StrPath(), "rt"), aiogzip.AsyncGzipTextFile)
    assert_type(aiogzip.open(BytesPath(), "wb"), aiogzip.AsyncGzipBinaryFile)
    assert_type(aiogzip.open(str_path_like), aiogzip.AsyncGzipBinaryFile)
    assert_type(aiogzip.open(bytes_path_like, "wt"), aiogzip.AsyncGzipTextFile)
    assert_type(aiogzip.AsyncGzipFile(pure, "rt"), aiogzip.AsyncGzipTextFile)
    assert_type(aiogzip.AsyncGzipFile(StrPath()), aiogzip.AsyncGzipBinaryFile)
    assert_type(aiogzip.AsyncGzipBinaryFile(pure), aiogzip.AsyncGzipBinaryFile)
    assert_type(aiogzip.AsyncGzipTextFile(BytesPath()), aiogzip.AsyncGzipTextFile)
    assert_type(await aiogzip.read(pure), bytes)
    assert_type(await aiogzip.read(StrPath()), bytes)
    assert_type(await aiogzip.read(str_path_like), bytes)
    assert_type(await aiogzip.read(bytes_path_like), bytes)
    assert_type(await aiogzip.write(pure, b"payload"), None)
    assert_type(await aiogzip.write(BytesPath(), b"payload"), None)
    assert_type(await aiogzip.inspect(pure), aiogzip.GzipInfo)
    assert_type(await aiogzip.inspect(str_path_like), aiogzip.GzipInfo)
    assert_type(await aiogzip.verify(pure), aiogzip.VerificationResult)
    assert_type(await aiogzip.verify(StrPath()), aiogzip.VerificationResult)
    assert_type(await aiogzip.verify(str_path_like), aiogzip.VerificationResult)


def name_contract() -> None:
    # The name annotation is as released; widening it would break callers.
    assert_type(aiogzip.open(path).name, str | bytes | Path | None)
    assert_type(aiogzip.open(path, "rt").name, str | bytes | Path | None)
    binary_name: str | bytes | Path | None = aiogzip.AsyncGzipBinaryFile(
        PurePosixPath("payload.gz")
    ).name
    text_name: str | bytes | Path | None = aiogzip.AsyncGzipTextFile(StrPath()).name
    del binary_name, text_name


async def fileobj_contract() -> None:
    # A sink only ever receives bytes, so a binary-only write() satisfies it.
    # An aiofiles binary handle has this shape. The fixture does not import
    # aiofiles: ty cannot resolve it in the minimum-dependencies CI legs.
    handle = BytesSink()
    assert_type(await aiogzip.write(None, b"payload", fileobj=handle), None)
    assert_type(aiogzip.open(None, "wb", fileobj=handle), aiogzip.AsyncGzipBinaryFile)
    assert_type(aiogzip.open(None, "wt", fileobj=handle), aiogzip.AsyncGzipTextFile)
    for sink in (BytesSink(), PositionalBytesSink(), Writer(), ReaderWriter()):
        assert_type(await aiogzip.write(None, b"payload", fileobj=sink), None)
    assert_type(
        aiogzip.open(None, "wb", fileobj=BytesSink()), aiogzip.AsyncGzipBinaryFile
    )
    assert_type(
        aiogzip.open(None, "wb", fileobj=PositionalBytesSink()),
        aiogzip.AsyncGzipBinaryFile,
    )
    assert_type(
        aiogzip.AsyncGzipFile(None, "wt", fileobj=BytesSink()),
        aiogzip.AsyncGzipTextFile,
    )


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


async def protocol_consumer_contract(
    writer: aiogzip.WithAsyncWrite, reader_writer: aiogzip.WithAsyncReadWrite
) -> None:
    # The public protocols are as released: write() takes str or bytes, and
    # ``data`` by keyword. Both remain valid sinks.
    assert_type(await writer.write(data=b"payload"), int)
    assert_type(await writer.write("payload"), int)
    assert_type(await reader_writer.write(data="payload"), int)
    assert_type(await reader_writer.write(b"payload"), int)
    assert_type(await aiogzip.write(None, b"payload", fileobj=writer), None)
    assert_type(await aiogzip.write(None, b"payload", fileobj=reader_writer), None)
    assert_type(aiogzip.open(None, "wb", fileobj=writer), aiogzip.AsyncGzipBinaryFile)
    assert_type(
        aiogzip.open(None, "wt", fileobj=reader_writer), aiogzip.AsyncGzipTextFile
    )


def diagnostic_contract() -> None:
    version: str = aiogzip.__version__
    del version
    assert_type(aiogzip.engine_info(), aiogzip.EngineInfo)
