"""Run the shapes used by the recipes in ``docs/recipes.md``.

The recipes name httpx, aiohttp and aiobotocore, none of which is a
dependency. These fakes have only the method names the recipes use, so the
tests show that aiogzip needs nothing else from those objects.
"""

import gzip
import io

import aiofiles.threadpool

import aiogzip

LINES = [f"line {n}\n" for n in range(5000)]
TEXT = "".join(LINES)
BLOB = gzip.compress(TEXT.encode())
LIMIT = 64 * 1024 * 1024


class FakeHttpxResponse:
    """Has ``aiter_raw()`` only, as the httpx recipes use it."""

    def __init__(self, body: bytes, step: int = 1000) -> None:
        self._body = body
        self._step = step

    async def aiter_raw(self):
        for start in range(0, len(self._body), self._step):
            yield self._body[start : start + self._step]


class FakeStreamReader:
    """Has ``read(n)`` and ``iter_chunked(n)``, like ``response.content``."""

    def __init__(self, body: bytes) -> None:
        self._raw = io.BytesIO(body)
        self.reads = 0

    async def read(self, n: int = -1) -> bytes:
        self.reads += 1
        # A network stream returns what has arrived, often less than asked.
        return self._raw.read(min(n, 777) if n > 0 else -1)

    async def iter_chunked(self, n: int):
        while chunk := self._raw.read(min(n, 777)):
            yield chunk


async def test_httpx_shape_to_chunks():
    response = FakeHttpxResponse(BLOB)
    parts = [
        chunk
        async for chunk in aiogzip.decompress_chunks(
            response.aiter_raw(), max_decompressed_size=LIMIT
        )
    ]
    assert b"".join(parts) == TEXT.encode()


async def test_httpx_shape_to_lines():
    reader = aiogzip.IterableReader(FakeHttpxResponse(BLOB).aiter_raw())
    async with aiogzip.open(
        None,
        "rt",
        fileobj=reader,
        closefd=True,
        newline="",
        max_decompressed_size=LIMIT,
    ) as f:
        assert [line async for line in f] == LINES
    assert reader.closed


async def test_aiohttp_shape_as_fileobj():
    """An object with only an async ``read(n)`` is enough, and stays open."""
    content = FakeStreamReader(BLOB)
    async with aiogzip.open(
        None,
        "rt",
        fileobj=content,
        closefd=False,
        newline="",
        max_decompressed_size=LIMIT,
    ) as f:
        assert [line async for line in f] == LINES
    assert content.reads > 1


async def test_aiohttp_shape_to_chunks():
    content = FakeStreamReader(BLOB)
    parts = [
        chunk
        async for chunk in aiogzip.decompress_chunks(
            content.iter_chunked(256 * 1024), max_decompressed_size=LIMIT
        )
    ]
    assert b"".join(parts) == TEXT.encode()


async def test_upload_shape():
    async def chunks():
        for line in LINES:
            yield line.encode()

    body = b"".join([part async for part in aiogzip.compress_chunks(chunks())])
    assert gzip.decompress(body) == TEXT.encode()


async def test_in_memory_helpers():
    blob = await aiogzip.compress(TEXT.encode())
    assert await aiogzip.decompress(blob, max_decompressed_size=LIMIT) == (
        TEXT.encode()
    )


async def test_wrapped_bytesio_reads_and_writes():
    source = aiofiles.threadpool.wrap(io.BytesIO(BLOB))
    async with aiogzip.open(None, "rt", fileobj=source, newline="") as f:
        assert [line async for line in f] == LINES

    raw = io.BytesIO()
    async with aiogzip.open(
        None, "wt", fileobj=aiofiles.threadpool.wrap(raw), newline=""
    ) as f:
        await f.write(TEXT)
    assert gzip.decompress(raw.getvalue()) == TEXT.encode()
