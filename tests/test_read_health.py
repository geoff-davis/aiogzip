"""WP6: binary read health is one authoritative three-state field.

Structure tests pin the representation; invariant tests check each transition
leaves the orthogonal state (EOF, buffers, decoder, closure) consistent.
"""

import ast
import asyncio
import gzip
import io
from pathlib import Path

import pytest

from aiogzip import AsyncGzipBinaryFile
from aiogzip._binary import _ReadHealth
from aiogzip.codec import GzipDecoder

SRC = Path(__file__).resolve().parents[1] / "src" / "aiogzip"
LEGACY = ("_read_broken", "_read_validation_failed")
PAYLOAD = b"read health payload\n" * 64


class _Source:
    """Non-seekable async source; optionally blocks reads until released."""

    def __init__(self, data: bytes, *, gated: bool = False) -> None:
        self._data = io.BytesIO(data)
        self.gate = asyncio.Event()
        if not gated:
            self.gate.set()

    async def read(self, size: int = -1) -> bytes:
        await self.gate.wait()
        return self._data.read(size)


def _corrupt_crc(data: bytes) -> bytes:
    corrupt = bytearray(data)
    corrupt[-8] ^= 1
    return bytes(corrupt)


async def _open(data: bytes, **kwargs) -> AsyncGzipBinaryFile:
    stream = AsyncGzipBinaryFile(
        None, "rb", fileobj=_Source(data), closefd=False, **kwargs
    )
    await stream.__aenter__()
    return stream


def _assert_fresh(stream: AsyncGzipBinaryFile) -> None:
    """State right after a successful open or rewind."""
    assert stream._read_health is _ReadHealth.HEALTHY
    assert stream._eof is False
    assert stream._position == 0
    assert len(stream._buffer) == 0
    assert stream._buffer_offset == 0
    assert stream._decoder is not None


def _assert_failed(stream: AsyncGzipBinaryFile, health: _ReadHealth) -> None:
    assert stream._read_health is health
    assert stream._eof is True
    assert stream._read_call_active is False


# Structure


def test_production_code_never_assigns_the_legacy_names():
    # Every store or delete of an attribute, including tuple/list targets.
    for path in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(
                node.ctx, (ast.Store, ast.Del)
            ):
                assert node.attr not in LEGACY, f"{path.name}:{node.lineno}"


def test_health_is_one_slot_and_the_legacy_names_are_properties():
    slots = AsyncGzipBinaryFile.__slots__
    assert "_read_health" in slots
    assert not set(LEGACY) & set(slots)
    for name in LEGACY:
        assert isinstance(getattr(AsyncGzipBinaryFile, name), property)
        assert getattr(AsyncGzipBinaryFile, name).fset is None
    assert [h.name for h in _ReadHealth] == [
        "HEALTHY",
        "VALIDATION_SALVAGE",
        "BROKEN",
    ]


@pytest.mark.parametrize(
    "health,broken,validation_failed",
    [
        (_ReadHealth.HEALTHY, False, False),
        (_ReadHealth.VALIDATION_SALVAGE, True, True),
        (_ReadHealth.BROKEN, True, False),
    ],
)
def test_legacy_views_are_derived_and_read_only(health, broken, validation_failed):
    stream = AsyncGzipBinaryFile(None, "rb", fileobj=_Source(b""), closefd=False)
    stream._read_health = health
    assert stream._read_broken is broken
    assert stream._read_validation_failed is validation_failed
    # The invalid (False, True) pair has no representation.
    assert not (validation_failed and not broken)
    for name in LEGACY:
        with pytest.raises(AttributeError):
            setattr(stream, name, False)


# Invariants across transitions


@pytest.mark.parametrize("mode", ["rb", "wb"])
def test_construction_is_healthy_before_open(mode):
    stream = AsyncGzipBinaryFile(None, mode, fileobj=io.BytesIO(), closefd=False)
    assert stream._read_health is _ReadHealth.HEALTHY
    assert stream._read_broken is False


