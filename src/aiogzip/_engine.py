"""Codec engine selection for aiogzip.

Single source of truth for which deflate implementation backs compression and
decompression. ``zlib-ng`` is a *soft* dependency: when the ``aiogzip[fast]``
extra is installed it is used automatically for **decompression** (its output
is byte-identical to stdlib ``zlib``, so this is transparent) and, only when a
caller explicitly opts in, for **compression** (its compressed bytes differ
from stdlib, so it is never selected silently). When ``zlib-ng`` is not
installed every path falls back to stdlib ``zlib`` and aiogzip stays
pure-Python.

Set ``AIOGZIP_ENGINE=stdlib`` to force stdlib everywhere (useful for
reproducible error behaviour or debugging).
"""

import asyncio
import importlib
import os
import sys
import zlib
from dataclasses import dataclass
from typing import Any, Callable, Tuple, Type, TypeVar

from ._common import ZlibEngine


def _load_zng() -> Any:
    """Return the zlib-ng module, or None if the extra is not installed.

    Imported dynamically and typed as Any so neither mypy nor ty objects to the
    stub-less module; behaviour is identical to ``from zlib_ng import zlib_ng``.
    """
    try:
        return importlib.import_module("zlib_ng.zlib_ng")
    except ImportError:  # pragma: no cover - exercised in environments without it
        return None


_zng: Any = _load_zng()

# Whether stdlib has been forced via the environment escape hatch.
_FORCE_STDLIB = os.environ.get("AIOGZIP_ENGINE", "").strip().lower() == "stdlib"

# Whether zlib-ng is available *and* permitted as the active engine.
_HAVE_ZNG = _zng is not None and not _FORCE_STDLIB

# Inputs below this size run inline; above it, a thread hop is amortized and
# keeps the event loop responsive during CPU-heavy codec work.
ZLIB_OFFLOAD_THRESHOLD = 256 * 1024


_T = TypeVar("_T")


