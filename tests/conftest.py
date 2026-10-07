import asyncio
import os
import struct
import tempfile
from functools import partial
from pathlib import Path
from typing import Dict, Union

import pytest


class FramedAsyncReader:
    """Async memory source that preserves caller-selected read boundaries."""

    def __init__(self, *frames: bytes, seekable: bool = True) -> None:
        self._frames = tuple(frames)
        self._frame_index = 0
        self._frame_offset = 0
        self._seekable = seekable
        self.read_calls = 0

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if self._frame_index >= len(self._frames):
            return b""
        frame = self._frames[self._frame_index]
        remaining = len(frame) - self._frame_offset
        take = remaining if size < 0 else min(size, remaining)
        start = self._frame_offset
        self._frame_offset += take
        if self._frame_offset == len(frame):
            self._frame_index += 1
            self._frame_offset = 0
        return frame[start : start + take]

    def seekable(self) -> bool:
        return self._seekable

    async def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if not self._seekable:
            raise OSError("not seekable")
        if offset != 0 or whence != os.SEEK_SET:
            raise OSError("test reader only supports rewind")
        self._frame_index = 0
        self._frame_offset = 0
        return 0

    async def close(self) -> None:
        pass


@pytest.fixture
def temp_file():
    """Create a temporary gzip file path for tests."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as f:
        temp_path = f.name
    yield temp_path
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def sample_data():
    """Sample binary data for roundtrip and partial-read tests."""
    return b"Hello, World! This is a test string for gzip compression."


@pytest.fixture
def large_data():
    """Large binary payload for chunking tests."""
    return b"Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 1000


@pytest.fixture
def sample_text():
    """Sample text for roundtrip and partial-read tests."""
    return "Hello, World! This is a test string for gzip compression."


@pytest.fixture
def large_text():
    """Large text payload for chunking tests."""
    return "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 1000


def parse_gzip_header_bytes(
    path: Union[str, os.PathLike],
) -> Dict[str, Union[int, bytes]]:
    """Parse basic gzip header metadata used by metadata tests."""
    raw = Path(path).read_bytes()
    assert len(raw) >= 10
    flags = raw[3]
    mtime = struct.unpack("<I", raw[4:8])[0]
    filename = b""
    if flags & 0x08:
        terminator = raw.find(b"\x00", 10)
        assert terminator != -1
        filename = raw[10:terminator]
    return {"flags": flags, "mtime": mtime, "filename": filename}


@pytest.fixture
def mock_codec_executor(monkeypatch):
    """Gate logical codec advancement at submission, preserving the real driver.

    These wrapper-state tests use async gates instead of native work. The native
    settlement suite separately exercises real executor threads and shutdown.
    Unrelated file I/O continues through the actual executor.
    """
    from aiogzip import _codec_async

    def install(advance):
        loop = asyncio.get_running_loop()
        original = loop.run_in_executor

        def submit(executor, method, *args):
            if (
                isinstance(method, partial)
                and method.func is _codec_async._raw_next_or_done
            ):
                return asyncio.create_task(advance(method, *args))
            return original(executor, method, *args)

        monkeypatch.setattr(loop, "run_in_executor", submit)

    return install


# A hang in the stateful harness must fail its test, not stall CI.
# faulthandler_timeout only dumps stacks, and a scenario's asyncio.timeout
# cannot fire while the event loop itself is blocked, so every stateful test
# gets a thread-method timeout. The row-coverage test replays the whole PR
# seed set when run alone, hence the generous bound.
_STATEFUL = Path(__file__).resolve().parent / "stateful"
_STATEFUL_TIMEOUT = pytest.mark.timeout(300, method="thread")


def pytest_collection_modifyitems(items):
    for item in items:
        if Path(item.path).resolve().parent == _STATEFUL:
            item.add_marker(_STATEFUL_TIMEOUT)