async def test_open_and_validated_eof_stay_healthy():
    stream = await _open(gzip.compress(PAYLOAD))
    _assert_fresh(stream)
    assert await stream.read() == PAYLOAD
    # Validated EOF is healthy: EOF is orthogonal to health.
    assert stream._read_health is _ReadHealth.HEALTHY
    assert stream._eof is True
    await stream.__aexit__(None, None, None)


async def test_validation_failure_keeps_salvage_then_fails_terminally():
    stream = await _open(_corrupt_crc(gzip.compress(PAYLOAD)))
    with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
        await stream.read()
    _assert_failed(stream, _ReadHealth.VALIDATION_SALVAGE)
    assert await stream.read() == PAYLOAD
    with pytest.raises(OSError, match="broken"):
        await stream.read(1)
    _assert_failed(stream, _ReadHealth.VALIDATION_SALVAGE)
    await stream.__aexit__(None, None, None)


async def test_limit_breaks_the_reader_until_rewind():
    stream = await _open(gzip.compress(PAYLOAD), max_decompressed_size=len(PAYLOAD) - 1)
    with pytest.raises(OSError, match="max_decompressed_size"):
        await stream.read()
    _assert_failed(stream, _ReadHealth.BROKEN)
    with pytest.raises(OSError, match="broken"):
        await stream.read(1)
    await stream.__aexit__(None, None, None)


async def test_rewind_of_a_broken_reader_is_fresh_and_healthy(tmp_path):
    path = tmp_path / "health.gz"
    path.write_bytes(_corrupt_crc(gzip.compress(PAYLOAD)))
    async with AsyncGzipBinaryFile(path, "rb") as stream:
        with pytest.raises(gzip.BadGzipFile):
            await stream.read()
        _assert_failed(stream, _ReadHealth.VALIDATION_SALVAGE)
        assert await stream.seek(0) == 0
        _assert_fresh(stream)


async def test_exceptional_exit_with_an_active_read_breaks_the_reader(monkeypatch):
    calls = []
    original = AsyncGzipBinaryFile._break_read_on_abort

    def spy(self):
        calls.append(self)
        return original(self)

    monkeypatch.setattr(AsyncGzipBinaryFile, "_break_read_on_abort", spy)
    source = _Source(gzip.compress(PAYLOAD), gated=True)
    stream = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=False)
    reader = None
    with pytest.raises(RuntimeError, match="body failed"):
        async with stream:
            reader = asyncio.create_task(stream.read())
            await asyncio.sleep(0)
            assert stream._read_call_active is True
            raise RuntimeError("body failed")
    assert calls == [stream]
    assert stream._read_health is _ReadHealth.BROKEN
    assert stream._eof is True
    source.gate.set()
    assert reader is not None
    await asyncio.gather(reader, return_exceptions=True)


async def test_raising_poison_observer_cannot_skip_decoder_discard(
    tmp_path, monkeypatch
):
    discarded = []
    original = GzipDecoder.discard

    def spy(self):
        discarded.append(self)
        return original(self)

    monkeypatch.setattr(GzipDecoder, "discard", spy)
    path = tmp_path / "observer.gz"
    path.write_bytes(_corrupt_crc(gzip.compress(PAYLOAD)))
    stream = AsyncGzipBinaryFile(path, "rb")
    await stream.__aenter__()
    decoder = stream._decoder
    observer_error = RuntimeError("observer failed")

    def observer(validation_failed):
        assert stream._read_health is _ReadHealth.VALIDATION_SALVAGE
        assert stream._eof is True
        raise observer_error

    stream._read_poison_observer = observer
    with pytest.raises(RuntimeError) as raised:
        await stream.read()
    assert raised.value is observer_error
    assert discarded == [decoder]
    _assert_failed(stream, _ReadHealth.VALIDATION_SALVAGE)
    underlying = stream._file
    await stream.__aexit__(None, None, None)
    assert stream.closed
    assert underlying is not None and underlying.closed
