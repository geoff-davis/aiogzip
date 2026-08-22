"""Cross-surface contract tests for exact public boolean options."""

from __future__ import annotations

import gzip
import io
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import aiogzip
from aiogzip import codec as codec_module


class _ObservedFile:
    def __init__(self) -> None:
        self.buffer = io.BytesIO(gzip.compress(b"payload"))
        self.calls: list[str] = []
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        self.calls.append("read")
        return self.buffer.read(size)

    async def write(self, data: bytes) -> int:
        self.calls.append("write")
        return self.buffer.write(data)

    async def close(self) -> None:
        self.calls.append("close")
        self.closed = True


class _ObservedSource:
    def __init__(self) -> None:
        self.iterations = 0
        self.pulls = 0

    def __aiter__(self) -> _ObservedSource:
        self.iterations += 1
        return self

    async def __anext__(self) -> bytes:
        self.pulls += 1
        raise StopAsyncIteration


class _BoolProbe:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls = 0

    def __bool__(self) -> bool:
        self.calls += 1
        return self.result


class _ExplodingBool:
    def __init__(self) -> None:
        self.calls = 0

    def __bool__(self) -> bool:
        self.calls += 1
        raise AssertionError("boolean validation must not invoke __bool__")


class _LenProbe:
    def __init__(self, result: int) -> None:
        self.result = result
        self.calls = 0

    def __len__(self) -> int:
        self.calls += 1
        return self.result


class _NumpyLikeBool:
    """Scalar test double without depending on NumPy in the core test suite."""

    dtype = "bool"

    def __init__(self) -> None:
        self.calls = 0

    def __bool__(self) -> bool:
        self.calls += 1
        return True


INVALID_VALUE_FACTORIES: list[tuple[str, Callable[[], object]]] = [
    ("zero", lambda: 0),
    ("one", lambda: 1),
    ("empty-string", lambda: ""),
    ("false-string", lambda: "false"),
    ("empty-list", list),
    ("truthy-object", lambda: _BoolProbe(True)),
    ("falsy-object", lambda: _LenProbe(0)),
    ("exploding-bool", _ExplodingBool),
    ("numpy-like-bool", _NumpyLikeBool),
]


@dataclass(frozen=True)
class _Surface:
    name: str
    parameter: str
    timing: str
    invoke: Callable[[Path, _ObservedFile, _ObservedSource, object], Any]


def _file_constructor_surface(
    name: str,
    factory: Callable[..., object],
    mode: str,
    parameter: str,
) -> _Surface:
    def invoke(
        path: Path,
        fileobj: _ObservedFile,
        source: _ObservedSource,
        value: object,
    ) -> object:
        del source
        return factory(path, mode, fileobj=fileobj, **{parameter: value})

    return _Surface(name, parameter, "immediate", invoke)


def _whole_file_surface(name: str, function: Callable[..., Any], parameter: str):
    def invoke(
        path: Path,
        fileobj: _ObservedFile,
        source: _ObservedSource,
        value: object,
    ) -> Any:
        del source
        kwargs = {parameter: value, "fileobj": fileobj}
        if function is aiogzip.write:
            return function(path, b"payload", mtime=0, **kwargs)
        return function(path, **kwargs)

    return _Surface(name, parameter, "coroutine", invoke)


FILE_CONSTRUCTORS = [
    ("AsyncGzipBinaryFile", aiogzip.AsyncGzipBinaryFile, "wb"),
    ("AsyncGzipTextFile", aiogzip.AsyncGzipTextFile, "wt"),
    ("AsyncGzipFile-binary", aiogzip.AsyncGzipFile, "wb"),
    ("AsyncGzipFile-text", aiogzip.AsyncGzipFile, "wt"),
    ("open-binary", aiogzip.open, "wb"),
    ("open-text", aiogzip.open, "wt"),
]

