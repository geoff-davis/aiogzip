"""Static-typing assertions for the ``AsyncGzipFile`` factory overloads.

This module is not run as a test (``assert_type`` is a no-op at runtime); it is
type-checked with ``mypy --strict`` by ``tests/test_factory_typing.py``. Each
``assert_type`` fails the type check if the factory does not narrow its return
type by mode.
"""

from pathlib import Path
from typing import AsyncIterator, Union, assert_type

from aiogzip import (
    AsyncGzipBinaryFile,
    AsyncGzipFile,
    AsyncGzipTextFile,
    EngineInfo,
    GzipInfo,
    GzipMemberInfo,
    VerificationResult,
    compress_chunks,
    decompress_chunks,
    engine_info,
    inspect,
    read,
    verify,
    write,
)
from aiogzip import open as gzip_open

p = Path("data.gz")

# --- Text modes narrow to AsyncGzipTextFile ---------------------------------
assert_type(AsyncGzipFile(p, "rt"), AsyncGzipTextFile)
assert_type(gzip_open(p, "rt"), AsyncGzipTextFile)
assert_type(AsyncGzipFile(p, "wt"), AsyncGzipTextFile)
assert_type(AsyncGzipFile(p, "at"), AsyncGzipTextFile)
assert_type(AsyncGzipFile(p, "xt"), AsyncGzipTextFile)
assert_type(AsyncGzipFile(p, "tr"), AsyncGzipTextFile)
assert_type(AsyncGzipFile(p, "rt+"), AsyncGzipTextFile)
assert_type(AsyncGzipFile(p, "r+t"), AsyncGzipTextFile)
# Text-only keyword arguments autocomplete and type-check.
assert_type(
    AsyncGzipFile(p, "wt", encoding="utf-8", errors="strict", newline="\n"),
    AsyncGzipTextFile,
)

# --- Binary modes narrow to AsyncGzipBinaryFile -----------------------------
assert_type(AsyncGzipFile(p), AsyncGzipBinaryFile)  # default mode "rb"
assert_type(gzip_open(p), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "rb"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "wb"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "ab"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "xb"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "r"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "w"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "a"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "x"), AsyncGzipBinaryFile)
assert_type(AsyncGzipFile(p, "rb+"), AsyncGzipBinaryFile)


# --- read() return types follow the mode ------------------------------------
async def _check_reads() -> None:
    async with AsyncGzipFile(p, "rt") as text_file:
        assert_type(text_file, AsyncGzipTextFile)
        assert_type(await text_file.read(), str)
    async with AsyncGzipFile(p, "rb") as binary_file:
        assert_type(binary_file, AsyncGzipBinaryFile)
        assert_type(await binary_file.read(), bytes)
    async with gzip_open(p, "rt") as text_file:
        assert_type(text_file, AsyncGzipTextFile)
        assert_type(await text_file.read(), str)


# --- A non-literal (dynamic) mode falls back to the union -------------------
def _dynamic(mode: str) -> None:
    assert_type(
        AsyncGzipFile(p, mode),
        Union[AsyncGzipBinaryFile, AsyncGzipTextFile],
    )


async def _check_whole_file_helpers() -> None:
    assert_type(await read(p), bytes)
    assert_type(await write(p, b"payload"), None)
    assert_type(await write(p, bytearray(b"payload")), None)
    assert_type(await write(p, memoryview(b"payload")), None)


def _check_engine_info() -> None:
    info = engine_info()
    assert_type(info, EngineInfo)
    assert_type(info.compression, str)
    assert_type(info.decompression, str)


def _check_inspection_result_types(
    member: GzipMemberInfo,
    info: GzipInfo,
    verified: VerificationResult,
) -> None:
    assert_type(member.index, int)
    assert_type(member.mtime, int)
    assert_type(info.members, tuple[GzipMemberInfo, ...])
    assert_type(info.member_count, int)
    assert_type(verified.uncompressed_size, int)


async def _check_inspection_functions() -> None:
    assert_type(await inspect(p), GzipInfo)
    assert_type(await verify(p), VerificationResult)


async def _compressed_source() -> AsyncIterator[bytes]:
    yield b"compressed"


def _check_streaming_functions() -> None:
    assert_type(decompress_chunks(_compressed_source()), AsyncIterator[bytes])
    assert_type(compress_chunks(_compressed_source()), AsyncIterator[bytes])
