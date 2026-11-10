"""``writelines()`` keeps the lines before one that fails to encode (#176).

Lines are joined into batches and encoded once, so an encode error used to
reject the whole batch: how much was lost depended on ``chunk_size``. The
result must now match separate ``write()`` calls and ``io.TextIOWrapper``.
"""

import gzip
import io
import random
import string

import pytest

from aiogzip import AsyncGzipTextFile

GOOD = ["a\n", "bb\n", "", "ccc\n", "d\n"]


def _stdlib(lines, encoding, newline):
    raw = io.BytesIO()
    text = io.TextIOWrapper(raw, encoding=encoding, newline=newline)
    error = None
    try:
        text.writelines(lines)
    except UnicodeEncodeError as exc:
        error = exc
    text.flush()
    return raw.getvalue(), error


@pytest.mark.parametrize(
    "encoding,bad", [("utf-8", "x\ud800y\n"), ("ascii", "é\n"), ("utf-16", "\udc00\n")]
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("chunk_size", [1, 4, 8, 256 * 1024])
@pytest.mark.parametrize("index", range(len(GOOD) + 1))
async def test_lines_before_the_bad_one_are_written(
    tmp_path, encoding, bad, newline, chunk_size, index
):
    lines = GOOD[:index] + [bad] + GOOD[index:]
    expected, expected_error = _stdlib(lines, encoding, newline)
    assert expected_error is not None

    path = tmp_path / "out.gz"
    async with AsyncGzipTextFile(
        path, "wt", encoding=encoding, newline=newline, chunk_size=chunk_size
    ) as f:
        with pytest.raises(UnicodeEncodeError) as caught:
            await f.writelines(lines)
    assert gzip.decompress(path.read_bytes()) == expected
    # The error describes the offending line, not the joined batch.
    assert caught.value.object == bad.replace("\n", newline)
    assert caught.value.start == expected_error.start


async def test_writer_stays_usable_and_bom_is_written_once(tmp_path):
    path = tmp_path / "out.gz"
    async with AsyncGzipTextFile(path, "wt", encoding="utf-16", newline="\n") as f:
        with pytest.raises(UnicodeEncodeError):
            await f.writelines(["\udc00", "never\n"])
        with pytest.raises(UnicodeEncodeError):
            await f.writelines(["a\n", "\udc00", "never\n"])
        await f.writelines(["b\n"])
    assert gzip.decompress(path.read_bytes()).decode("utf-16") == "a\nb\n"


async def test_error_handler_that_never_raises_is_unaffected(tmp_path):
    path = tmp_path / "out.gz"
    async with AsyncGzipTextFile(
        path, "wt", encoding="ascii", errors="replace", newline="\n"
    ) as f:
        await f.writelines(["a\n", "é\n", "b\n"])
    assert gzip.decompress(path.read_bytes()) == b"a\n?\nb\n"


async def test_sink_failure_is_not_retried_line_by_line():
    """A sink's own ``UnicodeEncodeError`` is not an encode failure."""

    class Sink:
        def __init__(self):
            self.failing_writes = 0
            self.fail = False

        async def write(self, data):
            if self.fail:
                self.failing_writes += 1
                raise UnicodeEncodeError("ascii", "x", 0, 1, "from the sink")
            return len(data)

        async def close(self):
            pass

    sink = Sink()
    f = AsyncGzipTextFile(None, "wt", fileobj=sink, chunk_size=4)
    await f.open()
    sink.fail = True
    rng = random.Random(1)
    lines = ["".join(rng.choices(string.ascii_letters, k=3)) for _ in range(300_000)]
    with pytest.raises(UnicodeEncodeError) as caught:
        await f.writelines(lines)
    assert caught.value.reason == "from the sink"
    assert sink.failing_writes == 1
