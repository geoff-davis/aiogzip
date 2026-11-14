"""G06 structural and replay regressions for locally accumulated text."""

import asyncio
import gzip

import pytest
from conftest import FramedAsyncReader

from aiogzip import AsyncGzipTextFile


@pytest.mark.parametrize("newline", ["", "\r\n"])
@pytest.mark.parametrize("surface", ["readline", "anext", "bounded"])
@pytest.mark.parametrize("mib", [1, 2])
async def test_generic_longline_building_work_is_linear(
    monkeypatch, newline, surface, mib
):
    payload = "x" * (mib * 1024 * 1024)
    source = FramedAsyncReader(gzip.compress(payload.encode(), mtime=0))
    work = 0
    original = AsyncGzipTextFile._append_buffer

    def append(handle, text):
        nonlocal work
        if text:
            work += len(handle._text_buffer) + len(text)
        return original(handle, text)

    monkeypatch.setattr(AsyncGzipTextFile, "_append_buffer", append)
    async with AsyncGzipTextFile(
        None, "rt", fileobj=source, closefd=False, newline=newline, chunk_size=65536
    ) as stream:
        if surface == "anext":
            result = await anext(stream)
        elif surface == "bounded":
            result = await stream.readline(len(payload))
        else:
            result = await stream.readline()
        assert result == payload
    # Charge characters presented to concatenation, not allocator-dependent copies.
    # A prefix plus one final join fits comfortably; growing suffix appends do not.
    assert work <= 2 * len(payload) + 65536


@pytest.mark.parametrize("newline", [None, "", "\n", "\r", "\r\n"])
@pytest.mark.parametrize(
    "surface", ["readline", "anext", "read", "readlines", "iter_batches"]
)
@pytest.mark.parametrize("start", ["initial", "empty-buffer", "buffered-prefix"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso2022_jp"])
async def test_cookie_during_unpublished_longline_replays_whole_line(
    monkeypatch, newline, surface, encoding, start
):
    terminator = "\r" if newline == "\r" else "\r\n"
    payload = "日" * 1000 + terminator
    if start == "buffered-prefix":
        prime = 1
    elif start == "empty-buffer":
        prime = {"utf-8": 33, "utf-16": 49, "iso2022_jp": 48}[encoding]
    else:
        prime = 0
    expected = payload.replace("\r\n", "\n") if newline is None else payload
    source = FramedAsyncReader(
        gzip.compress(("日" * prime + payload).encode(encoding), mtime=0)
    )
    async with AsyncGzipTextFile(
        None,
        "rt",
        fileobj=source,
        closefd=False,
        newline=newline,
        chunk_size=100,
        encoding=encoding,
    ) as stream:
        if prime:
            assert await stream.read(prime) == "日" * prime
        binary = stream._binary_file
        assert binary is not None
        original = type(binary).read
        reached, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def read(handle, size=-1):
            nonlocal calls
            calls += 1
            if calls == 3:
                reached.set()
                await release.wait()
            return await original(handle, size)

        monkeypatch.setattr(type(binary), "read", read)

        async def consume():
            if surface == "read":
                return await stream.read(len(expected))
            if surface == "anext":
                return await anext(stream)
            if surface == "readlines":
                return "".join(await stream.readlines(1))
            if surface == "iter_batches":
                batches = stream.iter_batches(1)
                try:
                    return "".join(await anext(batches))
                finally:
                    await batches.aclose()
            return await stream.readline()

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(reached.wait(), timeout=5)
            cookie = await stream.tell()
        finally:
            release.set()
            result = await asyncio.wait_for(task, timeout=5)
        assert result == expected
        completed = await stream.tell()
        await stream.seek(cookie)
        assert await consume() == expected
        await stream.seek(completed)
        assert await stream.read() == ""


@pytest.mark.parametrize("surface", ["readline", "read"])
@pytest.mark.parametrize("failure", ["cancel", "no-effect-error"])
@pytest.mark.parametrize("newline", [None, "", "\r\n"])
async def test_unpublished_cookie_origin_clears_after_failed_read(
    monkeypatch, surface, failure, newline
):
    line = "日" * 1000 + ("\r\n" if newline == "\r\n" else "\n")
    payload = line + "tail"
    source = FramedAsyncReader(gzip.compress(payload.encode(), mtime=0))
    async with AsyncGzipTextFile(
        None, "rt", fileobj=source, closefd=False, chunk_size=100, newline=newline
    ) as stream:
        binary = stream._binary_file
        assert binary is not None
        original = type(binary).read
        reached, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def read(handle, size=-1):
            nonlocal calls
            calls += 1
            if calls == 3:
                reached.set()
                await release.wait()
                raise OSError("injected before binary read")
            return await original(handle, size)

        monkeypatch.setattr(type(binary), "read", read)
        task = asyncio.create_task(
            stream.readline() if surface == "readline" else stream.read(len(line))
        )
        try:
            await asyncio.wait_for(reached.wait(), timeout=5)
            if failure == "cancel":
                task.cancel()
            else:
                release.set()
            with pytest.raises(
                asyncio.CancelledError if failure == "cancel" else OSError
            ):
                await asyncio.wait_for(task, timeout=5)
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        recovered = await stream.tell()
        assert await stream.readline() == line
        completed = await stream.tell()
        await stream.seek(recovered)
        assert await stream.readline() == line
        await stream.seek(completed)
        assert await stream.read() == "tail"
