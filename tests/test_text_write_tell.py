"""Write-mode text ``tell()`` is the encoded byte position (#175).

It once consulted the unused decoder, whose initial state is non-zero for BOM
and stateful encodings, and returned a large negative cookie.
"""

import gzip
import io

import pytest

from aiogzip import AsyncGzipTextFile

ENCODINGS = [
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-32",
    "latin-1",
    "shift_jis",
    "iso2022_jp",
]
PIECES = ["abc", "", "d\n", "ef\n" * 50]


def _stdlib_positions(encoding, newline, mode="w"):
    raw = io.BytesIO()
    positions = []
    with io.TextIOWrapper(raw, encoding=encoding, newline=newline) as text:
        positions.append(text.tell())
        for piece in PIECES:
            text.write(piece)
            positions.append(text.tell())
        text.flush()
        data = raw.getvalue()
    return positions, data


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("newline", ["\n", "\r\n", ""])
async def test_write_tell_matches_text_io_wrapper(tmp_path, encoding, newline):
    expected, data = _stdlib_positions(encoding, newline)
    path = tmp_path / "out.gz"
    positions = []
    async with AsyncGzipTextFile(path, "wt", encoding=encoding, newline=newline) as f:
        positions.append(await f.tell())
        for piece in PIECES:
            await f.write(piece)
            positions.append(await f.tell())
    assert positions == expected
    assert all(type(position) is int and position >= 0 for position in positions)
    assert gzip.decompress(path.read_bytes()) == data


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
async def test_write_tell_after_writelines_and_flush(tmp_path, encoding):
    path = tmp_path / "out.gz"
    async with AsyncGzipTextFile(path, "wt", encoding=encoding, newline="\n") as f:
        await f.writelines(["a\n", "b\n"])
        await f.flush()
        position = await f.tell()
    assert position == len("a\nb\n".encode(encoding))


async def test_append_tell_starts_at_zero(tmp_path):
    path = tmp_path / "out.gz"
    path.write_bytes(gzip.compress(b"old\n"))
    async with AsyncGzipTextFile(path, "at", encoding="utf-16") as f:
        start = await f.tell()
        await f.write("x")
        end = await f.tell()
    assert (start, end) == (0, len("x".encode("utf-16")))