SURFACES = [
    *[
        _file_constructor_surface(name, factory, mode, parameter)
        for name, factory, mode in FILE_CONSTRUCTORS
        for parameter in ("fast_compress", "strict_size", "closefd")
    ],
    _Surface(
        "GzipEncoder-fast_compress",
        "fast_compress",
        "immediate",
        lambda path, fileobj, source, value: aiogzip.GzipEncoder(fast_compress=value),
    ),
    _Surface(
        "GzipEncoder-strict_size",
        "strict_size",
        "immediate",
        lambda path, fileobj, source, value: aiogzip.GzipEncoder(strict_size=value),
    ),
    _Surface(
        "GzipDecoder-collect_member_info",
        "collect_member_info",
        "immediate",
        lambda path, fileobj, source, value: aiogzip.GzipDecoder(
            collect_member_info=value
        ),
    ),
    *[
        _whole_file_surface(f"write-{parameter}", aiogzip.write, parameter)
        for parameter in ("fast_compress", "strict_size", "closefd")
    ],
    _whole_file_surface("read-closefd", aiogzip.read, "closefd"),
    _whole_file_surface("inspect-closefd", aiogzip.inspect, "closefd"),
    _whole_file_surface("verify-closefd", aiogzip.verify, "closefd"),
    _Surface(
        "compress_chunks-fast_compress",
        "fast_compress",
        "stream",
        lambda path, fileobj, source, value: aiogzip.compress_chunks(
            source, fast_compress=value
        ),
    ),
    _Surface(
        "compress_chunks-strict_size",
        "strict_size",
        "stream",
        lambda path, fileobj, source, value: aiogzip.compress_chunks(
            source, strict_size=value
        ),
    ),
]

CLOSEFD_SURFACES = [surface for surface in SURFACES if surface.parameter == "closefd"]
REQUIRED_BOOL_SURFACES = [
    surface for surface in SURFACES if surface.parameter != "closefd"
]


async def _invoke_to_completion(
    surface: _Surface,
    path: Path,
    fileobj: _ObservedFile,
    source: _ObservedSource,
    value: object,
) -> None:
    result = surface.invoke(path, fileobj, source, value)
    if surface.timing == "coroutine":
        await result
    elif surface.timing == "stream":
        async for _ in result:
            pass


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.name)
@pytest.mark.parametrize(
    ("value_name", "value_factory"),
    INVALID_VALUE_FACTORIES,
    ids=[item[0] for item in INVALID_VALUE_FACTORIES],
)
async def test_invalid_boolean_is_rejected_before_side_effects(
    tmp_path,
    surface,
    value_name,
    value_factory,
):
    del value_name
    path = tmp_path / "must-not-exist.gz"
    fileobj = _ObservedFile()
    source = _ObservedSource()
    value = value_factory()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(TypeError, match=rf"{surface.parameter} must be a bool"):
            if surface.timing == "coroutine":
                await surface.invoke(path, fileobj, source, value)
            else:
                surface.invoke(path, fileobj, source, value)

    assert caught == []
    assert not path.exists()
    assert fileobj.calls == []
    assert source.iterations == 0
    assert source.pulls == 0
    assert getattr(value, "calls", 0) == 0


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.name)
@pytest.mark.parametrize("value", [False, True])
async def test_exact_booleans_are_accepted(tmp_path, surface, value):
    path = tmp_path / "unused-because-fileobj-is-supplied.gz"
    fileobj = _ObservedFile()
    source = _ObservedSource()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        await _invoke_to_completion(surface, path, fileobj, source, value)


@pytest.mark.parametrize("surface", CLOSEFD_SURFACES, ids=lambda surface: surface.name)
async def test_closefd_alone_accepts_none(tmp_path, surface):
    path = tmp_path / "unused-because-fileobj-is-supplied.gz"
    await _invoke_to_completion(
        surface,
        path,
        _ObservedFile(),
        _ObservedSource(),
        None,
    )


@pytest.mark.parametrize(
    "surface", REQUIRED_BOOL_SURFACES, ids=lambda surface: surface.name
)
async def test_required_boolean_options_reject_none(tmp_path, surface):
    path = tmp_path / "must-not-exist.gz"
    fileobj = _ObservedFile()
    source = _ObservedSource()

    with pytest.raises(TypeError, match=rf"{surface.parameter} must be a bool"):
        if surface.timing == "coroutine":
            await surface.invoke(path, fileobj, source, None)
        else:
            surface.invoke(path, fileobj, source, None)

    assert not path.exists()
    assert fileobj.calls == []
    assert source.pulls == 0


@pytest.mark.parametrize(
    ("parameter", "constructor"),
    [
        ("fast_compress", aiogzip.GzipEncoder),
        ("strict_size", aiogzip.GzipEncoder),
        ("collect_member_info", aiogzip.GzipDecoder),
    ],
)
def test_codec_boolean_validation_precedes_codec_state(
    monkeypatch, parameter, constructor
):
    def unexpected_state_construction(instance):
        raise AssertionError("codec state must not be constructed")

    monkeypatch.setattr(
        codec_module._CodecBase, "__init__", unexpected_state_construction
    )

    with pytest.raises(TypeError, match=rf"{parameter} must be a bool"):
        constructor(**{parameter: 1})
