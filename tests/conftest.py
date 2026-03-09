import os
import struct
import tempfile
from pathlib import Path
from typing import Dict, Union

import pytest


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