async def run_zlib_in_thread(method: Callable[[bytes], _T], data: bytes) -> _T:
    """Run one codec call in the event loop's default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, method, data)


@dataclass(frozen=True)
class EngineInfo:
    """Human-readable codec selections used by aiogzip by default."""

    compression: str
    decompression: str
    # Defaulted so third-party code constructing EngineInfo positionally
    # (it is public) keeps working; engine_info() always fills it in.
    crc32: str = "stdlib-zlib"


@dataclass(frozen=True, slots=True)
class _InflateStep:
    """One engine-neutral raw or gzip inflate step."""

    output: bytes
    consumed: int
    eof: bool


def _merged_retained_size(data: bytes, first: bytes, second: bytes) -> int:
    """Return the suffix length represented by two engine leftover fields.

    Known zlib engines duplicate post-EOF bytes in both fields. Other engines
    may use only one field, split the suffix, or expose overlapping fragments.
    Resolve those representations here so callers only reason about counts.
    """

    def current_span(fragment: bytes) -> bytes:
        if len(fragment) <= len(data):
            return fragment
        if not fragment.endswith(data):
            raise RuntimeError("inflate engine returned input not present in its span")
        return data

    first = current_span(first)
    second = current_span(second)

    if not first:
        if not data.endswith(second):
            raise RuntimeError("inflate engine returned input not present in its span")
        return len(second)
    if not second:
        if not data.endswith(first):
            raise RuntimeError("inflate engine returned input not present in its span")
        return len(first)
    if first == second:
        if not data.endswith(first):
            raise RuntimeError("inflate engine returned input not present in its span")
        return len(first)

    candidates: set[int] = set()
    for left, right in ((first, second), (second, first)):
        maximum_overlap = min(len(left), len(right))
        for overlap in range(maximum_overlap, -1, -1):
            if left[len(left) - overlap :] != right[:overlap]:
                continue
            merged = left + right[overlap:]
            if data.endswith(merged):
                candidates.add(len(merged))
                break
    if candidates:
        return max(candidates)

    raise RuntimeError("inflate engine returned irreconcilable leftover input")


def inflate_step(
    engine: ZlibEngine, data: bytes, *, max_length: int = 0
) -> _InflateStep:
    """Inflate one span and normalize engine-specific consumption details."""
    if max_length:
        output = engine.decompress(data, max_length=max_length)
    else:
        output = engine.decompress(data)
    eof = bool(getattr(engine, "eof", False))
    unused = bytes(getattr(engine, "unused_data", b""))
    tail = bytes(getattr(engine, "unconsumed_tail", b""))

    if eof:
        retained = _merged_retained_size(data, unused, tail)
    else:
        if not data.endswith(tail):
            raise RuntimeError("inflate engine returned a non-suffix unconsumed tail")
        retained = len(tail)

    consumed = len(data) - retained
    if not 0 <= consumed <= len(data):
        raise RuntimeError("inflate engine reported invalid input consumption")
    if data and not consumed and not output and not eof:
        raise OSError("gzip decompressor made no progress")
    return _InflateStep(output=output, consumed=consumed, eof=eof)


# Errors raised by the deflate engines. zlib-ng's (and isal's) error type is
# NOT zlib.error nor a subclass of it, so callers that mean to catch decode
# failures must catch this tuple — otherwise a corrupt stream decoded by
# zlib-ng would leak an unwrapped foreign exception. zlib-ng's error is
# included whenever the module is importable (regardless of the force flag),
# since including an extra type in an ``except`` is harmless.
ZLIB_ERRORS: Tuple[Type[BaseException], ...]
if _zng is not None:
    ZLIB_ERRORS = (zlib.error, _zng.error)
else:
    ZLIB_ERRORS = (zlib.error,)

# crc32 output is bit-identical across engines (CRC-32 is fully specified),
# so select the fastest implementation per platform. Measured on 8 MiB
# inputs: zlib-ng's SIMD crc32 is ~3.4x faster than stdlib on x86-64 Linux
# (12.9 vs 3.7 GB/s), but on macOS Apple ships a hardware-accelerated zlib
# whose crc32 is ~4x faster than zlib-ng's (42 vs 11 GB/s) — keep stdlib
# there. Every caller goes through this name, so the choice applies to the
# write path, streaming encoder, and inspection/verification alike.
if _HAVE_ZNG and sys.platform != "darwin":
    crc32 = _zng.crc32
else:
    crc32 = zlib.crc32

# Re-export the constants _binary.py needs so it has a single import surface.
MAX_WBITS = zlib.MAX_WBITS
Z_SYNC_FLUSH = zlib.Z_SYNC_FLUSH


def decompressobj(wbits: int) -> ZlibEngine:
    """Return a decompressor: zlib-ng when available, else stdlib zlib.

    Decompressed output is byte-identical across engines, so this selection is
    transparent to callers.
    """
    if _HAVE_ZNG:
        return _zng.decompressobj(wbits=wbits)
    return zlib.decompressobj(wbits=wbits)


def compressobj(level: int, wbits: int, fast: bool = False) -> ZlibEngine:
    """Return a compressor.

    Stdlib ``zlib`` by default. ``zlib-ng`` is used only when ``fast`` is True
    *and* it is available, because its compressed output is not byte-identical
    to stdlib — installing the extra alone must not change produced ``.gz``
    bytes.
    """
    if fast and _HAVE_ZNG:
        return _zng.compressobj(level=level, wbits=wbits)
    return zlib.compressobj(level=level, wbits=wbits)


def have_fast_engine() -> bool:
    """True when zlib-ng is available and not disabled via the env escape hatch."""
    return _HAVE_ZNG


def decompress_engine_name() -> str:
    """Name of the engine backing decompression: ``"zlib-ng"`` or ``"stdlib"``."""
    return "zlib-ng" if _HAVE_ZNG else "stdlib"


def engine_info() -> EngineInfo:
    """Return the default compression and active decompression engines.

    Compression remains on stdlib zlib unless a writer opts into zlib-ng with
    ``fast_compress=True``. The returned strings are intended for diagnostics,
    not machine-readable feature detection.
    """
    return EngineInfo(
        compression="stdlib-zlib",
        decompression="zlib-ng" if _HAVE_ZNG else "stdlib-zlib",
        crc32="zlib-ng" if crc32 is not zlib.crc32 else "stdlib-zlib",
    )
